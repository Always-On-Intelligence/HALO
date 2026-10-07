"""HALO run-mode adapter for ProAct (AgentACE-AI/ProAct at commit 7ac78fd), Directed Idle (Full-single-idle).

Each item is a short day for one ProActEval scenario: a morning message, an idle gap, and a later message.
The adapter drives the upstream ProactiveBenchAdapter the way ProactiveBenchRunner.run_single does
(experiments/ProactiveBench/eval/runner.py:182-428): per turn, run_ablation_turn(turn) runs Future-State
Prediction (BenchmarkFSP) and, when the idle time reaches the trigger, Idle-Time Exploration (BenchmarkITE:
search, admission to memory, push scoring and the direct-push gates); a direct push is recorded with
record_direct_push; then send_message(text) runs ChatHandler (topic monitor, planning, reactive search,
reply, incremental profile extraction). The scripted messages replace the LLM user simulator and the HALO
judge replaces the coverage judge. Condition and limits follow the README command: Full-single-idle,
max_queries_per_search=1, max_intents_per_idle=3, idle_trigger_seconds=5, max_total_searches=999, seed 42.

Replacements (see README.md):
  - tools/llm_client.py LLMClient (OpenAI; gpt-4o and gpt-4o-mini per agent) is subclassed: chat() sends
    every call to the HALO backbone; chat_json() and its JSON parsing are upstream's. Temperature, seed and
    max_tokens are not passed on, and there is no JSON response mode.
  - chromadb's default embedding function (an ONNX all-MiniLM-L6-v2 that chromadb downloads) is replaced by
    chromadb's SentenceTransformerEmbeddingFunction with the locally cached all-MiniLM-L6-v2 on CPU,
    normalized, for both the memory vector store and the benchmark's external fact store. Telemetry is off.
  - Simulated idle seconds: run_ablation_turn draws them from adapter._idle_rng (1-3 s for turns 1-2, 5-10 s
    later, adapter.py:405-409). Here the draw returns the scripted gap between the two messages.
  - python-dotenv's load_dotenv (core/config.py:14) is a no-op, so no .env file is read; storage goes to a
    temporary folder under cases/proact/.work instead of experiments/ProactiveBench/runtime.

Cut sites (receiving end):
  S->M  memory admits nothing sensed: the session buffer drops the user's message (MemorySystem.add_message,
        memory/memory_system.py:614, called at server/handlers/chat_handler.py:236); acquired search results
        are not admitted (submit_update of ADD_KNOWLEDGE, services/search_service.py:346 ->
        memory/memory_system.py:393) for idle-time and reactive searches; the incremental extraction
        (chat_handler.py:849-953) receives the turn without the user's message.
  M->A  Action reads an empty memory: the FSP inputs (eval/adapter.py:430-432; fsp_module.py:316-317, 349-350,
        384, 414), the push scorer's interests and context (ite_module.py:266-268, 334), the planner's
        memory context (agents/planning_agent.py:61, passed to the reply at chat_handler.py:272-276) and
        the reply's profile (agents/assistant_agent.py:62-63) all get what an empty memory returns.
  A->S  acquisition receives no target: SearchService.search (services/search_service.py:105) gets an empty
        topic and purpose instead of the FSP intent (ite_module.py:224-233) or the planner's query
        (chat_handler.py:247-250), so the search planner plans from the profile alone.
  M->S  Sensing gets no memory: the topic monitor receives no current topic, history or stored topics
        (chat_handler.py:222-228, agents/topic_monitor.py:37), and the search planner no user profile
        (services/search_service.py:133-137, agents/search_planner.py:37).
  A->M  memory admits nothing the assistant did: the session buffer drops assistant replies and direct pushes
        (chat_handler.py:279; eval/adapter.py:614-619), the incremental extraction receives the turn without
        the assistant's reply (chat_handler.py:849-953), and ITE keeps no delivery record
        (ite_module.py:419-438).
ProAct does not revise its own mechanism (memory holds knowledge, profile, facts and conversation records),
so no evidence step is cut.
"""
import asyncio, json, os, re, shutil, sys, tempfile, types
from pathlib import Path
from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                 # vendored upstream code, see core/SOURCE.md
SCENARIOS = CORE / 'experiments' / 'ProactiveBench' / 'data' / 'scenarios'
MINILM = 'sentence-transformers/all-MiniLM-L6-v2'
CONDITION = 'Full-single-idle'       # Directed Idle (paper Appendix F); same AblationConfig as 'Full'
RUN_ARGS = dict(seed=42, max_queries_per_search=1, max_intents_per_idle=3, idle_trigger_seconds=5.0,
                max_total_searches=999)   # README / RUN_COMMANDS.md smoke and full commands

