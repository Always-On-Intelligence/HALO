"""HALO run-mode adapter for PAHF (facebookresearch/PAHF at commit 7a11213), embodied agent.

Each item is one short session of PAHF's embodied (household robot) agent with one persona, taken from
PAHF's own benchmark (core/data/embodied). The session runs one learning request (a phase-1 task with
pre-action clarification and post-action feedback, as run_full_study runs phase 1) and then two later
requests (phase-2 tasks without feedback and with the no-ask action prompt, as phase 2 runs). Every task
goes through the upstream loop EmbodiedAgent.run_study -> run_exp -> get_mc_dataset + get_test_predictions
with the defaults of run_agent.py: SQLite per-user memory (initialize_memory_banks) and both feedback types
in the learning phase. The judge compares the two later decisions.

Replacements (see README.md):
  - utils/llm.py (the OpenAI client) is replaced by a stub module whose LLMClient sends the agent's calls to
    the HALO backbone. Calls of the simulated user (generate(..., use_human_model=True), base.py:132, and the
    post-action feedback call with the persona as system prompt, embodied_agent.py:229-236) go to a second
    backbone role tagged 'user:'. The benchmark's option generator (utils/agent_utils.py:35) and its
    ground-truth judge (embodied_agent.py:123-138) are tagged 'env:' and 'gt:'. Temperature and max_tokens
    are not passed on.
  - DragonPlusEmbedding (memory/banks.py:20, two BERT encoders not in the local cache) is replaced by
    all-MiniLM-L6-v2 on CPU, normalized, so the bank's dot product stays a cosine similarity.
  - memory/banks.py does not parse at the pinned commit: FAISSMemoryBank has an IndentationError at lines
    580-581 and 639-650. The adapter executes the file's unchanged lines 1-413 (the embedding class,
    MemoryBank and SQLiteMemoryBank) as module memory.banks; FAISSMemoryBank, unused by the SQL
    configuration, becomes a placeholder that raises. faiss (imported, unused) is a stub module.
  - agents/__init__.py is bypassed (it would import the shopping agent); pdb.set_trace raises instead of
    blocking the worker (embodied_agent.py:174, only reached on malformed options).

Cut sites (receiving end):
  S->M  user evidence is not admitted to memory: SQLiteMemoryBank.add / update_memory (memory/banks.py:309,
        :270) drop the write, for both write paths: the pre-action Q&A note (agents/base.py:135-143) and the
        post-action feedback note (agents/embodied_agent.py:244-306).
  M->A  retrieved preference notes do not reach Action: the retrieval inside retrieve_memory_context
        (agents/base.py:66, simple_memory_retrieval) returns nothing, so the summary appended to the action
        prompt (embodied_agent.py:186-193) is PAHF's own empty-memory summary.
  A->S  the robot's clarification question does not reach the user: handle_pre_feedback runs its own
        no-answer branch (agents/base.py:119-124) instead of the simulated-user call (base.py:126-133); the
        question is still generated (base.py:113-115) and Action still offers 'Ask human'.
  A->M  the robot's question is withheld from the memory note writer: the Q&A prompt at agents/base.py:137
        reaches the model without its 'Question: ...' line, so the note is written from the user's reply.
M->S is not realized in the code (no memory reaches question generation or the user), and PAHF does not
revise its own mechanism (memory holds per-user preference notes), so no evidence step is cut.
"""
import json, os, pdb, shutil, sys, tempfile, types
from pathlib import Path
from halo.run.adapter import BaseAdapter
from halo.run.llm import LLM

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                 # vendored upstream code, see core/SOURCE.md
SCENARIOS = CORE / 'data' / 'embodied' / 'scenarios'
MINILM = 'sentence-transformers/all-MiniLM-L6-v2'


class MiniLMEmbedding:
    """Stands in for DragonPlusEmbedding (memory/banks.py:20-94): same two methods, one shared model."""
    _model = None

    def __init__(self, *args, **kwargs):
        if MiniLMEmbedding._model is None:
            from sentence_transformers import SentenceTransformer
            MiniLMEmbedding._model = SentenceTransformer(MINILM, device='cpu')

    def embed_documents(self, texts):
        return self._model.encode(list(texts), normalize_embeddings=True).tolist()

    def embed_query(self, text):
        return self._model.encode([text], normalize_embeddings=True)[0].tolist()


def _pdb_guard(*args, **kwargs):
    raise RuntimeError('upstream reached pdb.set_trace (embodied_agent.py:174): malformed generated options')


