---
title: 工具
description: HALO 插件的九个 MCP 工具，以及它们的参数和返回内容。
---

每个记录工具都接受 `summary`、`uses`、`session` 和 `agent` 这几个参数。每个工具下方的表格只列出它额外增加的参数。六个记录工具标注为写操作，并注明不会改变 HALO 之外的任何内容。三个读取工具标注为只读。

## 共用参数

| 参数 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `summary` | 字符串，必填 | | 用几个词说明发生了什么，不要写入机密信息或原始个人数据。 |
| `uses` | id 数组 | `[]` | 这一步依赖的较早事件，例如 `["e3", "e7"]`。 |
| `session` | 字符串 | 当前的 MCP 会话 | 这次对话或这次唤醒的标签。 |
| `agent` | 字符串 | 先取 `--agent`，再取客户端名称 | 智能体的名称。 |

## 记录工具

### `halo_observe`

感知：智能体此刻接收到的内容。如果之前的某个行动促使智能体去查看，就把那个行动写进 `uses`。

### `halo_remember`

记忆：智能体为以后的交互保存的内容。把保存的对象写进 `uses`，可以是一次观察、一次行动或一个结果。

### `halo_recall`

记忆：智能体查找它之前保存的内容。把检索到的 `remember` 事件写进 `uses`。

### `halo_act`

行动：智能体为用户做的事，或者保持沉默的决定。

| 参数 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `trigger` | `request` 或 `self`，必填 | | 用户要求过这个行动或事先设置了它时，用 `request`，用户要求或安排的一次运行中的各个步骤也包括在内。只有当这个行动并非由用户要求或安排的任何事情引发，而是智能体自己决定是否行动时，才用 `self` |
| `form` | `silence`、`communication`、`preparation` 或 `execution` | `communication` | 这次行动属于哪一类 |

### `halo_outcome`

感知：智能体之前某个行动的结果如何。

| 参数 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `about` | 事件 id，必填 | | 该结果针对的那个较早的 `act` 事件 |

### `halo_revise`

机制：对智能体工作方式的持久修改，之后的运行会沿用它。

| 参数 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `target` | 字符串，必填 | | 改了什么：提示词、规则、技能、调度策略或类似内容 |
| `made_by` | `agent` 或 `user`，必填 | | 由谁做出这次修改 |
| `governance` | `approved`、`bounded` 或 `none`，必填 | | 是用户批准了修改，还是修改没有超出用户设定的限制，或者两者都不是 |

### 返回内容

记录工具会返回新建的事件，或者返回一条错误，说明如何修正这次调用：

```json
{ "id": "e5", "agent": "demo", "session": "day2", "note": "Logged e5 (Action, act). Channels: S→A, M→A." }
```

```json
{ "error": "unknown event id(s) e42 for agent 'demo'; call halo_trace to see the ids of your earlier events" }
```

## 读取工具

### `halo_trace`

列出智能体最近的事件及其 id，便于后续步骤引用它们。

| 参数 | 类型 | 默认值 |
|---|---|---|
| `limit` | 1 到 200 之间的整数 | `20` |
| `session` | 字符串，留空表示全部会话 | `""` |
| `agent` | 字符串 | 同上 |

```text
e4 [day2] act: reminded at 9:30 (uses e3) {trigger=self, form=communication}
```

### `halo_report`

以 Markdown 返回对智能体轨迹（它记下的全部事件）的诊断，也可以只诊断其中一个会话。[报告](/HALO/zh-cn/reference/report/)介绍了报告的各个部分。

### `halo_guide`

返回给智能体的说明，与服务器作为 MCP 说明发送的文字相同。这个工具不接受参数。
