---
title: 只读模式
description: 三个监督智能体阅读一项工作的资料，判断每条通路和每个证据步骤。
---

只读模式根据资料审阅一项已发表的工作。审阅由三个监督智能体完成，它们是能联网的编程智能体。三者各自独立阅读这项工作的论文、文档和公开的代码，对每条通路和每个证据步骤作出判断，并附上原文引用和出处位置。结果表中的每一格由多数投票决定。

## 标签

| | 标签 |
|---|---|
| 通路 S→M、M→A、A→S、M→S、A→M | `reported`（已报告）、`absent`（明确不存在，即资料明确排除了这条信息流）、`insufficient`（信息不足，即资料没有说明所需的某个环节） |
| 证据步骤 | `stated`（已陈述）并附逐字的原文引用和出处位置，或 `not_stated`（未陈述）并附理由 |

每个智能体系统都有基本的 S→A 路径，因此不作审阅。完整规则见 `halo/read/protocol/PROTOCOL.md`，每份审阅结果都必须通过 `halo/read/schema.json` 的校验。

## 如何运行

```bash
python scripts/clone_upstream.py                         # the code the agents read, at pinned commits
halo read --backend codex:gpt-6-astra --workers 6        # one oversight agent over all works
halo read --backend claude:claude-opus-5-5 --workers 6
halo read --backend claude:claude-fable-5-1 --workers 6
halo vote                                                # results/read/votes.json and disagreements.md
halo tables                                              # results/read/table.md, table.csv, counts.json
```

模型通过本地编程智能体的 CLI 调用，所用的 CLI 由 `HALO_CODEX_BIN` 和 `HALO_CLAUDE_BIN` 指定，因此仓库中不保存任何 API 密钥。

## 结果

论文的只读模式结果表分为[研究系统](/HALO/zh-cn/results/research/)和[产品](/HALO/zh-cn/results/products/)两部分。

## 只读模式与插件

只读模式告诉你产品自称做了什么，插件告诉你运行中的智能体记录了什么。对于闭源产品，从外部能得到的证据就是这两种，而且两者可能不一致。比如，产品的文档写了某种记忆，你的轨迹（插件记下的步骤）里却从没用到它。产品也可能记录了一次检查，而它的文档并没有提到这种检查。
