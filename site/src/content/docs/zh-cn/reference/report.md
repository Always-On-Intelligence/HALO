---
title: 报告
description: HALO 报告由哪几部分组成，以及如何读懂每个单元格。
---

`halo_report` 和 `halo trace report` 返回相同的 Markdown，内容分为四个部分。

1. **开头**：事件数和会话数、时间跨度，以及这条轨迹（智能体记下的事件）支持的闭环等级。
2. **通路**：每条通路一行。S→A 标为 basic（基本），因为每个智能体系统都有这条路径。
3. **自演化证据**：每个证据步骤一行。如果轨迹中有一条相连的链，随后列出这条链：一个行动，关于它的结果，使用了该结果的修订，以及使用了该修订的后续行动。
4. **等级**：从 L0 到 L5，每个等级一行，列出满足其条件的事件，或者说明这个等级还缺什么。最后一行说明下一个等级还需要什么。

## 单元格

| 取值 | 含义 |
|---|---|
| `observed`（已观察到） | 轨迹中有满足该条件的事件关联 |
| `not observed`（未观察到） | 轨迹中没有这样的关联，这并不表示智能体没有这条信息流 |

## 证据记法

| 记法 | 含义 |
|---|---|
| `e3→e5` | 事件 e5 使用了事件 e3 |
| `e5⇠e7→e9` | 结果 e7 针对行动 e5，并且 e9 使用了 e7 |
| `e9` | 事件本身 |

每个单元格最多列出三个例子。

## 示例

下面是 [ChatGPT dots](/HALO/zh-cn/connect/chatgpt-dots/) 中那个 dot 的报告，有删节：

```md
**The trace supports L0 (Session local).**

| Channel | In this trace | Evidence |
|---|---|---|
| S→A (basic) | observed | e1→e4, e2→e4, e1→e5 |
| S→M | observed | e2→e7, e6→e7 |
| M→A | observed | e3→e4, e3→e5 |
| A→S | observed | e5→e6 |
| M→S | not observed |  |
| A→M | observed | e4→e7, e5→e7 |

| Step | In this trace | Evidence |
|---|---|---|
| attribution | not observed | outcomes name their action, but no later action or revision used them |

To support L1, the trace needs something kept in memory and used in a later session.
```
