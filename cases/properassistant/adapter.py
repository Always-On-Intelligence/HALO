"""HALO run-mode adapter for ProPerAssistant (jiho283/ProPerSim at commit 013b9ee).

ProPerSim pairs a user agent (John Lin, a Generative Agents persona with a hidden preference rubric) with
the assistant (Eddy Lin). At every simulation step the assistant reads its memory, sees John's current
activity and either recommends something or answers "No Recommendation". In the reviewed setting
(RANKING "ranking", FORCE_NOREC_RATIO "norec0") it samples two candidates per step, the user agent rates
both on four criteria, the higher-rated candidate becomes "chosen" in a preference pair, and at 00:02:30
every night the assistant's LoRA adapter is retrained with DPO on these pairs.

What runs from core/ (paths below are under core/reverie/backend_server): Agent and Persona with their
memories (agent/agent.py, persona/persona.py), suggest/make_suggestion with memory retrieval
(agent/cognitive_modules/suggestion.py, retrieve.py), the suggestion prompt, parsing and refine step
(agent/prompt_template/run_gpt_prompt.py:2456-2613), opensource_inference (gpt_structure.py:198-303), the
user agent's rating, memory and summaries (persona/cognitive_modules/evaluation.py), the preference-pair
builder (agent/agent.py:262-362), the nightly update with its replay buffer (agent/agent.py:368-482) and
update_total_records. The adapter reproduces reverie.py's per-step body for this setting (lines 437-466
and 477-479) and the 00:02:30 update (lines 389-392); reverie.py itself (Django front end, maze, Llama
tokenizer for logging) is not run. John's activity at each moment is scripted (inputs/days.json) instead
of being planned by Generative Agents; it reaches the assistant through John's scratch.act_description,
as in the upstream loop.

Replaced (model clients only):
  * Llama-3.3-70B (+ LoRA) behind persona.suggestion_model -> _Llama/_Tokenizer: opensource_inference runs
    unchanged and model.generate sends its system/user turns to the HALO backbone.
  * DPO_train (opensource_training_methods.py:19-117) -> _dpo_substitute. No weights can be trained here
    (no GPU, 70B model). The substitute receives the same combined_preference_data that update_suggestion_model
    passes to DPO_train and writes a durable prompt-level revision into the LoRA model object: a block of
    the chosen/rejected pairs (each with the [ACTION] part of its prompt) that every later generate() call
    appends to the system prompt. This is a prompt-level revision standing in for LoRA DPO.
  * OpenAI client (gpt-4o-mini refine and memory summaries, text-embedding-3-small) and the Gemini client
    (gemini-2.0 user rating): chat calls go to the backbone (assistant side) or to a second LLM with the
    same backend (user-simulator side, tags prefixed 'user:'); embeddings are all-MiniLM-L6-v2 on CPU.
  * The five per-criterion rating calls of run_gpt_prompt_make_evaluation_seperate are answered in one
    user-simulator call: the function runs once to collect its five prompts, they are answered together,
    and the function runs again on those answers (parsing and score combination stay upstream).
  * temp_sleep (API pacing in both gpt_structure.py files) is a no-op. JSON objects in replies are re-serialized
    with standard spacing (_spaced): the upstream parsers split on '"Suggestion": ' and similar, and the
    backbone writes compact JSON.
  * Last day: only the delivered candidate (cand2) is generated and rated; summaries that nothing reads
    (the user agent's at the last moment of a day, the assistant's at the last moment) are not requested.

Cut sites:
  S->M  persona/cognitive_modules/evaluation.py:157-158,193-194,240: the assistant's memory record is built
        from scratch.user_action_for_suggestion; the cut blanks it while the assistant's record is written.
  M->A  agent/cognitive_modules/suggestion.py:108: the retrieved memory goes to run_gpt_prompt_make_suggestion
        as `retrieved` ([MEMORY] block, run_gpt_prompt.py:2483-2497); the cut passes "No Relevant Memory",
        the code's own value when nothing is retrieved (suggestion.py:80-82).
  A->M  persona/cognitive_modules/evaluation.py:193-194: at AGENT_MEMORY_LEVEL "AS" the record holds the
        assistant's suggestion; the cut writes it at the code's "A" level (lines 196-197), user action only.
  record       reverie.py:462 -> agent/agent.py:294-305: the preference data gets empty assistant turns
               instead of the assistant's two suggestions, so no usable pair reaches the update.
  outcome      reverie.py:453-461: the ratings do not reach the pair builder; better_num keeps its initial ''
               and update_preference_data adds no pair (agent.py:307-314).
  attribution  reverie.py:462: each candidate's rating is attached to the other candidate (suggestion_1 and
               suggestion_2 exchanged), so chosen and rejected are swapped.
  revision     agent/agent.py:457 (DPO_train): the update is built but not written into the model, so the
               next day runs with the unrevised policy (this also removes later use).
Not cut: A->S and M->S. John's activities come from his own planner (scripted here) and his perception skips
the assistant's suggestion events (persona/cognitive_modules/perceive.py:112); nothing from the assistant's
memory or actions steers what it observes.
"""
import contextlib, datetime, io, json, os, re, shutil, sys, tempfile, types
from pathlib import Path
from types import SimpleNamespace
from halo.run.adapter import BaseAdapter
from halo.run.llm import LLM

