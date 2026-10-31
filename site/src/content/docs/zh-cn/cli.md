---
title: 命令行参考
description: 全部 halo 命令。
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

启动插件。不加 `--http` 时，插件通过 stdio 使用 MCP 通信，供会自己启动插件的客户端使用。[服务器与账本](/HALO/zh-cn/reference/server/)列出了全部选项。

```bash
halo serve --agent claude-code                                   # stdio
halo serve --http --port 8765                                    # http://127.0.0.1:8765/mcp
halo serve --http --port 8765 --public-host x.trycloudflare.com  # behind a tunnel, secret path
```

## `halo trace`

不通过 MCP 客户端，直接读取账本，也就是插件保存事件的文件。

```bash
halo trace                      # the agents in the ledger and their event counts
halo trace report dot           # the report for one agent
halo trace report dot --session 2026-10-31
halo trace list dot --last 30   # its recent events
```

`--db` 用于选择另一个账本文件。

## `halo read`、`halo vote`、`halo tables`

只读模式：三个监督智能体（能联网的编程智能体）审阅每个案例，每一格由多数投票决定，最后由表格统计结果。详见[只读模式](/HALO/zh-cn/modes/read/)。

## `halo run`

运行模式：一个案例先按发布时的原样运行，再在它的切断点切断后运行，然后交给不知道输出来源的评判模型盲评。详见[运行模式](/HALO/zh-cn/modes/run/)。
