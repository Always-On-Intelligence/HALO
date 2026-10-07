"""HALO run-mode adapter for the Proactive Agent (thunlp/ProactiveAgent at commit 3fcf9be) in its Environment Gym.

The gym (gym/main.py, gym/components/) runs three components on a codelinker event bus: the environment
simulator (EnvManager) turns each activity into events, the user simulator (User) acts and judges the
agent's proposals, and the ProactiveAgent watches the events, proposes a task or stays silent, and, after
the user's verdict, executes the task with its operations; each executed action is again an activity that
the environment turns into events. Every component reads the shared event store through gather(), so the
agent's proposal prompt is its retained event and dialogue history (activeagent.py:111-130).

What runs from core/ unchanged: the three components, their prompts and pydantic models, and codelinker
(pip package) for the bus and the requests (tool-call schemas, validation, JSON fixes). The adapter
reproduces gym/main.py's data_loop (lines 35-57) with a fresh EventSink per run, without the jsonl dump and
without the environment-adaptation dialogue between the simulators (lines 49-52). The user takes each scripted
step once the bus is idle (user.step called by the adapter, action_times=0); in the gym user.step re-fires on
every event batch and waits for the agent (user.py:51,88-112), which races with instant cached replies.

Replaced (model client only): codelinker's 'openai' request function (codelinker/request/openai.py) is
replaced by Adapter._request, registered with OBJGenerator.register_request_lib. It answers
  * from the scripted episode (inputs/episodes.json): the environment's scene expansion
    (expand_scene_description), the user's profile (update_info), the user's next activity
    (generate_activities), and the environment's events for the user's activity (refine_events with
    <From User>) - the recorded ProactiveBench trace events, so the event stream is scripted;
  * with the HALO backbone: the agent's proposal (activeagent.py:126-130) and execution (activeagent.py:70-74);
  * with a second LLM on the same backend (tags 'user:' and 'env:'): the user's verdict on a proposal
    (user.py:136-141) and the environment's events for the agent's executed actions (environment.py:141-146
    with <From ProactiveAgent>), plus codelinker's schema-fix requests.
  Tool calls become a JSON-schema instruction appended to the system prompt, and the reply comes back as the
  call's arguments, made valid JSON as the API would return them: no code fence, backslashes that are not JSON
  escapes escaped (the backbone copies code such as a Ruby regex verbatim), brackets left open closed; anything
  else that does not parse goes to codelinker's own schema fix. Multi-turn messages become one transcript with
  role labels. Temperature is not passed on.

Cut sites:
  S->M  gym/components/activeagent.py:111-115 and 67-68 (agent.gather over the event store): events the
        agent has already answered (those before its last own entry) are not kept; the current events,
        its own proposals and actions, and the user's verdicts remain.
  M->A  gym/components/activeagent.py:111-129: the proposal prompt gets no history (hist stays empty, so
        messages = system prompt + current Observations); execution (lines 67-74) is unchanged.
  A->S  gym/components/environment.py:61,121-154: the environment does not take up the agent's executed
        action (env.step returns for an activity whose source is ProactiveAgent), so no event reports
        what the agent did. With scripted user activities this is the only route from the agent's actions
        to later observations; the gym's other route, the simulated user's next activity reacting to
        proposals and verdicts (user.py:102-112), is replaced by the script.
No evidence-step cuts: nothing in the gym revises the agent's prompts, rules or weights during a run
(learning happens offline from the logged data, dataset/build_agent_trainset.py).
"""
import asyncio, datetime, json, logging, os, random, re, sys
from pathlib import Path
from halo.run.adapter import BaseAdapter
from halo.run.llm import LLM

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'
UTC8 = datetime.timezone(datetime.timedelta(hours=8))   # the ProactiveBench traces were recorded in UTC+8
ROLES = [  # system-prompt openings -> (model role, tag prefix)
    ('<Role> You are a helpful assistant that provides proactive suggestions', 'agent'),   # activeagent.py:11
    ('<Role>\nYou are tasked with simulating a user', 'user'),                            # user.py:9
    ('<Role>\nYou are tasked with simulating an environment', 'env'),                     # environment.py:6
    ('Your task is to fix the string with schema errors', 'fix'),                         # codelinker objGen.py
]
TRANSCRIPT = ('The conversation so far, oldest first. Turns marked [assistant] are your own earlier replies. '
              'Reply to the last [user] turn.')
TOOL = ('\n\nAnswer by calling the function `{name}`{desc}. Reply with only a JSON object holding the '
        "function's arguments, following this JSON Schema:\n{schema}")


def _transcript(turns):
    if len(turns) == 1 and turns[0]['role'] == 'user':
        return turns[0]['content']
    return TRANSCRIPT + '\n\n' + '\n\n'.join(f"[{m['role']}]\n{m['content']}" for m in turns)


