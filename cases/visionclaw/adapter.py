"""HALO run-mode adapter for VisionClaw (Intent-Lab/VisionClaw at commit 82699ec).

At this commit VisionClaw is three processes: the phone app streams glasses video and audio into a LiveKit
room; the voice worker (agent/main.py) joins the room with a realtime model (Gemini Live) and the tools
execute, browse, quick_search, show_card, save_note, recall_notes and delete_note; the gateway (gateway/src,
TypeScript) is the action-agent backend the paper calls OpenClaw: it speaks the OpenClaw protocol in front and
drives an Anthropic Managed Agents (CMA) session per call behind, with the user's connected apps as MCP tools.
The gateway also keeps the user's notes, the task ledger that briefs the next call, and parked results.

What runs (executed, unchanged):
- the gateway, under node 24 with tsx (core/gateway/src/*.ts), one process per call, with the store file kept
  across calls. Its model client module (cma.ts, imported as "./cma.js") resolves to shim/cma_stub.mjs.
- the voice worker's code (core/agent/main.py): entrypoint (pending-result drain and relay, app check, tool
  wiring), the tools and their gateway calls, the delegation loop, Tracer.

What is replaced:
- Gemini Live (the realtime model inside livekit.agents.AgentSession) -> a fake AgentSession whose turns are
  backbone calls. Each call sees the worker's INSTRUCTIONS, the tool declarations taken from the worker's tool
  functions, the call's conversation, the latest camera frame as text, and any generate_reply instructions,
  and returns what it says plus its function calls; the adapter runs the worker's tool functions.
- LiveKit rooms and media -> fake JobContext, room and participant; frames and audio are scripted text.
  encode_latest_frame (main.py:142, Pillow over a LiveKit frame) returns the frame description, base64.
- Anthropic Managed Agents (cma.ts) -> the bridge in this file: environments, agents, vaults and sessions as
  the gateway uses them, and each session turn run on the backbone with the gateway's AGENT_SYSTEM_PROMPT
  (provision.ts:6). The user's connected apps (Google Calendar through google_workspace_mcp, Notion) are
  simulated MCP tools over the item's scripted stores. The CMA agent toolset (bash, files, web) is not offered.
- quick_search's Gemini grounded search -> a backbone call without web access; Browser Use stays disabled.
- Timing: QUICK_ANSWER_S (main.py:350) is raised and the worker's gateway HTTP timeouts lifted, so a result
  always returns inside its turn whatever the backbone's latency; the gateway's clock reads the scripted call
  time (shim/clock.mjs) so ledger and briefing texts match across arms; the worker starts after the ticket's
  session pre-warm, as it does in a live call. shim/serial_store.mjs serializes the store's temp-file
  write-then-rename: saveStore always writes <store>.json.tmp (store.ts:99-105), and overlapping saves (e.g.
  the un-awaited pair at server.ts:289 and 295 on the hang-up path) otherwise fail and exit the process.

Cut sites (receiving end; file:line in core/):
  S->M  sensed or user-supplied content is not admitted to memory: save_note's POST /notes
        (main.py:547-558, 561-578) is answered 201 but never reaches the notes store (server.ts:529-548), and
        the simulated calendar and Notion keep their state when the action agent writes what the user showed.
  M->A  retained content does not reach action: recall_notes' GET /notes (main.py:581-600 -> server.ts:550-561)
        returns no notes; the call-start drain of parked results (main.py:444-456, 1260) returns none; the
        action agent's turn drops the system.message context that carries the task-ledger briefing
        (server.ts:433 -> turn.ts:75-85); calendar and Notion reads return nothing.
  A->M  action records are not retained: the task ledger (recordTask, server.ts:72-82, 289) and parked results
        (queuePending, server.ts:291-299, notify.ts:62-71) are cleared from the store before the next call
        starts (the gateway is restarted per call, so no reader sees them); the worker's own parking
        (_park_text, main.py:407-421) is not stored.
  A->S  the camera frame that the voice model's execute(attach_view=True) attaches (main.py:822-840 ->
        server.ts:242 -> turn.ts:65-74) does not reach the action agent: its turn gets the task text only.
Not realized: M->S (frame sampling and attachment do not read retained state). VisionClaw does not revise its
own mechanism, so no evidence step is cut.
"""
import asyncio
import base64
import copy
import inspect
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                                   # vendored upstream code, see core/SOURCE.md
NODE = os.environ.get('HALO_NODE_BIN') or shutil.which('node') or 'node'
USER_TOKEN, SERVICE_TOKEN = 'halo-user-token', 'halo-service-token'
MAX_TOOL_ROUNDS = 3        # model turns after tool results within one user turn
MAX_AGENT_ROUNDS = 4       # action-agent turns with tool calls within one delegated task

VOICE_PROTOCOL = """[Realtime session]
You are the realtime voice model of this assistant. Each message shows the conversation of the current call, the
latest camera frame you received (described in text) and what happens now: what the user just said, tool results
coming back, or an instruction from the app for your next reply.

You can call these functions:
{tools}

Answer with exactly one JSON object and nothing else:
{{"say": "what you say aloud now (may be empty)", "calls": [{{"name": "function name", "args": {{...}}}}]}}
Leave "calls" empty when you only speak. Function results come back in the next message and you speak again."""

