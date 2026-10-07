"""HALO run-mode adapter for User as Code (19PINE-AI/user-as-code at commit 3d47361).

Configuration (case.yaml): two-phase executable personal memory with the Active Service constraint
pipeline. One item is one Active Service scenario from the upstream suite (user-authored sessions with
dates; the last session is a cue-free update) followed by one question the user asks. For every
session, in order:

  memory        UserAsCodeV5.ingest_session (experiments/user_as_code_v5.py:65-89): Phase 1 extracts
                every fact, appends it to the fact list and its Chroma index, and archives the raw
                session in Chroma.
  constraints   the per-session body of run_uac_case (experiments/run_active_service_v3.py:167-209),
                reproduced in _update() around upstream calls: the session joins the retained
                history (v2.render_history), the model writes the memory-and-constraint IR
                (generate_valid_ir, up to three validated attempts), trusted code compiles it
                (active_service_engine.compile_constraint_module), the module is written to the
                run's programs directory and validated (v2.validate_generated_source), and the stored
                module is executed in the isolated sandbox at the session date
                (v2.execute_generated_source -> experiments/active_service_sandbox.py, 5 s timeout,
                CPU/memory/file limits, inside the run's temporary directory).
After the last session the question goes to UserAsCodeV5.answer (user_as_code_v5.py:269-296), which
runs Phase 2 (structure(): typed Python dataclasses from the fact list) and the three-channel
retrieval (structured code, facts, archive excerpts).

Replaced: krill_client.krill_call (the GPT-5.6 Luna client) -> the HALO backbone; KrillModelGenerator
-> a generator over the same backbone; Chroma's default embedder (an ONNX copy of all-MiniLM-L6-v2
that it downloads) -> sentence-transformers/all-MiniLM-L6-v2 from the local cache.

Cut sites (upstream file:line where the receiver gets what the cut withholds):
  S->M      user sessions are not retained: the Phase-1 writes user_as_code_v5.py:79 (fact_list),
            :83 (fact index) and :156 (archive) are dropped, and the session is not added to the
            retained history at run_active_service_v3.py:168, so each IR update sees only the
            current session.
  M->A      retained memory does not reach the answer: the retrieval result read at
            user_as_code_v5.py:277 (structured code, facts, archive excerpts) is empty.
  revision  the compiled constraint module is generated but not written at run_active_service_v3.py:184;
            later updates execute the newest module that was stored (run_active_service_v3.py:198),
            so they run without the new constraints (this also covers later_use).
The service keeps no record of its alerts and receives no outcome for them, so record, outcome and
attribution have no site in this configuration.
"""
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'
EXPERIMENTS = CORE / 'experiments'


class _CutList(list):
    """fact_list whose writes the S->M cut drops (user_as_code_v5.py:79)."""

    def __init__(self, adapter):
        super().__init__()
        self._adapter = adapter

    def extend(self, items):
        if self._adapter._withhold('S->M', 'fact_list.extend'):
            return
        super().extend(items)


