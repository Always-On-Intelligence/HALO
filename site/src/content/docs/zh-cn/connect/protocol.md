---
title: 接入协议
description: 所有智能体共用一套事件，再按智能体支持什么来选接入方式。
---

所有智能体接入 HALO 的方式都一样：把闭环中的每一步记成一个事件，HALO 再从事件之间的引用读出闭环。智能体之间的区别只在于事件怎样到达 HALO，这取决于各个智能体支持什么。

## 事件

一个事件就是闭环中的一步，共六类：observe、remember、recall、act、outcome 和 revise。每个事件在 `uses` 里列出这一步用到的更早事件。act 还要说明它是不是由请求引起的，outcome 要指明它评价的是哪次 act，revise 要说明改了什么、由谁改的、用户是否同意。各个字段的定义见[事件模型](/HALO/zh-cn/architecture/events/)。下面每种接入方式传的都是这同一套事件，检查规则也相同，所以每个智能体得到的报告都使用同样的术语。

## 选择接入方式

| 智能体支持什么 | 接入方式 | 案例 |
|---|---|---|
| 自定义 MCP 服务器 | 把 HALO 加为 MCP 服务器：云端的智能体用公网地址，本机的宿主（比如 Claude Code 或 Codex）用本地命令 | [ChatGPT dots](/HALO/zh-cn/connect/chatgpt-dots/)、[Grok Bot](/HALO/zh-cn/connect/grok-bot/)、[Claude](/HALO/zh-cn/connect/claude/) |
| 能发网页请求，但不支持 MCP | 智能体把每个事件以 JSON 格式发到 HALO 的 [HTTP 地址](/HALO/zh-cn/reference/http/) | [Muse](/HALO/zh-cn/connect/muse/)，尚未测试 |
| 你能修改它的代码 | 由执行每一步的代码写入事件，用 Python 库或 HTTP 地址 | [你自己的智能体](/HALO/zh-cn/connect/local-agents/#你自己的智能体) |
| 只会发出自己的事件，比如 webhook、事件流或追踪记录 | 转接：一个小适配器，把产品的每个事件转成 HALO 事件，再通过 HTTP 发给 HALO | 暂无，候选产品见[这里](/HALO/zh-cn/connect/coverage/#转接) |
| 以上都没有 | 没有任何东西能到达 HALO，只剩[只读模式](/HALO/zh-cn/modes/read/)，以及用[测试身份](/HALO/zh-cn/modes/run/)做的 A/B 测试 | 大多数手机、可穿戴设备和机器人产品 |

前两行由智能体按照给它的[指令](/HALO/zh-cn/connect/instructions/)自己记录步骤，后两行由代码记录。代码记录的证据更强，因为每一步都由执行它的代码记下，不依赖智能体的自述。

## 不需要给智能体搭框架

HALO 不包住智能体，也不改变它的工作方式，所以接入时不需要搭新的框架。支持 MCP 的智能体只需要 HALO 的地址和指令。不支持 MCP 的智能体只要能发网页请求就行，能运行命令、能写代码或者能自己搭连接器的智能体都做得到。只会发出自己事件的产品需要一个转接，它把产品的每种事件对应到一类 HALO 事件，通常只有几十行代码。

## 接入之后

无论走哪种方式，事件都写进同一个账本，得到的报告也一样：MCP 下调用 `halo_report`，HTTP 下请求 `GET /report`，命令行里运行 `halo trace report`。每个智能体固定用一个名字，每次对话或唤醒各用一个会话标签，报告才能区分不同的会话。
