---
title: 快速上手
description: 接入一个智能体，记录一个小闭环三天里的步骤，然后阅读报告。
---

本页把一个本地 MCP 客户端接到 HALO 上，记录一个提醒助手三天里的闭环。同样的步骤适用于任何宿主（即运行智能体的应用），只是接入方式不同。

## 1. 接入客户端

Claude Code、Codex 这类本地宿主会自己启动 MCP 服务器。对这类宿主，把 HALO 注册为一个 stdio 服务器（通过标准输入输出通信）：

```json title=".mcp.json"
{
  "mcpServers": {
    "halo": { "command": "/path/to/HALO/.venv/bin/halo", "args": ["serve", "--agent", "demo"] }
  }
}
```

`--agent demo` 把这个连接中每个事件（即记录下的每一步）的智能体名都设为 `demo`。不加这个参数时，HALO 使用客户端发来的名字。如果是托管智能体，就改为用 HTTP 启动服务器，再按 [ChatGPT dots](/HALO/zh-cn/connect/chatgpt-dots/) 或 [Grok Bot](/HALO/zh-cn/connect/grok-bot/) 中的说明操作。

## 2. 记录闭环

让智能体先调用一次 `halo_guide`，它会返回智能体需要的说明。之后，智能体在每一步发生时把它记录下来。一个会学习用户提醒时间偏好的提醒助手，三天里记录了下面这些调用：

```text
day1  halo_observe   "user asks for reminders before meetings"                      -> e1
day1  halo_remember  "preference: remind before meetings"         uses [e1]         -> e2
day2  halo_observe   "calendar shows a 10:00 meeting"                                -> e3
day2  halo_recall    "reminder preference"                        uses [e2]         -> e4
day2  halo_act       "reminded the user at 9:30"  trigger self    uses [e3, e4]     -> e5
day2  halo_remember  "record: reminder sent at 9:30"              uses [e5]         -> e6
day2  halo_outcome   "user: 30 minutes is too early"  about e5                       -> e7
day2  halo_remember  "the 9:30 reminder was too early"            uses [e7, e6]     -> e8
day2  halo_revise    "remind 10 minutes before"  made_by agent, governance approved,
                     target "reminder timing rule"                uses [e8]         -> e9
day3  halo_observe   "calendar shows a 14:00 meeting"                                -> e10
day3  halo_act       "reminded the user at 13:50"  trigger self   uses [e10, e9]    -> e11
```

每次调用的回复都会给出新事件的编号，以及这一步实现的通路，例如 `Logged e5 (Action, act). Channels: S→A, M→A.`

## 3. 阅读报告

`halo_report` 返回诊断结果。上面这条轨迹的报告如下：

```md
**The trace supports L5 (Governed revision).**

| Channel | In this trace | Evidence |
|---|---|---|
| S→A (basic) | observed | e3→e5, e10→e11 |
| S→M | observed | e1→e2, e7→e8 |
| M→A | observed | e4→e5 |
| A→S | not observed |  |
| M→S | not observed |  |
| A→M | observed | e5→e6 |

One connected chain: e5 → e7 → e9 → e11 (action, outcome, revision, later action).
```

这条轨迹支持 L5，因为 L5 及以下每一级的条件都出现在其中。第 1 天保存的偏好引导了第 2 天的一次行动。智能体是自己决定行动的，trigger 为 `self`。这次行动的结果关联到了这次行动，之后也被用到。第 3 天用到了一次经用户批准的修订。[分析](/HALO/zh-cn/architecture/analysis/)一页给出每一行背后的规则。在客户端之外也能得到同样的报告：

```bash
halo trace report demo
```

## 下一步

- [插件架构](/HALO/zh-cn/architecture/)：各部分如何配合。
- [智能体指令](/HALO/zh-cn/connect/instructions/)：一条始终生效的长期指令，让智能体坚持记录。
