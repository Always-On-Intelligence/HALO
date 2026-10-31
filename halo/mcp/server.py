"""The HALO plugin: an MCP server that a personal agent calls while it works.

The agent logs each step of its loop with one of six tools (observe, remember, recall, act, outcome,
revise) and names the earlier events each step used. HALO keeps the events in the ledger and reads
the loop off them on request (halo_report). Nothing here calls a model.

    halo serve                                   stdio, for local hosts such as Claude Code or Codex
    halo serve --http --port 8765                Streamable HTTP on http://127.0.0.1:8765/mcp
    halo serve --http --public-host x.example    behind a tunnel, at https://x.example/<token>/mcp
"""
import argparse
import os
import secrets
from typing import Annotated, Literal

from pydantic import Field

from halo.mcp.analysis import KINDS, MODULES, arrow, report
from halo.mcp.ledger import Ledger, LedgerError

GUIDE = """HALO records how your loop runs, so it can show which channels of the loop carry information and
how far your evidence for self-improvement goes. Log each step as it happens, in a few words:

- halo_observe: you take in something new (a user message, a page, a sensor reading, a tool result).
- halo_remember: you keep something for later conversations (a fact, a preference, a record of what you did).
- halo_recall: you look up something you kept earlier.
- halo_act: you do something for the user, or decide to stay silent. trigger is "request" when the user asked
  for it or set it up, including every step inside a run the user requested or scheduled, even when you choose
  how to do it. trigger is "self" only when no request or schedule of the user's started it and you decided on
  your own, between requests, whether to act or stay silent (a follow-up you chose to send, a check you chose
  to make).
- halo_outcome: you learn how one of your earlier actions went (a reply, a rating, a correction, a result).
  Pass the action's id as about.
- halo_revise: you change your own way of working (a prompt, rule, skill, or policy you will reuse).

Always pass uses: the ids of the earlier events this step relied on. Those links are what HALO reads.
Use one session label per conversation or wake-up. Keep summaries short and leave out secrets, passwords,
and raw personal data. halo_trace lists your recent events and their ids, and halo_report gives the diagnosis."""

Uses = Annotated[list[str], Field(description='Ids of earlier events this step relied on, e.g. ["e3", "e7"]. '
                                              'These links are how HALO sees information move through your loop.')]
Summary = Annotated[str, Field(description='What happened, in a few words, without secrets or raw personal data.')]
Session = Annotated[str, Field(description='A label for the current conversation or wake-up, the same for every '
                                           'step of it, e.g. "2026-10-31 morning check".')]
Agent = Annotated[str, Field(description='Your name as an agent, e.g. "dot" or "grok-bot". '
                                         'Leave empty to use the name your client sent.')]


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
        name = who(ctx, agent)
        params = getattr(ctx.session, 'client_params', None) if ctx else None
        client = getattr(getattr(params, 'client_info', None), 'name', '') if params else ''
        try:
            e = ledger.add(name, kind, summary, uses, where(ctx, session), client, **extra)
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

    server = build(Ledger(args.db), args.agent)
    if not args.http:
        server.run('stdio')
        return
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = [f'{args.host}:*', 'localhost:*', '127.0.0.1:*']
    path = '/mcp'
    if args.public_host:
        token = args.token or secrets.token_urlsafe(18)
        path = f'/{token}/mcp'
        hosts.append(args.public_host)
        print(f'HALO plugin URL: https://{args.public_host}{path}', flush=True)
    print(f'HALO plugin listening on http://{args.host}:{args.port}{path} (ledger {Ledger(args.db).path})', flush=True)
    # behind a tunnel the server keeps no MCP sessions, so a restart does not break hosts that are already connected
    server.run('streamable-http', host=args.host, port=args.port, streamable_http_path=path, stateless_http=bool(args.public_host),
               transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[]))


if __name__ == '__main__':
    main()
