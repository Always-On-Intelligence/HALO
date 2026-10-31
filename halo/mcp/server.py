"""The HALO plugin: a server that a personal agent calls while it works, over MCP or plain HTTP.

The agent logs each step of its loop as one of six kinds of events (observe, remember, recall, act, outcome,
revise) and names the earlier events each step used. Over MCP each kind is a tool. Over plain HTTP, for agents
without MCP and for bridges, each event is a JSON object sent to /events. HALO keeps the events in the ledger
and reads the loop off them on request (halo_report, or GET /report). Nothing here calls a model.

    halo serve                                   stdio, for local hosts such as Claude Code or Codex
    halo serve --http --port 8765                MCP on http://127.0.0.1:8765/mcp, plain HTTP on /events
    halo serve --http --public-host x.example    behind a tunnel, at https://x.example/<token>/mcp and /events
"""
import argparse
import os
import secrets
from typing import Annotated, Literal

from pydantic import Field

from halo.mcp.analysis import KINDS, MODULES, arrow, report
from halo.mcp.ledger import Ledger, LedgerError

INTRO = """HALO records how your loop runs, so it can show which channels of the loop carry information and
how far your evidence for self-improvement goes. Log each step as it happens, in a few words"""

# the same rules for every way in; {p} is the tool prefix over MCP and empty over plain HTTP
STEPS = """- {p}observe: you take in something new (a user message, a page, a sensor reading, a tool result).
- {p}remember: you keep something for later conversations (a fact, a preference, a record of what you did).
- {p}recall: you look up something you kept earlier.
- {p}act: you do something for the user, or decide to stay silent. trigger is "request" when the user asked
  for it or set it up, including every step inside a run the user requested or scheduled, even when you choose
  how to do it. trigger is "self" only when no request or schedule of the user's started it and you decided on
  your own, between requests, whether to act or stay silent (a follow-up you chose to send, a check you chose
  to make).
- {p}outcome: you learn how one of your earlier actions went (a reply, a rating, a correction, a result).
  Pass the action's id as about.
- {p}revise: you change your own way of working (a prompt, rule, skill, or policy you will reuse)."""

GUIDE = INTRO + ':\n\n' + STEPS.format(p='halo_') + """

Always pass uses: the ids of the earlier events this step relied on. Those links are what HALO reads.
Use one session label per conversation or wake-up. Keep summaries short and leave out secrets, passwords,
and raw personal data. halo_trace lists your recent events and their ids, and halo_report gives the diagnosis."""

# served at GET {base}/guide with {base} filled in, so an agent without MCP can read how to log
HTTP_GUIDE = INTRO + """, by sending it as JSON in a POST request to {base}/events with the
header Content-Type: application/json. For example:

    {"agent": "muse", "session": "2026-11-01 errand", "kind": "act", "summary": "drafted the reply",
     "uses": ["e3"], "trigger": "request", "form": "preparation"}

The reply gives the new event's id, which later steps name in uses. kind is one of:

""" + STEPS.format(p='') + """

An act also takes form: silence, communication (the default), preparation, or execution. An outcome needs
about, the id of the act. A revise needs target (what you changed), made_by ("agent" or "user"), and
governance ("approved" if the user approved the change, "bounded" if it stays within limits the user set
in advance, "none" otherwise).

Always send uses: the ids of the earlier events this step relied on. Those links are what HALO reads.
Send the same agent name with every event, and one session label per conversation or wake-up. Keep summaries
short and leave out secrets, passwords, and raw personal data. GET {base}/events?agent=NAME lists your recent
events and their ids, and GET {base}/report?agent=NAME gives the diagnosis."""

CHOICES = {'trigger': ('request', 'self'), 'form': ('silence', 'communication', 'preparation', 'execution'),
           'made_by': ('agent', 'user'), 'governance': ('approved', 'bounded', 'none')}
FIELDS = {'act': ('trigger', 'form'), 'outcome': ('about',), 'revise': ('target', 'made_by', 'governance')}

Uses = Annotated[list[str], Field(description='Ids of earlier events this step relied on, e.g. ["e3", "e7"]. '
                                              'These links are how HALO sees information move through your loop.')]
