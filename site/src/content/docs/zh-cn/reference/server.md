---
title: 服务器与账本
description: 传输方式、地址、Host 头检查和账本文件。
---

## 传输方式

| 命令 | 传输方式 | 地址 |
|---|---|---|
| `halo serve` | stdio | 由客户端启动 |
| `halo serve --http` | Streamable HTTP | `http://127.0.0.1:8765/mcp` |
| `halo serve --http --public-host HOST` | 位于隧道或代理之后的 Streamable HTTP | `https://HOST/<token>/mcp` |

HTTP 服务器还在 `/mcp` 旁边提供[普通 HTTP 路由](/HALO/zh-cn/reference/http/)：`/events`、`/report` 和 `/guide`，有秘密路径时也在同一个秘密路径下。

## 选项

| 选项 | 默认值 | 含义 |
|---|---|---|
| `--db PATH` | `$HALO_LEDGER`，未设置时为 `~/.halo/ledger.sqlite` | 保存事件的账本文件 |
| `--agent NAME` | 客户端名称 | 该服务器上所有事件使用的智能体名称 |
| `--http` | 关闭 | 用 Streamable HTTP 代替 stdio 提供服务 |
| `--host` | `127.0.0.1` | 监听的网络接口 |
| `--port` | `8765` | 监听的端口 |
| `--public-host HOST` | 无 | 架在服务器前面的隧道的公网主机名。设置后启用秘密路径，并允许这个 Host 头 |
| `--token TOKEN` | `$HALO_TOKEN`，未设置时随机生成 | 秘密路径段 |

## Host 头与路径检查

如果请求的 Host 头不是 `127.0.0.1`、`localhost` 或 `--public-host` 指定的主机名，服务器会拒绝请求，这样可以保护本地服务器免受 DNS 重绑定攻击。设置 `--public-host` 后，插件只在 `/<token>/` 下提供服务，包括 `/mcp` 和普通 HTTP 路由，其他路径一律返回 404。如果宿主（接入插件的应用）已经保存了这个地址，请用 `--token` 或 `HALO_TOKEN` 让 token 保持不变。

## 账本

账本是一张名为 `events` 的 SQLite 表，每个记录下来的事件占一行：

| 列 | 内容 |
|---|---|
| `seq` | 事件编号，显示为 `e<seq>` |
| `ts` | 记录该事件时的 UTC 时间 |
| `agent`、`session` | 由谁记录，以及在哪个会话中记录 |
| `kind`、`summary`、`uses` | 事件种类、事件摘要，以及它使用的事件 id（以 JSON 存储） |
| `trigger`、`form`、`about`、`target`、`made_by`、`governance` | 行动、结果和修订事件的字段 |
| `client` | MCP 客户端的名称，通过普通 HTTP 发来的事件记为 `http` |

服务器只追加事件。要开始一条新的轨迹（一个智能体名下的全部事件），可以给智能体换一个新名字，或者把 `--db` 指向一个新文件。
