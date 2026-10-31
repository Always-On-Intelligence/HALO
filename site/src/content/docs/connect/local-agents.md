---
title: Claude Code, Codex, and other local hosts
description: Connect HALO to a host that starts MCP servers on your machine.
---

A host that runs on your machine can start HALO itself over stdio. No tunnel or HTTP server is needed, and the ledger stays in the same place.

## Claude Code

```bash
claude mcp add halo -- /path/to/HALO/.venv/bin/halo serve --agent claude-code
```

Or add it to the project's `.mcp.json`:

```json title=".mcp.json"
{
  "mcpServers": {
    "halo": {
      "command": "/path/to/HALO/.venv/bin/halo",
      "args": ["serve", "--agent", "claude-code"]
    }
  }
}
```

## Codex

```toml title="~/.codex/config.toml"
[mcp_servers.halo]
command = "/path/to/HALO/.venv/bin/halo"
args = ["serve", "--agent", "codex"]
```

## Any other MCP client

Use the stdio command above, or start `halo serve --http` and point the client at `http://127.0.0.1:8765/mcp`. Several clients can share one ledger. Give each its own `--agent` name, or let HALO use the name the client sends, so their traces stay apart.

## Your own agent

An agent you build can call HALO through any MCP client library, or log to the ledger directly:

```python
from halo.mcp.ledger import Ledger
from halo.mcp.analysis import report

ledger = Ledger("~/.halo/ledger.sqlite")
seen = ledger.add("my-agent", "observe", "user asks for a weekly summary", session="mon")
kept = ledger.add("my-agent", "remember", "wants a summary every Monday", [seen["id"]], session="mon")
print(report(ledger.events("my-agent"), "my-agent"))
```

Logging from your own code puts HALO in the path: the agent no longer decides what to report, because the code that runs each step also logs it.
