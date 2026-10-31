"""`halo trace`: read the ledger without a client.

    halo trace                      list the agents in the ledger
    halo trace report dot           the diagnosis of one agent's trace
    halo trace list dot [--last 30] its recent events
"""
import argparse
import os

from halo.mcp.analysis import report
from halo.mcp.ledger import Ledger


def main():
    ap = argparse.ArgumentParser(prog='halo trace', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('what', nargs='?', choices=['report', 'list'])
    ap.add_argument('agent', nargs='?')
    ap.add_argument('--session', default='')
    ap.add_argument('--last', type=int, default=30)
    ap.add_argument('--db', default=os.environ.get('HALO_LEDGER', '~/.halo/ledger.sqlite'))
    args = ap.parse_args()
    ledger = Ledger(args.db)
    if not args.what or not args.agent:
        for name in ledger.agents():
            print(name, len(ledger.events(name)), 'events')
        return
    events = ledger.events(args.agent, args.session or None)
    if args.what == 'report':
        print(report(events, args.agent, args.session))
    else:
        for e in events[-args.last:]:
            print(e['id'], e['session'] or '-', e['kind'], e['summary'], ('uses ' + ', '.join(e['uses'])) if e['uses'] else '')


if __name__ == '__main__':
    main()