Summary = Annotated[str, Field(description='What happened, in a few words, without secrets or raw personal data.')]
Session = Annotated[str, Field(description='A label for the current conversation or wake-up, the same for every '
                                           'step of it, e.g. "2026-10-31 morning check".')]
Agent = Annotated[str, Field(description='Your name as an agent, e.g. "dot" or "grok-bot". '
                                         'Leave empty to use the name your client sent.')]


def record(ledger, name, kind, summary, uses, session, client, **extra):
    """Store one event and tell the agent which channels it adds, so a wrong link shows up at once."""
    try:
        e = ledger.add(name, kind, summary, uses, session, client, **extra)
    except LedgerError as err:
        return {'error': str(err)}
    events = {x['id']: x for x in ledger.events(name)}
    to = KINDS[kind]
    flows = sorted({f'{KINDS[events[u]["kind"]]}->{to}' for u in e['uses']
                    if u in events and to and KINDS[events[u]['kind']] and KINDS[events[u]['kind']] != to
                    and not (to == 'M' and kind != 'remember')})
    module = MODULES.get(to, 'mechanism')
    note = f'Logged {e["id"]} ({module}, {kind}).'
    if flows:
        note += ' Channels: ' + ', '.join(arrow(f) for f in flows) + '.'
    return {'id': e['id'], 'agent': name, 'session': e['session'], 'note': note}


def post_event(ledger, body, default_agent=''):
    """One event sent as JSON over plain HTTP, checked as strictly as the MCP tools check their arguments.
    Returns the HTTP status and the reply."""
    if not isinstance(body, dict):
        return 400, {'error': 'send one event as a JSON object'}
    kind = body.get('kind')
    if kind not in KINDS:
        return 400, {'error': 'kind must be one of ' + ', '.join(KINDS)}
    name = str(body.get('agent') or default_agent).strip()
    if not name:
        return 400, {'error': 'agent is missing: send the same agent name with every event'}
    uses = body.get('uses') or []
    if not isinstance(uses, list) or not all(isinstance(u, str) for u in uses):
        return 400, {'error': 'uses must be a list of event ids, such as ["e3", "e7"]'}
    extra = {}
    for field in FIELDS.get(kind, ()):
        value = body.get(field) or ('communication' if field == 'form' else '')
        if not isinstance(value, str) or not value.strip():
            return 400, {'error': f'{kind} needs {field}'}
        if field in CHOICES and value not in CHOICES[field]:
            return 400, {'error': f'{field} must be one of ' + ', '.join(CHOICES[field])}
        extra[field] = value.strip()
    reply = record(ledger, name, kind, str(body.get('summary') or ''), uses, str(body.get('session') or ''), 'http',
                   **extra)
    return (400 if 'error' in reply else 201), reply