class _CutCollection:
    """A Chroma collection whose add() the S->M cut drops (user_as_code_v5.py:83, :156)."""

    def __init__(self, collection, adapter, site):
        self._c, self._adapter, self._site = collection, adapter, site

    def add(self, *args, **kwargs):
        if self._adapter._withhold('S->M', self._site):
            return None
        return self._c.add(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._c, name)


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'user sessions become Phase-1 facts, archive chunks and the retained history the constraint IR is written from',
        'M->A': 'structured code, retrieved facts and archive excerpts delivered to the answer',
    }
    steps = {
        'revision': 'the compiled constraint module (a reusable alert rule) is written to the programs directory; '
                    'later updates execute the newest stored module (covers later_use)',
    }

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag_base, self.stage, self.withheld = set(), '', '', {}
        self._install_stubs()
        sys.path.insert(0, str(EXPERIMENTS))
        import active_service_engine as engine
        import run_active_service_v2 as v2
        import run_active_service_v3 as v3
        import user_as_code_v5 as uac
        self.engine, self.v2, self.v3, self.uac = engine, v2, v3, uac
        protocol = v2.load_protocol()
        scenarios = v2.load_scenario_map(CORE / protocol['source_suite']['path'])
        self.rubrics = protocol['rubrics']
        spec = json.loads((CASE / 'inputs' / 'items.json').read_text())
        self.items_spec = {s['scenario']: s for s in spec['items']}
        self.scenarios = {}
        for sid in self.items_spec:
            v2.validate_scenario(scenarios[sid])
            self.scenarios[sid] = scenarios[sid]

    # ---- replacements -----------------------------------------------------------------------
    def _install_stubs(self):
        adapter = self

        def krill_call(contents, system_instruction=None, *, model=None, max_retries=6, thinking_budget=None,
                       temperature=None):
            # experiments/krill_client.py:122: system message (optional) + user message, text reply
            return adapter.llm(system_instruction or '', contents, tag=f'{adapter.tag_base}|{adapter.stage}').strip()

        mod = types.ModuleType('krill_client')
        mod.KRILL_MODEL, mod.KRILL_BASE_URL = 'halo-backbone', ''
        mod.krill_call = krill_call
        mod.usage_snapshot = lambda: {}
        sys.modules['krill_client'] = mod

        # Outbound network is disabled in this process: the backbone runs in its own subprocess and
        # everything else is local.
        import socket
        real_connect = socket.socket.connect

        def _connect(sock, address):
            if not isinstance(address, tuple) or str(address[0]) in ('127.0.0.1', '::1', 'localhost'):
                return real_connect(sock, address)
            raise ConnectionRefusedError(f'outbound network is disabled in this HALO run ({address[0]})')
        socket.socket.connect = _connect

        # Chroma's default embedder downloads an ONNX all-MiniLM-L6-v2; use the same model from the
        # local sentence-transformers cache instead. Chroma's anonymized telemetry is off.
        os.environ['ANONYMIZED_TELEMETRY'] = 'False'
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        ef = SentenceTransformerEmbeddingFunction(model_name='sentence-transformers/all-MiniLM-L6-v2', device='cpu')
        real_client = chromadb.Client

        class _Client:
            def __init__(self, *a, **k):
                if not a and 'settings' not in k:
                    k['settings'] = Settings(anonymized_telemetry=False)
                self._c = real_client(*a, **k)

            def create_collection(self, *a, **k):
                k.setdefault('embedding_function', ef)
                return self._c.create_collection(*a, **k)

            def __getattr__(self, name):
                return getattr(self._c, name)

        chromadb.Client = _Client

    class _Generator:
        """Stands in for run_active_service_v2.KrillModelGenerator (the same call, the HALO backbone)."""

        def __init__(self, adapter):
            self.adapter = adapter

        def generate(self, system_prompt, user_prompt):
            text = self.adapter.llm(system_prompt, user_prompt, tag=f'{self.adapter.tag_base}|{self.adapter.stage}')
            return {'text': text.strip(), 'latency_seconds': 0.0, 'usage': {}}

    def _withhold(self, channel, site):
        if channel in self.cut:
            key = f'{channel}:{site}'
            self.withheld[key] = self.withheld.get(key, 0) + 1
            return True
        return False

    # ---- items ------------------------------------------------------------------------------
    def items(self):
        out = []
        for sid, spec in self.items_spec.items():
            scen = self.scenarios[sid]
            sessions = self.v2.scenario_sessions(scen)
            told = '\n'.join(f'- {s["timestamp"]}: "{s["user_text"]}"' for s in sessions)
            out.append({'id': sid, 'judge_context': (
                'A personal assistant keeps an executable memory of what the user tells it and, after every '
                'update, runs stored constraint checks that can raise an alert without being asked. The user '
                f'wrote these updates, in order (the last one is the newest):\n{told}\n'
                f'Afterwards the user asked: "{spec["question"]}"\n'
                f'Reference, from the scenario author: at the last update a good assistant raises this alert: '
                f'"{scen["expected_alert"]["message"]}" Before the last update nothing was actionable yet.')})
        return out

    # ---- one run ----------------------------------------------------------------------------
    def run(self, item, cut, sample):
        sid = item['id']
        scen, spec = self.scenarios[sid], self.items_spec[sid]
        self.cut, self.withheld = set(cut), {}
        self.tag_base = f'{sid}|s{sample}'
        sessions = self.v2.scenario_sessions(scen)
        workdir = Path(tempfile.mkdtemp(prefix='halo-uac-'))
        try:
            memory = self.uac.UserAsCodeV5(user_id=f'halo-{sid}')
            memory.fact_list = _CutList(self)
            memory._facts_db = _CutCollection(memory._facts_db, self, 'facts_db.add')
            memory._archive = _CutCollection(memory._archive, self, 'archive.add')
            if 'M->A' in self.cut:
                def _no_retrieval(query, top_k=10):
                    self._withhold('M->A', 'answer context (retrieve)')
                    return ''
                memory.retrieve = _no_retrieval
            programs = workdir / 'programs'
            cumulative, updates = [], []
            for index, session in enumerate(sessions):
                stage = 'trigger' if index == len(sessions) - 1 else 'pretrigger'
                self.stage = f'{session["session_id"]}/phase1'
                memory.ingest_session([f'User: {session["user_text"]}'], str(session['session_id']),
                                      session['timestamp'])
                updates.append(self._update(sid, index, stage, session, cumulative, programs))
            self.stage = 'answer'
            answer = memory.answer(spec['question'])
            facts_stored = len(memory.fact_list)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        return self._result(sid, scen, spec, sessions, updates, answer, facts_stored)

    def _update(self, sid, index, stage, session, cumulative, programs):
        """run_active_service_v3.run_uac_case, one session (lines 167-209), with the S->M and revision sites."""
        v2, v3, engine = self.v2, self.v3, self.engine
        if not self._withhold('S->M', 'retained history (run_active_service_v3.py:168)'):
            cumulative.append(session)
        history = v2.render_history(cumulative if session in cumulative else [session])
        update = {'stage': stage, 'date': session['timestamp'], 'alerts': [], 'stored': False}
        self.stage = f'{session["session_id"]}/ir'
        try:
            ir, attempts = v3.generate_valid_ir(self._Generator(self), session['timestamp'], history)
            update['ir_attempts'] = len(attempts)
            update['constraints'] = [c['id'] for c in ir['constraints']]
            source = engine.compile_constraint_module(ir)
            source_path = programs / sid / f'{index + 1:02d}_{stage}.py'
            if not self._withhold('revision', 'module write (run_active_service_v3.py:184)'):
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(source, encoding='utf-8')
                update['stored'] = True
            update['validation'] = v2.validate_generated_source(source)['valid']
        except Exception as exc:     # upstream records the failure and skips execution for this update
            update['error'] = f'generation_ir_or_compilation: {exc}'[:500]
            return update
        # later use: the newest stored module runs (upstream runs the module it has just stored; under
        # the revision cut nothing new was stored, so the previous mechanism, if any, runs)
        stored = sorted((programs / sid).glob('*.py')) if (programs / sid).exists() else []
        update['executed_module'] = stored[-1].name if stored else None
        if stored:
            try:
                execution = v2.execute_generated_source(stored[-1], session['timestamp'])
                update['alerts'] = [str(a['message']) for a in execution['alerts']]
            except Exception as exc:
                update['error'] = f'execution: {exc}'[:500]
        return update

    # ---- outputs ----------------------------------------------------------------------------
    def _result(self, sid, scen, spec, sessions, updates, answer, facts_stored):
        alert_lines = []
        for u in updates:
            when = 'last update' if u['stage'] == 'trigger' else 'earlier update'
            if u['alerts']:
                alert_lines += [f'[{u["date"]}, {when}] ALERT: {a}' for a in u['alerts']]
            else:
                alert_lines.append(f'[{u["date"]}, {when}] no alert')
        trigger = next(u for u in updates if u['stage'] == 'trigger')
        score = self.v2.score_candidates(trigger['alerts'], self.rubrics[sid])
        hits = sum(any(alt.lower() in answer.lower() for alt in kw.split('|')) for kw in spec['expect'])
        answer_text = f'User asked: {spec["question"]}\nAssistant answered: {answer}'
        return {
            'output': '\n'.join(alert_lines) + '\n\n' + answer_text,
            'output_alerts': '\n'.join(alert_lines),
            'output_answer': answer_text,
            'updates': updates,
            'withheld': dict(self.withheld),
            'metrics': {
                'trigger_rubric_passed': int(score['passed']),
                'trigger_alerts': len(trigger['alerts']),
                'pretrigger_alerts': sum(len(u['alerts']) for u in updates if u['stage'] == 'pretrigger'),
                'answer_expected_hits': round(hits / len(spec['expect']), 4) if spec['expect'] else None,
                'facts_stored': facts_stored,
                'modules_stored': sum(1 for u in updates if u.get('stored')),
                'update_errors': sum(1 for u in updates if u.get('error')),
            },
        }
