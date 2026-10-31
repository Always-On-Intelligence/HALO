---
title: 参与贡献
description: 如何修改 HALO 和这份文档。
---

## 修改规则

分析遵循论文和 `halo/read/protocol/PROTOCOL.md` 中的定义。如果要修改通路、证据步骤或等级的判读方式，应当引用所依据的定义，修改 `halo/mcp/analysis.py`，在 `tests/test_mcp.py` 中添加一个测试用例，并更新[分析](/HALO/zh-cn/architecture/analysis/)页面。

## 添加工具

事件模型（事件有哪些种类和字段）要保持精简。新的事件种类必须归属于闭环中的某个模块或证据链中的某个步骤，分析中也要有读取它的规则。工具描述是给智能体读的，所以描述要用平实的话说明什么时候调用这个工具。

## 这份文档

这份文档是位于 `site/` 的 Astro Starlight 站点。

```bash
cd site
npm install
npm run dev        # http://localhost:4321/HALO/
npm run build      # static files in site/dist
```

页面是 `site/src/content/docs/` 中的 Markdown 文件。主题样式是 `site/src/styles/theme.css`，页眉标签页和侧边栏是 `site/src/components/` 中的组件。