def _balanced(text):
    """Close the brackets a reply left open (the backbone sometimes drops closers at the end of long nested JSON)."""
    out, stack, in_str, esc = [], [], False, False
    closer = {'{': '}', '[': ']'}
    for ch in text:
        if in_str:
            esc, in_str = (False, in_str) if esc else (ch == '\\', ch != '"')
        elif ch == '"':
            in_str = True
        elif ch in closer:
            stack.append(ch)
        elif ch in '}]':
            while stack and closer[stack[-1]] != ch:
                out.append(closer[stack.pop()])
            if stack:
                stack.pop()
        out.append(ch)
    return text if in_str else ''.join(out) + ''.join(closer[c] for c in reversed(stack))


def _arguments(text):
    """Tool-call arguments as the API would return them: valid JSON. The reply loses its code fence, backslashes
    that are not JSON escapes are escaped (the backbone copies code such as /\\A./ verbatim), and brackets left
    open are closed. Text that still does not parse is left to codelinker's own schema fix."""
    m = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.S)
    text = m.group(1) if m else text
    escaped = re.sub(r'\\(.)', lambda e: e.group(0) if e.group(1) in '"\\/bfnrtu' else '\\\\' + e.group(1), text, flags=re.S)
    for candidate in (text, escaped, _balanced(escaped)):
        try:
            json.loads(candidate)
            return candidate
        except ValueError:
            pass
    return text


def _tool_reply(name, args):
    args = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call_0', 'type': 'function', 'function': {'name': name, 'arguments': args}}]}}]}


def _is_event(msg):
    if msg['role'] != 'user':
        return False
    try:
        return 'events' in json.loads(msg['content']).get('Tags', [])
    except (ValueError, AttributeError):
        return False


