"""Command line: `halo read | vote | tables | run | serve | trace`.

  halo read   --backend codex:gpt-6-astra [--workers 5] [--only <case> ...]   review every case variant
  halo vote   [--backends ...]                                               majority vote per cell
  halo tables                                                               per-work counts and the table
  halo run    cases/<case> [--workers 4] [--items N] [--samples N]           A/B run of one case
  halo serve  [--http] [--port 8765] [--public-host HOST]                     the MCP plugin (needs the mcp extra)
  halo trace  [report|list] [agent]                                         read the plugin's ledger
"""
import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__); return
    cmd, sys.argv = sys.argv[1], [f'halo {sys.argv[1]}'] + sys.argv[2:]
    if cmd == 'read':
        from halo.read.batch import main as m
    elif cmd == 'vote':
        from halo.read.vote import main as m
    elif cmd == 'tables':
        from halo.read.tables import main as m
    elif cmd == 'run':
        from halo.run.harness import main as m
    elif cmd == 'serve':
        from halo.mcp.server import main as m
    elif cmd == 'trace':
        from halo.mcp.cli import main as m
    else:
        sys.exit(f'unknown command {cmd!r}\n{__doc__}')
    m()


if __name__ == '__main__':
    main()
