"""HALO run-mode adapter for ContextAgent (openaiotlab/ContextAgent at commit f4674bf).

The configuration reviewed is the CAB/CAB-Lite evaluated reasoner: given the sensory context of one
sample (text) and the persona supplied with that sample, an LLM reasons, decides whether to offer help,
and plans a tool chain; the tools run; the tool results, contexts and thoughts go to the LLM again for
the final message. Each item runs src/icl/inference_api.py run_single_sample unchanged:

  reasoner   azure_inference with the repo's ICL prompt (prompt/baselines/icl_fs.txt, 10 demonstrations,
             thoughts and personas: the zs=false / w_t / w_p setting of src/cab_lite/icl/icl_infer_api.sh)
  parsing    utils.parse_proactive_agent_results, inference_api.parse_tool_spec
  tools      inference_api.run_tools -> utils.execute_tools_with_memory -> tool_registry.process_function_call,
             all tools in sandbox mode (their in-repo fake returns)
  response   inference_api.summarize_with_llm_azure (prompt/prompt_summarize.txt)

The fine-tuned reasoner (Qwen/Llama LoRA served by LLaMA-Factory, src/sft/inference.py) is replaced by the
HALO backbone. Its system prompt prompt/prompt_sys.txt carries no output format (the trained model learned
it), so the backbone gets the repo's own prompt for untrained API models instead. CAB-Lite has no training
split in the repo, so the demonstrations are drawn from data/cab/cab_train.json with the module's
random.seed(42) (inference_api.py:22), exactly as build_system_prompt draws them.

Replacements and settings:
  - `openai.AzureOpenAI` / `OpenAI` -> stub whose chat.completions.create calls the backbone (self.llm);
    temperature and max_tokens are not passed on. Reasoner and response calls carry the stage in the tag.
  - Libraries imported only by code the run never executes are stubbed and raise if called: the tools' live
    API clients (requests, geocoder, gcsa, dateparser, ddgs, googlesearch, yfinance, pandas,
    langchain_community) and utils.py's scoring/ollama imports (ollama, transformers, bert_score, sklearn).
    So no tool can reach the network; every tool returns its sandbox value.
  - The response step runs its model call: summarize_with_llm_azure returns the fixed string
    "sandbox outputs." when config.MODE == "sandbox" (inference_api.py:175-176), which would leave the
    acquired context unread. The adapter sets config.MODE = "live" only for the duration of that call;
    the tools, which ran before it, stay in sandbox mode.
  - The executor's clock (inference_api.py:139 seeds `now_iso` with datetime.now(); utils.parse_time_phrase
    falls back to it) is fixed at 2025-09-13 15:46:47, the time the sandboxed get_current_datetime returns
    (src/tools/get_current_time.py:12), so prompts do not depend on the day of the run and both arms
    resolve time phrases alike.
  - Credential environment variables read by the upstream modules are removed from this process first.
  - Identical backbone calls from parallel workers are serialized by a file lock (_shared_call), so arms
    that send the same prompt really share one cached reply (a gap in the harness, solved here).

Cut site:
  A->S  src/icl/inference_api.py:224-226 (run_single_sample hands the planned chain to run_tools, which
        passes it to utils.execute_tools_with_memory, src/utils.py:455-525). Under the cut, the calls to
        information-gathering tools in the plan (location, time, weather, agenda, health data, vision query,
        search and lookups) are not delivered to the executor, so nothing is acquired; effector calls
        (add_to_agenda, book_uber, play_music, set_timer, add_meeting, send_email) still run. The plan
        itself, and so the reasoner's reply, is unchanged and shared between arms.
No other channel is cut. The persona is a field of each sample ('Personas'), passed in fresh at
inference_api.py:193 and 199-203; nothing writes or keeps it across samples, so there is no retained memory
to withhold (the survey marks M->A not reported). The executor's `memory` dict (inference_api.py:139) is a
per-sample scratch buffer for $RESULT(...) placeholders, rebuilt for every sample.
"""
import argparse, contextlib, copy, datetime, fcntl, hashlib, json, os, random, sys, tempfile, types
from pathlib import Path
from halo.run.adapter import BaseAdapter

CORE = Path(__file__).resolve().parent / 'core'   # vendored upstream code, see core/SOURCE.md
LOCKS = Path(tempfile.gettempdir()) / 'halo-run-locks'