class Adapter(BaseAdapter):
    channels = {
        'S->M': "user answers and post-action feedback admitted as preference notes to the per-user SQLite memory",
        'M->A': "retrieved preference notes summarized into the action prompt",
        'A->S': "the robot's clarification question delivered to the user, whose answer is acquired",
        'A->M': "the robot's clarification question summarized together with the user's answer into the memory note",
    }
    steps = {}   # PAHF stores per-user preference notes (content); it does not revise its own mechanism

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
        # simulated user, option generator and ground-truth judge: a second role on the same backend and cache
        self.role_llm = LLM(llm.backend, llm.effort, llm.cache)
        self.cut, self.tag, self.counts, self.calls, self.writes = set(), '', {}, [], []
        self.work = Path(case_dir) / '.work'
        self.work.mkdir(exist_ok=True)
        self._install_stubs()
        sys.path.insert(0, str(CORE))
        import agents.base as base
        import utils.agent_utils as agent_utils
        from agents.embodied_agent import EmbodiedAgent
        from data.embodied.personas.original_persona import prompt_dict
        from prompts import embodied_prompts as ep
        pdb.set_trace = _pdb_guard
        self.ep, self.agent_utils, self.prompt_dict = ep, agent_utils, prompt_dict
        self.personas = set(prompt_dict.values())
        agent_utils.DragonPlusEmbedding = MiniLMEmbedding        # used by initialize_memory_banks (agent_utils.py:103)
        sys.modules['memory.banks'].DragonPlusEmbedding = MiniLMEmbedding
        MiniLMEmbedding()                                       # load once per worker
        # M->A cut site: the retrieval that feeds retrieve_memory_context (agents/base.py:66)
        self._retrieve = base.simple_memory_retrieval
        base.simple_memory_retrieval = self._simple_memory_retrieval
        self.agent = EmbodiedAgent(self.client)
        # A->S cut site: wraps the upstream method and only switches its own enable_pre_feedback flag
        self._pre_feedback = self.agent.handle_pre_feedback
        self.agent.handle_pre_feedback = self._handle_pre_feedback
        self.A = json.loads((SCENARIOS / 'original_scenarios_A.json').read_text())
        self.B = json.loads((SCENARIOS / 'original_scenarios_B.json').read_text())
        self.items_data = json.loads((Path(case_dir) / 'inputs' / 'items.json').read_text())['items']

    # ---- cut sites -------------------------------------------------------------------------
    def _simple_memory_retrieval(self, memory, task, top_k=5):
        if 'M->A' in self.cut:
            return ''          # what an empty memory returns (memory/utils.py:69-84)
        return self._retrieve(memory, task, top_k)

    def _handle_pre_feedback(self, action, whole_scenario, scenario, prompt_human, memory, name,
                             aug_mem=False, enable_pre_feedback=True):
        if 'A->S' in self.cut:
            enable_pre_feedback = False   # base.py:119-124: the question goes unanswered, '[No answer provided]'
        return self._pre_feedback(action, whole_scenario, scenario, prompt_human, memory, name, aug_mem,
                                  enable_pre_feedback)

    def _guard_bank(self, bank):
        """S->M cut site: the bank admits nothing (memory/banks.py:309 add, :270 update_memory)."""
        add, update = bank.add, bank.update_memory

        def guarded_add(text):
            self.writes.append({'task': self.tag.split('|')[-1], 'op': 'add', 'text': text, 'admitted': 'S->M' not in self.cut})
            if 'S->M' not in self.cut:
                add(text)

        def guarded_update(memory_id, new_text):
            self.writes.append({'task': self.tag.split('|')[-1], 'op': 'update', 'text': new_text, 'admitted': 'S->M' not in self.cut})
            if 'S->M' not in self.cut:
                update(memory_id, new_text)

        bank.add, bank.update_memory = guarded_add, guarded_update

    # ---- model client -> HALO backbone --------------------------------------------------------
    def _stage(self, system, user):
        ep = self.ep
        if system == ep.judge_prompt:
            return 'gt', 'gt'
        if system in self.personas:
            return 'feedback', 'user'                     # embodied_agent.py:229-236, the simulated user reacts
        if user.startswith(ep.mc_gen_prompt_template.strip()):
            return 'options', 'env'
        if user.startswith(ep.prompt_react_no_ask) or user.startswith(ep.prompt_react):
            return 'act', 'agent'
        if user.startswith(ep.prompt_question):
            return 'question', 'agent'
        if user.startswith(ep.prompt_summarize):
            return 'retrieve', 'agent'
        if user.startswith('Question: ') and 'According to this Q&A, please summarize' in user:
            return 'qa_note', 'agent'
        if 'Does the feedback contain any personalized information' in user:
            return 'feedback_check', 'agent'
        if 'please summarize the personalized information about' in user:
            return 'feedback_note', 'agent'
        if 'Does this feedback CHANGE a previously stated preference' in user:
            return 'update_check', 'agent'
        if 'please summarize the previous' in user:
            return 'previous_pref', 'agent'
        if user.startswith('Please create a concise, integrated summary'):
            return 'merge', 'agent'
        return 'other', 'agent'

    def _install_stubs(self):
        adapter = self

        class LLMClient:
            """Same interface as utils/llm.py LLMClient; calls go to the HALO backbone."""

            def __init__(self, model='gpt-4o', human_model=None, api_key=None):
                self.model = model
                self.human_model = human_model if human_model is not None else model

            def build_msgs(self, messages):
                return [{'role': m['role'], 'content': m['content']} for m in messages
                        if m['role'] in ('system', 'user', 'assistant')]

            def generate(self, prompt, use_human_model=False, temperature=1.0, max_tokens=512, top_p=1.0):
                msgs = [{'role': 'user', 'content': prompt}] if isinstance(prompt, str) else self.build_msgs(prompt)
                system = '\n\n'.join(m['content'] for m in msgs if m['role'] == 'system')
                user = '\n\n'.join(m['content'] for m in msgs if m['role'] != 'system')
                stage, role = ('answer', 'user') if use_human_model else adapter._stage(system, user)
                if stage == 'qa_note' and 'A->M' in adapter.cut and '\nHuman: ' in user:
                    user = user[user.index('\nHuman: ') + 1:]      # A->M cut site (base.py:137)
                n = adapter.counts[stage] = adapter.counts.get(stage, 0) + 1
                tag = f'{adapter.tag}|{stage}{n}'
                if role == 'agent':
                    text = adapter.llm(system, user, tag=tag)
                else:
                    text = adapter.role_llm(system, user, tag=f'{role}:{tag}')
                adapter.calls.append({'task': adapter.tag.split('|')[-1], 'stage': f'{stage}{n}', 'reply': text})
                return text

        adapter.client = LLMClient()
        llm_mod = types.ModuleType('utils.llm')
        llm_mod.LLMClient = LLMClient
        sys.modules['utils.llm'] = llm_mod
        sys.modules.setdefault('faiss', types.ModuleType('faiss'))   # imported by banks.py:14, embodied_agent.py:21; used only by FAISS
        # memory/banks.py: execute the unchanged lines before `class FAISSMemoryBank` (the class does not parse)
        path = CORE / 'memory' / 'banks.py'
        src = path.read_text()
        banks = types.ModuleType('memory.banks')
        banks.__file__ = str(path)
        exec(compile(src[:src.index('\nclass FAISSMemoryBank')], str(path), 'exec'), banks.__dict__)

        class FAISSMemoryBank:
            def __init__(self, *args, **kwargs):
                raise NotImplementedError('FAISSMemoryBank does not parse at the pinned commit (memory/banks.py:581)')

        banks.FAISSMemoryBank = FAISSMemoryBank
        sys.modules['memory.banks'] = banks
        pkg = types.ModuleType('agents')        # skip agents/__init__.py, which also imports the shopping agent
        pkg.__path__ = [str(CORE / 'agents')]
        sys.modules['agents'] = pkg

    # ---- items -----------------------------------------------------------------------------------
    def _context(self, it, which=None):
        """What the judge sees: the earlier request, then the user's own preference and wish for each later
        request (both requests, or only request `which`)."""
        name, learn = it['user'], self.A[it['learn']]
        ks = range(len(it['test'])) if which is None else [which]
        lines = [f'{name} lives with a household robot that fetches things. Earlier in the same session {name} asked: '
                 f'"{learn["task"]}" (scene: {learn["scene"]}); the robot could ask one clarifying question and got '
                 f'{name}\'s feedback afterwards. Later the robot decided without asking.']
        for k in ks:
            t = self.B[it['test'][k]]
            lines.append(f'Later request {k + 1}: "{t["task"]}" (scene: {t["scene"]}). {it["preferences"][k]} '
                         f'What {name} wants here: {t["user_intent_object"]}.')
        return '\n'.join(lines)

    def items(self):
        return [{'id': it['id'], 'judge_context': self._context(it)} for it in self.items_data]

    # ---- one session: learning task, then later test tasks ------------------------------------------
    def _task(self, it, source, idx, label, work, banks, feedback):
        data = self.A if source == 'A' else self.B
        task = data[idx]
        assert task['user'] == it['user'], (it['id'], source, idx)
        path = work / f'{label}.json'
        path.write_text(json.dumps([task]))
        self.tag, self.counts = f'{self._base}|{label}', {}
        saved = list(sys.path)
        try:
            # EmbodiedAgent.run_study (embodied_agent.py:393), as run_full_study calls it for phase 1 / phase 2
            test_set, _ = self.agent.run_study(
                str(path), self.prompt_dict, enable_memory=True, mem_style='sql', all_memories=banks,
                phase_idx=1 if feedback else 2, enable_pre_feedback=feedback, enable_post_feedback=feedback)
        finally:
            sys.path[:] = saved
        r = test_set[0]
        prefix = self.ep.prompt_react if feedback else self.ep.prompt_react_no_ask
        acts = [c['reply'] for c in self.calls if c['task'] == label and c['stage'].startswith('act')]
        final = acts[-1] if acts else ''
        whole = r['mc_gen_raw'].strip()
        chosen = next((line[2:].strip() for line in whole.split('\n') if line.startswith(f'{r["aciton"]})')), '')
        return {
            'label': label, 'source': f'original_scenarios_{source}.json[{idx}]', 'scenario': whole,
            'gt': r['gt_option'], 'action': r['aciton'], 'chosen': chosen, 'correct': r['correct'],
            'wanted': task['user_intent_object'], 'asked': r['pre_feedback'], 'post_feedback_stored': r['post_feedback'],
            'human_feedback': r['human_feedback'],
            'thought': final.split('Action:')[0].replace('Thought:', '').strip(),
            'transcript': r['whole_prompt'][len(prefix):].strip() if r['whole_prompt'].startswith(prefix) else r['whole_prompt'],
        }

    def run(self, item, cut, sample):
        it = next(x for x in self.items_data if x['id'] == item['id'])
        self.cut, self.calls, self.writes = set(cut), [], []
        # The tag names the item, the sample and the stage, not the arm: arms whose prompts are identical
        # share the cached reply, so each comparison differs only where the cut changes a prompt.
        self._base = f'{it["id"]}|s{sample}'
        work = Path(tempfile.mkdtemp(prefix=f'{it["id"]}-', dir=self.work))
        banks = None
        try:
            # utils/agent_utils.py:69 with the defaults of run_agent.py (mem_style='sql'): fresh per-user SQLite memory
            banks = self.agent_utils.initialize_memory_banks(self.prompt_dict, 'sql', str(work), 'embodied_agent_pahf')
            for bank in banks.values():
                self._guard_bank(bank)
            learned = self._task(it, 'A', it['learn'], 'learn1', work, banks, True)
            notes = [t for _, t in banks[it['user']].get_all_memories()]
            tests = [self._task(it, 'B', idx, f'test{k + 1}', work, banks, False) for k, idx in enumerate(it['test'])]
        finally:
            if banks:
                for bank in banks.values():
                    bank.close()
            shutil.rmtree(work, ignore_errors=True)
        out = [f'{t["scenario"]}\nRobot\'s decision: {t["action"]}) {t["chosen"]}\nRobot\'s reasoning: {t["thought"]}'
               for t in tests]
        return {
            # later request 1: the situation of the learning request again (new wording and scene)
            'output': out[0],
            'context_same': self._context(it, 0),
            # later request 2: a different situation, with the learned object among the options
            'output_other': out[1],
            'context_other': self._context(it, 1),
            'learning': learned,
            'memory_after_learning': notes,
            'memory_writes': self.writes,
            'tests': tests,
            'calls': [{'task': c['task'], 'stage': c['stage']} for c in self.calls],
            'metrics': {
                'test_accuracy': round(sum(t['correct'] for t in tests) / len(tests), 4),
                'test1_correct': tests[0]['correct'],
                'test2_correct': tests[1]['correct'] if len(tests) > 1 else None,
                'learn_correct': learned['correct'],
                'learn_asked': learned['asked'],
                'notes_after_learning': len(notes),
                'backbone_calls': len(self.calls),
            },
        }
