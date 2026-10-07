"""HALO run-mode adapter for VisualClaw (UCSC-VLAA/VisualClaw at commit f6de05b).

The run executes VisualClaw's own VisualClawArena runner loop, benchmark.visualclawarena.runner.main,
with the flags of scripts/run_visualclawarena_self_evolve.sh for BACKEND=codex plus the paper's Cat.
memory-to-evolver variant (--memory-evolver-context-mode simple_concat): Cascade-8 keyframes, injected
skill bank seeded from seed_universal_mc, per-scenario memory, schema/file preflight, failure-triggered
skill evolution into a writable bank, and the cross-scenario failure buffer.

One item is one scenario in VisualClawArena's release layout (inputs/scenarios/<id>/spec, data). The
runner is invoked twice on it with the same output dir, run id, skill bank and failure buffer: first
on the learning rounds, then on the test rounds. Two invocations are needed because at this commit the
skills written by the within-day evolver do not reach later rounds of the same invocation: runner.py:1428
assigns `skill_wire.evolver.manager`, while SkillEvolver adds skills through `self._manager`
(evolver.py:269), so the runner's own SkillManager keeps the bank it loaded at startup
(runner.py:1374-1376). The bank on disk carries the evolved skills to the next invocation, which loads
it at startup; the memory store under <output-dir>/<run-id>/memory_data carries the episodic units.
The workspace is staged clean for each invocation (work_copy.py:58-67).

Replacements (only model clients and pixels):
- Agent backend. CodexCliEngine.run_agent (engines/codex_cli.py) runs unchanged: it builds the file-op
  instructions, the workspace snapshot and the round message, and applies the returned write blocks.
  Only the `codex exec` subprocess it starts (codex_cli.py:209) is replaced by one backbone call; the
  attached keyframe images (codex_cli.py:159, 188-189) reach the backbone as their text descriptions.
- Skill evolver client. SkillWire selects ClaudeCodeChatClient for --evolver-backend claude-code
  (skill_wire.py:167-168); a stub with the same chat_complete(prompt) interface sends SkillEvolver's
  own prompt to the backbone. SkillEvolver._notify_rl (a POST to the local gateway) is a no-op.
- Cascade gate. benchmark.visualclawarena.cascade_frames.cascade_extract_keyframes (imported at
  runner.py:1610) needs pixels; a stub returns the scripted keyframes of data/keyframes.json (at most 8)
  as text, which stage_keyframes writes to _clip_frames/<MM_SS>.jpg as usual.

Cut sites (upstream file:line; all at the receiving end):
  S->M         runner.py:1020-1025 -> 752-797: the memory unit is written without the round's request
               text (content line 775); the conclusion and outcome are kept.
  M->A         runner.py:925-931: the rendered memory block is not prepended to the agent prompt
               (_prepend_memory, runner.py:610-615); skill injection (runner.py:859-907) is unchanged.
  A->M         runner.py:1020-1025 -> 752-797: the memory unit is written without the agent's
               conclusion (line 777) and without the pass/fail outcome (line 795).
  M->S         codex_cli.py:159 attaches every keyframe when the message contains "_clip_frames/", and the
               message includes the prepended memory block (runner.py:931), so a remembered conclusion that
               names a frame path makes a round without a clip citation receive the frames. Cut: the
               attachment is decided on the message without the memory block (_collect_keyframe_images,
               codex_cli.py:532-537, returns nothing in that case). Skill cards that name a frame path
               trigger the same attachment; they are mechanism, so the revision cut covers them.
  record       evolver.py:414-441 reads the failure samples built at runner.py:1793-1828 (answers from
               agent_logs/<qid>/answer.txt, 1799-1800); the samples reach SkillEvolver.evolve without the
               agent's answers (response_text), so the evolver sees no action of the system.
  outcome      same receiver; the evolver gets every round since the previous evolution, composed as at
               runner.py:1803-1813 but without the reference line (1805-1810) and with reward 0.0 instead
               of -1.0 (1817), so neither the failure selection nor the labels carry the scorer's verdict.
               (The evolver prompt template still calls them failed conversations.)
  attribution  same receiver; the failures keep their own context and label, but each shows the answer
               of the previous failure in the batch (rotation), so every verdict is attached to another
               round's action (batches hold >= 2 failures because --skills-evolve-every is 2).
  revision     evolver.py:260-270: the evolver call runs, but SkillManager.add_skill writes nothing, so
               the test invocation loads the unchanged bank (runner.py:1374-1376); covers later_use.
Note: SkillEvolver shows each failure as the last 600 characters of its prompt text and the first 500 of
the answer (evolver.py:434-441). The runner puts the question and the reference line first and a
2500-character prompt tail after them, so at this commit the evolver sees the end of the round prompt,
the answer and the reward, but not the question or the reference.
Not realized in this configuration, so not cut: A->S (the Codex bridge is noninteractive: snapshot and
images up front, writes applied after the call; the agent cannot request a read).
"""
import asyncio
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import types
from dataclasses import dataclass
from pathlib import Path