CASE = Path(__file__).resolve().parent
SERVER = CASE / 'core' / 'reverie' / 'backend_server'
STORAGE = CASE / 'core' / 'environment' / 'frontend_server' / 'storage'
WORK = CASE / '.work'

# utils.py as the upstream README asks for it (Step 1), with the setting the survey reviewed.
CONFIG = [('AGENT_MODEL', 'llama-3.3-70b'), ('TRAIN_METHOD', 'DPO'), ('PERSONA_GIVEN', ''), ('REASON_', 'noreason'),
          ('MEMORY_RET', 'ret_suggest'), ('RANKING', 'ranking'), ('AGENT_MEMORY_LEVEL', 'AS'),
          ('EVALUATOR', 'gemini-2.0'), ('EVALUATE_SEPERATE', 'seperate'), ('FORCE_NOREC_RATIO', 'norec0'),
          ('VISUALIZATION', 'novis'), ('REPLAY_BUFFER', 'equally200'), ('REC_REVISION', 'recnorev'), ('MMLU_EVAL', '')]
TRAIN_MODE = '_'.join(v for _, v in CONFIG)
NO_MEMORY = 'No Relevant Memory'          # agent/cognitive_modules/suggestion.py:82
# First lines of the prompt templates that reach the OpenAI client: (role, kind)
CHAT_TEMPLATES = [
    ('Please keep the content of the following sentence as it is', 'assistant', 'refine'),   # agent .../refine_suggestion.txt
    ('You are an assistant that provides recommendations to help the user.', 'assistant', 'memory-summary'),  # agent_summ_*.txt
    ('I live with an assistant', 'user', 'memory-summary'),                                   # summarization_*.txt
]
BATCH_SYSTEM = ('You will receive several separate prompts. Answer each one on its own, exactly as if it were the only '
                'prompt you received, in the output format that prompt asks for. Start each answer on a new line with '
                'the marker "### ANSWER k ###", where k is the number of the prompt, and write nothing else.')
LEARNED_HEADER = ('[PREFERENCE DATA FROM EARLIER DAYS]\nIn each situation below you gave two responses and the user rated '
                  'the chosen response above the rejected one. Respond the way the chosen responses do and avoid what '
                  'the rejected responses did.')


# ---- stand-ins for the model objects ---------------------------------------------------------------
class _ChatText(str):
    """What tokenizer.apply_chat_template(..., tokenize=False) returns; keeps the turns."""
    conversation = ()


class _Ids:
    def __init__(self, conversation):
        self.conversation = conversation

    def to(self, device):
        return self