AGENT_PROTOCOL = """[Managed agent session]
Current date and time: {now}.
The user's connected apps are reachable through these MCP tools:
{tools}
A call to an app the user has not connected fails with an authorization error.

Answer with exactly one JSON object and nothing else:
{{"calls": [{{"server": "server name", "tool": "tool name", "input": {{...}}}}], "message": "your reply"}}
While you still need tool results, list the calls and leave "message" empty; the results come back in the next
message. When you are done, return no calls and put your final reply, the one the voice layer speaks, in "message"."""

MCP_TOOLS = {
    'gcal-self': [
        ('get_events', 'List calendar events. Input: {"time_min": "YYYY-MM-DDTHH:MM", "time_max": "YYYY-MM-DDTHH:MM", "query": "optional text"}'),
        ('create_event', 'Create an event. Input: {"summary": str, "start_time": "YYYY-MM-DDTHH:MM", "end_time": "YYYY-MM-DDTHH:MM", "location": str, "description": str}'),
        ('modify_event', 'Change an event. Input: {"event_id": str, plus any of summary, start_time, end_time, location, description}'),
        ('delete_event', 'Delete an event. Input: {"event_id": str}'),
    ],
    'notion': [
        ('notion-search', 'Search pages. Input: {"query": str}'),
        ('notion-fetch', 'Read a page. Input: {"id": str}'),
        ('notion-create-pages', 'Create a page. Input: {"title": str, "content": str}'),
        ('notion-update-page', 'Append to a page. Input: {"page_id": str, "append": str}'),
    ],
}


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _json_object(text):
    """First JSON object in a model reply (tolerates fences and surrounding text)."""
    text = re.sub(r'```(?:json)?', '', text or '')
    start = text.find('{')
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find('{', start + 1)
    return None


def _ms(at):
    return int(datetime.fromisoformat(at).timestamp() * 1000)


# ------------------------------------------------------------------------------------------------
# Fake LiveKit layer (the realtime model inside it is the backbone)
# ------------------------------------------------------------------------------------------------
class _Frame:
    def __init__(self, description):
        self.description = description


class _Item:
    def __init__(self, role, text):
        self.role, self.text_content, self.interrupted = role, text, False


class _Event:
    def __init__(self, item):
        self.item = item


class FakeLocalParticipant:
    def __init__(self, cards):
        self.cards = cards

    async def send_text(self, payload, topic=None):
        try:
            self.cards.append(json.loads(payload))
        except json.JSONDecodeError:
            pass


class FakeRoom:
    def __init__(self, name, cards):
        self.name, self.remote_participants = name, {}
        self.local_participant = FakeLocalParticipant(cards)

    def on(self, event):
        return lambda fn: fn


class FakeParticipant:
    def __init__(self, identity, metadata):
        self.identity, self.metadata = identity, metadata


class FakeJobContext:
    def __init__(self, room, participant):
        self.room, self._participant, self.shutdown = room, participant, []

    async def connect(self):
        return None

    async def wait_for_participant(self):
        return self._participant

    def add_shutdown_callback(self, fn):
        self.shutdown.append(fn)


class FakeRunContext:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, session, userdata):
        self.session, self.userdata = session, userdata


class FakeSession:
    """livekit.agents.AgentSession with the realtime model replaced by backbone turns (see Adapter._model_turn)."""
    adapter = None

    def __init__(self, llm=None, userdata=None, video_sampler=None, **kwargs):
        self.userdata, self.agent, self.room = userdata, None, None
        self.handlers, self.items, self.pending = {}, [], []
        self.closed, self.agent_state, self.user_state = False, 'listening', 'listening'
        FakeSession.adapter.session = self

    def on(self, event):
        def register(fn):
            self.handlers.setdefault(event, []).append(fn)
            return fn
        return register

    def emit_item(self, role, text):
        for fn in self.handlers.get('conversation_item_added', []):
            fn(_Event(_Item(role, text)))

    async def start(self, agent=None, room=None, room_input_options=None, **kwargs):
        self.agent, self.room = agent, room

    def generate_reply(self, instructions=None, **kwargs):
        if self.closed:
            raise RuntimeError('the agent session is closed')
        self.pending.append(instructions or '')


