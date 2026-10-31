---
title: 安装
description: 安装带插件的 HALO，并确认服务器能够启动。
---

HALO 是一个 Python 包。插件需要 `mcp` 这个可选依赖（extra），它会安装 MCP Python SDK。插件中没有任何部分调用语言模型，所以不需要 API 密钥。

## 安装

在克隆下来的仓库目录中运行：

```bash
uv venv .venv -p 3.11
uv pip install -p .venv/bin/python -e ".[mcp]"
```

这会把 `halo` 命令放进 `.venv/bin`。你可以先激活这个环境，也可以直接调用 `.venv/bin/halo`。

## 检查服务器

用 Streamable HTTP 传输方式启动插件，并让它保持运行：

```bash
halo serve --http --port 8765
```

```text
HALO plugin listening on http://127.0.0.1:8765/mcp (ledger /Users/you/.halo/ledger.sqlite)
```

账本是一个 SQLite 文件，HALO 把记录下来的步骤保存在里面。它在首次使用时创建，默认位置是 `~/.halo/ledger.sqlite`，除非你传入 `--db` 或设置了 `HALO_LEDGER`。

## 环境要求

- Python 3.10 或更新版本，以及 MCP Python SDK 2.3 或更新版本（由上面这个可选依赖安装）。
- 对于 ChatGPT dots 或 Grok Bot 这类托管智能体，服务器需要一个公网 HTTPS 地址。[接入托管智能体](/HALO/zh-cn/connect/chatgpt-dots/)介绍如何用隧道（把本机服务转发到公网的工具）获得这样的地址。
- 只读模式和运行模式有各自的配置，见[只读模式](/HALO/zh-cn/modes/read/)和[运行模式](/HALO/zh-cn/modes/run/)。
