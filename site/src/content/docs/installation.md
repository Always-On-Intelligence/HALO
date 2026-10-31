---
title: Installation
description: Install HALO with the plugin and check that the server starts.
---

HALO is a Python package. The plugin needs the `mcp` extra, which installs the MCP Python SDK. Nothing in the plugin calls a language model, so it needs no API key.

## Install

From a checkout of the repository:

```bash
uv venv .venv -p 3.11
uv pip install -p .venv/bin/python -e ".[mcp]"
```

This puts the `halo` command in `.venv/bin`. Activate the environment, or call `.venv/bin/halo` directly.

## Check the server

Start the plugin on Streamable HTTP and leave it running:

```bash
halo serve --http --port 8765
```

```text
HALO plugin listening on http://127.0.0.1:8765/mcp (ledger /Users/you/.halo/ledger.sqlite)
```

The ledger is a SQLite file. It is created on first use, at `~/.halo/ledger.sqlite` unless you pass `--db` or set `HALO_LEDGER`.

## Requirements

- Python 3.10 or newer, and the MCP Python SDK 2.3 or newer (installed by the extra).
- For hosted agents such as ChatGPT dots or Grok Bot, a public HTTPS address for the server. [Connect a hosted agent](/HALO/connect/chatgpt-dots/) shows how to get one with a tunnel.
- Read mode and run mode have their own setup, described in [Read mode](/HALO/modes/read/) and [Run mode](/HALO/modes/run/).
