---
title: HTTP 接口
description: 普通 HTTP 路由，供不支持 MCP 的智能体和转接使用。
---

提供 MCP 的 HTTP 服务器同时提供四个普通路由。它们收发的事件和 [MCP 工具](/HALO/zh-cn/reference/tools/)相同，检查规则也相同。设置 `--public-host` 后，所有路由都在秘密路径下，比如 `https://HOST/<token>/events`。本地服务器上则是 `http://127.0.0.1:8765/events` 等地址。

| 路由 | 作用 |
|---|---|
| `POST /events` | 记录一个事件，以 JSON 格式发送，并带上 `Content-Type: application/json` |
| `GET /events?agent=NAME` | 按时间顺序列出这个智能体的事件。可选参数 `session` 和 `limit`（默认 50，最多 500） |
| `GET /report?agent=NAME` | 以 Markdown 返回[报告](/HALO/zh-cn/reference/report/)。可选参数 `session` |
| `GET /guide` | 以纯文本返回通过 HTTP 记录的说明，其中已经填好这台服务器的地址 |

## 记录一个事件

```bash
curl -s https://HOST/<token>/events \
  -H 'Content-Type: application/json' \
  -d '{"agent": "muse", "session": "2026-11-01 errand", "kind": "act",
       "summary": "drafted the reply", "uses": ["e3"],
       "trigger": "request", "form": "preparation"}'
```

```json title="返回，状态码 201"
{"id": "e4", "agent": "muse", "session": "2026-11-01 errand", "note": "Logged e4 (Action, act). Channels: S→A."}
```

| 字段 | 何时需要 | 取值 |
|---|---|---|
| `agent` | 每个事件 | 智能体的名字，每次都相同 |
| `kind` | 每个事件 | `observe`、`remember`、`recall`、`act`、`outcome` 或 `revise` |
| `summary` | 每个事件 | 用几个词说明发生了什么 |
| `uses` | 用到了更早事件的每个事件 | 那些事件的编号，比如 `["e3"]` |
| `session` | 可选 | 这次对话或唤醒的标签 |
| `trigger` | act | `request` 或 `self` |
| `form` | act，可选 | `silence`、`communication`（默认）、`preparation` 或 `execution` |
| `about` | outcome | 这个结果评价的那次 act 的编号 |
| `target`、`made_by`、`governance` | revise | 改了什么，`agent` 或 `user`，以及 `approved`、`bounded` 或 `none` |

各字段的含义见[事件模型](/HALO/zh-cn/architecture/events/)。

## 错误

无法保存的事件返回状态码 400 和 `{"error": ...}`，说明该怎么改，比如 `act needs trigger` 或 `unknown event id(s) e9`。没有带 JSON 内容类型的请求返回 415，Host 头不认识的请求返回 421。

这些路由不发送 CORS 头，`POST /events` 也只接受 JSON 内容类型，所以别的网站上的网页无法向你本机运行的服务器写入事件。
