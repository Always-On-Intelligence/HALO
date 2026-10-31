---
title: Muse
description: 通过普通 HTTP 把 Meta 的 Muse 接入 HALO，连接器由 Muse 自己搭建。
---

Meta 关于 Muse 的文档没有提到 MCP。不过 Muse 有自己的电脑，带文件系统、终端和完整的浏览器（[How We Designed Muse](https://introducing.muse.ai/)），而且在对话里请它为一个有 API 的服务创建自定义连接器，它就会自己搭建（[Meta 帮助中心](https://www.meta.com/help/artificial-intelligence/1687253048996149/)）。HALO 的 [HTTP 地址](/HALO/zh-cn/reference/http/)就是这样一个 API，`GET /guide` 用纯文本说明了它的用法，所以 Muse 读完说明就能自己搭好连到 HALO 的连接器。一篇[第三方指南](https://parallel.ai/articles/meta-muse-custom-integrations)提到，Muse 也能用这种方式连接远程 MCP 服务器，我们还没有试过。

Muse 运行在 Meta 的云端，所以 HALO 需要一个公网地址，做法同 [ChatGPT dots](/HALO/zh-cn/connect/chatgpt-dots/)。

## 接入

1. 和 ChatGPT dots 一样，在隧道后面启动插件。服务器会在 MCP 地址旁边打印普通 HTTP 的地址 `https://HOST/<token>/events`，用法说明在 `https://HOST/<token>/guide`。
2. 在 Muse 的对话里请它搭建连接器：

```text title="发给 Muse 的消息"
请为 HALO 创建一个自定义连接器，它用来记录你自己的工作步骤。用法见
https://HOST/<token>/guide，不需要任何凭据。之后在这个对话里，边做边把每一步记到 HALO，
agent 用 "muse"，每次对话用一个会话标签。只记真实发生的事，不要记录密钥和隐私内容。
```

3. Muse 发出请求之前，可能会请你批准。

## 测试

这个案例还没有运行。测试时，参照 [Claude 的测试](/HALO/zh-cn/connect/claude/)，让 Muse 做一件小事并逐步记录，再请求 `GET /report?agent=muse` 查看报告。