def _install_stubs():
    def module(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    class _Any:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs

    def function_tool(f=None, *, name=None, description=None):
        def mark(fn):
            fn.__halo_tool__ = name or fn.__name__
            return fn
        return mark(f) if f is not None else mark

    class Agent:
        def __init__(self, instructions='', tools=None, **kwargs):
            self.instructions, self.tools = instructions, list(tools or [])

    class Client:                       # google.genai.Client, used only by quick_search
        def __init__(self, *args, **kwargs):
            self.aio = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=self._generate))

        async def _generate(self, model=None, contents=None, config=None):
            text = await asyncio.to_thread(FakeSession.adapter._search, str(contents))
            return types.SimpleNamespace(text=text)

    rtc = module('livekit.rtc', Room=type('Room', (), {}), VideoFrame=type('VideoFrame', (), {}),
                 VideoBufferType=types.SimpleNamespace(RGBA='RGBA'), VideoStream=_Any, Track=type('Track', (), {}),
                 TrackKind=types.SimpleNamespace(KIND_VIDEO='video', KIND_AUDIO='audio'),
                 TrackPublication=type('TrackPublication', (), {}), RemoteParticipant=type('RemoteParticipant', (), {}))
    voice = module('livekit.agents.voice', VoiceActivityVideoSampler=_Any)
    agents = module('livekit.agents', Agent=Agent, AgentSession=FakeSession, JobContext=FakeJobContext,
                    RoomInputOptions=_Any, RunContext=FakeRunContext, WorkerOptions=_Any,
                    cli=types.SimpleNamespace(run_app=lambda *a, **k: None), function_tool=function_tool, voice=voice)
    lk_google = module('livekit.plugins.google', beta=types.SimpleNamespace(realtime=types.SimpleNamespace(RealtimeModel=_Any)))
    lk_openai = module('livekit.plugins.openai', realtime=types.SimpleNamespace(RealtimeModel=_Any))
    plugins = module('livekit.plugins', google=lk_google, openai=lk_openai)
    module('livekit', rtc=rtc, agents=agents, plugins=plugins)
    gtypes = module('google.genai.types', GenerateContentConfig=_Any, Tool=_Any, GoogleSearch=_Any,
                    ThinkingConfig=_Any, AudioTranscriptionConfig=_Any)
    genai = module('google.genai', Client=Client, types=gtypes)
    module('google', genai=genai)
    session_mod = module('openai.types.beta.realtime.session', TurnDetection=_Any)
    realtime = module('openai.types.beta.realtime', session=session_mod)
    beta = module('openai.types.beta', realtime=realtime)
    otypes = module('openai.types', beta=beta)
    module('openai', types=otypes)
    image = module('PIL.Image')
    module('PIL', Image=image)