def build(ledger, default_agent=''):
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer('HALO', title='HALO: Harness for Always-On Loop Oversight', instructions=GUIDE,
                       website_url='https://github.com/Always-On-Intelligence/HALO')
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    read = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    def who(ctx, agent):
        if agent:
            return agent.strip()
        if default_agent:
            return default_agent
        params = getattr(ctx.session, 'client_params', None) if ctx else None
        name = getattr(getattr(params, 'client_info', None), 'name', '') if params else ''
        return name or 'agent'

    def where(ctx, session):
        if session:
            return session.strip()
        sid = getattr(getattr(ctx, 'request_context', None), 'session_id', None) if ctx else None
        return f'mcp-{sid[:8]}' if sid else ''

    def log(ctx, agent, kind, summary, uses, session, **extra):
        params = getattr(ctx.session, 'client_params', None) if ctx else None
        client = getattr(getattr(params, 'client_info', None), 'name', '') if params else ''
        return record(ledger, who(ctx, agent), kind, summary, uses, where(ctx, session), client, **extra)

    @server.tool(annotations=write)
    def halo_observe(summary: Summary, uses: Uses = [], session: Session = '', agent: Agent = '', ctx: Context = None) -> dict:
        """Sensing: log something you take in now, such as a user message, a page, a sensor reading, or a tool result.
        If an earlier action of yours made you look (checking whether it worked), include that action in uses."""
        return log(ctx, agent, 'observe', summary, uses, session)

    @server.tool(annotations=write)
    def halo_remember(summary: Summary, uses: Uses = [], session: Session = '', agent: Agent = '', ctx: Context = None) -> dict:
        """Memory: log something you keep for later conversations, such as a fact, a preference, or a record of
        what you did or how it went. Include in uses what you are keeping (an observation, an action, an outcome)."""
        return log(ctx, agent, 'remember', summary, uses, session)

    @server.tool(annotations=write)
    def halo_recall(summary: Summary, uses: Uses = [], session: Session = '', agent: Agent = '', ctx: Context = None) -> dict:
        """Memory: log that you looked up something you kept earlier. Include the remember events you retrieved in uses."""
        return log(ctx, agent, 'recall', summary, uses, session)

    @server.tool(annotations=write)
    def halo_act(summary: Summary,
                 trigger: Annotated[Literal['request', 'self'], Field(description=(
                     '"request" if the user asked for it or set it up, including steps inside a run the user requested '
                     'or scheduled, even when you choose how to do them. "self" only if no request or schedule of the '
                     'user started it and you decided on your own, between requests, whether to act or stay silent.'))],
                 form: Annotated[Literal['silence', 'communication', 'preparation', 'execution'], Field(description=(
                     'silence: you decided not to act; communication: you told or asked the user; preparation: you '
                     'got something ready; execution: you changed something in the world for the user.'))] = 'communication',
                 uses: Uses = [], session: Session = '', agent: Agent = '', ctx: Context = None) -> dict:
        """Action: log something you did for the user, or a decision to stay silent. Include in uses the observations
        and memories the decision relied on."""
        return log(ctx, agent, 'act', summary, uses, session, trigger=trigger, form=form)

    @server.tool(annotations=write)
    def halo_outcome(summary: Summary,
                     about: Annotated[str, Field(description='The id of the earlier act event this outcome is about.')],
                     uses: Uses = [], session: Session = '', agent: Agent = '', ctx: Context = None) -> dict:
        """Sensing: log how one of your earlier actions went, such as a reply, a rating, a dismissal, a correction,
        or a task result. If you checked the result yourself because of the action, also include the action in uses."""
        return log(ctx, agent, 'outcome', summary, uses, session, about=about)

    @server.tool(annotations=write)
    def halo_revise(summary: Summary,
                    target: Annotated[str, Field(description='What you changed in your own way of working: a prompt, '
                                                             'rule, skill, schedule policy, or similar.')],
                    made_by: Annotated[Literal['agent', 'user'], Field(description=(
                        '"agent" if you made the change yourself; "user" if the user or a developer wrote it.'))],
                    governance: Annotated[Literal['approved', 'bounded', 'none'], Field(description=(
                        '"approved" if the user approved this change; "bounded" if it stays within limits the user '
                        'set in advance; "none" otherwise.'))],
                    uses: Uses = [], session: Session = '', agent: Agent = '', ctx: Context = None) -> dict:
        """Mechanism: log a durable change to how you work that later runs will reuse. Facts or preferences you store
        are memory, not a revision. Include in uses the outcomes that led to the change."""
        return log(ctx, agent, 'revise', summary, uses, session, target=target, made_by=made_by, governance=governance)

    @server.tool(annotations=read)
    def halo_trace(limit: Annotated[int, Field(ge=1, le=200, description='How many recent events to list.')] = 20,
                   session: Annotated[str, Field(description='Only this session; empty for all.')] = '',
                   agent: Agent = '', ctx: Context = None) -> str:
        """List your recent events with their ids, so that later steps can name them in uses or about."""
        name = who(ctx, agent)
        rows = ledger.events(name, session or None, limit)
        if not rows:
            return f'No events logged for {name} yet.'
        out = []
        for e in rows:
            extra = ', '.join(f'{k}={e[k]}' for k in ('trigger', 'form', 'about', 'target', 'made_by', 'governance') if k in e)
            out.append(f'{e["id"]} [{e["session"] or "-"}] {e["kind"]}: {e["summary"]}'
                       + (f' (uses {", ".join(e["uses"])})' if e['uses'] else '') + (f' {{{extra}}}' if extra else ''))
        return '\n'.join(out)

    @server.tool(annotations=read)
    def halo_report(session: Annotated[str, Field(description='Only this session; empty for the whole trace.')] = '',
                    agent: Agent = '', ctx: Context = None) -> str:
        """The diagnosis of your trace: which channels carried information, which evidence steps for self-improvement
        appear, and which loop-closure level (L0 to L5) the trace supports."""
        name = who(ctx, agent)
        return report(ledger.events(name, session or None), name, session)

    @server.tool(annotations=read)
    def halo_guide() -> str:
        """How to log your loop with HALO: what each tool is for and how to link steps. Read this first."""
        return GUIDE

    return server


