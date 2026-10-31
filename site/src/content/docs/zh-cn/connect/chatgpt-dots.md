---
title: ChatGPT dots
description: 把 HALO 作为自定义 MCP 服务器加成 ChatGPT 的个人插件，再让 dot 使用它。
---

dot 是 ChatGPT 的持续在线智能体。它在云端运行，可以使用你账号里已安装并启用的插件。把 HALO 添加为自定义 MCP 服务器后，它就成了这样一个插件。

## 1. 给服务一个公网地址

dot 运行在 OpenAI 的云端，访问不到你的 `localhost`，所以要让插件跑在隧道后面。隧道会把本机的服务转发到一个公网地址。用 Cloudflare 的快速隧道不需要账号：

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

记下它打印出的 `https://<name>.trycloudflare.com` 地址，再用这个主机名启动 HALO：

```bash
halo serve --http --port 8765 --public-host <name>.trycloudflare.com
```

```text
HALO plugin URL: https://<name>.trycloudflare.com/<random>/mcp
```

路径里的随机段让只有拿到完整地址的人才能访问，其他路径一律返回 404。快速隧道每次启动都会换一个名字，插件地址也随之改变。用命名隧道或你自己的 HTTPS 主机，地址就能固定下来。

## 2. 把 HALO 添加为自定义 MCP 服务器

1. 打开 [chatgpt.com/plugins](https://chatgpt.com/plugins)，选择 **添加**，再选 **添加自定义 MCP 服务器**。
2. 名称填 `HALO`，粘贴插件地址，身份验证选 **无需身份验证**。
3. 阅读风险提示并确认，然后选择 **创建为插件**。ChatGPT 会连接服务器并列出它的工具。
4. 在 **连接 HALO** 对话框里选择 **连接**。对话框说明 ChatGPT 可能会把相关记忆和聊天内容分享给这个插件。

之后 HALO 会出现在插件页的 **个人** 标签下。

## 3. 让 dot 使用它

打开 dot 的对话，输入 `@` 并选择 **HALO**，然后把[智能体指令](/HALO/zh-cn/connect/instructions/)发给它。如果把指令写进 dot 的记忆，它在之后的对话里，以及在它自己发起的行动中，都会继续记录。

## 第一次测试

2026 年 10 月 31 日，我们把 HALO 接到一个 dot 上。这个 dot 每天发送一次会议截稿倒计时，这个提醒是用户自己设定的。我们让它记录这个提醒最近一次运行的过程，再调用 `halo_report`。它记了 7 条事件，每条都注明是事后补记，并写上了实际发生的时间：

| 编号 | 类型 | 步骤 | 用到 |
|---|---|---|---|
| e1 | observe | 定时的倒计时任务开始运行 | |
| e2 | observe | 读取官方日期 | e1 |
| e3 | recall | 回看用户有没有新的反馈，没有找到 | e1 |
| e4 | act | 计算剩余时间，准备建议 | e1、e2、e3 |
| e5 | act | 发出倒计时 | e1 到 e4 |
| e6 | outcome | 消息工具接受了发送请求，about 为 e5 | e5 |
| e7 | remember | 保存日期、提醒时间和发送记录 | e2、e4、e5、e6 |

报告给出的等级是 **L0**。它观察到了 S→A、S→M、M→A、A→S（e6 检查 e5）和 A→M（e7 保存 e5），以及记录和结果两个证据步骤。M→S、归因和修订都没有观察到。dot 自己解释了等级为什么低。所有事情都发生在同一个会话里，看不出记忆在之后的会话中被用到，而 L1 需要这一点。提醒是用户设定的，所以两次行动都记成 trigger `request`，这也排除了 L3。这和论文对用户定时提醒的判断一致。

下一步是把指令写进 dot 的记忆，记录几天的日常使用。
