"""HALO run-mode adapter for EAIA, the Executive AI Assistant (langchain-ai/executive-ai-assistant, commit 758db71).

The run executes EAIA's own LangGraph code from core/: the main graph (eaia/main/graph.py) with
draft_response, rewrite and the human-in-the-loop nodes of human_inbox.py, and the reflection graphs
of eaia/reflection_graphs.py, with an in-memory LangGraph store and checkpointer. The adapter plays
the parts that run outside that code: the cron job and the LangGraph server (it starts one thread per
email and attaches the store and checkpointer), the Agent Inbox user (a simulated user answers the
interrupts), and Gmail/Calendar (in-memory fakes).

Replacements (README.md lists them in full):
  * ChatOpenAI and ChatAnthropic (all six model sites) -> HaloChat, a LangChain chat model that sends
    each request to the HALO backbone. bind_tools/with_structured_output ask the backbone for one JSON
    tool call, which is parsed into AIMessage.tool_calls; LangChain's own parsers build the pydantic or
    TypedDict result. Tool-call ids are a hash of the call, so trajectories are reproducible.
  * eaia/gmail.py -> in-memory fakes; langgraph_sdk client (human_inbox.LGC) -> an in-process client
    whose runs.create(None, "multi_reflection_graph", input) queues the run; like the server's
    background run, it executes the vendored reflection graph as a separate top-level invocation, here
    as soon as the main graph pauses or ends; langchain.agents.react.agent.create_react_agent ->
    langgraph.prebuilt.create_react_agent (used only by find_meeting_time, not reached here).
  * Triage is not run: each email enters the graph as triaged "email" via
    update_state(as_node="triage_input"), the real route_after_triage then sends it to draft_response.

One item = a learning phase (Alex edits drafts and answers questions, memory on) and a test phase on
new emails (memory off, neutral answers, drafts left pending in the inbox). The judge compares the
test drafts against Alex's hidden rules R1-R5.

Cut sites (receiving end; the rest of the run is unchanged):
  record       reflection input loses the assistant's own messages (its draft or tool calls):
               human_inbox.py:105-117, 171-183, 215-230 build the input; reflection_graphs.py:153 and
               :72 read it through get_trajectory_clean. Cut in _reflection_run.
  outcome      EAIA's own memory switch is off during learning (config memory, read at
               human_inbox.py:76/142; branches :103, :169, :212, :232 never call save_email or the
               reflection graph), so no feedback reaches reflection.
  attribution  each reflection run gets the feedback with the previous email's trajectory instead of
               its own (input["messages"] replaced in _reflection_run before reflection_graphs.py:153);
               the first email's feedback runs after the last learning email, with that email's
               trajectory.
  revision     the reflection graphs run, but update_general's write (reflection_graphs.py:90-93) is
               discarded by the store view, so later drafts read the original prompts at
               draft_response.py:102-125 and rewrite.py:38-49 (this also covers later_use).
  A->S         the Question tool's request (human_inbox.py:79-89, action_request.args) does not reach
               the inbox: the simulated user sees the email but not the question. Only learning-phase
               answers change, since test-phase answers are neutral in every arm.
  M->A         (implemented, not in run.yaml) draft_response.py:102-125 and rewrite.py:38-49 read the
               config defaults instead of the stored prompts. The test drafts then get the same prompts
               as under the revision cut, so the test duplicates `revision`; `later_use` is an alias.
  S->M, A->M   aliases of `outcome` and `record`: the user's feedback (S->M) and the assistant's own
               trajectory (A->M) reach memory only through the reflection input, at the same sites.
M->S is not realized: no stored information reaches the reading of a new email (triage few-shot
examples would be M->A, and triage is not run).
"""
import asyncio, fcntl, hashlib, json, os, re, sys, tempfile, traceback, types, uuid
from pathlib import Path
from typing import Any, Optional

