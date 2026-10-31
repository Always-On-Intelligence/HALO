---
title: CLI reference
description: Every halo command.
---

```text
halo read   --backend codex:gpt-6-astra [--workers 5] [--only <case> ...]   review every case variant
halo vote   [--backends ...]                                               majority vote per cell
halo tables                                                               per-work counts and the table
halo run    cases/<case> [--workers 4] [--items N] [--samples N]           A/B run of one case
halo serve  [--http] [--port 8765] [--public-host HOST]                     the MCP plugin
halo trace  [report|list] [agent]                                         read the plugin's ledger
```

## `halo serve`

Starts the plugin. Without `--http` it speaks MCP over stdio, for clients that start it themselves. [Server and ledger](/HALO/reference/server/) lists every option.

```bash
halo serve --agent claude-code                                   # stdio
halo serve --http --port 8765                                    # http://127.0.0.1:8765/mcp
halo serve --http --port 8765 --public-host x.trycloudflare.com  # behind a tunnel, secret path
```

## `halo trace`

Reads the ledger without an MCP client.

```bash
halo trace                      # the agents in the ledger and their event counts
halo trace report dot           # the report for one agent
halo trace report dot --session 2026-10-31
halo trace list dot --last 30   # its recent events
```

`--db` selects another ledger file.

## `halo read`, `halo vote`, `halo tables`

Read mode: three oversight agents review every case, a majority vote decides each cell, and the tables count the result. See [Read mode](/HALO/modes/read/).

## `halo run`

Run mode: one case run as released and with its cut sites cut, judged blind. See [Run mode](/HALO/modes/run/).