class _Tokenizer:
    """Stands in for the Llama-3.3 tokenizer inside opensource_inference (gpt_structure.py:224-258)."""
    pad_token = eos_token = '<|eot_id|>'
    eos_token_id = 128009

    def apply_chat_template(self, conversation, add_generation_prompt=True, tokenize=False, **kw):
        text = _ChatText(json.dumps(conversation, ensure_ascii=False))
        text.conversation = conversation
        return text

    def __call__(self, text, **kw):
        ids = _Ids(text.conversation)
        return SimpleNamespace(input_ids=ids, attention_mask=ids)

    def decode(self, reply, skip_special_tokens=True):
        return 'assistant\n\n' + reply          # opensource_inference keeps the text after 'assistant\n\n'

    def save_pretrained(self, *a, **k):
        pass


class _Llama:
    """Stands in for Llama-3.3-70B (lora=False) or the model with its LoRA adapter (lora=True).
    `learned` is the adapter state: the prompt-level revision written by _dpo_substitute."""
    def __init__(self, adapter, lora=False):
        self.adapter, self.lora, self.learned = adapter, lora, ''
        self.config = SimpleNamespace(use_cache=True, pad_token_id=None)

    def generate(self, input_ids, **kw):
        conv = input_ids.conversation
        system = '\n\n'.join(m['content'] for m in conv if m['role'] == 'system')
        user = '\n\n'.join(m['content'] for m in conv if m['role'] != 'system')
        if self.learned:
            system = system + '\n\n' + self.learned
        return [self.adapter._call('assistant', self.adapter.cand, system, user)]

    def eval(self):
        return self

    def parameters(self):
        return iter(())


class _OpenAI:
    """Stands in for openai.OpenAI (reverie.py:99): chat.completions.create and embeddings.create."""
    def __init__(self, adapter, role):
        self.adapter, self.role = adapter, role
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _create(self, model=None, messages=(), **kw):
        system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
        user = '\n\n'.join(m['content'] for m in messages if m['role'] != 'system')
        text = self.adapter._chat(self.role, system, user)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    def _embed(self, input=(), model=None, **kw):
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.adapter._embedding(input[0]))])


class _Gemini:
    """Stands in for google.genai.Client: models.generate_content(model=..., contents=prompt).text."""
    def __init__(self, adapter):
        self.models = SimpleNamespace(generate_content=lambda model=None, contents=None, config=None:
                                      SimpleNamespace(text=adapter._rate(contents)))


class _Only(dict):
    """The personas dict seen by perceive_suggestion_eval, iterating over one persona only."""
    def __init__(self, personas, name):
        super().__init__(personas)
        self._name = name

    def items(self):
        return [(self._name, self[self._name])]


class _Unavailable:
    def __init__(self, *a, **k):
        raise RuntimeError('not available in this run')


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


def _text(response):
    """The suggestion inside an assistant turn '{"Suggestion": ...}'."""
    return response.split('"Suggestion": ', 1)[-1].rstrip('}').strip() if response else ''


def _clean(suggestion):
    return (suggestion or '').strip().strip('"').strip()


_JSON = json.JSONDecoder()


def _spaced(text):
    """Re-serialize every JSON object in a reply with standard separators. The upstream parsers split on
    '"Suggestion": ', '"Score": ', ', "Reason": ' and '"Summary": ' (the spacing the original models wrote);
    the backbone writes compact JSON. The content is unchanged."""
    out, i = [], 0
    while (j := text.find('{', i)) >= 0:
        try:
            obj, end = _JSON.raw_decode(text, j)
        except ValueError:
            out.append(text[i:j + 1])
            i = j + 1
            continue
        out.append(text[i:j] + (json.dumps(obj, ensure_ascii=False) if isinstance(obj, dict) else text[j:end]))
        i = end
    return ''.join(out) + text[i:]