os.environ['LANGSMITH_TRACING'] = 'false'        # human_inbox's @traceable must not upload traces
os.environ['LANGCHAIN_TRACING_V2'] = 'false'

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore, GetOp, PutOp
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from halo.run.adapter import BaseAdapter
from halo.run.llm import LLM

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                      # vendored upstream code, see core/SOURCE.md
NS = ('default',)                         # EAIA's prompt namespace: (assistant_id,), assistant_id "default"
PROMPT_KEYS = {                           # store key -> config key holding its default (draft_response.py, rewrite.py)
    'schedule_preferences': 'schedule_preferences',
    'random_preferences': 'background_preferences',
    'response_preferences': 'response_preferences',
    'rewrite_instructions': 'rewrite_preferences',
}
ALIASES = {'S->M': 'outcome', 'A->M': 'record', 'later_use': 'M->A'}
LOCKS = Path(tempfile.gettempdir()) / 'halo-eaia-locks'
RETRY_NOTE = '\n\n(Your previous reply was not one valid JSON object of the requested form. Reply with the JSON object only.)'
_ROUTER = None                            # the Adapter instance that HaloChat sends requests to


# ---- model clients -> HALO backbone ------------------------------------------------------------
class HaloChat(BaseChatModel):
    """Stands in for ChatOpenAI and ChatAnthropic. Constructor arguments are accepted as upstream
    passes them; temperature and the model name are not forwarded (the CLI backbone has no such knobs).
    tool_choice given to the constructor (draft_response.py:85-90) applies when a call sets none."""
    model: str = 'gpt-4o'
    temperature: Optional[float] = None
    parallel_tool_calls: Optional[bool] = None
    tool_choice: Any = None

    @property
    def _llm_type(self):
        return 'halo-backbone'

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], tool_choice=tool_choice, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._result(messages, run_manager, kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return await asyncio.to_thread(self._result, messages, run_manager, kwargs)

    def _result(self, messages, run_manager, kwargs):
        choice = kwargs.get('tool_choice') or self.tool_choice
        node = (getattr(run_manager, 'metadata', None) or {}).get('langgraph_node', 'model')
        msg = _ROUTER.chat(messages, kwargs.get('tools') or [], choice, node)
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _text(content):
    if isinstance(content, str):
        return content
    return '\n'.join(c.get('text', '') if isinstance(c, dict) else str(c) for c in content or [])


def _render_messages(messages):
    """OpenAI-style chat messages as one transcript (a single user message is passed as is)."""
    system = [_text(m.content) for m in messages if isinstance(m, SystemMessage)]
    convo = [m for m in messages if not isinstance(m, SystemMessage)]
    if len(convo) == 1 and isinstance(convo[0], HumanMessage):
        return system, _text(convo[0].content)
    parts = []
    for m in convo:
        if isinstance(m, HumanMessage):
            parts.append('[user]\n' + _text(m.content))
        elif isinstance(m, AIMessage):
            lines = [_text(m.content)] if _text(m.content).strip() else []
            lines += [f'(called tool {tc["name"]} with arguments {json.dumps(tc["args"], ensure_ascii=False)})'
                      for tc in m.tool_calls]
            parts.append('[assistant]\n' + '\n'.join(lines))
        elif isinstance(m, ToolMessage):
            parts.append((f'[result of tool {m.name}]\n' if m.name else '[tool result]\n') + _text(m.content))
        else:
            parts.append(f'[{m.type}]\n' + _text(m.content))
    return system, '\n\n'.join(parts)


def _choice(tools, choice):
    """-> (forced tool name or None, a tool call is required)."""
    names = [t['function']['name'] for t in tools]
    if isinstance(choice, dict):
        return (choice.get('function') or {}).get('name') or choice.get('name'), True
    if choice in names:
        return choice, True
    if choice in ('any', 'required', True):
        return (names[0] if len(names) == 1 else None), True
    return None, False


def _render_tools(tools, forced, required):
    lines = ['You can call these tools:']
    for t in tools:
        f = t['function']
        lines.append(f'- {f["name"]}: {(f.get("description") or "").strip()}\n'
                     f'  arguments (JSON schema): {json.dumps(f.get("parameters", {}), ensure_ascii=False)}')
    if forced:
        lines.append(f'\nCall the tool `{forced}`.')
    elif required:
        lines.append('\nCall exactly one of these tools.')
    else:
        lines.append('\nCall one of these tools, or answer without a tool.')
    lines.append('Reply with one JSON object only, with no code fence: {"tool": "<tool name>", "args": {<arguments>}}'
                 + ('' if forced or required else ', or {"tool": null, "content": "<your answer>"} to answer without a tool') + '.')
    return '\n'.join(lines)


def _first_json(text):
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', (text or '').strip())
    try:
        return json.loads(t)
    except ValueError:
        i, j = t.find('{'), t.rfind('}')
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except ValueError:
                return None
    return None


def _fill(args, schema):
    """Schema-valid arguments, as an API with tool calling returns them: missing required fields get an
    empty value and a list field given as a string becomes a list."""
    props = schema.get('properties', {})
    for k in schema.get('required', []):
        if k not in args:
            args[k] = {'array': [], 'string': '', 'boolean': True, 'object': {}}.get(props.get(k, {}).get('type'), '')
    for k, p in props.items():
        if p.get('type') == 'array' and isinstance(args.get(k), str):
            v = _first_json(args[k]) if args[k].strip().startswith('[') else None
            args[k] = v if isinstance(v, list) else ([args[k]] if args[k].strip() else [])
    return args


def _parse(text, tools, forced, required):
    obj = _first_json(text)
    names = [t['function']['name'] for t in tools]
    if not isinstance(obj, dict):
        return None if required else AIMessage(content=text)
    name, args = obj.get('tool', obj.get('name')), obj.get('args', obj.get('arguments'))
    if forced or (required and name is None and len(names) == 1):
        if not isinstance(args, dict):
            args = {k: v for k, v in obj.items() if k not in ('tool', 'name', 'args', 'arguments')}
        name = forced or names[0]
    elif name is None:
        return None if required else AIMessage(content=_text(obj.get('content', text)))
    args = args if isinstance(args, dict) else {}
    schema = next((t['function'].get('parameters', {}) for t in tools if t['function']['name'] == name), None)
    if schema:
        args = _fill(args, schema)
    call_id = 'call_' + hashlib.sha256(json.dumps([name, args], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': call_id, 'type': 'tool_call'}])


# ---- store views used at cut sites -------------------------------------------------------------
class StoreView(BaseStore):
    """The run's store as one graph sees it. mask: prompt keys read as missing (M->A); a prompt write
    then only initializes a key the store does not hold yet. drop: prompt writes are discarded
    (revision). log: prompt writes are recorded with whether they were kept."""

    def __init__(self, base, mask=False, drop=False, log=None):
        self.base, self.mask, self.drop, self.log = base, mask, drop, log

    def batch(self, ops):
        ops = list(ops)
        out, keep = [None] * len(ops), []
        for i, op in enumerate(ops):
            prompt = getattr(op, 'namespace', None) == NS and getattr(op, 'key', None) in PROMPT_KEYS
            if prompt and isinstance(op, GetOp) and self.mask:
                continue
            if prompt and isinstance(op, PutOp):
                kept = not self.drop and (not self.mask or self.base.get(op.namespace, op.key) is None)
                if self.log is not None:
                    self.log.append({'key': op.key, 'written': kept})
                if not kept:
                    continue
            keep.append(i)
        if keep:
            for i, r in zip(keep, self.base.batch([ops[i] for i in keep])):
                out[i] = r
        return out

    async def abatch(self, ops):
        return self.batch(ops)


class _Runs:
    def __init__(self, adapter):
        self.adapter = adapter

    async def create(self, thread_id, assistant_id, *, input=None, **kwargs):
        if thread_id is not None or assistant_id != 'multi_reflection_graph':
            raise ValueError(f'unexpected background run {assistant_id!r} on thread {thread_id!r}')
        self.adapter.background.append(input)


class _ServerClient:
    """Replaces the langgraph_sdk client of human_inbox.py:13. As on the LangGraph server, the
    reflection run is a separate background run: it is queued here and runs as a top-level graph
    invocation once the main graph pauses or ends, before the next inbox answer or email."""

    def __init__(self, adapter):
        self.runs = _Runs(adapter)


def _is_assistant(m):
    if isinstance(m, dict):
        return m.get('role') in ('assistant', 'ai') or m.get('type') == 'ai'
    return isinstance(m, AIMessage)


class Adapter(BaseAdapter):
    channels = {
        'A->S': 'the Question tool call reaches the Agent Inbox as the interrupt request the user answers (human_inbox.py:79-89)',
        'M->A': 'stored prompts read by draft_response (draft_response.py:102-125) and rewrite (rewrite.py:38-49); duplicates revision in the test phase',
        'S->M': 'user feedback, edits, and answers reach the reflection input (human_inbox.py); same site as outcome',
        'A->M': "the assistant's own draft or tool calls reach the reflection input (human_inbox.py); same site as record",
    }
    steps = {
        'record': "reflection input keeps only the user's messages, without the assistant's draft or tool calls",
        'outcome': "EAIA's memory switch off during learning: no feedback reaches the reflection graph",
        'attribution': "each feedback reaches reflection with the previous email's trajectory",
        'revision': "reflection runs but update_general's prompt write is discarded; later drafts read the original prompts (covers later_use)",
    }

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        global _ROUTER
        _ROUTER = self
        inputs = Path(case_dir) / 'inputs'
        self.scenario = json.loads((inputs / 'scenario.json').read_text())
        emails = json.loads((inputs / 'emails.json').read_text())
        self.emails = {e['id']: e for e in emails['train'] + emails['test']}
        self.config = yaml.safe_load((inputs / 'config.yaml').read_text())
        self.rules = '\n'.join(self.scenario['rules'])
        self.user = self._user_llm()
        self.outbox, self.marked_read, self.invites = [], [], []
        self.ctx, self.cut, self.rec = '', set(), None
        self._install_stubs()
        import eaia.main.graph as main_graph
        import eaia.main.human_inbox as human_inbox
        import eaia.reflection_graphs as reflection_graphs
        from eaia.schemas import RespondTo, email_template
        human_inbox.LGC = _ServerClient(self)
        self.main_graph, self.multi_reflection = main_graph.graph, reflection_graphs.multi_reflection_graph
        self.RespondTo, self.email_template = RespondTo, email_template

    def _user_llm(self):
        """The simulated user: the same backend and cache as the backbone, effort medium, tags 'user:'."""
        return LLM(self.llm.backend, 'medium', self.llm.cache)

    # ---- stubs installed before the upstream import ------------------------------------------
    def _install_stubs(self):
        adapter = self
        for name, cls in (('langchain_openai', 'ChatOpenAI'), ('langchain_anthropic', 'ChatAnthropic')):
            mod = types.ModuleType(name)
            setattr(mod, cls, HaloChat)
            sys.modules[name] = mod
        # find_meeting_time.py:5 imports create_react_agent from langchain.agents.react.agent and calls
        # it as create_react_agent(llm, tools), the signature of langgraph.prebuilt.create_react_agent.
        from langgraph.prebuilt import create_react_agent
        for name in ('langchain', 'langchain.agents', 'langchain.agents.react'):
            sys.modules.setdefault(name, types.ModuleType(name))
        # langchain_core.globals reads these from a top-level `langchain` module when one is importable
        for attr, value in (('debug', False), ('verbose', False), ('llm_cache', None)):
            setattr(sys.modules['langchain'], attr, value)
        react = types.ModuleType('langchain.agents.react.agent')
        react.create_react_agent = create_react_agent
        sys.modules['langchain.agents.react.agent'] = react

        # eaia/gmail.py -> in-memory Gmail and Calendar with the same signatures
        from langchain_core.tools import tool
        from pydantic import BaseModel, Field
        gmail = types.ModuleType('eaia.gmail')

        def send_email(email_id, response_text, email_address, gmail_token=None, gmail_secret=None, addn_receipients=None):
            adapter.outbox.append({'email_id': email_id, 'text': response_text, 'added': list(addn_receipients or [])})

        def mark_as_read(message_id, user_email, gmail_token=None, gmail_secret=None):
            adapter.marked_read.append(message_id)

        def send_calendar_invite(emails, title, start_time, end_time, email_address, timezone='PST'):
            adapter.invites.append({'emails': emails, 'title': title, 'start': start_time, 'end': end_time})
            return True

        class CalInput(BaseModel):
            date_strs: list[str] = Field(description='The days for which to retrieve events. Each day should be represented by dd-mm-yyyy string.')

        @tool(args_schema=CalInput)
        def get_events_for_days(date_strs: list[str]):
            """
            Retrieves events for a list of days. If you want to check for multiple days, call this with multiple inputs.

            Input in the format of ['dd-mm-yyyy', 'dd-mm-yyyy']

            Args:
            date_strs: The days for which to retrieve events (dd-mm-yyyy string).

            Returns: availability for those days.
            """
            return ''.join(f'***FOR DAY {d}***\n\nNo events\n\n' for d in date_strs)

        for fn in (send_email, mark_as_read, send_calendar_invite, get_events_for_days):
            setattr(gmail, fn.name if hasattr(fn, 'name') else fn.__name__, fn)
        sys.path.insert(0, str(CORE))
        import eaia
        sys.modules['eaia.gmail'] = gmail
        eaia.gmail = gmail

    # ---- backbone and simulated-user calls ------------------------------------------------------
    def _call(self, llm, system, user, tag):
        """llm(system, user, tag) under a lock per request, so that arms running in parallel workers
        make an identical request once and share the cached reply (keeps the arms paired)."""
        key = hashlib.sha256(json.dumps([getattr(llm, 'backend', ''), getattr(llm, 'effort', ''), tag, system, user]).encode()).hexdigest()[:40]
        LOCKS.mkdir(exist_ok=True)
        with open(LOCKS / f'{key}.lock', 'w') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                return llm(system, user, tag=tag)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def chat(self, messages, tools, choice, node):
        """One chat-model request from EAIA code (called by HaloChat)."""
        system, user = _render_messages(messages)
        forced, required = _choice(tools, choice)
        if tools:
            system.append(_render_tools(tools, forced, required))
        system = '\n\n'.join(system)
        tag, text = f'{self.ctx}|{node}', ''
        for attempt in range(3):
            self.calls += 1
            text = self._call(self.llm, system, user + (RETRY_NOTE if attempt else ''), tag + (f'|retry{attempt}' if attempt else ''))
            msg = _parse(text, tools, forced, required) if tools else AIMessage(content=text)
            if msg is not None:
                return msg
        return AIMessage(content=text)

    def _ask_user(self, system, user, stage, field):
        tag = f'user:{self.ctx}|{stage}'
        for attempt in range(3):
            self.user_calls += 1
            obj = _first_json(self._call(self.user, system, user + (RETRY_NOTE if attempt else ''), tag + (f'|retry{attempt}' if attempt else '')))
            if isinstance(obj, dict) and isinstance(obj.get(field), str):
                return obj
        raise RuntimeError(f'simulated user gave no valid reply at {tag}')

    # ---- the reflection run started by the inbox nodes (cut sites record and attribution) -------
    async def _reflection_run(self, inp):
        inp = dict(inp)
        self.reflection_inputs[self.email['id']] = list(inp['messages'])
        entry = {'feedback': inp['feedback'], 'prompt_types': inp['prompt_types']}
        self.rec['reflections'].append(entry)
        if 'record' in self.cut:
            inp['messages'] = [m for m in inp['messages'] if not _is_assistant(m)]
        if 'attribution' in self.cut:
            if not self.trajectories:          # first email: paired with the last learning email, later
                entry['deferred'] = True
                self.deferred.append((inp, entry))
                return
            inp['messages'] = self.trajectories[-1]
        await self._reflect(inp, entry)

    async def _reflect(self, inp, entry):
        n = len(self.write_log)
        await self.reflection.ainvoke(inp)
        entry['writes'] = self.write_log[n:]
        self.reflection_runs += 1

    def _trajectory(self, e, draft):
        """What EAIA's reflection input holds for an email: its last reflection input, or else the
        edit branch's form (human_inbox.py:216-225) built from the final draft."""
        if e['id'] in self.reflection_inputs:
            return self.reflection_inputs[e['id']]
        msgs = [{'role': 'user', 'content': f'Draft a response to this email:\n\n{self._template(e)}'}]
        return msgs + ([{'role': 'assistant', 'content': draft}] if draft else [])

    def _template(self, e):
        return self.email_template.format(email_thread=e['page_content'], author=e['from_email'],
                                          subject=e['subject'], to=e.get('to_email', ''))

    # ---- one email, from ingestion until it leaves the inbox --------------------------------------
    async def _email(self, e, phase):
        self.email, self.ctx = e, f'{self.item_id}|s{self.sample}|{phase}|{e["id"]}'
        rec = self.rec = {'email': e['id'], 'questions': [], 'draft': None, 'recipients': [], 'reflections': []}
        email = {'id': e['id'], 'thread_id': e['id'], 'from_email': e['from_email'], 'to_email': e['to_email'],
                 'subject': e['subject'], 'page_content': e['page_content'], 'send_time': '2026-10-05T09:00:00-07:00'}
        thread_id = str(uuid.UUID(hex=hashlib.md5(email['thread_id'].encode('UTF-8')).hexdigest()))   # cron_graph.py:22-24
        memory = phase == 'learn' and 'outcome' not in self.cut
        config = {'configurable': {**self.config, 'memory': memory, 'thread_id': thread_id}, 'recursion_limit': 40}
        triage = self.RespondTo(logic='Every email in this scenario needs a reply from Alex (triage not run).', response='email')
        await self.graph.aupdate_state(config, {'email': email, 'triage': triage}, as_node='triage_input')
        nxt, questions = None, 0
        for _ in range(12):
            await self.graph.ainvoke(nxt, config)
            while self.background:             # reflection runs started by the inbox nodes
                await self._reflection_run(self.background.pop(0))
            state = await self.graph.aget_state(config)
            pending = [i for t in state.tasks for i in t.interrupts]
            if not pending:
                break
            request = pending[0].value[0]
            action, args = request['action_request']['action'], request['action_request']['args']
            if action == 'Question':
                questions += 1
                answer = self._answer(e, phase, args.get('content', ''), questions)
                rec['questions'].append({'question': args.get('content', ''), 'answer': answer})
                response = {'type': 'ignore', 'args': None} if answer is None else {'type': 'response', 'args': answer}
            elif action == 'ResponseEmailDraft':
                rec['draft'], rec['recipients'] = args.get('content', ''), list(args.get('new_recipients') or [])
                if phase == 'test':
                    break                      # the draft waits in the inbox; the test reads it there
                response = self._edit(e, args, rec)
            elif action == 'SendCalendarInvite':
                response = {'type': 'response', 'args': self.scenario['user']['calendar_answer']}
            else:
                response = {'type': 'ignore', 'args': None}
            nxt = Command(resume=[response])
        if phase == 'learn':
            self.trajectories.append(self._trajectory(e, rec['draft']))
        return rec

    def _answer(self, e, phase, question, n):
        u = self.scenario['user']
        if n > 3:
            return None                        # the user ignores a fourth question
        if n == 3:
            return u['third_question_answer']
        if phase == 'test':
            return u['test_answer']
        if 'A->S' in self.cut:
            user = u['answer_user_without_question'].format(email=self._template(e))
        else:
            user = u['answer_user'].format(email=self._template(e), question=question)
        return self._ask_user(u['answer_system'].format(rules=self.rules), user, f'answer{n}', 'answer')['answer']

    def _edit(self, e, args, rec):
        u = self.scenario['user']
        draft, recipients = args.get('content', ''), list(args.get('new_recipients') or [])
        out = self._ask_user(u['edit_system'].format(rules=self.rules),
                             u['edit_user'].format(email=self._template(e), draft=draft, recipients=', '.join(recipients) or 'none'),
                             'edit', 'edited')
        edited = out['edited']
        new = out.get('new_recipients')
        new = [str(x) for x in new] if isinstance(new, list) else recipients
        rec['edited'], rec['edited_recipients'] = edited, new
        # Unchanged means the same lines (spacing and blank lines aside): line breaks matter for R3.
        lines = lambda s: [' '.join(ln.split()) for ln in s.strip().splitlines() if ln.strip()]
        if lines(edited) == lines(draft) and sorted(new) == sorted(recipients):
            rec['user'] = 'accept'
            return {'type': 'accept', 'args': None}
        rec['user'] = 'edit'
        return {'type': 'edit', 'args': {'action': 'ResponseEmailDraft', 'args': {'content': edited, 'new_recipients': new}}}

    # ---- harness interface ----------------------------------------------------------------------
    def items(self):
        out = []
        for it in self.scenario['items']:
            emails = '\n\n'.join(f'[{eid}] From: {self.emails[eid]["from_email"]}\nSubject: {self.emails[eid]["subject"]}\n\n'
                                 f'{self.emails[eid]["page_content"]}' for eid in it['test'])
            ctx = ("Alex Rivera is CEO of Lumen. An email assistant drafted Alex's replies to the new emails below. "
                   "Alex's rules for replies (the assistant was never told them; it could only learn them from "
                   "Alex's edits of its drafts on earlier emails):\n" + self.rules + '\n\nThe new emails:\n\n' + emails)
            out.append({'id': it['id'], 'judge_context': ctx})
        return out

    def run(self, item, cut, sample):
        return asyncio.run(self._run(item, {ALIASES.get(c, c) for c in cut}, sample))

    async def _run(self, item, cut, sample):
        spec = next(it for it in self.scenario['items'] if it['id'] == item['id'])
        self.item_id, self.sample, self.cut = item['id'], sample, cut
        self.calls = self.user_calls = self.reflection_runs = 0
        self.outbox, self.marked_read, self.invites = [], [], []
        self.reflection_inputs, self.trajectories, self.deferred, self.write_log, self.background = {}, [], [], [], []
        store = InMemoryStore()
        self.graph = self.main_graph.copy(update={'checkpointer': InMemorySaver(),
                                                  'store': StoreView(store, mask='M->A' in cut)})
        self.reflection = self.multi_reflection.copy(update={'store': StoreView(store, drop='revision' in cut, log=self.write_log)})
        errors, learning, tests = [], [], []
        for eid in spec['train']:
            learning.append(await self._safe(self.emails[eid], 'learn', errors))
        for inp, entry in self.deferred:       # attribution cut: the first email's feedback, paired with the last trajectory
            self.ctx = f'{self.item_id}|s{sample}|learn|{spec["train"][0]}|deferred'
            try:
                inp['messages'] = self.trajectories[-1]
                await self._reflect(inp, entry)
            except Exception as ex:
                print(f'[eaia] {self.ctx}: {type(ex).__name__}: {ex}\n{traceback.format_exc()}', file=sys.stderr, flush=True)
                errors.append(f'learn:deferred: {type(ex).__name__}: {str(ex)[:300]}')
        prompts = {k: (store.get(NS, k).value.get('data') if store.get(NS, k) else None) for k in PROMPT_KEYS}
        for eid in spec['test']:
            tests.append(await self._safe(self.emails[eid], 'test', errors))
        return {
            'output': self._format(tests),
            'prompts_at_test': prompts,
            'learning': learning,
            'test': tests,
            'errors': errors,
            'metrics': self._metrics(tests, prompts, errors),
        }

    async def _safe(self, e, phase, errors):
        try:
            return await self._email(e, phase)
        except Exception as ex:                # one failed email is reported, the arm goes on
            self.background.clear()
            print(f'[eaia] {self.ctx}: {type(ex).__name__}: {ex}\n{traceback.format_exc()}', file=sys.stderr, flush=True)
            errors.append(f'{phase}:{e["id"]}: {type(ex).__name__}: {str(ex)[:300]}')
            return {'email': e['id'], 'questions': [], 'draft': None, 'recipients': [], 'reflections': [], 'error': True}

    def _format(self, tests):
        blocks = []
        for r in tests:
            e = self.emails[r['email']]
            head = f'Reply to [{e["id"]}] "{e["subject"]}" from {e["from_email"]}'
            if r.get('draft') is None:
                blocks.append(head + '\n(no draft)')
            else:
                blocks.append(head + '\nAdded recipients: ' + (', '.join(r['recipients']) or 'none') + '\n---\n' + r['draft'].strip())
        return '\n\n'.join(blocks)

    def _metrics(self, tests, prompts, errors):
        """Rough rule checks on the test drafts (the judge is the main measure) and process counts."""
        checks = self.scenario['rule_checks']
        greeting = re.compile(r'^\s*(hi|hello|hey|dear|good (morning|afternoon|evening)|greetings)\b', re.I)
        r1, r3, r4, r5 = [], [], [], []
        for r in tests:
            d = (r.get('draft') or '').strip()
            lines = [ln.strip() for ln in d.splitlines() if ln.strip()]
            r1.append(bool(lines) and not greeting.match(lines[0]))
            r3.append(bool(lines) and lines[-1] == 'Thanks, Alex')
            if r['email'] in checks['deadline_asks']:
                r4.append('friday' in d.lower())
            if r['email'] in checks['partnership_asks']:
                r5.append('jordan@lumen.dev' in [x.lower() for x in r.get('recipients') or []] and 'jordan' in d.lower())
        rate = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
        changed = sum(1 for k, ck in PROMPT_KEYS.items() if (prompts.get(k) or '') != (self.config.get(ck) or ''))
        return {
            'no_greeting': rate(r1), 'signoff_thanks_alex': rate(r3), 'confirm_by_friday': rate(r4),
            'jordan_handoff': rate(r5), 'rule_checks_passed': rate(r1 + r3 + r4 + r5),
            'prompts_changed': changed, 'reflection_runs': self.reflection_runs,
            'backbone_calls': self.calls, 'user_calls': self.user_calls, 'errors': len(errors),
        }
