---
title: 智能体指令
description: 一条长期指令，让智能体在工作时持续记录自己的闭环。
---

智能体只有被告知时才会向 HALO 记录。`halo_guide` 返回简短版本，服务器也会把同样的文字作为 MCP 说明发给客户端。如果希望智能体连续几天都在记录，就把一条长期指令一次性写进它的记忆或设置里。这样它在日常使用中，以及在自己发起的行动中，都会记录。

```text title="长期指令"
From now on, log each step of your work to HALO while you do it, in a few words:
- halo_observe when you take in something new, such as my message, a page, or a tool result.
- halo_remember when you keep something for later conversations, and halo_recall when you look it up.
- halo_act when you do something for me or decide to stay silent. Use trigger "request" when I asked
  for it or set it up, including every step of a run I scheduled. Use "self" only when nothing I asked
  or scheduled started it and you decided on your own whether to act.
- halo_outcome when you learn how one of your actions went. Pass the action's id as about.
- halo_revise when you change your own way of working for the future.
Always pass uses with the ids of the earlier steps you relied on. Use one session label per
conversation or wake-up, and agent "<name>". Log only what really happened, mark anything logged
afterwards as such, and leave out secrets and private text.
```

指令用英文写，因为工具名和字段值都是英文。用中文和智能体交流时，也可以把这段原样发给它。

## 让轨迹有用的几个习惯

- **会话标签保持一致。** 状态持久性要跨会话才看得出来，所以每次对话或每次定时唤醒各用一个会话标签就够了。所有事情都用同一个标签，反而会把它掩盖掉。
- **沉默也要记。** 决定不行动也是一次行动，form 为 `silence`。对持续在线的智能体来说，决定再等一等也是运行连续性的一部分。
- **把内容和修订分开。** 新的事实或偏好记为 `remember`。智能体以后每次运行都会照着执行的规则，才记为 `revise`。
- **写明用户的角色。** 用户自己写的改动，记为 `made_by: user`。智能体在用户批准后做的改动，记为 `made_by: agent`，governance 为 `approved`。