# Tool roles, from the tool set in prompt/baselines/icl_fs.txt and prompt/prompt_sys.txt.
SENSING = {'get_current_gps_coordinates', 'get_current_datetime', 'get_city_weather', 'check_agenda_time_conflict',
           'get_health_data', 'vllm', 'wikipedia_search', 'google_search', 'get_online_product_price',
           'get_medical_knowledge', 'google_map', 'check_bus_schedule', 'search_rednote', 'search_reddit', 'query_stock'}
EFFECTORS = {'add_to_agenda', 'book_uber', 'play_music', 'set_timer', 'add_meeting', 'send_email'}

# Setting of src/cab_lite/icl/icl_infer_api.sh ("false w_t w_p"), sandbox tools, 10 demonstrations.
ARGS = dict(mode='sandbox', model_base='halo-backbone', dataset='cab_lite', zs='false', personas='w_p',
            think='w_t', n_fewshot=10)

UNUSED = ['requests', 'geocoder', 'gcsa', 'gcsa.google_calendar', 'gcsa.event', 'dateparser', 'ddgs', 'googlesearch',
          'yfinance', 'pandas', 'langchain_community', 'langchain_community.utilities',
          'ollama', 'transformers', 'bert_score', 'sklearn', 'sklearn.metrics']
# Environment variables the upstream modules read (inference_api.py:32-34, the tools' module constants).
CREDENTIALS = ['AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_VERSION', 'GOOGLE_MAP_API_KEY',
               'AMAP_API_KEY', 'LOCATIONIQ_API_KEY', 'SERPAPI_KEY', 'GOOGLE_CALENDAR_ACCOUNT', 'API_KEY', 'API_PORT']


def _blocked_module(name):
    mod = types.ModuleType(name)
    mod.__path__ = []   # lets submodules such as gcsa.google_calendar be registered under it

    def __getattr__(attr):
        if attr.startswith('__'):
            raise AttributeError(attr)

        def blocked(*args, **kwargs):
            raise RuntimeError(f'{name}.{attr} is a live-mode dependency and is not available in the HALO run')
        return blocked
    mod.__getattr__ = __getattr__
    return mod