def _gym_time(ts):
    return datetime.datetime.fromtimestamp(ts, UTC8).strftime('%m-%d %H:%M:%S')   # environment.py:115 format


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'events kept in the shared event store and gathered into the agent history (activeagent.py:111-115)',
        'M->A': 'the retained event/dialogue history in the proposal prompt (activeagent.py:116-129)',
        'A->S': "the agent's executed actions turned into observed events by the environment (environment.py:61,121-154)",
    }
    steps = {}

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.sim_llm = LLM(llm.backend, llm.effort, llm.cache)   # second role: the gym's user and environment simulators
        self.spec = json.loads((CASE / 'inputs' / 'episodes.json').read_text())
        self.items_by_id = {it['id']: it for it in self.spec['items']}
        os.environ['CODELINKER_CFG'] = str(CASE / 'inputs' / 'codelinker.toml')   # gym/config.py:37
        sys.path.insert(0, str(CORE))
        import yaml, codelinker
        import gym.config as G
        import gym.components.base as B
        from gym.components import ProactiveAgent, UserAgent, EnvironmentStateManager
        self.codelinker, self.G, self.B = codelinker, G, B
        self.Agent, self.User, self.Env = ProactiveAgent, UserAgent, EnvironmentStateManager
        logging.getLogger().setLevel(logging.ERROR)   # gym/config.py logs every event at DEBUG to stderr
        G.clinker.objGen.register_request_lib('openai', self._request)
        self.scenes = yaml.safe_load((CORE / 'dataset' / 'new_scenes_good.yaml').read_text())
        self.cut, self.tag, self.batch, self._attempts, self._error, self.calls = set(), '', 0, {}, None, {}

    # ---- the scripted episode ----------------------------------------------------------------------
    def _load(self, item):
        trace = json.loads((CORE / item['trace']).read_text())
        scene = self.scenes[item['scene']]
        times = [float(x['observation']['time']) for x in trace]
        ops = []
        for s in scene['environment']['agent_ops']:
            m = re.match(r'\s*([\w.]+)\((.*)\)\s*$', s)
            ops.append({'name': m.group(1) if m else s, 'doc': s,
                        'arguments': [a.strip() for a in m.group(2).split(',') if a.strip()] if m else []})
        setting = {'overview': scene['environment']['description'], 'time': _gym_time(times[0] - 1), 'agent_ops': ops,
                   'entities': [{'name': e, 'description': e, 'status': 'Available', 'properties': [],
                                 'available_ops': [], 'past_actions': []} for e in scene['environment']['entities']]}
        batches = []
        for b in item['batches']:
            events = [{'event': trace[i]['observation']['event'], 'updated_entities': [],
                       'deltatime': max(1, round(times[i] - (times[i - 1] if i else times[0] - 1)))} for i in b['events']]
            batches.append({'activity': b['activity'], 'events': events,
                            'needs_help': bool(trace[b['events'][-1]].get('task_status'))})
        return scene, setting, batches

    def _scripted(self, name, turns):
        """Replies that come from the scripted episode instead of a model; None when a model answers."""
        if name == 'expand_scene_description':                      # environment.py:42-53
            return self.setting
        if name == 'update_info':                                   # user.py:61-66
            return self.item['user_info']
        if name == 'generate_activities':                           # user.py:105-110
            self.batch += 1
            if self.batch > len(self.batches):
                return {'is_finished': True, 'act': 'I have finished the task.'}
            self.starts.append(len(self.sink.all_events))
            return {'is_finished': False, 'act': self.batches[self.batch - 1]['activity']}
        if name == 'refine_events':                                 # environment.py:141-146
            source = re.search(r'<From (\w+)>', turns[-1]['content'] if turns else '')
            if source and source.group(1) == 'User':
                return {'thoughts': 'Events recorded for this activity.', 'events': self.batches[self.batch - 1]['events']}
        return None

    # ---- model client --------------------------------------------------------------------------------
    async def _request(self, *, config=None, **kw):
        """Stands in for codelinker.request.openai.chatcompletion_request; returns a ChatCompletion-shaped dict."""
        messages = [m for m in kw.get('messages', []) if isinstance(m.get('content'), str)]
        system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
        turns = [m for m in messages if m['role'] != 'system']
        tool = (kw.get('tools') or [{}])[0].get('function')
        if tool:
            scripted = self._scripted(tool['name'], turns)
            if scripted is not None:
                return _tool_reply(tool['name'], scripted)
        role = next((r for sig, r in ROLES if system.startswith(sig)), 'agent')
        if role == 'fix':
            role = self._last_role
        self._last_role = role
        last = turns[-1]['content'] if turns else ''
        kind = tool['name'] if tool else ('propose' if 'Now analyze the history events' in last else
                                          'execute' if 'Decide what to do next by executing' in last else 'chat')
        if tool:
            desc = f": {tool['description']}" if tool.get('description') else ''
            system += TOOL.format(name=tool['name'], desc=desc, schema=json.dumps(tool['parameters'], ensure_ascii=False))
        text = await asyncio.to_thread(self._call, role, kind, system, _transcript(turns))
        if tool:
            return _tool_reply(tool['name'], _arguments(text))
        return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': text}}]}

    def _call(self, role, kind, system, user):
        """One model call. The tag names item, sample, batch and stage, never the arm; repeats of the same
        request within a batch (codelinker retries) get their own tag."""
        if self._error:
            raise self._error
        key = (self.batch, role, kind, system, user)
        n = self._attempts[key] = self._attempts.get(key, -1) + 1
        prefix = '' if role == 'agent' else f'{role}:'
        tag = f'{prefix}{self.tag}|b{self.batch}|{kind}' + (f'|retry{n}' if n else '')
        self.calls[role] = self.calls.get(role, 0) + 1
        try:
            return (self.llm if role == 'agent' else self.sim_llm)(system, user, tag=tag)
        except Exception as e:   # the gym's tasks swallow exceptions; keep it and raise after the episode
            self._error = e
            raise

    # ---- cut sites -----------------------------------------------------------------------------------
    def _install_cuts(self, env, agent):
        ch = self.G.sinkChannels
        gather = agent.gather

        def agent_gather(tags=None, return_dumper='json'):
            msgs = gather(tags, return_dumper)
            own = [i for i, m in enumerate(msgs) if m['role'] == 'assistant']
            last = own[-1] if own else -1
            if 'M->A' in self.cut and tags is not None and ch.activity not in tags:
                return msgs[last + 1:]      # proposal prompt (activeagent.py:111-129): no history turns
            if 'S->M' in self.cut:
                return [m for i, m in enumerate(msgs) if i > last or not _is_event(m)]
            return msgs
        agent.gather = agent_gather

        step = env.step

        async def env_step():
            if 'A->S' in self.cut:
                activity = json.loads(env.gather(ch.activity)[-1]['content'])   # as environment.py:127
                if activity.get('Source') == 'ProactiveAgent':
                    return
            return await step()
        env.step = env_step               # registered by env.setup (environment.py:61)

    # ---- one episode (gym/main.py:35-57) ---------------------------------------------------------------
    async def _episode(self, scene):
        G, ch = self.G, self.G.sinkChannels
        self.sink = self.codelinker.EventSink(sinkChannels=ch, logger=G.logger)
        G.eventSink = self.B.eventSink = self.sink          # a fresh store per run (gym/config.py:42)
        self.sink.init()
        env = self.Env(**scene['environment'])
        # dataset/build_scenes.py:189 gives the user the scene's theme when it writes a gym config. action_times=0
        # turns off the event-triggered user.step (user.py:51); the loop below calls user.step itself.
        user = self.User(**dict(scene['user'], theme=scene['environment']['theme']), action_times=0)
        agent = self.Agent()
        self._install_cuts(env, agent)
        self.sink.add(tags=ch.setup, content='Setup Components...')
        await self.sink.wait(ch.setup)
        self.sink.add(tags=ch.setup, content='Setup Completed!', silent=True)
        # gym/main.py:49-52, the environment-adaptation dialogue between simulators, is not run.
        # gym/main.py:55-57 starts the user once; user.step then re-fires on every event batch and waits for the
        # agent (user.py:88-112). Here the user takes each scripted step once the bus is idle, the order
        # user.step intends; its own re-firing races with instant (cached) replies and can skip the agent.
        for _ in self.batches:
            await user.step()
            await self.sink.wait(sorted(ch.all))
        self.sink.cleanup_thd.cancel()
        self.sink.run_scheduled_thd.cancel()

    def items(self):
        out = []
        for item in self.spec['items']:
            scene, _, batches = self._load(item)
            steps = [f'Step {k}. The user: {b["activity"]}\nEvents: ' + ' '.join(e['event'] for e in b['events'])
                     for k, b in enumerate(batches, 1)]
            out.append({'id': item['id'], 'judge_context': json.dumps({
                'user goal': scene['user']['goal'], 'user': scene['user']['description'],
                "assistant's available operations": scene['environment']['agent_ops'],
                'what happened, step by step': steps}, ensure_ascii=False, indent=1)})
        return out

    def run(self, item, cut, sample):
        self.item = self.items_by_id[item['id']]
        scene, self.setting, self.batches = self._load(self.item)
        self.cut, self.tag = set(cut), f'{item["id"]}|s{sample}'
        self.batch, self.starts, self._attempts, self._error, self.calls, self._last_role = 0, [], {}, None, {}, 'agent'
        random.seed(self.tag)   # env.step samples events_example (environment.py:130); same draws in every arm
        asyncio.run(asyncio.wait_for(self._episode(scene), timeout=3600))
        if self._error:
            raise RuntimeError(f'model call failed: {self._error}')
        return self._result()

    def _result(self):
        events, starts = self.sink.all_events, self.starts + [len(self.sink.all_events)]
        steps = []
        for k, b in enumerate(self.batches):
            rec = {'step': k + 1, 'needs_help': b['needs_help'], 'proposal': None, 'response': None,
                   'accepted': None, 'actions': [], 'action_events': [], 'answered': False}
            if k >= len(self.starts):
                rec['reached'] = False
                steps.append(rec)
                continue
            scripted = 0
            for e in events[starts[k]:starts[k + 1]]:
                if e.source == 'ProactiveAgent' and 'agent.proactive' in e.tags:
                    rec['answered'] = True    # null proposals are stored too (silent), activeagent.py:174
                    try:
                        p = json.loads(e.content)
                        rec['proposal'], rec['response'] = p.get('Proactive Task'), p.get('Response')
                    except ValueError:
                        rec['proposal'] = e.content
                elif e.source == 'User' and 'agent.proactive' in e.tags:
                    rec['accepted'] = e.content.rstrip().endswith('Is Accepted: True')
                elif e.source == 'ProactiveAgent' and 'activity' in e.tags:
                    try:
                        rec['actions'].append(json.loads(e.content).get('Action'))
                    except ValueError:
                        rec['actions'].append(e.content)
                elif e.source == 'EnvManager' and 'events' in e.tags:
                    if scripted < len(b['events']):
                        scripted += 1
                    else:
                        rec['action_events'].append(e.content)
            if rec['proposal'] in ('null', ''):
                rec['proposal'] = None
            steps.append(rec)

        def line(r):
            if r.get('reached') is False:
                return f'Step {r["step"]}: (not reached)'
            if not r['answered']:
                return f'Step {r["step"]}: no reply (the agent\'s step failed).'
            if not r['proposal']:
                return f'Step {r["step"]}: no proposal (stays silent).'
            s = f'Step {r["step"]}: proposes "{r["proposal"]}". Message to the user: "{r["response"]}".'
            if r['actions']:
                s += ' Then executes: ' + '; '.join(str(a) for a in r['actions']) + '.'
            return s

        proposed = [r for r in steps if r['proposal']]
        accepted = [r for r in proposed if r['accepted']]
        return {
            'output': '\n'.join(line(r) for r in steps),
            'steps': steps,
            'calls': self.calls,
            'metrics': {
                'proposals': len(proposed),
                'accepted': len(accepted),
                'acceptance_rate': round(len(accepted) / len(proposed), 4) if proposed else None,
                'label_agreement': round(sum(bool(r['proposal']) == r['needs_help'] for r in steps) / len(steps), 4),
                'executed_actions': sum(len(r['actions']) for r in steps),
                'observed_action_events': sum(len(r['action_events']) for r in steps),
                'failed_steps': sum(1 for r in steps if not r['answered']),
                'backbone_calls': sum(self.calls.values()),
            },
        }