STAGES = [   # system prompt prefix -> stage name used in the cache tag
    ('You are a topic monitoring assistant', 'topic'),
    ('Extract the main topic from the text', 'topic_infer'),
    ('Determine whether the message belongs to one of the listed topics', 'topic_match'),
    ('You are a planning assistant', 'plan'),
    ('You are a helpful personalized AI assistant', 'reply'),
    ('You extract user profile information from the conversation and generate a summary', 'extract'),
    ('You are a knowledge validation expert', 'fsp_critic'),
    ('You are a research topic prediction expert', 'fsp_predict'),
    ('You are a research value evaluator', 'fsp_evaluate'),
    ('You are a push-value evaluator', 'push_score'),
    ('You are a search planning expert', 'search_plan'),
    ('You generate concise summaries for web content', 'summarize'),
    ('You are a knowledge base manager helping decide how to handle duplicate content', 'dedup'),
    ('You are an information organization assistant', 'merge'),
    ('You are a topic extraction assistant', 'research_topic'),
]
STOP = set('a an the and or of to in on at for with by from is are was be it this that your you my me i we our '
           'as if not no do does must should can will within than then into per each'.split())


def _tokens(text):
    return {t for t in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(t) > 2 and t not in STOP}


class ScriptedIdle:
    """Stands in for adapter._idle_rng: the idle time before a turn is the scripted gap, not a random draw."""
    def __init__(self, gaps):
        self.gaps, self.turn = gaps, 1

    def uniform(self, low, high):
        return float(self.gaps[self.turn - 1])


