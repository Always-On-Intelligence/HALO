---
title: 论文中的产品
description: 根据各家厂商的文档，HALO 能以什么方式接入论文审阅的每个个人智能产品。
---

我们根据厂商公开的文档，逐一查看了 HALO 能以什么方式接入论文审阅的每个产品，查看时间是 2026 年 10 月 31 日。产品变化很快，所以这张表只是一个起点，用到某一行之前，请先核对对应的文档。“未确认”表示文档里没有写。

每个产品属于下面三类之一：

- **插件。** 产品的智能体可以把 HALO 加为自定义 MCP 服务器，并记录自己的步骤。
- **转接。** 产品会通过 webhook、事件流、API 或它自己的 MCP 服务器，发出或开放自己的事件，HALO 可以读取。转接记录的是产品实际做了什么，不依赖智能体的自述。HALO 目前还没有提供转接：每一个都是一个小适配器，把产品的事件转换成 HALO 事件。
- **只能从外部。** 没有任何东西能到达 HALO。剩下的办法是[只读模式](/HALO/zh-cn/modes/read/)，以及在产品边界上、用[测试身份](/HALO/zh-cn/modes/run/)做的 A/B 测试。

## 插件

| 产品 | HALO 的接入方式 | 说明 |
|---|---|---|
| ChatGPT dots | 自定义 MCP 服务器，创建为个人插件 | [2026 年 10 月 31 日已测试](/HALO/zh-cn/connect/chatgpt-dots/) |
| Grok Bot | 在对话里请 bot 添加自定义 MCP 服务器 | [2026 年 10 月 31 日已测试](/HALO/zh-cn/connect/grok-bot/) |
| Claude（Cowork、Duet） | Customize、Connectors、Add custom connector | [2026 年 10 月 31 日已用 Cowork 测试](/HALO/zh-cn/connect/claude/)。需要付费方案。定时任务可以使用连接器。Duet 沿用账号已连接的应用，但能否使用自定义连接器未确认 |
| Manus | Connectors、Create、Add MCP by URL | 定时任务能否调用自定义服务器未确认 |
| OpenClaw | `openclaw mcp add`，stdio 或 HTTP | 自托管。单独的测试智能体可以让测试不进入主智能体的记忆，但它需要自己的模型凭据 |
| Hermes Agent | `~/.hermes/config.yaml` 里的 `mcp_servers` | 自托管。定时任务可以指定这个服务器 |
| Vellum | `assistant mcp add` | 托管平台 2026 年 11 月 2 日关闭，自托管的运行时仍可使用 |
| Pally | 在对话里发送服务器地址 | 自动任务能否调用它未确认 |
| Town | Integrations、Add an integration、服务器地址 | 付费方案的定时任务可以使用 |
| folk | 已连接的应用 | 添加自定义服务器的步骤未确认 |
| HeyClicky | 按地址或命令添加自定义 MCP 连接 | 仅限 macOS |
| Gemini（定时操作、Tasks） | 开发者模式下的 Connected Apps、Custom apps | 美国。需要 OAuth。定时操作能否调用自定义应用未确认 |
| Alexa+ | 通过 Alexa+ for Builders 的 MCP 插件 | 开发者预览，面向品牌而不是用户 |

## 转接

| 产品 | HALO 可以读取的事件 | 说明 |
|---|---|---|
| EAIA | 每次 LangGraph 运行或定时运行后的 webhook，以及 LangSmith 追踪 | 代码仓库已在 2026 年 7 月归档 |
| Omi | 实时转写、新记忆和每日摘要的 webhook，以及 Omi 自己的 MCP 服务器 | 需要开发者模式 |
| Bee | 可以转发到 webhook 的实时事件流、REST API 和本地 MCP 服务器 | 需要开发者模式，集成需要 Bee Pro |
| Memoket Gem | 每次录音和摘要完成后的 webhook，以及只读的 MCP 服务器 | |
| Inbox Zero | “Call webhook” 规则动作，以及 REST API | |
| Muse | Muse 在对话里创建的自定义连接器 | 是否支持 MCP 未确认 |
| Kindroid | 需要 HALO 轮询的 REST API | |
| Looki L1 | REST API | 需要申请批准 |
| Leon | 技能，以及本地 HTTP API | API 没有文档 |
| Soulog Sense | 它自己的只读 MCP 服务器 | 需要 Max 方案 |
| Sony aibo | 需要 HALO 轮询状态的 Web API | 不开放 aibo 的记忆 |
| Lio | 面向合作伙伴的机器人 API | 细节未确认 |
| Windows Recall | 快照导出 | 仅限欧洲经济区 |
| macOS 27 上的 Siri | HALO 应用自己的 App Intents | 只能看到经过这个应用执行的操作 |

## 只能从外部

| 领域 | 产品 |
|---|---|
| 数字 | Gemini Daily Brief、Today、Brea、Orchid、Instinct、Catch、Caddy |
| 手机和手表 | Pixel Magic Cue、三星 Now Nudge、华为小艺建议、vivo 小V建议、OPPO 小布、Apple Watch 智能叠放提示 |
| 可穿戴设备 | Oura Advisor、RayNeo iO、Even Realities G2、MemoMind One |
| 家用和陪伴机器人 | ElliQ、Amazon Astro、卡西欧 Moflin、Loona Deskmate、Hyodol |

Instinct 的服务条款禁止自动化使用和基准测试，测试之前请先看清条款。

## 研究系统

公开了代码的研究系统，通过[运行模式](/HALO/zh-cn/modes/run/)的适配器接入，而不是通过插件。适配器运行系统代码的一份副本，从内部切断它的通路。代码仓库里已有论文所审阅工作中 20 项的适配器，它们的只读模式结果见[研究系统](/HALO/zh-cn/results/research/)。
