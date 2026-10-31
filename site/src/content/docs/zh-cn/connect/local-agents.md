---
title: Claude Code、Codex 和其他本地宿主
description: 把 HALO 接到在你本机启动 MCP 服务器的宿主上。
---

宿主就是运行智能体的应用。运行在你本机的宿主可以自己通过 stdio（标准输入输出）启动 HALO，不需要隧道或 HTTP 服务，账本也还在同一个位置。

## Claude Code

```bash
claude mcp add halo -- /path/to/HALO/.venv/bin/halo serve --agent claude-code
```

也可以写进项目的 `.mcp.json`：

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

## 其他 MCP 客户端

用上面的 stdio 命令，或者启动 `halo serve --http`，再让客户端连接 `http://127.0.0.1:8765/mcp`。多个客户端可以共用一个账本。给每个客户端一个自己的 `--agent` 名称，或者让 HALO 使用客户端发来的名称，这样它们的轨迹就不会混在一起。

## 你自己的智能体

你自己写的智能体可以通过任何 MCP 客户端库调用 HALO，也可以直接写账本：

```python
from halo.mcp.ledger import Ledger
from halo.mcp.analysis import report

ledger = Ledger("~/.halo/ledger.sqlite")
seen = ledger.add("my-agent", "observe", "user asks for a weekly summary", session="mon")
kept = ledger.add("my-agent", "remember", "wants a summary every Monday", [seen["id"]], session="mon")
print(report(ledger.events("my-agent"), "my-agent"))
```

从你自己的代码里记录，就等于让 HALO 站在每一步的必经之路上。记什么不再由智能体决定，因为执行每一步的代码同时也负责记录它。
