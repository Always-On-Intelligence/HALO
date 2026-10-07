"""HALO run-mode adapter for PASK (xzf-thu/Pask at commit d54646c).

What the repository releases is the LatentNeeds-Bench protocol, not the deployed system: the
IntentFlow weights, the MemLoader, the Pask-MM tree store and the PAS runtime are not in it. The
run therefore executes the two pieces of the DD-MM loop that are released, unchanged:

  Memory (Pask-MM stand-in)  bench/03c_memory.py run(): at a part boundary, the earlier part of the
                             stream is turned into a memory document for the AI serving the primary
                             user (MEMORY_SYSTEM, build_memory_prompt), through bench/llm_client.py
                             AsyncLLMClient.complete_json. This is the memory field that the evaluated
                             IntentFlow read in LatentNeeds-Bench (03c -> 03d -> LatentNeeds-Bench.jsonl).
  Demand detection (DD)      eval/run.py build_tasks + eval_model + parse_response with eval/prompts.py
                             build_prompt at the 'neutral' level (IntentFlow's reported run,
                             eval/results/intentflow_neutral.jsonl): at every turn of the later part the
                             model gets scene, memory, the part's dialogue so far and the current turn,
                             and outputs either a proactive response or [NO_DEMAND].

Each item is one conversation split into an earlier and a later part, as bench/02_build_turns.py
splits long sessions. The memory is written at the boundary, before the later part streams, so
build_memory_prompt takes its own '(no preview available)' branch (03c_memory.py:76-80); the benchmark
build gave the writer a five-turn preview of the next part, which an online system would not have.

Only the model clients are replaced: the `openai` module that bench/llm_client.py and eval/run.py
import is a stub whose chat.completions.create sends the messages to the HALO backbone. The stub's
async create finishes the backbone call without yielding, so the 60 s asyncio.wait_for in
eval/run.py:103-106 cannot cancel a 20-120 s backbone call. Temperature, max_tokens and
reasoning_effort are not passed on (the CLI backends do not expose them). A retry of an identical
prompt (complete_json re-asks after a JSON parse failure, call_one after an API error) gets a
'|retryN' tag so that it is a new backbone call, not the cached reply. Backbone failures that the
upstream retry loops would turn into silence or an empty memory are re-raised after the loop. The
API-key and endpoint variables the modules read at import are removed from this process first.
Identical backbone calls from parallel workers are serialized by a file lock (_shared_call), so arms
that send the same prompt really share one cached reply (a gap in the harness, solved here).

Cut sites (both at the receiving end):
  S->M  bench/03c_memory.py:141-151 -- the earlier part of the stream is not delivered to the memory
        writer, so run() takes its 'no prior part found' branch and the memory stays "".
  M->A  eval/prompts.py:95,118-119 -- the memory is not delivered to the demand-detection prompt
        (session['memory'] = None, so the '[Memory from earlier conversation]' block is left out).
The two sites lie on one serial path (one writer, one reader), so both cut arms send the same
demand-detection prompts and share cached replies; the S->M arm also skips the memory-writing call.
No evidence step is cut: PASK's runtime does not revise its own mechanism (IntentFlow is trained
offline; Pask-MM's post-session updates change memory content).
"""
import asyncio, fcntl, hashlib, importlib, json, os, re, sys, tempfile, types
from pathlib import Path
from halo.run.adapter import BaseAdapter