def http_routes(server, ledger, base, url, hosts, default_agent=''):
    """Plain HTTP next to MCP: POST and GET {base}/events, GET {base}/report, and GET {base}/guide."""
    from starlette.responses import JSONResponse, PlainTextResponse

    def refused(request):
        # the MCP endpoint checks the Host header itself, these routes have to do it here
        host = request.headers.get('host', '').rsplit(':', 1)[0].lower()
        return None if host in hosts else PlainTextResponse('unknown host', 421)

    def agent_of(request):
        return (request.query_params.get('agent') or default_agent).strip()

    @server.custom_route(f'{base}/events', methods=['GET', 'POST'], include_in_schema=False)
    async def events(request):
        if (no := refused(request)):
            return no
        if request.method == 'GET':
            if not (name := agent_of(request)):
                return JSONResponse({'error': 'add ?agent=NAME'}, 400)
            limit = request.query_params.get('limit', '50')
            limit = min(int(limit), 500) if limit.isdigit() and int(limit) > 0 else 50
            return JSONResponse(ledger.events(name, request.query_params.get('session') or None, limit))
        # a JSON content type keeps browsers from posting here from other sites without a preflight
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            return JSONResponse({'error': 'send the event as JSON, with Content-Type: application/json'}, 415)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({'error': 'the body is not valid JSON'}, 400)
        status, reply = post_event(ledger, body, default_agent)
        return JSONResponse(reply, status)

    @server.custom_route(f'{base}/report', methods=['GET'], include_in_schema=False)
    async def report_route(request):
        if (no := refused(request)):
            return no
        if not (name := agent_of(request)):
            return PlainTextResponse('add ?agent=NAME', 400)
        session = request.query_params.get('session', '')
        return PlainTextResponse(report(ledger.events(name, session or None), name, session),
                                 media_type='text/markdown; charset=utf-8')

    @server.custom_route(f'{base}/guide', methods=['GET'], include_in_schema=False)
    async def guide(request):
        return refused(request) or PlainTextResponse(HTTP_GUIDE.replace('{base}', url))


def main():
    ap = argparse.ArgumentParser(prog='halo serve', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=os.environ.get('HALO_LEDGER', '~/.halo/ledger.sqlite'), help='ledger file')
    ap.add_argument('--agent', default='', help='name every event with this agent instead of the client name')
    ap.add_argument('--http', action='store_true', help='serve Streamable HTTP instead of stdio')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--public-host', default='', help='the host name of a tunnel in front of this server; '
                                                     'turns on a secret path')
    ap.add_argument('--token', default=os.environ.get('HALO_TOKEN', ''), help='secret path segment (default: random)')
    args = ap.parse_args()

    ledger = Ledger(args.db)
    server = build(ledger, args.agent)
    if not args.http:
        server.run('stdio')
        return
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = [f'{args.host}:*', 'localhost:*', '127.0.0.1:*']
    base, url = '', f'http://{args.host}:{args.port}'
    if args.public_host:
        base = '/' + (args.token or secrets.token_urlsafe(18))
        url = f'https://{args.public_host}{base}'
        hosts.append(args.public_host)
        print(f'HALO plugin URL: {url}/mcp', flush=True)
    http_routes(server, ledger, base, url, {h.split(':')[0].lower() for h in hosts}, args.agent)
    print(f'HALO plugin listening on http://{args.host}:{args.port}{base}/mcp (ledger {ledger.path})', flush=True)
    print(f'Plain HTTP: POST {url}/events, guide at {url}/guide', flush=True)
    # behind a tunnel the server keeps no MCP sessions, so a restart does not break hosts that are already connected
    server.run('streamable-http', host=args.host, port=args.port, streamable_http_path=f'{base}/mcp',
               stateless_http=bool(args.public_host),
               transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[]))


if __name__ == '__main__':
    main()