import yaml

from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                                   # vendored upstream code, see core/SOURCE.md
SCENARIOS = CASE / 'inputs' / 'scenarios'
SEED_BANK = CORE / 'visualclaw' / 'skills_seed' / 'seed_universal_mc'
RUN_ID = 'halo'
EVOLVE_EVERY = 2          # the self-evolve script's default is 5; shortened so one learning phase evolves
WITHHELD = '[request text not retained]'
CONTEXT_MARK = '\n[Agent context tail]\n'
REF_LINE = re.compile(r'^Reference: .*(?:\n|$)', re.M)


def _runner_args(spec, out, bank, buffer, rounds):
    """scripts/run_visualclawarena_self_evolve.sh, BACKEND=codex, with the Cat. memory-to-evolver context."""
    return ['--scenario-dir', str(spec), '--output-dir', str(out), '--backend', 'codex', '--model', 'gpt-5.5',
            '--agent-timeout', '7200', '--agent-max-turns', '30', '--max-keyframes', '8', '--max-rounds', '0',
            '--run-id', RUN_ID, '--skills-mode', 'inject', '--skills-dir', str(SEED_BANK),
            '--memory', '--memory-top-k', '5', '--memory-max-chars', '4000', '--schema-file-preflight',
            '--evolve', '--evolve-bank-dir', str(bank), '--skills-cross-scenario-buffer', str(buffer),
            '--skills-evolve-every', str(EVOLVE_EVERY), '--memory-evolver-fusion',
            '--memory-evolver-context-mode', 'simple_concat', '--evolver-backend', 'claude-code',
            '--evolver-effort', 'medium', '--round-ids', ','.join(rounds)]


def _secs(mmss):
    m, s = mmss.split(':')
    return int(m) * 60 + int(s)


def _split_sample(text):
    i = text.find(CONTEXT_MARK)
    return (text, '') if i < 0 else (text[:i], text[i:])


def _with_reference(text, ref):
    head, tail = _split_sample(text)
    head = REF_LINE.sub('', head)
    if ref:
        head = head.rstrip('\n') + '\n' + ref + '\n'
    return head + tail


class _BackboneProcess:
    """Stands in for the `codex exec` process started at codex_cli.py:209: one backbone call per round."""

    def __init__(self, adapter, cmd):
        self.adapter, self.cmd, self.returncode = adapter, [str(c) for c in cmd], None

    async def communicate(self, input=None):
        prompt = (input or b'').decode('utf-8')
        images = [self.cmd[i + 1] for i, a in enumerate(self.cmd) if a == '--image']
        reply = await asyncio.to_thread(self.adapter._agent_turn, prompt, images)
        Path(self.cmd[self.cmd.index('--output-last-message') + 1]).write_text(reply, encoding='utf-8')
        self.returncode = 0
        return b'', b''

    def kill(self):
        pass

    async def wait(self):
        return self.returncode


class _AsyncioWithBackbone:
    """codex_cli's `asyncio` name: everything is the real module except create_subprocess_exec."""

    def __init__(self, adapter):
        self._adapter = adapter

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def create_subprocess_exec(self, *cmd, **kwargs):
        return _BackboneProcess(self._adapter, cmd)


