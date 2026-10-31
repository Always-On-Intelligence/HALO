---
title: Repository layout
description: Where each part of HALO lives in the repository.
---

```text
halo/                 the package
  mcp/                the plugin: server, ledger, analysis, and the trace command
  backends/           model calls through local coding-agent CLIs (Codex, Claude Code)
  read/               read mode: protocol, review, batch, vote, tables
  run/                run mode: adapter base class, worker, harness, judge, cached LLM
cases/<work>/         one folder per reviewed work (40 works)
  case.yaml           the configuration reviewed, its sources, and its code
  core/               the upstream code that run mode executes, copied unchanged
  adapter.py          connects the upstream code to the harness and defines the cut sites
results/read/         read-mode reviews, votes, per-work counts, and the table
results/run/          run-mode reports
site/                 these docs (Astro Starlight)
tests/                unit tests, including tests/test_mcp.py for the plugin
```

## The plugin's modules

| Module | Role |
|---|---|
| `halo/mcp/server.py` | the MCP server: tool definitions, agent and session naming, `halo serve` |
| `halo/mcp/ledger.py` | the append-only SQLite ledger and its link checks |
| `halo/mcp/analysis.py` | channels, evidence steps, levels, and the report, from links alone |
| `halo/mcp/cli.py` | `halo trace` |

`analysis.py` imports nothing from MCP, so the rules can be tested and reused on any list of events.

## Tests

```bash
.venv/bin/python -m pytest -q tests/
```

`tests/test_mcp.py` replays the three-day reminder trace from the [Quickstart](/HALO/quickstart/) and checks that each level drops when its condition is removed.

## Adding a run-mode case

`docs/adding_a_case.md` in the repository gives the rules, and `cases/aiget/` is the reference case.
