---
title: Claude（Cowork 和对话）
description: 把 HALO 作为自定义连接器加到 Claude，让 Cowork 任务记录自己的步骤。
---

Claude 的连接器就是 MCP 服务器，自定义连接器可以指向 HALO。连接由 Claude 的服务器发起，所以 HALO 需要一个公网地址，做法见 [ChatGPT dots](/HALO/zh-cn/connect/chatgpt-dots/)。自定义连接器需要付费方案。论文里的两个 Claude 产品 Cowork 和 Duet，用的都是账号里的连接器。

## 添加连接器

1. 在 Claude 里打开 **Customize**，进入 **Connectors**，选择 **Add**，再选 **Add custom connector**。
2. 名称填 `HALO`，粘贴插件地址，选择 **Continue**。Claude 会检查服务器，并识别出它不需要登录。
3. 保持 **No sign-in**，选择 **Add**，再选 **Connect**。

Claude 会把 HALO 的工具分成两组：3 个只读工具和 6 个写入工具，默认每个都需要批准。任务进行中，Claude 第一次调用某个工具时会询问。只读工具可以设为一直允许，记录用的工具只在当前任务内允许。

## 第一次测试

2026 年 10 月 31 日，我们给一个 Cowork 任务布置了一件小事，并请它在做的过程中用 HALO 记录每一步：写一段三句话的 HALO 简介，按“三句以内、不堆术语”自查，把检查结果记成初稿的结果，不合格就修改一次。和之前 dot、Grok Bot 的测试不同，这次的步骤是边做边记的，一分钟内记完：

| 编号 | 类型 | 步骤 | 用到 |
|---|---|---|---|
| e22 | observe | 用户的请求 | |
| e23 | observe | 阅读 HALO 的说明 | e22 |
| e24 | act | 写出初稿 | e22、e23 |
| e25 | outcome | 自查通过：三句，没有术语，about 为 e24 | e24、e22 |
| e26 | act | 原样交付初稿 | e24、e25 |

报告给出的等级是 **L0**。它观察到了 S→A 和 A→S（e25 检查 e24），以及归因：对初稿的检查（e25，about 为 e24）决定了交付（e26）。所以 L4 的条件出现了，但没有任何东西被存进记忆，也没有在之后的会话中被用到。Claude 还指出，它是先读了说明才开始记录的，所以 e23 记下的时间比它实际发生的时间晚。

Claude 发出的客户端名称是 `claude-code`，所以要在指令里给智能体单独起个名字，比如这次测试用的 `claude-cowork`。