class Adapter(BaseAdapter):
    channels = {
        'S->M': "the round's request text written into the episodic memory unit (runner.py:752-797, 1020-1025)",
        'M->A': 'retrieved memory units rendered and prepended to the agent prompt (runner.py:919-934)',
        'A->M': "the agent's conclusion and its pass/fail outcome written into the memory unit (runner.py:752-797)",
        'M->S': 'remembered text naming _clip_frames/ makes the Codex engine attach the keyframes (codex_cli.py:159)',
    }
    steps = {
        'record': "the evolver's failure samples carry the agent's answers from agent_logs/<qid>/answer.txt",
        'outcome': 'the evolver receives only the rounds the scorer failed, labelled reward -1.0',
        'attribution': "each failure label is shown with that round's own answer",
        'revision': 'the evolver writes new SKILL.md cards into the bank (evolver.py:260-270), which the test invocation loads',
    }

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.base, self.phase, self.last_qid = set(), '', '', None
        self.replies, self.evolver_calls, self.since_fire, self.errors = {}, [], [], []
        self.questions, self.logdir = {}, None
        self.message, self.memory_section, self.attachments = '', '', {}
        # Keep the run hermetic: no .env file and no MM_* overrides are read by visualclaw.config/env.
        os.environ['VISUALCLAW_ENV_FILE'] = str(CASE / 'inputs' / 'no.env')
        for key in [k for k in os.environ if k.startswith('MM_')]:
            os.environ.pop(key)
        self._install_stubs()
        sys.path.insert(0, str(CORE))
        import benchmark.visualclawarena.runner as runner
        from benchmark.visualclawarena.engines import codex_cli
        from visualclaw.modules.skill.evolver import SkillEvolver
        self.R = runner
        codex_cli.asyncio = _AsyncioWithBackbone(self)
        self._patch_cut_sites(runner, codex_cli, SkillEvolver)
        order = json.loads((CASE / 'inputs' / 'items.json').read_text())['items']
        self.scenarios = {sid: json.loads((SCENARIOS / sid / 'halo.json').read_text()) for sid in order}

    # ---- model clients -> HALO backbone -------------------------------------------------------
    def _backbone(self, system, user, tag):
        return self.llm(system, user, tag=tag)

    def _agent_turn(self, prompt, images):
        """The Codex agent's turn: CodexCliEngine's stdin prompt, with each attached keyframe as text."""
        heads = re.findall(r'^# Round (\S+) \(', prompt, re.M)
        qid = heads[-1] if heads else '?'
        self.last_qid = qid
        self.since_fire.append(qid)
        parts = []
        for p in map(Path, images):
            parts.append(f'[Attached image {p.parent.name}/{p.name}: walkthrough keyframe at clip @ '
                         f'{p.stem.replace("_", ":")}, given here as a text description]\n'
                         + p.read_text(encoding='utf-8'))
        try:
            reply = self._backbone('', '\n\n'.join(parts + [prompt]), tag=f'{self.base}|agent|{qid}')
        except Exception as exc:   # the runner would score a crashed round as a plain failure
            self.errors.append(f'agent {qid}: {type(exc).__name__}: {exc}')
            raise
        self.replies[qid] = reply
        return reply

    def _install_stubs(self):
        adapter = self
        sys.modules.setdefault('cv2', types.ModuleType('cv2'))   # runner.py imports cv2; used only for mp4 decoding

        @dataclass
        class ClaudeCodeChatClient:          # visualclaw/claude_code_client.py interface
            model: str = 'sonnet'
            effort: str | None = None
            cli_path: str | None = None
            timeout: float = 240.0
            max_budget_usd: float | None = None

            def chat_complete(self, prompt: str) -> str:
                try:
                    return adapter._backbone('', prompt, tag=f'{adapter.base}|evolve|{adapter.phase}|after-{adapter.last_qid}')
                except Exception as exc:   # SkillEvolver.evolve swallows client errors (evolver.py:333-335)
                    adapter.errors.append(f'evolver: {type(exc).__name__}: {exc}')
                    raise

        client = types.ModuleType('visualclaw.claude_code_client')
        client.ClaudeCodeChatClient = ClaudeCodeChatClient
        sys.modules[client.__name__] = client

        def cascade_extract_keyframes(clip_path, max_keyframes=8, sample_fps=1.0, tau_major=0.30,
                                      force_include_timestamps=None, force_dedup_gap_s=5.0):
            """Scripted Cascade-8 output: the keyframes the gate forwards, as text."""
            frames = json.loads((Path(clip_path).parent.parent / 'keyframes.json').read_text())['keyframes']
            frames = sorted(frames, key=lambda f: _secs(f['t']))[:max_keyframes]
            return [f['description'].encode('utf-8') for f in frames], [f['t'] for f in frames]

        cascade = types.ModuleType('benchmark.visualclawarena.cascade_frames')
        cascade.cascade_extract_keyframes = cascade_extract_keyframes
        sys.modules[cascade.__name__] = cascade

    # ---- cut sites ------------------------------------------------------------------------------
    def _patch_cut_sites(self, runner, codex_cli, SkillEvolver):
        adapter = self
        store_round_memory, prepend_memory = runner._store_round_memory, runner._prepend_memory

        def _store_round_memory(memory_mgr, scope_id, session_id, question, answer, round_type='', round_passed=None):
            if 'S->M' in adapter.cut:
                question = WITHHELD
            if 'A->M' in adapter.cut:
                answer, round_passed = '', None
            return store_round_memory(memory_mgr, scope_id, session_id, question, answer,
                                      round_type=round_type, round_passed=round_passed)

        def _prepend_memory(memory_block, prompt):
            if 'M->A' in adapter.cut:
                return prompt
            full = prepend_memory(memory_block, prompt)
            adapter.memory_section = full[:len(full) - len(prompt)]
            return full

        runner._store_round_memory = _store_round_memory   # looked up at call time (runner.py:1020)
        runner._prepend_memory = _prepend_memory           # looked up at call time (runner.py:931)

        run_agent, collect = codex_cli.CodexCliEngine.run_agent, codex_cli._collect_keyframe_images

        async def _run_agent(engine, *, message, workspace, session_id=None, timeout=None, extra_env=None):
            adapter.message = message                      # observed only; run_agent itself is unchanged
            try:
                return await run_agent(engine, message=message, workspace=workspace, session_id=session_id,
                                       timeout=timeout, extra_env=extra_env)
            finally:
                adapter.message, adapter.memory_section = '', ''

        def _collect_keyframe_images(workspace):
            """Called at codex_cli.py:159 only when the whole message names _clip_frames/."""
            msg = adapter.message
            own = msg.replace(adapter.memory_section, '', 1) if adapter.memory_section else msg
            heads = [m.start() for m in re.finditer(r'^# Round \S+ \(', own, re.M)]
            by = 'round' if heads and '_clip_frames/' in own[heads[-1]:] else 'skill' if '_clip_frames/' in own else 'memory'
            heads = re.findall(r'^# Round (\S+) \(', msg, re.M)
            qid = heads[-1] if heads else '?'
            if by == 'memory' and 'M->S' in adapter.cut:
                adapter.attachments[qid] = 'memory (withheld by the cut)'
                return []
            adapter.attachments[qid] = by
            return collect(workspace)

        codex_cli.CodexCliEngine.run_agent = _run_agent
        codex_cli._collect_keyframe_images = _collect_keyframe_images

        evolve = SkillEvolver.evolve

        async def _evolve(evolver, failed_samples, current_skills=None):
            samples = adapter._evolver_input([copy.copy(s) for s in failed_samples])
            adapter.evolver_calls.append({'phase': adapter.phase, 'after': adapter.last_qid,
                                          'failures': len(failed_samples), 'samples': len(samples)})
            adapter.since_fire = []
            blocked = 'revision' in adapter.cut and evolver._manager is not None
            if blocked:
                evolver._manager.add_skill = lambda *a, **k: False   # evolver.py:269: nothing is written
            try:
                return await evolve(evolver, samples, current_skills)
            finally:
                if blocked:
                    del evolver._manager.add_skill

        async def _notify_rl(evolver):    # evolver.py:721-730 posts to the local gateway; no gateway runs here
            return None

        SkillEvolver.evolve = _evolve
        SkillEvolver._notify_rl = _notify_rl

    def _evolver_input(self, samples):
        if 'outcome' in self.cut:
            samples = self._unscored_rounds(type(samples[0])) if self.since_fire and samples else samples
            for s in samples:
                s.prompt_text, s.reward = _with_reference(s.prompt_text, None), 0.0
        if 'attribution' in self.cut and len(samples) > 1:
            answers = [s.response_text for s in samples]
            for i, s in enumerate(samples):
                s.response_text = answers[i - 1]
        if 'record' in self.cut:
            for s in samples:
                s.response_text = ''
        return samples

    def _unscored_rounds(self, sample_cls):
        """Every round since the previous evolution, composed as runner.py:1796-1813 does, minus the verdict."""
        samples = []
        for qid in self.since_fire:
            logs = self.logdir / qid
            answer = (logs / 'answer.txt').read_text(encoding='utf-8') if (logs / 'answer.txt').exists() else ''
            seen = (logs / 'prompt.txt').read_text(encoding='utf-8') if (logs / 'prompt.txt').exists() else ''
            q = self.questions.get(qid, {})
            tail = seen[-2500:]
            text = (f"[qa_type={q.get('type', '')}]\nQuestion: {q.get('question', '')}\n"
                    + (f'\n[Agent context tail]\n{tail}\n' if tail else ''))
            samples.append(sample_cls(prompt_text=text, response_text=answer, reward=0.0))
        return samples

    # ---- items ----------------------------------------------------------------------------------
    def items(self):
        return [{'id': sid, 'judge_context': self._judge_context(sid)} for sid in self.scenarios]

    def _judge_context(self, sid):
        root, sc = SCENARIOS / sid, self.scenarios[sid]
        ws = root / 'data' / 'workspace'
        rounds = {r['id']: r for r in json.loads((root / 'spec' / 'questions.json').read_text())['rounds']}
        frames = json.loads((root / 'data' / 'keyframes.json').read_text())['keyframes']
        docs = [f'--- {p.relative_to(ws)} ---\n{p.read_text().strip()}' for p in sorted(ws.rglob('*'))
                if p.is_file() and p.name not in ('AGENTS.md', 'IDENTITY.md', 'USER.md', 'README.md')]
        asks = []
        for qid in sc['test_rounds']:
            r = rounds[qid]
            opts = ''.join(f'\n  {k}: {v}' for k, v in r.get('eval', {}).get('options', {}).items())
            asks.append(f'{qid} ({r["type"]}): {r["question"]}{opts}')
        return '\n\n'.join([
            'Stakeholder request:\n' + (ws / 'USER.md').read_text().strip(),
            "Operating contract of this workspace (the stakeholder's rules):\n" + (ws / 'AGENTS.md').read_text().strip(),
            'What the walkthrough keyframes show:\n' + '\n'.join(f'- [clip @ {f["t"]}] {f["description"]}' for f in frames),
            'Workspace documents:\n' + '\n'.join(docs),
            'Later requests whose outputs are compared:\n' + '\n'.join(asks),
            'Expected results: ' + sc['expected_for_judge'],
        ])

    # ---- one scenario: learning invocation, then test invocation --------------------------------
    def run(self, item, cut, sample):
        sid = item['id']
        sc = self.scenarios[sid]
        self.cut, self.base = set(cut), f'{sid}|s{sample}'      # the tag names item and sample, not the arm
        self.replies, self.evolver_calls, self.last_qid, self.errors = {}, [], None, []
        self.attachments = {}
        self.questions = {r['id']: r for r in json.loads((SCENARIOS / sid / 'spec' / 'questions.json').read_text())['rounds']}
        work = Path(tempfile.mkdtemp(prefix=f'halo-visualclaw-{sid}-'))
        try:
            root = work / 'VisualClawArena' / 'scenarios' / sid
            shutil.copytree(SCENARIOS / sid / 'spec', root / 'spec')
            shutil.copytree(SCENARIOS / sid / 'data', root / 'data')
            (root / 'data' / 'clip').mkdir(exist_ok=True)
            (root / 'data' / 'clip' / 'clip.mp4').write_bytes(b'')   # placeholder; frames come from keyframes.json
            out = work / 'runs'
            bank, buffer = out / 'skill_bank', out / 'failure_buffer.jsonl'
            self.logdir = out / RUN_ID / 'agent_logs'
            cfg = work / 'config'
            cfg.mkdir()
            (cfg / 'config.yaml').write_text(yaml.safe_dump({
                'skill': {'skills_dir': str(bank), 'evolution_history_path': str(out / 'evolution_history.jsonl')},
                'memory': {'data_dir': str(out / 'memory_default'), 'user_memory_path': str(out / 'user_memory.md')},
            }))
            os.environ['MM_VISUALCLAW_CONFIG_DIR'] = str(cfg)
            cwd = os.getcwd()
            os.chdir(work)
            try:
                learn = self._invoke(root / 'spec', out, bank, buffer, sc['learning_rounds'], 'learn')
                evolved = self._bank_snapshot(bank)
                test = self._invoke(root / 'spec', out, bank, buffer, sc['test_rounds'], 'test')
            finally:
                os.chdir(cwd)
            return self._result(root, sc, learn, test, evolved, bank)
        finally:
            if not os.environ.get('HALO_VISUALCLAW_KEEP'):
                shutil.rmtree(work, ignore_errors=True)

    def _invoke(self, spec, out, bank, buffer, rounds, phase):
        self.phase, self.since_fire = phase, []
        rc = self.R.main(_runner_args(spec, out, bank, buffer, rounds))
        if self.errors:
            raise RuntimeError(f'backbone failed in the {phase} invocation: ' + ' | '.join(self.errors)[:1500])
        if rc != 0:
            raise RuntimeError(f'VisualClawArena runner exited with {rc} in the {phase} invocation')
        per_q = json.loads((out / RUN_ID / 'results.json').read_text(encoding='utf-8'))['per_question']
        logs = out / RUN_ID / 'agent_logs'
        rows = []
        for qid in rounds:
            r = per_q.get(qid, {})
            answer = logs / qid / 'answer.txt'
            rows.append({'id': qid, 'type': r.get('type'), 'passed': bool(r.get('passed')),
                         'extracted': r.get('extracted'), 'injected_skills': r.get('injected_skills', []),
                         'memory_hits': r.get('memory_hits', 0), 'memory_stored': r.get('memory_stored', 0),
                         'agent_status': r.get('agent_status'), 'check_stdout': (r.get('stdout_tail') or '').strip(),
                         'answer': answer.read_text(encoding='utf-8') if answer.exists() else '',
                         'reply': self.replies.get(qid, '')})
        return rows

    @staticmethod
    def _bank_snapshot(bank):
        seed = {p.parent.name for p in SEED_BANK.glob('*/SKILL.md')}
        tags = json.loads((bank / 'qa_types.json').read_text()) if (bank / 'qa_types.json').exists() else {}
        cards = []
        for path in sorted(bank.glob('*/SKILL.md')):
            if path.parent.name not in seed:
                cards.append({'name': path.parent.name, 'qa_types': tags.get(path.parent.name),
                              'card': path.read_text(encoding='utf-8')})
        return cards

    def _result(self, root, sc, learn, test, evolved, bank):
        from benchmark.visualclawarena.engines.codex_cli import WRITE_FILE_BLOCK_RE
        rounds = {r['id']: r for r in json.loads((root / 'spec' / 'questions.json').read_text())['rounds']}
        names = {c['name'] for c in evolved}
        blocks = []
        for r in test:
            q = rounds[r['id']]
            if q['type'] == 'multi_choice':
                blocks.append(f'Request {r["id"]} (multiple choice): {q["question"]}\n'
                              f'Chosen option: {r["extracted"] or "none"}\n'
                              f'End of the reply: {r["answer"].strip()[-600:]}')
            else:
                files = [f'--- {m.group(2)} ---\n{m.group(3).strip()[:2500]}'
                         for m in WRITE_FILE_BLOCK_RE.finditer(r['reply'])]
                blocks.append(f'Request {r["id"]} (file task): {q["question"]}\n'
                              + ('Files written:\n' + '\n'.join(files) if files else 'Files written: none')
                              + f'\nReply text: {r["answer"].strip()[-400:]}')
        history = bank / 'v3_evolution_history.jsonl'
        proposals = [json.loads(line) for line in history.read_text().splitlines() if line.strip()] if history.exists() else []
        n_test = len(test) or 1
        return {
            'output': '\n\n'.join(blocks),
            'learning': [{k: r[k] for k in ('id', 'type', 'passed', 'extracted', 'injected_skills', 'memory_hits')} for r in learn],
            'test': [{k: r[k] for k in ('id', 'type', 'passed', 'extracted', 'injected_skills', 'memory_hits', 'check_stdout')} for r in test],
            'evolved_skills': evolved,
            'evolver_proposals': [{'skills': [s.get('name') for s in p.get('skills', [])], 'written': p.get('skill_names', [])} for p in proposals],
            'evolver_calls': self.evolver_calls,
            'keyframes_attached_by': self.attachments,   # what in the message named _clip_frames/: round, skill or memory
            'metrics': {
                'test_pass_rate': round(sum(r['passed'] for r in test) / n_test, 4),
                'learn_pass_rate': round(sum(r['passed'] for r in learn) / (len(learn) or 1), 4),
                'evolver_calls_learning': sum(c['phase'] == 'learn' for c in self.evolver_calls),
                'skills_written_learning': len(evolved),
                'evolved_skill_injections_test': sum(len(set(r['injected_skills']) & names) for r in test),
                'memory_hits_test': sum(r['memory_hits'] or 0 for r in test),
                'test_rounds_with_frames_from_retained_text': sum(self.attachments.get(r['id']) in ('skill', 'memory') for r in test),
            },
        }