CORE = Path(__file__).resolve().parent / 'core'   # vendored upstream code, see core/SOURCE.md
LOCKS = Path(tempfile.gettempdir()) / 'halo-run-locks'
CREDENTIALS = ['OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENROUTER_API_KEY', 'OPENROUTER_BASE_URL', 'VLLM_BASE_URL']
LEVEL = 'neutral'                                  # IntentFlow's reported prompt level
# Model entry in the form eval/config.py uses for a locally served model (line 16); the stub ignores the URL.
MODEL_CFG = {'id': 'intentflow', 'name': 'intentflow', 'base_url': 'halo-backbone', 'api_key': 'EMPTY'}


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'earlier stream turns delivered to the memory writer (bench/03c_memory.py build_memory_prompt)',
        'M->A': 'memory document delivered to the demand-detection prompt (eval/prompts.py build_prompt)',
    }
    steps = {}   # no self-revision in the released code

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.tag, self._seen, self._errors = '', {}, []
        for k in CREDENTIALS:   # read into module constants by bench/llm_client.py:38-41, eval/config.py:16
            os.environ.pop(k, None)
        self._install_openai_stub()
        sys.path.insert(0, str(CORE))
        from eval import run as dd_run                 # inserts core/bench into sys.path itself (run.py:19-21)
        self.dd = dd_run
        self.mm = importlib.import_module('03c_memory')
        data = json.loads((Path(case_dir) / 'inputs' / 'streams.json').read_text())
        self.streams = {s['id']: s for s in data['streams']}

    # ---- model clients -> HALO backbone ----------------------------------------------------
    def _install_openai_stub(self):
        adapter = self

        def reply(messages):
            system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
            user = '\n\n'.join(m['content'] for m in messages if m['role'] != 'system')
            text = adapter._call(system, user)
            msg = types.SimpleNamespace(content=text)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)

        class _Completions:
            def create(self, model=None, messages=None, **kwargs):
                return reply(messages)

        class _AsyncCompletions:
            async def create(self, model=None, messages=None, **kwargs):
                return reply(messages)   # no await inside: the call cannot be cancelled half-way

        class OpenAI:
            def __init__(self, *args, **kwargs):
                self.chat = types.SimpleNamespace(completions=_Completions())

        class AsyncOpenAI:
            def __init__(self, *args, **kwargs):
                self.chat = types.SimpleNamespace(completions=_AsyncCompletions())

        mod = types.ModuleType('openai')
        mod.OpenAI, mod.AsyncOpenAI = OpenAI, AsyncOpenAI
        sys.modules['openai'] = mod

    def _call(self, system, user):
        key = hashlib.sha256((system + '\0' + user).encode()).hexdigest()
        n = self._seen.get(key, 0)
        self._seen[key] = n + 1
        try:
            return self._shared_call(system, user, self.tag + (f'|retry{n}' if n else ''))
        except Exception as e:   # upstream retry loops would swallow this; re-raised in run()
            self._errors.append(f'{type(e).__name__}: {e}')
            raise

    def _shared_call(self, system, user, tag):
        """Arms are paired by sharing the cached reply to an identical call, but parallel workers that
        miss the cache at the same moment would each get a fresh reply. Identical calls therefore take
        a file lock (outside the repo, in the system temp dir), so the second one reads the cached reply."""
        key = hashlib.sha256(json.dumps([str(getattr(self.llm, 'cache', '')), tag, system, user]).encode()).hexdigest()
        LOCKS.mkdir(exist_ok=True)
        with open(LOCKS / f'{key}.lock', 'w') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                return self.llm(system, user, tag=tag)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _check(self, stage):
        if self._errors:
            raise RuntimeError(f'backbone failed during {stage}: {self._errors[-1]}')

    # ---- sessions in the LatentNeeds-Bench format ----------------------------------------------
    def _parts(self, st):
        base = {'original_session_id': st['id'], 'subcategory': st['subcategory'], 'language': st['language'],
                'scene': st['scene'], 'total_parts': 2}
        earlier = dict(base, session_id=f'{st["id"]}_p0', part_index=0,
                       turns=[dict(t, turn_id=i) for i, t in enumerate(st['earlier'])])
        later = dict(base, session_id=f'{st["id"]}_p1', part_index=1, turns=[
            dict(t, turn_id=i, annotation={'has_demand': i in st['need_turns'], 'demands': []})
            for i, t in enumerate(st['later'])])
        return earlier, later

    def _write_memory(self, sessions):
        """bench/03c_memory.py run() over the parts present at the boundary; returns the later part's memory."""
        with tempfile.TemporaryDirectory() as d:
            inp, out = Path(d) / 'in.jsonl', Path(d) / 'out.jsonl'
            inp.write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in sessions))
            asyncio.run(self.mm.run(input_file=inp, output_file=out, concurrency=1, max_sessions=0))
            rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        return next(r for r in rows if r['part_index'] == 1).get('memory') or ''

    def _detect(self, session):
        """eval/run.py: one demand-detection call per turn of the later part."""
        tasks = self.dd.build_tasks([session], LEVEL)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'results.jsonl'
            asyncio.run(self.dd.eval_model(MODEL_CFG, tasks, out, concurrency=1))
            rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
        return sorted(rows, key=lambda r: r['turn_id'])

    # ---- items ------------------------------------------------------------------------------
    def items(self):
        out = []
        for st in self.streams.values():
            sc = st['scene']
            people = '; '.join(f'{c["name"]} ({c["role"]}, {c["background"]})' for c in sc['characters'])
            ctx = (f'Scene: {sc["scene"]}\nPeople: {people}\n'
                   f'Primary user (the person the assistant serves): {sc["primary_user"]["name"]}, '
                   f'{sc["primary_user"]["reason"]}.\n\n'
                   'Earlier part of the conversation (the assistant may only know it through its memory):\n'
                   + '\n'.join(f'  {t["speaker"]}: {t["text"]}' for t in st['earlier'])
                   + '\n\nLater part (at each turn T1-T%d the assistant either stays silent or speaks up):\n'
                   % len(st['later'])
                   + '\n'.join(f'  T{i + 1} {t["speaker"]}: {t["text"]}' for i, t in enumerate(st['later'])))
            out.append({'id': st['id'], 'judge_context': ctx})
        return out

    def run(self, item, cut, sample):
        st = self.streams[item['id']]
        cut = set(cut)
        self._seen, self._errors = {}, []
        # The tag names the stream, the sample and the stage, not the arm (see docs/adding_a_case.md).
        base = f'{st["id"]}|s{sample}'
        earlier, later = self._parts(st)

        # Memory write at the part boundary: the later part has not streamed yet.
        self.tag = base + '|memory'
        boundary = dict(later, turns=[])
        memory = self._write_memory([boundary] if 'S->M' in cut else [earlier, boundary])
        self._check('memory writing')

        # Demand detection at every turn of the later part.
        self.tag = base + '|dd'
        delivered = None if 'M->A' in cut else memory
        rows = self._detect(dict(later, memory=delivered))
        self._check('demand detection')

        lines, hits, cited, other = [], 0, 0, 0
        for r in rows:
            i, said = r['turn_id'], r['response'] if r['has_response'] else ''
            lines.append(f'T{i + 1}: ' + (said if said else '(silent)'))
            if i in st['need_turns']:
                hits += bool(said)
                cited += bool(said) and any(re.search(c, said, re.I) for c in st['cues'])
            else:
                other += bool(said)
        n_need = len(st['need_turns'])
        return {
            'output': '\n'.join(lines),
            'memory_written': memory,
            'memory_delivered': bool(delivered),
            'decisions': [{'turn': r['turn_id'] + 1, 'has_response': r['has_response'], 'response': r['response']}
                          for r in rows],
            'metrics': {
                'interventions': sum(r['has_response'] for r in rows),
                'need_turn_hit_rate': round(hits / n_need, 4),
                'need_turn_uses_earlier_rate': round(cited / n_need, 4),
                'other_turn_interventions': other,
                'memory_chars_delivered': len(delivered or ''),
            },
        }