class _AiohttpNoTimeout:
    """main.py's `aiohttp` name: the real module, except that gateway calls have no total timeout."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def ClientTimeout(self, *args, **kwargs):
        return self._real.ClientTimeout(total=None)


# ------------------------------------------------------------------------------------------------
# Bridge: the Managed Agents API the gateway calls, served over local HTTP
# ------------------------------------------------------------------------------------------------
class Bridge:
    def __init__(self, adapter):
        self.a = adapter
        self.cv = threading.Condition()
        self.reset()
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))) or b'{}')
                try:
                    out = {'result': bridge.handle(body.get('op'), body.get('args') or {})}
                    code = 200
                except Exception as exc:        # surfaced to the gateway as an SDK error
                    out, code = {'error': f'{type(exc).__name__}: {exc}'}, 500
                    bridge.a.errors.append(f'bridge {body.get("op")}: {exc}')
                data = json.dumps(out).encode()
                self.send_response(code)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/'

    def reset(self):
        with self.cv:
            self.agents, self.sessions, self.vaults = {}, {}, {}
            self.counter, self.inflight, self.started = 0, 0, 0

    def _id(self, prefix):
        self.counter += 1
        return f'{prefix}_{self.counter:03d}'

    def wait_started(self, after, timeout=120):
        with self.cv:
            return self.cv.wait_for(lambda: self.started > after, timeout)

    def wait_idle(self, timeout=900):
        with self.cv:
            return self.cv.wait_for(lambda: self.inflight == 0, timeout)

    def handle(self, op, a):
        with self.cv:
            if op == 'environments.create':
                return {'id': 'env_visionclaw'}
            if op == 'agents.create':
                agent = {'id': 'agent_visionclaw', 'version': 1, 'name': a.get('name'), 'model': a.get('model'),
                         'system': a.get('system', ''), 'mcp_servers': a.get('mcp_servers', []), 'tools': a.get('tools', [])}
                self.agents[agent['id']] = agent
                return agent
            if op == 'agents.retrieve':
                return self.agents[a['id']]
            if op == 'agents.update':
                agent = self.agents[a['id']]
                agent.update({k: v for k, v in a.items() if k != 'id'})
                agent['version'] += 1
                return agent
            if op == 'vaults.create':
                vid = self._id('vault')
                self.vaults[vid] = a.get('display_name', '')
                return {'id': vid}
            if op == 'vaults.credentials.list':
                servers = {s['name']: s['url'] for ag in self.agents.values() for s in ag['mcp_servers']}
                return [{'id': f'cred_{app}', 'auth': {'type': 'mcp_oauth', 'mcp_server_url': servers[app]}}
                        for app in self.a.day['connected_apps'] if app in servers]
            if op == 'vaults.credentials.validate':
                return {'status': 'valid'}
            if op in ('vaults.credentials.create', 'vaults.credentials.delete', 'sessions.update'):
                return {}
            if op == 'sessions.create':
                sid = self._id('sesn')
                self.sessions[sid] = {'id': sid, 'agent': a.get('agent'), 'events': [], 'turns': []}
                return {'id': sid}
            if op == 'sessions.retrieve':
                agent = self.agents.get(self.sessions[a['id']]['agent'], {})
                return {'id': a['id'], 'status': 'idle', 'archived_at': None,
                        'agent': {'mcp_servers': agent.get('mcp_servers', []), 'tools': agent.get('tools', [])}}
            if op == 'sessions.events.open':
                return {'cursor': len(self.sessions[a['session_id']]['events'])}
            if op == 'sessions.events.next':
                events, cursor = self.sessions[a['session_id']]['events'], a['cursor']
                if not self.cv.wait_for(lambda: len(events) > cursor, 1800):
                    raise TimeoutError('no session event')
                return {'event': events[cursor], 'cursor': cursor + 1}
            if op == 'sessions.events.list':
                return self.sessions[a['session_id']]['events']
            if op == 'sessions.events.send':
                sess = self.sessions[a['session_id']]
                message = next((e for e in a.get('events', []) if e.get('type') == 'user.message'), None)
                if message is None:                     # tool confirmations: nothing waits on them here
                    return {}
                notes = [b.get('text', '') for e in a['events'] if e.get('type') == 'system.message'
                         for b in e.get('content', []) if b.get('type') == 'text']
                self.inflight += 1
                self.started += 1
                self.cv.notify_all()
            else:
                raise ValueError(f'unsupported operation {op}')
        # sessions.events.send: run the action agent's turn outside the lock, then publish its events
        events = []
        try:
            events = self.a._agent_turn(sess, message.get('content', []), notes)
        finally:
            with self.cv:
                sess['events'].extend(events)
                self.inflight -= 1
                self.cv.notify_all()
        return {}


# ------------------------------------------------------------------------------------------------
class Adapter(BaseAdapter):
    channels = {
        'S->M': 'what the user says or shows is written to notes (save_note) or, through the action agent, to the connected calendar and Notion',
        'M->A': 'notes (recall_notes), parked results (call-start drain), the task-ledger briefing and connected-app reads reach the voice model and the action agent',
        'A->M': 'delegated tasks and their results go to the task ledger and, when no one is listening, to parked results',
        'A->S': "the voice model's execute(attach_view=True) sends the current camera frame for the action agent to read",
    }
    steps = {}   # no self-revision in VisionClaw

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.base, self.session, self.errors = set(), '', None, []
        _install_stubs()
        FakeSession.adapter = self
        sys.path.insert(0, str(CORE / 'agent'))
        import main
        import aiohttp
        self.M = main
        main.QUICK_ANSWER_S = 24 * 3600            # a delegated result always returns inside its turn
        main.aiohttp = _AiohttpNoTimeout(aiohttp)  # no total timeout on the worker's gateway calls
        main.encode_latest_frame = self._encode_latest_frame
        self._patch_cut_sites(main)
        self.bridge = Bridge(self)
        data = json.loads((CASE / 'inputs' / 'days.json').read_text())
        self.days = {d['id']: d for d in data['items']}

    # ---- model clients -> HALO backbone ---------------------------------------------------------
    def _backbone(self, system, user, tag):
        self.calls[tag.split('|')[2]] = self.calls.get(tag.split('|')[2], 0) + 1
        try:
            return self.llm(system, user, tag=tag)
        except Exception as exc:
            self.errors.append(f'{tag}: {type(exc).__name__}: {exc}')
            raise

    def _search(self, query):
        """quick_search's grounded Gemini call (main.py:307-330); no web access here."""
        self.n_search += 1
        return self._backbone('Answer the question in two or three spoken sentences.', query,
                              f'{self.base}|search|c{self.ci}|{self.n_search}')

    def _encode_latest_frame(self, holder):
        """main.py:142-163 encodes the latest LiveKit frame as JPEG; here the frame is its description."""
        frame = holder.frame
        return base64.b64encode(frame.description.encode('utf-8')).decode() if frame is not None else None

    # ---- cut sites in the worker ----------------------------------------------------------------
    def _patch_cut_sites(self, main):
        adapter = self
        notes_call, drain_pending, park_text = main._notes_call, main._drain_pending, main._park_text

        async def _notes_call(method, user_id, payload=None, query=''):
            if method == 'POST' and 'S->M' in adapter.cut:       # the note never reaches server.ts:529-548
                p = payload or {}
                return {'status': 201, 'note': {'id': 'not-stored', 'text': p.get('text'), 'tag': p.get('tag')}}
            if method == 'GET' and 'M->A' in adapter.cut:        # server.ts:550-561 is not read
                return {'status': 200, 'notes': []}
            return await notes_call(method, user_id, payload, query)

        async def _drain_pending(user_id):
            if 'M->A' in adapter.cut:                            # parked results stay parked, unread
                return []
            pending = await drain_pending(user_id)
            adapter.parked_relayed += len(pending)
            return pending

        async def _park_text(user_id, text):
            if 'A->M' in adapter.cut:                            # the worker's parking is not stored
                return None
            return await park_text(user_id, text)

        main._notes_call, main._drain_pending, main._park_text = _notes_call, _drain_pending, _park_text

    # ---- the action agent (CMA session turn) ----------------------------------------------------
    def _agent_turn(self, sess, content, notes):
        agent = self.bridge.agents.get(sess['agent'], {})
        text = '\n'.join(b.get('text', '') for b in content if b.get('type') == 'text').strip()
        images = [base64.b64decode(b['source']['data']).decode('utf-8', 'replace')
                  for b in content if b.get('type') == 'image' and b.get('source', {}).get('data')]
        if 'A->S' in self.cut:
            images = []
        if 'M->A' in self.cut:
            notes = []
        servers = [s['name'] for s in agent.get('mcp_servers', []) if s['name'] in MCP_TOOLS]
        tools = '\n'.join(f'- server "{s}", tool "{t}": {desc}' for s in servers for t, desc in MCP_TOOLS[s])
        system = agent.get('system', '') + '\n\n' + AGENT_PROTOCOL.format(now=self.now_text, tools=tools or '(none)')
        turn = {'user': text, 'images': images, 'notes': notes, 'steps': [], 'reply': ''}
        events, k = [], len(sess['turns'])
        for rnd in range(MAX_AGENT_ROUNDS + 1):
            prompt = self._agent_transcript(sess['turns'] + [turn])
            reply = self._backbone(system, prompt, f'{self.base}|agent|c{self.ci}|t{k}|r{rnd}')
            parsed = _json_object(reply) or {'message': reply}
            calls = [c for c in (parsed.get('calls') or []) if isinstance(c, dict)]
            if not calls or rnd == MAX_AGENT_ROUNDS:
                turn['reply'] = str(parsed.get('message') or '').strip() or 'Done.'
                break
            for c in calls:
                server, tool, inp = str(c.get('server', '')), str(c.get('tool', '')), c.get('input') or {}
                result, error = self._mcp(server, tool, inp)
                uid = f'mcptu_{self.bridge.counter + len(events)}'
                events.append({'type': 'agent.mcp_tool_use', 'id': uid, 'name': tool, 'mcp_server_name': server, 'input': inp})
                events.append({'type': 'agent.mcp_tool_result', 'mcp_tool_use_id': uid, 'is_error': error,
                               'content': [{'type': 'text', 'text': result}]})
                turn['steps'].append({'server': server, 'tool': tool, 'input': inp, 'result': result})
        sess['turns'].append(turn)
        self.agent_turns.append({'call': self.ci, 'task': text, 'image_attached': bool(images), 'context': notes,
                                 'tools': [(s['server'], s['tool']) for s in turn['steps']], 'reply': turn['reply']})
        events.append({'type': 'agent.message', 'id': f'msg_{len(self.agent_turns)}',
                       'content': [{'type': 'text', 'text': turn['reply']}]})
        events.append({'type': 'session.status_idle', 'stop_reason': {'type': 'end_turn'}})
        return events

    @staticmethod
    def _agent_transcript(turns):
        lines = []
        for i, t in enumerate(turns):
            lines.append(f'[user message {i + 1}]\n{t["user"]}')
            for img in t['images']:
                lines.append(f'[image attached to this message, described in text]\n{img}')
            for note in t['notes']:
                lines.append(f'[system message]\n{note}')
            for s in t['steps']:
                lines.append(f'[tool call] {s["server"]}.{s["tool"]} {json.dumps(s["input"], ensure_ascii=False)}\n'
                             f'[tool result] {s["result"]}')
            if t['reply']:
                lines.append(f'[your reply]\n{t["reply"]}')
        return '\n\n'.join(lines)

    def _mcp(self, server, tool, inp):
        """Simulated MCP servers of the connected apps, over the item's scripted stores."""
        if server not in MCP_TOOLS or tool not in dict(MCP_TOOLS[server]):
            return f'Unknown tool {server}.{tool}.', True
        if server not in self.day['connected_apps']:
            return f'Authorization required: {server} is not connected for this user.', True
        read_cut, write_cut = 'M->A' in self.cut, 'S->M' in self.cut
        cal, pages = self.stores['calendar'], self.stores['notion']
        if tool == 'get_events':
            lo, hi, q = str(inp.get('time_min') or '')[:16], str(inp.get('time_max') or '9999')[:16], str(inp.get('query') or '').lower()
            hits = [] if read_cut else [e for e in cal if lo <= e['start'][:16] <= hi
                                       and (not q or q in json.dumps(e).lower())]
            return json.dumps({'events': hits}, ensure_ascii=False), False
        if tool == 'create_event':
            event = {'id': f'evt_{len(self.created) + 1}', 'summary': str(inp.get('summary', '')),
                     'start': str(inp.get('start_time', ''))[:16], 'end': str(inp.get('end_time', ''))[:16],
                     'location': str(inp.get('location', '')), 'description': str(inp.get('description', ''))}
            self.created.append(event)
            if not write_cut:
                cal.append(event)
            return json.dumps({'created': event['id']}), False
        if tool in ('modify_event', 'delete_event'):
            event = next((e for e in cal if e['id'] == inp.get('event_id')), None)
            if event is None or read_cut:
                return 'Event not found.', True
            if not write_cut:
                if tool == 'delete_event':
                    cal.remove(event)
                else:
                    for key, field in (('summary', 'summary'), ('start_time', 'start'), ('end_time', 'end'),
                                       ('location', 'location'), ('description', 'description')):
                        if key in inp:
                            event[field] = str(inp[key])[:16] if field in ('start', 'end') else str(inp[key])
            return json.dumps({'ok': True}), False
        if tool == 'notion-search':
            words = [w for w in re.findall(r'\w+', str(inp.get('query', '')).lower()) if len(w) > 2]
            hits = [] if read_cut else [{'id': p['id'], 'title': p['title'], 'snippet': p['content'][:160]}
                                       for p in pages if any(w in (p['title'] + ' ' + p['content']).lower() for w in words)]
            return json.dumps({'results': hits}, ensure_ascii=False), False
        if tool == 'notion-fetch':
            page = None if read_cut else next((p for p in pages if p['id'] == inp.get('id')), None)
            return (json.dumps(page, ensure_ascii=False), False) if page else ('Page not found.', True)
        if tool == 'notion-create-pages':
            page = {'id': f'page_{len(pages) + len(self.created) + 1}', 'title': str(inp.get('title', '')),
                    'content': str(inp.get('content', ''))}
            self.created.append(page)
            if not write_cut:
                pages.append(page)
            return json.dumps({'created': page['id']}), False
        if tool == 'notion-update-page':
            page = None if read_cut else next((p for p in pages if p['id'] == inp.get('page_id')), None)
            if page is None:
                return 'Page not found.', True
            self.created.append({'page': page['id'], 'append': str(inp.get('append', ''))})
            if not write_cut:
                page['content'] += '\n' + str(inp.get('append', ''))
            return json.dumps({'ok': True}), False
        return 'Unsupported.', True

    # ---- the realtime voice model -----------------------------------------------------------------
    def _tool_specs(self, tools):
        lines = []
        for fn in tools:
            sig = inspect.signature(fn)
            params = [p for name, p in sig.parameters.items() if name != 'ctx']
            args = ', '.join(f'{p.name}: {getattr(p.annotation, "__name__", str(p.annotation)).replace("typing.", "")}'
                             + ('' if p.default is inspect.Parameter.empty else f' = {p.default!r}') for p in params)
            lines.append(f'- {fn.__halo_tool__}({args})\n  ' + (inspect.getdoc(fn) or '').replace('\n', '\n  '))
        return '\n'.join(lines)

    def _voice_prompt(self, session, now):
        lines = ['Conversation of this call so far:']
        for item in session.items:
            kind = item[0]
            if kind == 'camera':
                lines.append(f'[camera] {item[1]}')
            elif kind == 'user':
                lines.append(f'User: {item[1]}')
            elif kind == 'assistant':
                lines.append(f'You said: {item[1]}')
            elif kind == 'tool':
                lines.append(f'You called {item[1]}({json.dumps(item[2], ensure_ascii=False)}) -> {item[3]}')
            elif kind == 'instruction':
                lines.append(f'[instruction from the app] {item[1]}')
        if len(lines) == 1:
            lines.append('(nothing yet)')
        frame = session.userdata.frames.frame if session.userdata else None
        lines.append(f'\nLatest camera frame: {frame.description if frame else "(no video yet)"}')
        lines.append(f'\nNow: {now}')
        return '\n'.join(lines)

    async def _model_turn(self, session, now, hangup=False):
        system = (session.agent.instructions + '\n\n'
                  + VOICE_PROTOCOL.format(tools=self._tool_specs(session.agent.tools)))
        tools = {fn.__halo_tool__: fn for fn in session.agent.tools}
        for rnd in range(MAX_TOOL_ROUNDS + 1):
            self.voice_step += 1
            reply = await asyncio.to_thread(self._backbone, system, self._voice_prompt(session, now),
                                            f'{self.base}|voice|c{self.ci}|{self.voice_step}')
            parsed = _json_object(reply)
            if parsed is None:
                parsed = {'say': reply.strip(), 'calls': []}
            say = str(parsed.get('say') or '').strip()
            calls = [c for c in (parsed.get('calls') or []) if isinstance(c, dict) and c.get('name') in tools]
            if say:
                session.items.append(('assistant', say))
                session.emit_item('assistant', say)
            if not calls or rnd == MAX_TOOL_ROUNDS:
                return False
            for c in calls:
                fn, args = tools[c['name']], c.get('args') if isinstance(c.get('args'), dict) else {}
                sig = inspect.signature(fn)
                kwargs = {k: v for k, v in args.items() if k in sig.parameters and k != 'ctx'}
                call = (fn(FakeRunContext(session, session.userdata), **kwargs) if 'ctx' in sig.parameters
                        else fn(**kwargs))
                if hangup and c['name'] in ('execute', 'browse'):
                    # The user ends the call while the task runs: once the request has reached the gateway the
                    # job process goes away with the call, which closes the worker's HTTP request at once
                    # (the gateway then parks the finished result, server.ts:291-299).
                    started, running = self.bridge.started, set(asyncio.all_tasks())
                    task = asyncio.ensure_future(call)
                    await asyncio.to_thread(self.bridge.wait_started, started)
                    spawned = [t for t in asyncio.all_tasks() - running if t is not asyncio.current_task()]
                    for t in spawned:
                        t.cancel()
                    await asyncio.gather(task, *spawned, return_exceptions=True)
                    session.items.append(('tool', c['name'], kwargs, '(the call ended before the result came back)'))
                    self.hung_up = True
                    return True
                try:
                    result = str(await call)
                except Exception as exc:
                    result = f'Tool error: {type(exc).__name__}: {exc}'
                session.items.append(('tool', c['name'], kwargs, result))
            now = 'The function results are above; continue the conversation.'
        return False

    async def _flush_replies(self, session):
        while session.pending and not session.closed:
            instructions = session.pending.pop(0)
            session.items.append(('instruction', instructions))
            await self._model_turn(session, 'Reply now, following the instruction from the app.')

    # ---- gateway process ----------------------------------------------------------------------------
    def _start_gateway(self, at, attempts=3):
        # The free-port probe can race with another worker, and a busy machine occasionally drops the
        # gateway right after provisioning; start again on a fresh port before giving up.
        for i in range(attempts):
            try:
                return self._start_gateway_once(at)
            except RuntimeError:
                if i == attempts - 1:
                    raise
                time.sleep(2)

    def _start_gateway_once(self, at):
        port = _free_port()
        env = {'PATH': os.path.dirname(NODE) + ':/usr/bin:/bin', 'HOME': os.environ.get('HOME', ''),
               'PORT': str(port), 'STORE_PATH': str(self.store_path), 'GATEWAY_TOKENS': f'{USER_TOKEN}:{self.uid}',
               'GATEWAY_SERVICE_TOKEN': SERVICE_TOKEN, 'HALO_BRIDGE_URL': self.bridge.url,
               'HALO_FROZEN_NOW_MS': str(_ms(at)), 'SLACK_DISABLED': 'true',
               # connected-app registry: the self-hosted Google Workspace MCP is active when its URL is set
               'WORKSPACE_MCP_URL': 'http://127.0.0.1:9/workspace-mcp/mcp/',
               # local LiveKit ticket signing for /livekit-token; no LiveKit server is contacted
               'LIVEKIT_URL': 'ws://127.0.0.1:9', 'LIVEKIT_API_KEY': 'halo-local',
               'LIVEKIT_API_SECRET': 'halo-local-ticket-signing-value-0000000000'}
        log = open(self.work / 'gateway.log', 'a')
        proc = subprocess.Popen([NODE, '--import', './shim/clock.mjs', '--import', './shim/serial_store.mjs', '--import', 'tsx',
                                 '--import', './shim/register.mjs',
                                 'core/gateway/src/server.ts'], cwd=CASE, env=env, stdout=log, stderr=subprocess.STDOUT)
        url = f'http://127.0.0.1:{port}'
        deadline = time.time() + 180   # tsx compiles the TypeScript at start; slow when the machine is busy
        while time.time() < deadline:
            try:
                urllib.request.urlopen(url + '/health', timeout=1).read()
                return proc, url
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
        proc.kill()
        raise RuntimeError('gateway did not start; see gateway.log: '
                           + (self.work / 'gateway.log').read_text()[-800:])

    def _stop_gateway(self, proc):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _store(self):
        return json.loads(self.store_path.read_text()) if self.store_path.exists() else {'shared': {}, 'users': {}}

    # ---- one call -----------------------------------------------------------------------------------
    async def _call(self, ci, call):
        import aiohttp
        self.ci, self.voice_step, self.hung_up = ci, 0, False
        self.now_text = datetime.fromisoformat(call['at']).strftime('%A %Y-%m-%d %H:%M (UTC%z)')
        proc, url = self._start_gateway(call['at'])
        os.environ['GATEWAY_URL'], os.environ['GATEWAY_SERVICE_TOKEN'] = url, SERVICE_TOKEN
        cards, transcript = [], []
        try:
            # The phone fetches its room ticket (LiveKitSession.fetchTicket -> POST /livekit-token), which rotates
            # the action agent's session and queues the briefing from the task ledger (server.ts:413-471).
            sessions = len(self.bridge.sessions)
            async with aiohttp.ClientSession() as http:
                async with http.post(url + '/livekit-token', json={'engine': 'gemini', 'source': 'glasses'},
                                     headers={'Authorization': f'Bearer {USER_TOKEN}'}) as resp:
                    resp.raise_for_status()
            # The worker joins seconds later in the live system, after the ticket's pre-warm has created the
            # call's action-agent session (server.ts:436-439); wait for it the same way.
            for _ in range(100):
                if len(self.bridge.sessions) > sessions:
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.3)
            room = FakeRoom(f'vc-{self.uid}-{ci}', cards)
            ctx = FakeJobContext(room, FakeParticipant(self.uid, json.dumps({'engine': 'gemini', 'source': 'glasses'})))
            before = set(asyncio.all_tasks())
            await self.M.entrypoint(ctx)
            session = self.session
            session.on('conversation_item_added')(lambda ev: transcript.append((ev.item.role, ev.item.text_content)))
            await self._flush_replies(session)                       # parked results relayed at call start
            ended = False
            for turn in call['turns']:
                session.userdata.frames.frame = _Frame(turn['view'])
                session.userdata.frames.arrived_at = time.time()
                session.items.append(('camera', turn['view']))
                session.items.append(('user', turn['say']))
                session.emit_item('user', turn['say'])
                ended = await self._model_turn(session, f'The user says: "{turn["say"]}"', bool(turn.get('hangup')))
                if ended:
                    break
                await self._flush_replies(session)
            # End of call: the session closes, shutdown callbacks run, the job's background tasks stop.
            session.closed = True
            for cb in ctx.shutdown:
                await cb()
            leftover = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task() and not t.done()]
            for t in leftover:
                t.cancel()
            await asyncio.gather(*leftover, return_exceptions=True)
            await asyncio.to_thread(self.bridge.wait_idle)           # a hung-up task still finishes at the gateway
            for _ in range(50):                                      # let the gateway record, park and save
                await asyncio.sleep(0.2)
                user = self._store().get('users', {}).get(self.uid, {})
                if not self.hung_up or user.get('pendingNotifications'):
                    break
            await asyncio.sleep(0.5)
            return {'at': call['at'], 'transcript': transcript, 'cards': [c.get('fallback_text') or c.get('title') for c in cards]}
        finally:
            if proc.poll() is not None:
                self.errors.append('the gateway exited during the call: '
                                   + (self.work / 'gateway.log').read_text()[-600:])
            self._stop_gateway(proc)
            if 'A->M' in self.cut:
                store = self._store()
                for u in store.get('users', {}).values():            # nothing written this call is retained
                    u['recentTasks'], u['pendingNotifications'] = [], []
                self.store_path.write_text(json.dumps(store, indent=2))

    # ---- items ----------------------------------------------------------------------------------------
    def items(self):
        return [{'id': d['id'], 'judge_context': self._judge_context(d)} for d in self.days.values()]

    @staticmethod
    def _judge_context(d):
        lines = [f'User: {d["user"]["about"]}',
                 f'Connected apps: {", ".join(d["connected_apps"]) or "none"} (gcal-self is Google Calendar).',
                 'State before the first call: ' + json.dumps(d['stores'], ensure_ascii=False)]
        for i, call in enumerate(d['calls']):
            head = 'Final call' if i == len(d['calls']) - 1 else f'Call {i + 1}'
            lines.append(f'\n{head} at {call["at"]}:')
            for t in call['turns']:
                lines.append(f'  camera: {t["view"]}\n  user: {t["say"]}' + ('  (the user hangs up right after asking)' if t.get('hangup') else ''))
        lines.append('\nFacts the final call should get right: ' + '; '.join(' / '.join(alts) for alts in d['expect']))
        return '\n'.join(lines)

    def run(self, item, cut, sample):
        day = copy.deepcopy(self.days[item['id']])
        self.day, self.uid, self.cut = day, day['user']['id'], set(cut)
        self.base = f'{day["id"]}|s{sample}'         # the tag names item and sample, not the arm
        self.stores = {'calendar': [dict(e, id=f'evt_seed{i}') for i, e in enumerate(day['stores']['calendar'])],
                       'notion': [dict(p, id=f'page_seed{i}') for i, p in enumerate(day['stores']['notion'])]}
        self.created, self.agent_turns, self.calls, self.errors = [], [], {}, []
        self.parked_relayed, self.n_search, self.session = 0, 0, None
        self.bridge.reset()
        self.work = Path(tempfile.mkdtemp(prefix=f'halo-visionclaw-{day["id"]}-'))
        self.store_path = self.work / 'data' / 'gateway-store.json'
        self.store_path.parent.mkdir(parents=True)
        notes = [{'id': f'seed{i}', 'ts': day['calls'][0]['at'], 'text': n['text'], **({'tag': n['tag']} if n.get('tag') else {})}
                 for i, n in enumerate(day['stores']['notes'])]
        self.store_path.write_text(json.dumps({'shared': {}, 'users': {self.uid: {'notes': notes}}}, indent=2))
        try:
            calls = []
            for ci, call in enumerate(day['calls']):
                calls.append(asyncio.run(self._call(ci, call)))
                if self.errors:
                    raise RuntimeError('backbone or bridge failed: ' + ' | '.join(self.errors)[:1500])
            return self._result(day, calls)
        finally:
            if not os.environ.get('HALO_VISIONCLAW_KEEP'):
                shutil.rmtree(self.work, ignore_errors=True)

    def _result(self, day, calls):
        def render(call):
            out = []
            for role, text in call['transcript']:
                out.append(('User: ' if role == 'user' else 'Assistant: ') + text)
            out += [f'[card on screen] {c}' for c in call['cards'] if c]
            return '\n'.join(out)
        final = calls[-1]
        spoken = ' '.join(t for r, t in final['transcript'] if r == 'assistant') + ' ' + ' '.join(c or '' for c in final['cards'])
        hits = [any(alt.lower() in spoken.lower() for alt in alts) for alts in day['expect']]
        store = self._store().get('users', {}).get(self.uid, {})
        seed_pages = {f'page_seed{i}': p['content'] for i, p in enumerate(day['stores']['notion'])}
        kept = (len(self.stores['calendar']) - len(day['stores']['calendar'])
                + sum(1 for p in self.stores['notion'] if seed_pages.get(p['id']) != p['content']))
        return {
            'output': render(final),
            'calls': [{'at': c['at'], 'transcript': render(c)} for c in calls],
            'agent_turns': self.agent_turns,
            'notes_after': [n.get('text') for n in store.get('notes', [])],
            'calendar_after': self.stores['calendar'],
            'notion_after': self.stores['notion'],
            'metrics': {
                'final_facts_stated': round(sum(hits) / len(hits), 4) if hits else None,
                'notes_saved': len(store.get('notes', [])) - len(day['stores']['notes']),
                'app_writes_attempted': len(self.created),
                'app_writes_kept': kept,
                'ledger_entries': len(store.get('recentTasks', [])),
                'parked_relayed': self.parked_relayed,
                'delegated_turns': len(self.agent_turns),
                'frames_attached': sum(t['image_attached'] for t in self.agent_turns),
                'voice_model_calls': self.calls.get('voice', 0),
                'agent_calls': self.calls.get('agent', 0),
            },
        }