class Adapter(BaseAdapter):
    channels = {
        'S->M': "user messages and acquired search results admitted to memory (session, knowledge store, extracted profile and facts)",
        'M->A': "memory (dialogue, profile, knowledge, topics) read by Future-State Prediction, push scoring, planning and the reply",
        'A->S': "predicted needs (FSP intents) and the planner's queries given to the search as its target",
        'M->S': "conversation history, stored topics and the profile read by the topic monitor and the search planner",
        'A->M': "assistant replies, direct pushes and the delivery record admitted to memory",
    }
    steps = {}   # ProAct stores knowledge, profiles and records (content); it does not revise its own mechanism

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
        os.environ['ANONYMIZED_TELEMETRY'] = 'False'
        for key in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'SERPER_API_KEY', 'JINA_API_KEY'):
            os.environ.pop(key, None)          # read by core/config.py; nothing in this run may use them
        self.cut, self.tag, self.counts, self.calls = set(), '', {}, []
        self.work = Path(case_dir) / '.work'
        self.work.mkdir(exist_ok=True)
        self._install_stubs()
        sys.path.insert(0, str(CORE))
        self._install_chromadb()
        from tools.llm_client import LLMClient
        from core.models import MemoryUpdateResult, UpdateAction, UpdateType, UserProfile
        from experiments.ProactiveBench.eval.adapter import ProactiveBenchAdapter
        from experiments.ProactiveBench.generation.models import Scenario
        self.models = types.SimpleNamespace(MemoryUpdateResult=MemoryUpdateResult, UpdateAction=UpdateAction,
                                            UpdateType=UpdateType, UserProfile=UserProfile)
        self.PBA, self.Scenario = ProactiveBenchAdapter, Scenario
        adapter = self
        build_config = ProactiveBenchAdapter._build_config

        def _build_config(pba):                # eval/adapter.py:667-689, with storage in this run's folder
            cfg = build_config(pba)
            cfg.storage.data_dir = adapter.run_dir
            return cfg

        ProactiveBenchAdapter._build_config = _build_config

        class HaloLLMClient(LLMClient):
            """tools/llm_client.py LLMClient with chat() on the HALO backbone (chat_json is upstream's)."""

            def __init__(self):
                self.config, self.request_timeout, self.max_retries, self._usage_stats = None, None, 1, {}

            def chat(self, messages, model, temperature=0.7, max_tokens=None, response_format=None, seed=None):
                system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
                user = '\n\n'.join(m['content'] for m in messages if m['role'] != 'system')
                stage = next((name for prefix, name in STAGES if system.startswith(prefix)), 'other')
                n = adapter.counts[stage] = adapter.counts.get(stage, 0) + 1
                text = adapter.llm(system, user, tag=f'{adapter.tag}|{stage}{n}')
                bucket = self._usage_stats.setdefault(model, {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})
                bucket['calls'] += 1
                adapter.calls.append({'phase': adapter.tag.split('|')[-1], 'stage': f'{stage}{n}', 'model': model})
                return text

            def get_embedding(self, text):
                raise NotImplementedError('not used on this path')

            get_embeddings = get_embedding

        self.Client = HaloLLMClient
        self.items_data = json.loads((Path(case_dir) / 'inputs' / 'days.json').read_text())['items']

    # ---- environment -------------------------------------------------------------------------------
    def _install_stubs(self):
        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False      # core/config.py:14 would read a .env file
        # Skip package __init__ files that import the FastAPI app, the web search tools or unused agents;
        # the two packages imported by name (services.deep_research, services.proactive) keep theirs.
        for pkg in ('agents', 'core', 'memory', 'server', 'server.handlers', 'services', 'tools', 'experiments',
                    'experiments.ProactiveBench', 'experiments.ProactiveBench.eval',
                    'experiments.ProactiveBench.generation'):
            mod = types.ModuleType(pkg)
            mod.__path__ = [str(CORE.joinpath(*pkg.split('.')))]
            sys.modules[pkg] = mod

    def _install_chromadb(self):
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        from chromadb.api.client import SharedSystemClient
        ef = SentenceTransformerEmbeddingFunction(model_name=MINILM, device='cpu', normalize_embeddings=True)
        persistent, ephemeral = chromadb.PersistentClient, chromadb.Client

        def with_ef(client):
            get_or_create, create = client.get_or_create_collection, client.create_collection
            client.get_or_create_collection = lambda name, **kw: get_or_create(name, **{**kw, 'embedding_function': ef})
            client.create_collection = lambda name, **kw: create(name, **{**kw, 'embedding_function': ef})
            return client

        chromadb.PersistentClient = lambda *a, **kw: with_ef(persistent(*a, **kw))   # memory/vector_store.py:41
        chromadb.Client = lambda *a, **kw: with_ef(ephemeral(*a, **{'settings': Settings(anonymized_telemetry=False), **kw}))
        self.clear_chroma = SharedSystemClient.clear_system_cache                # external_fact_store.py:26

    # ---- cut sites ------------------------------------------------------------------------------------
    def _memory_view(self, memory):
        """What an Action component reads of MemorySystem. Under M->A every read returns what an empty memory
        returns; writes and everything else go to the real memory."""
        adapter, models = self, self.models

        class MemoryView:
            def __getattr__(self, name):
                return getattr(memory, name)

            @property
            def current_topic(self):
                return None if 'M->A' in adapter.cut else memory.current_topic

            def format_context_for_query(self, query):
                return 'No relevant memory available' if 'M->A' in adapter.cut else memory.format_context_for_query(query)

            def get_user_profile(self):
                return models.UserProfile(user_id=memory.user_id) if 'M->A' in adapter.cut else memory.get_user_profile()

            def get_current_messages_formatted(self):
                return '' if 'M->A' in adapter.cut else memory.get_current_messages_formatted()

            def search_knowledge(self, query, n_results=5):
                return [] if 'M->A' in adapter.cut else memory.search_knowledge(query, n_results)

            def get_recent_topics(self, limit=5):
                return [] if 'M->A' in adapter.cut else memory.get_recent_topics(limit)

        return MemoryView()

    def _install_cuts(self, pba):
        adapter, models = self, self.models
        memory, deps, chat = pba.memory, pba.deps, pba.chat_handler
        add_message, submit_update = memory.add_message, memory.submit_update

        def guarded_add_message(role, content):                 # memory/memory_system.py:614
            if (role == 'user' and 'S->M' in adapter.cut) or (role == 'assistant' and 'A->M' in adapter.cut):
                return
            add_message(role, content)

        def guarded_submit_update(request):                     # memory/memory_system.py:393
            if 'S->M' in adapter.cut and request.update_type == models.UpdateType.ADD_KNOWLEDGE:
                return models.MemoryUpdateResult(success=True, action=models.UpdateAction.SKIPPED,
                                                 message='not admitted (S->M cut)')
            return submit_update(request)

        memory.add_message, memory.submit_update = guarded_add_message, guarded_submit_update

        extract = chat._incremental_extract_and_save           # chat_handler.py:849

        async def guarded_extract(user_query, assistant_response):
            if 'S->M' in adapter.cut:
                user_query = ''
            if 'A->M' in adapter.cut:
                assistant_response = ''
            return await extract(user_query, assistant_response)

        chat._incremental_extract_and_save = guarded_extract

        if pba.ite is not None:                                  # ite_module.py:419
            record = pba.ite._record_direct_push
            pba.ite._record_direct_push = lambda fact_ids, sources=None: (
                None if 'A->M' in adapter.cut else record(fact_ids, sources))

        view = self._memory_view(memory)                         # M->A receivers
        pba.memory = view                                        # FSP inputs (eval/adapter.py:430-432); writes pass through
        deps.planning_agent.memory = view
        deps.assistant_agent.memory = view
        if pba.fsp is not None:
            pba.fsp.memory = view
        if pba.ite is not None:
            pba.ite.memory = view

        search = deps.search_service.search                      # services/search_service.py:105

        def guarded_search(topic, purpose, generate_report=False):
            if 'A->S' in adapter.cut:
                topic, purpose = '', ''
            return search(topic=topic, purpose=purpose, generate_report=generate_report)

        deps.search_service.search = guarded_search

        monitor = deps.topic_monitor.run                         # agents/topic_monitor.py:37

        def guarded_monitor(current_topic, conversation_history, new_message, existing_topics):
            if 'M->S' in adapter.cut:
                current_topic, conversation_history, existing_topics = None, [], []
            return monitor(current_topic=current_topic, conversation_history=conversation_history,
                           new_message=new_message, existing_topics=existing_topics)

        deps.topic_monitor.run = guarded_monitor
        plan_search = deps.search_service.search_planner.run    # agents/search_planner.py:37

        def guarded_plan(topic, purpose, user_profile=None, existing_knowledge=None):
            if 'M->S' in adapter.cut:
                user_profile = None
            return plan_search(topic=topic, purpose=purpose, user_profile=user_profile,
                               existing_knowledge=existing_knowledge)

        deps.search_service.search_planner.run = guarded_plan

    # ---- items -------------------------------------------------------------------------------------------
    def _scenario(self, it):
        return json.loads((SCENARIOS / f'{it["scenario"]}.json').read_text())

    def _context(self, it):
        sc = self._scenario(it)
        p, facts = sc['user_profile'], {f['id']: f['fact'] for f in sc['fact_sheet']}
        m1, m2 = it['messages']
        lines = [f'The user is a {p["persona"]}. Situation: {p["context"]}. Communication style: {p["communication_style"]}.',
                 f'At {m1["time"]} the user wrote: "{m1["text"]}" The assistant replied (not shown) and the user was then away '
                 f'until {m2["time"]}. The assistant may send an unprompted note while the user is away. At {m2["time"]} '
                 f'the user wrote: "{m2["text"]}"',
                 'The assistant can find facts about this user\'s situation only by searching. The true facts that '
                 'matter here are:']
        lines += [f'- {facts[f]}' for f in it['judge_facts']]
        return '\n'.join(lines)

    def items(self):
        return [{'id': it['id'], 'judge_context': self._context(it)} for it in self.items_data]

    # ---- one day -------------------------------------------------------------------------------------------
    @staticmethod
    def _minutes(t):
        h, m = t.split(':')
        return int(h) * 60 + int(m)

    @staticmethod
    def _push_events(abl):
        """ProactiveBenchRunner._push_events_from_ablation (runner.py:533-553)."""
        events = [e for e in (abl.get('push_events', []) or []) if isinstance(e, dict)]
        if events:
            return events
        if abl.get('has_direct_push') and abl.get('push_content'):
            return [{'push_content': abl.get('push_content'), 'push_fact_ids': abl.get('push_fact_ids', [])}]
        return []

    def run(self, item, cut, sample):
        it = next(x for x in self.items_data if x['id'] == item['id'])
        self.cut, self.calls = set(cut), []
        # The tag names the item, the sample and the phase, not the arm: arms whose prompts are identical
        # share the cached reply, so each comparison differs only where the cut changes a prompt.
        base = f'{it["id"]}|s{sample}'
        msgs = it['messages']
        gaps = [0] + [60 * (self._minutes(b['time']) - self._minutes(a['time'])) for a, b in zip(msgs, msgs[1:])]
        self.run_dir = Path(tempfile.mkdtemp(prefix=f'{it["id"]}-', dir=self.work))
        turns = []
        try:
            scenario = self.Scenario.from_dict(self._scenario(it))
            pba = self.PBA(CONDITION, self.Client(), **RUN_ARGS)
            pba.reset(scenario)                                  # eval/adapter.py:292
            self._install_cuts(pba)
            pba._idle_rng = idle = ScriptedIdle(gaps)
            for turn, msg in enumerate(msgs, 1):
                # runner.py:233-322: idle phase (FSP, ITE, direct push), then the user's message and the reply
                self.tag, self.counts, idle.turn = f'{base}|idle{turn}', {}, turn
                abl = pba.run_ablation_turn(turn)
                pushes = [e.get('push_content') or e.get('content') for e in self._push_events(abl)]
                for content in pushes:
                    if content:
                        pba.record_direct_push(content)
                self.tag, self.counts = f'{base}|turn{turn}', {}
                res = asyncio.run(pba.send_message(msg['text']))
                turns.append({
                    'time': msg['time'], 'idle_seconds': gaps[turn - 1], 'pushes': [p for p in pushes if p],
                    'intents': [{k: i.get(k) for k in ('topic', 'source', 'confidence')} for i in abl.get('exploration_intents', [])],
                    'intent_results': [{k: r.get(k) for k in ('topic', 'decision', 'push_score', 'facts_stored', 'fact_ids')}
                                       for tick in abl.get('idle_tick_results', []) for r in tick.get('intent_results', [])],
                    'ite_ran': abl.get('ite_ran', False), 'idle_facts_stored': abl.get('facts_stored', 0),
                    'user': msg['text'], 'reply': res['agent_response'], 'searched': bool(res.get('search_performed')),
                    'topic': res.get('topic'),
                })
            memory = pba.deps.memory
            knowledge = [k.summary or k.content[:200] for k in memory.search_knowledge(it['messages'][-1]['text'], 10)]
            profile = memory.get_user_profile().to_prompt_text()
        finally:
            self.clear_chroma()
            shutil.rmtree(self.run_dir, ignore_errors=True)
        first, last = turns[0], turns[-1]
        note = '\n\n'.join(last['pushes']) if last['pushes'] else '(no unprompted message)'
        output = (f'[between {first["time"]} and {last["time"]}, while the user is away] Assistant, unprompted:\n{note}\n\n'
                  f'[{last["time"]}] User: {last["user"]}\n\n[{last["time"]}] Assistant:\n{last["reply"]}')
        facts = {f['id']: f['fact'] for f in self._scenario(it)['fact_sheet']}
        delivered = _tokens(note + ' ' + last['reply'])
        recall = [len(_tokens(facts[f]) & delivered) / max(1, len(_tokens(facts[f]))) for f in it['judge_facts']]
        return {
            'output': output,
            'day': turns,
            'knowledge_at_end': knowledge,
            'profile_at_end': profile,
            'calls': self.calls,
            'metrics': {
                'pushed': len(last['pushes']),
                'idle_intents': len(last['intents']),
                'idle_facts_stored': last['idle_facts_stored'],
                'reply_searched': int(last['searched']),
                # share of each ground-truth fact's content words found in the note plus the reply (lexical)
                'key_fact_recall': round(sum(recall) / len(recall), 4),
                'backbone_calls': len(self.calls),
            },
        }