class Adapter(BaseAdapter):
    channels = {
        'A->S': 'information-gathering calls of the planned tool chain delivered to the tool executor '
                '(src/icl/inference_api.py run_tools -> src/utils.py execute_tools_with_memory)',
    }
    steps = {}   # no self-revision: fine-tuning is done offline by the authors

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag, self.base, self._errors = set(), '', '', []
        for k in CREDENTIALS:
            os.environ.pop(k, None)
        self._install_stubs()
        for p in (CORE / 'src' / 'icl', CORE / 'src'):
            sys.path.insert(0, str(p))
        import config
        import inference_api as ia
        self.config, self.ia = config, ia
        ia.apply_mode('sandbox')
        self._wrap_upstream()
        inputs = Path(case_dir) / 'inputs'
        self.samples = json.loads((inputs / 'cab_lite_samples.json').read_text())['samples']
        pool = json.loads((inputs / 'cab_train_demo_pool.json').read_text())
        train_ds = {k: pool['demos'].get(k) for k in pool['keys']}   # same keys, same order as cab_train.json
        with contextlib.chdir(CORE):                                  # upstream opens prompt files relative to the repo root
            base_prompt = ia.load_prompt_base(ARGS['zs'], ARGS['think'])
            random.seed(42)   # inference_api.py:22 seeds at import; main() then draws the demonstrations first
            self.sys_prompt, chosen = ia.build_system_prompt(base_prompt, ARGS['zs'], train_ds, ARGS['n_fewshot'],
                                                             ARGS['think'], ARGS['personas'])
        if chosen != pool['selected']:
            raise RuntimeError(f'demonstration draw differs from the recorded one: {chosen}')
        self.client = ia.get_azure_client()

    # ---- model clients -> HALO backbone; unused live dependencies blocked -------------------
    def _install_stubs(self):
        adapter = self

        def create(model=None, messages=None, **kwargs):
            system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
            user = '\n\n'.join(m['content'] for m in messages if m['role'] != 'system')
            try:
                text = adapter._shared_call(system, user, adapter.tag)
            except Exception as e:   # upstream turns errors into reply text; re-raised in run()
                adapter._errors.append(f'{type(e).__name__}: {e}')
                raise
            msg = types.SimpleNamespace(content=text)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)

        class _Client:
            def __init__(self, *args, **kwargs):
                self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))

        openai = types.ModuleType('openai')
        openai.AzureOpenAI, openai.OpenAI = _Client, _Client
        sys.modules['openai'] = openai
        for name in UNUSED:
            sys.modules[name] = _blocked_module(name)

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

    def _wrap_upstream(self):
        adapter, ia, config = self, self.ia, self.config
        run_tools, summarize = ia.run_tools, ia.summarize_with_llm_azure

        def run_tools_with_cut(json_tool):
            # A->S cut site: information-gathering calls of the plan do not reach the executor.
            if 'A->S' in adapter.cut:
                json_tool = [c for c in json_tool if not (isinstance(c, dict) and c.get('name') in SENSING)]
            return run_tools(json_tool)

        def summarize_with_model(*args, **kwargs):
            adapter.tag = adapter.base + '|respond'
            config.MODE = 'live'          # only the response step's model call; the tools already ran
            try:
                return summarize(*args, **kwargs)
            finally:
                config.MODE = 'sandbox'

        ia.run_tools, ia.summarize_with_llm_azure = run_tools_with_cut, summarize_with_model

        # The executor seeds its memory with the machine clock (inference_api.py:139) and resolves time
        # phrases against it (utils.py:313-379). Fix that clock at the sandbox's own time, the value the
        # sandboxed get_current_datetime returns (src/tools/get_current_time.py:12), so a run does not depend
        # on the day it is made and both arms resolve "this weekend" the same way.
        class SandboxClock(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2025, 9, 13, 15, 46, 47)

        ia.datetime = sys.modules['utils'].datetime = SandboxClock

    # ---- items ------------------------------------------------------------------------------
    @staticmethod
    def _situation(sample):
        persona = '.'.join(sample.get('Personas', [])) or '(none)'
        return ('The assistant runs on the user\'s smart glasses and earphones and decides on its own whether to '
                'offer help; the user has not asked for anything.\n'
                f'What the device senses (camera and microphone, as text): {sample["Rawdata Context"]}\n'
                f'Persona supplied with this sample: {persona}')

    def items(self):
        return [{'id': k, 'judge_context': self._situation(s)} for k, s in self.samples.items()]

    def run(self, item, cut, sample):
        key = item['id']
        record = copy.deepcopy(self.samples[key])
        self.cut, self._errors = set(cut), []
        # The tag names the sample, the repetition and the stage, not the arm (docs/adding_a_case.md).
        self.base = f'{key}|s{sample}'
        self.tag = self.base + '|reason'
        with contextlib.chdir(CORE):
            preds = self.ia.run_single_sample(self.client, key, record, argparse.Namespace(**ARGS),
                                              self.sys_prompt, ARGS['dataset'])
        if self._errors:
            raise RuntimeError(f'backbone failed: {self._errors[-1]}')

        planned = self.ia.parse_tool_spec(preds['tools']) if preds['tools'] != 'None' else []
        results = preds['tools_results'] if isinstance(preds['tools_results'], list) else []
        names = [c.get('name') for c in planned if isinstance(c, dict)]
        acquired = [r for r in results if r.get('tool_name') in SENSING]
        readings = '\n'.join(f'  {r["tool_name"]}({json.dumps(r["tool_parameters"], ensure_ascii=False)}) -> '
                             f'{json.dumps(r["results"], ensure_ascii=False)}' for r in results) or '  (no tool ran)'
        response = preds['response'] if preds['response'] not in ('None', None, '') else ''
        score = str(preds['proactive_score'])
        return {
            'output': response or '(no proactive message)',
            'context': self._situation(self.samples[key]) +
                       '\nTools the assistant ran and what they returned (the device\'s sensors and services; '
                       'treat these readings as true):\n' + readings,
            'decision': {'proactive_index': preds['proactive_idx'], 'proactive_score': preds['proactive_score'],
                         'thoughts': preds['thoughts'], 'actions': preds['actions']},
            'planned_tools': planned,
            'tool_results': results,
            'gold_tools': [t.get('name') for t in json.loads(self.samples[key]['Tools'])],
            'metrics': {
                'proactive': int(str(preds['proactive_idx']).lower() == 'true'),
                'proactive_score': int(score) if score.isdigit() else None,
                'sensing_calls_planned': sum(n in SENSING for n in names),
                'sensing_results_delivered': len(acquired),
                'effector_calls_run': sum(r.get('tool_name') in EFFECTORS for r in results),
                'tool_errors': sum(isinstance(r.get('results'), dict) and 'error' in r['results'] for r in results),
            },
        }
