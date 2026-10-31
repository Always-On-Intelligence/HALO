---
title: 仓库结构
description: HALO 的各个部分在仓库中的位置。
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

## 插件的代码模块

| 模块 | 作用 |
|---|---|
| `halo/mcp/server.py` | MCP 服务器：工具定义、智能体和会话的命名、`halo serve` |
| `halo/mcp/ledger.py` | 只追加的 SQLite 账本，以及它对事件关联的检查 |
| `halo/mcp/analysis.py` | 只依据事件之间的关联，得出通路、证据步骤、等级和报告 |
| `halo/mcp/cli.py` | `halo trace` |

`analysis.py` 不导入任何 MCP 相关的代码，因此这些规则可以在任意事件列表上测试和复用。

## 测试

```bash
.venv/bin/python -m pytest -q tests/
```

`tests/test_mcp.py` 重放[快速开始](/HALO/zh-cn/quickstart/)中为期三天的提醒轨迹，并检查：去掉某个等级的条件后，报告的等级会随之下降。

## 添加运行模式案例

仓库中的 `docs/adding_a_case.md` 给出了规则，`cases/aiget/` 是参考案例。