class Adapter(BaseAdapter):
    channels = {
        'S->M': "John's observed activity written into the assistant's evaluation memory (evaluation.py:157-198,240)",
        'M->A': 'retrieved memory and summaries in the [MEMORY] block of the suggestion prompt (suggestion.py:108)',
        'A->M': "the assistant's suggestion written into its own memory record at level AS (evaluation.py:193-194)",
    }
    steps = {
        'record': "the assistant's own two candidates enter the preference data (reverie.py:462, agent.py:294-305)",
        'outcome': "the user agent's ratings decide chosen/rejected (reverie.py:453-461)",
        'attribution': 'each rating is linked to the candidate it rated (reverie.py:462)',
        'revision': 'the nightly DPO update writes the new policy into the model (agent.py:457); prompt-level here',
    }

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.user_llm = LLM(llm.backend, llm.effort, llm.cache)   # second role: ProPerSim's user agent
        self.cut, self.tag, self.moment, self.cand = set(), '', '', 'cand2'
        self._attempts, self._error, self.calls, self._emb = {}, None, {}, {}
        self._mode, self._batch, self._seen, self._dead, self.revisions = None, {}, {}, set(), []
        self.spec = {it['id']: it for it in json.loads((CASE / 'inputs' / 'days.json').read_text())['items']}
        from sentence_transformers import SentenceTransformer   # loads the real transformers before any stub
        self.minilm = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu')
        self._install_stubs()
        sys.path.insert(0, str(SERVER))
        import agent.agent as A
        import persona.persona as P
        import agent.cognitive_modules.suggestion as S
        import persona.cognitive_modules.evaluation as E
        import agent.prompt_template.gpt_structure as AG
        import persona.prompt_template.gpt_structure as PG
        self.A, self.P = A, P
        A.llm_model_upload = lambda train_mode, cache_dir='./cache', max_len=2304: (lambda m: (m, m, _Tokenizer()))(_Llama(self))
        A.peft_lm_model_upload = lambda base_model, tokenizer, train_mode, cache_dir='./cache', max_len=2304: \
            (_Llama(self, lora=True), base_model, tokenizer)
        A.DPO_train = self._dpo_substitute
        AG.temp_sleep = PG.temp_sleep = lambda seconds=0.1: None
        self._make_suggestion_prompt, S.run_gpt_prompt_make_suggestion = S.run_gpt_prompt_make_suggestion, self._suggestion_prompt
        self._evaluate, E.run_gpt_prompt_make_evaluation_seperate = E.run_gpt_prompt_make_evaluation_seperate, self._evaluate_batched
        self._perceive, E.perceive_suggestion_eval = E.perceive_suggestion_eval, self._perceive_suggestion_eval
        self.assistant_client, self.user_client, self.user_gemini = _OpenAI(self, 'assistant'), _OpenAI(self, 'user'), _Gemini(self)

    def _install_stubs(self):
        import importlib.util
        u = _stub('utils', openai_api_key='', GOOGLE_API_KEY='', key_owner='HALO',
                  maze_assets_loc='../../environment/frontend_server/static_dirs/assets',
                  fs_storage=str(STORAGE), fs_temp_storage='', collision_block_id='32125', debug=False,
                  ORIGIN_PERSONA='', SAVE_DIR='', TRAIN_MODE=TRAIN_MODE, HF_CACHE_DIR='./')
        u.__dict__.update(dict(CONFIG))
        u.env_matrix, u.env_visuals = f'{u.maze_assets_loc}/the_ville/matrix', f'{u.maze_assets_loc}/the_ville/visuals'
        _stub('openai', api_key='', OpenAI=_Unavailable, ChatCompletion=_Unavailable)
        gtypes = _stub('google.genai.types', GenerateContentConfig=dict, ThinkingConfig=dict)
        genai = _stub('google.genai', types=gtypes, Client=_Unavailable)
        if 'google' not in sys.modules and importlib.util.find_spec('google') is None:
            _stub('google').__path__ = []
        import google
        google.genai = genai
        vllm = _stub('vllm', LLM=_Unavailable, SamplingParams=_Unavailable)
        vllm.lora = _stub('vllm.lora')
        vllm.lora.request = _stub('vllm.lora.request', LoRARequest=_Unavailable)
        _stub('trl', **{n: _Unavailable for n in ('SFTConfig', 'SFTTrainer', 'DataCollatorForCompletionOnlyLM', 'DPOConfig',
                                                    'DPOTrainer', 'KTOConfig', 'KTOTrainer')},
              apply_chat_template=_Unavailable, extract_prompt=_Unavailable, unpair_preference_dataset=_Unavailable)
        _stub('peft', LoraConfig=_Unavailable, get_peft_model=_Unavailable, PeftModel=_Unavailable,
              prepare_model_for_kbit_training=_Unavailable)
        _stub('datasets', Dataset=_Unavailable, load_dataset=_Unavailable)
        _stub('wandb', init=_Unavailable, finish=lambda *a, **k: None)
        _stub('accelerate', Accelerator=_Unavailable)

    # ---- model calls ------------------------------------------------------------------------------
    def _call(self, role, kind, system, user):
        """One backbone call. The tag names item, sample, moment and stage, never the arm; a repeated request
        within a stage is an upstream retry and gets its own tag."""
        if self._error:
            raise self._error
        key = (self.moment, role, kind, system, user)
        n = self._attempts[key] = self._attempts.get(key, -1) + 1
        tag = ('user:' if role == 'user' else '') + f'{self.tag}|{self.moment}|{kind}' + (f'|retry{n}' if n else '')
        llm = self.llm if role == 'assistant' else self.user_llm
        self.calls[role] = self.calls.get(role, 0) + 1
        try:
            return _spaced(llm(system, user, tag=tag))
        except Exception as e:      # upstream wrappers swallow exceptions; keep it and raise after the call
            self._error = e
            raise

    def _check(self):
        if self._error:
            raise RuntimeError(f'backbone call failed: {self._error}')

    def _chat(self, client_role, system, user):
        role, kind = next(((r, k) for sig, r, k in CHAT_TEMPLATES if (system or user).lstrip().startswith(sig)),
                          (client_role, 'chat'))
        if kind == 'memory-summary' and role in self._dead:
            # Nothing reads this summary: the user agent's memory is reset at the next 00:02:30
            # (persona.py:257-264) or the run ends. The reply is not requested.
            return '{"Summary": "(not requested: nothing reads this summary)"}'
        if kind == 'refine':
            kind = f'{self.cand}-refine'
        return self._call(role, kind, system, user)

    def _embedding(self, text):
        if text not in self._emb:
            self._emb[text] = self.minilm.encode(text, convert_to_numpy=True).tolist()
        return self._emb[text]

    def _rate(self, prompt):
        """The Gemini user-rating call, inside or outside _evaluate_batched."""
        if self._mode == 'collect':
            self._batch.setdefault(prompt, None)
            return '{"Score": 1, "Reason": "collecting prompts"}'
        if self._mode == 'replay':
            n = self._seen[prompt] = self._seen.get(prompt, -1) + 1
            if n == 0 and self._batch.get(prompt):
                return self._batch[prompt]
        return self._call('user', 'rate', '', prompt)     # an upstream retry, or a rating outside a batch

    def _evaluate_batched(self, *args, **kw):
        """run_gpt_prompt_make_evaluation_seperate (persona/prompt_template/run_gpt_prompt.py:2631-2755), with its
        five Gemini calls answered by one user-simulator call."""
        self._mode, self._batch, self._seen = 'collect', {}, {}
        try:
            self._evaluate(*args, **kw)
            prompts = list(self._batch)
            user = '\n\n'.join(f'### PROMPT {k} ###\n{p}' for k, p in enumerate(prompts, 1))
            parts = re.split(r'#{3}\s*ANSWER\s*(\d+)\s*#{3}', self._call('user', 'rate-batch', BATCH_SYSTEM, user))
            for i in range(1, len(parts) - 1, 2):
                if 1 <= int(parts[i]) <= len(prompts):
                    self._batch[prompts[int(parts[i]) - 1]] = parts[i + 1].strip()
            self._mode = 'replay'
            return self._evaluate(*args, **kw)
        finally:
            self._mode = None

    # ---- cut sites ------------------------------------------------------------------------------
    def _suggestion_prompt(self, persona, user_persona, train_mode, retrieved=None, client=None,
                           is_john_walking=None, curr_time=None):
        """M->A: agent/cognitive_modules/suggestion.py:108 hands the retrieved memory to the suggestion prompt."""
        if 'M->A' in self.cut:
            retrieved = NO_MEMORY
        return self._make_suggestion_prompt(persona, user_persona, train_mode, retrieved=retrieved, client=client,
                                            is_john_walking=is_john_walking, curr_time=curr_time)

    def _perceive_suggestion_eval(self, personas, action, suggestion, score, score_reason, revision, train_mode, client=None):
        """persona/cognitive_modules/evaluation.py:127-244 writes John's record, then the assistant's (dict order
        of meta.json persona_names). The assistant's record is where S->M and A->M are cut."""
        events = self._perceive(_Only(personas, 'John Lin'), action, suggestion, score, score_reason, revision,
                                train_mode, client)
        eddy = personas['Eddy Lin']
        observed = eddy.scratch.user_action_for_suggestion
        if 'S->M' in self.cut:
            eddy.scratch.user_action_for_suggestion = ''           # evaluation.py:158
        level = train_mode.replace('_AS_', '_A_') if 'A->M' in self.cut else train_mode   # evaluation.py:193-197
        try:
            events += self._perceive(_Only(personas, 'Eddy Lin'), action, suggestion, score, score_reason, revision,
                                     level, client)
        finally:
            eddy.scratch.user_action_for_suggestion = observed
        return events

    def _dpo_substitute(self, total_records, preference_data, model, base_model, train_mode, tokenizer, cache_dir,
                        max_len=2048 + 256):
        """Stands in for DPO_train (opensource_training_methods.py:19-117): same inputs, same return value.
        Pairs without two different assistant turns carry no preference; DPO_train cannot train on them either
        (its failure path, lines 106-107, returns the model unchanged)."""
        pairs = []
        for chosen, rejected in zip(preference_data['chosen'], preference_data['rejected']):
            try:
                prompt, c, r = chosen[1]['content'], chosen[2]['content'], rejected[2]['content']
            except (TypeError, IndexError, KeyError):
                continue
            if _text(c) and _text(r) and c != r:
                situation = prompt.split('[ACTION]\n', 1)[-1].split('\n\nRemember to provide', 1)[0].strip()
                pairs.append(f'{situation}\nChosen: {c}\nRejected: {r}')
        block = (LEARNED_HEADER + '\n\n' + '\n\n'.join(pairs)) if pairs else ''
        installed = bool(block) and 'revision' not in self.cut
        if installed:
            model.learned = block
        self.revisions.append({'moment': self.moment, 'pairs_in_data': len(preference_data['chosen']),
                               'pairs_used': len(pairs), 'installed': installed, 'block': block})
        return model, base_model, tokenizer

    # ---- inputs -----------------------------------------------------------------------------------
    def items(self):
        out = []
        for item_id, spec in self.spec.items():
            s = json.loads((STORAGE / spec['persona'] / 'personas' / 'John Lin' / 'bootstrap_memory' / 'scratch.json').read_text())
            profile = {k: s[k] for k in ('name', 'age', 'big_five_personality_traits', 'background', 'current_interests',
                                         'lifestyle', 'daily_plan_req')}
            prefs = {k.replace('_', ' '): v for k, v in s['criteria'].items()}
            out.append({'id': item_id, 'judge_context': json.dumps(
                {'user': profile, "the user's stated preferences for recommendations": prefs,
                 'setting': 'A home assistant observes what the user is doing and, at each listed moment of one day, '
                            'either makes one suggestion or answers "No Recommendation" (stays silent).'},
                ensure_ascii=False, indent=1)})
        return out

    # ---- one simulation step (reverie.py:437-479 for this setting) ------------------------------------
    def _learning_step(self, eddy, john, personas, t, rec):
        when = t.strftime('%A %B %d -- %I:%M:%S %p')
        self.cand = 'cand1'      # reverie.py:445-446 (norec0: the first candidate also comes from the model)
        action, first = eddy.suggest(personas, TRAIN_MODE, is_john_walking='no', movement_path='', step=0, curr_time=when)
        eddy.scratch.suggestion = None                                                   # reverie.py:447
        self.cand = 'cand2'      # reverie.py:448-449
        action, second = eddy.suggest(personas, TRAIN_MODE, is_john_walking='no', movement_path='', step=0, curr_time=when)
        self._check()
        rec.update(observed=action, candidates=[_clean(first), _clean(second)], shown=_clean(second))
        if second:                                                                       # reverie.py:451-466
            r1, r2, deducted = john.eval_suggestion(personas, train_mode=TRAIN_MODE, first_suggestion=first)
            self._check()
            if r2:
                better = '[#1]' if float(r1[0]) > float(r2[0]) else '[#2]' if float(r1[0]) < float(r2[0]) else '[]'
                rec.update(scores=[float(r1[0]), float(r2[0])], score=float(r2[0]), preferred=better,
                           reasons=[r1[1].strip(), r2[1].strip()])
                s1, s2, totals = first, second, (r1, r2)
                if 'outcome' in self.cut:
                    better, totals = '', ((None, None), (None, None))   # no rating reaches the pair builder
                if 'record' in self.cut:
                    s1 = s2 = ''                                     # the update does not see what was suggested
                if 'attribution' in self.cut:
                    s1, s2 = s2, s1                                  # each rating attached to the other candidate
                eddy.update_preference_data(TRAIN_MODE, eddy.current_prompt, r1, r2, better, '', s1, s2)
                eddy.update_total_records(t.strftime('%B %d, %Y'), action, (s1, s2), *totals, deducted)
        eddy.scratch.suggestion = None                                                   # reverie.py:477-479
        eddy.scratch.suggestion_eval_result = None

    def _test_step(self, eddy, john, personas, t, rec):
        """Last day: only the delivered candidate (cand2) is generated and rated. The first candidate and the
        preference pair matter only to an update after the last day, which the run does not reach."""
        when = t.strftime('%A %B %d -- %I:%M:%S %p')
        self.cand = 'cand2'
        eddy.scratch.suggestion = None
        action, shown = eddy.suggest(personas, TRAIN_MODE, is_john_walking='no', movement_path='', step=0, curr_time=when)
        self._check()
        rec.update(observed=action, shown=_clean(shown))
        if shown:
            score, reason, deducted = john.eval_suggestion(personas, train_mode=TRAIN_MODE)
            self._check()
            if score is not None:
                rec.update(score=float(score), reasons=[reason.strip()])
        eddy.scratch.suggestion = None
        eddy.scratch.suggestion_eval_result = None

    def run(self, item, cut, sample):
        spec = self.spec[item['id']]
        self.cut, self.tag = set(cut), f'{item["id"]}|s{sample}'
        self._attempts, self._error, self.calls, self.revisions = {}, None, {}, []
        base = STORAGE / spec['persona']
        meta = json.loads((base / 'reverie' / 'meta.json').read_text())
        start = datetime.datetime.strptime(meta['start_date'], '%B %d, %Y')
        step = datetime.timedelta(seconds=meta['sec_per_step'])
        WORK.mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='run-', dir=WORK))   # upstream opens prompts by relative path and
        for name in ('agent', 'persona'):                         # pickles total_data_*.pkl into the cwd
            (work / name).symlink_to(SERVER / name)
        cwd, moments = os.getcwd(), []
        os.chdir(work)
        try:
            with contextlib.redirect_stdout(io.StringIO()):       # upstream prints every prompt
                eddy = self.A.Agent('Eddy Lin', suggestion_model_name=TRAIN_MODE, client=self.assistant_client,
                                    folder_mem_saved=str(base / 'personas' / 'Eddy Lin'), hf_cache_dir='./')
                john = self.P.Persona('John Lin', str(base / 'personas' / 'John Lin'), client=self.user_client,
                                      gemini=self.user_gemini)
                personas = {name: {'John Lin': john, 'Eddy Lin': eddy}[name] for name in meta['persona_names']}
                for d, day in enumerate(spec['days']):
                    date = start + datetime.timedelta(days=d)
                    self.moment, self._dead = f'd{d + 1}-0002', set()
                    eddy.update_suggestion_model(TRAIN_MODE)                              # reverie.py:389-392
                    john.init_e_mem(str(base / 'personas' / 'John Lin'))
                    self._check()
                    for k, m in enumerate(day['moments']):
                        t = datetime.datetime.combine(date.date(), datetime.time.fromisoformat(m['time']))
                        self.moment = f'd{d + 1}m{k + 1}'
                        last_of_day = k == len(day['moments']) - 1
                        self._dead = ({'user'} if last_of_day else set()) | \
                                     ({'assistant'} if last_of_day and d == len(spec['days']) - 1 else set())
                        # John's move for this step: his activity, as Persona.move/plan would set it.
                        john.scratch.curr_time, john.scratch.act_description = t, m['act_description']
                        # The assistant's move at the previous step (agent.py:246, execute.py:58,168).
                        eddy.scratch.curr_time, eddy.scratch.act_description = t - step, 'suggestion'
                        rec = {'day': d + 1, 'phase': day['phase'], 'time': t.strftime('%A %B %d, %I:%M %p'),
                               'activity': m['act_description']}
                        (self._learning_step if day['phase'] == 'learn' else self._test_step)(eddy, john, personas, t, rec)
                        eddy.scratch.curr_time = t
                        moments.append(rec)
        finally:
            os.chdir(cwd)
            shutil.rmtree(work, ignore_errors=True)
        return self._result(moments, eddy)

    def _result(self, moments, eddy):
        def lines(phase, with_candidates=False):
            out = []
            for m in moments:
                if m['phase'] != phase:
                    continue
                said = m.get('shown') or '(nothing)'
                if with_candidates and m.get('candidates'):
                    sc = m.get('scores') or [None, None]
                    said = (f'candidate 1: {m["candidates"][0]} (rated {sc[0]}/4); candidate 2: {m["candidates"][1]} '
                            f'(rated {sc[1]}/4); preferred {m.get("preferred", "-")}')
                out.append(f'{m["time"]}. John Lin is {m["activity"]}.\nAssistant: {said}')
            return '\n\n'.join(out)

        test = [m for m in moments if m['phase'] == 'test']
        learn = [m for m in moments if m['phase'] == 'learn']
        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
        last = self.revisions[-1] if self.revisions else {}
        return {
            'output': lines('test'),
            'learning_day': lines('learn', with_candidates=True),
            'revision': last,
            'moments': moments,
            'calls': self.calls,
            'metrics': {
                'test_mean_rating': mean([m['score'] for m in test if 'score' in m]),
                'test_recommendations': sum(1 for m in test if m.get('shown') and 'no recommendation' not in m['shown'].lower()),
                'learn_mean_rating': mean([m['score'] for m in learn if 'score' in m]),
                'learn_preference_pairs': sum(1 for m in learn if m.get('preferred') in ('[#1]', '[#2]')),
                'pairs_in_policy': last.get('pairs_used', 0) if last.get('installed') else 0,
                'backbone_calls': sum(self.calls.values()),
            },
        }
