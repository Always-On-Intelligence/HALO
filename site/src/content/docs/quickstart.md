---
title: Quickstart
description: Connect an agent, log three days of a small loop, and read the report.
---

This page connects a local MCP client to HALO and logs the loop of a reminder service over three days. The same steps work from any host. Only the way of connecting differs.

## 1. Connect a client

For a local host that starts MCP servers itself, such as Claude Code or Codex, register HALO as a stdio server:

```json title=".mcp.json"
{
  "mcpServers": {
    "halo": { "command": "/path/to/HALO/.venv/bin/halo", "args": ["serve", "--agent", "demo"] }
  }
}
```

`--agent demo` names every event in this connection `demo`. Without it, HALO uses the name the client sends. For a hosted agent, start the server on HTTP instead and follow [ChatGPT dots](/HALO/connect/chatgpt-dots/) or [Grok Bot](/HALO/connect/grok-bot/).

## 2. Log the loop

Ask the agent to call `halo_guide` once. It returns the instructions the agent needs. Then the agent logs each step as it happens. Over three days, a reminder service that learns the user's timing logs these calls:

```text
day1  halo_observe   "user asks for reminders before meetings"                      -> e1
day1  halo_remember  "preference: remind before meetings"         uses [e1]         -> e2
day2  halo_observe   "calendar shows a 10:00 meeting"                                -> e3
day2  halo_recall    "reminder preference"                        uses [e2]         -> e4
day2  halo_act       "reminded the user at 9:30"  trigger self    uses [e3, e4]     -> e5
day2  halo_remember  "record: reminder sent at 9:30"              uses [e5]         -> e6
day2  halo_outcome   "user: 30 minutes is too early"  about e5                       -> e7
day2  halo_remember  "the 9:30 reminder was too early"            uses [e7, e6]     -> e8
day2  halo_revise    "remind 10 minutes before"  made_by agent, governance approved,
                     target "reminder timing rule"                uses [e8]         -> e9
day3  halo_observe   "calendar shows a 14:00 meeting"                                -> e10
day3  halo_act       "reminded the user at 13:50"  trigger self   uses [e10, e9]    -> e11
```

Each reply gives the new event's id and the channels it realized, for example `Logged e5 (Action, act). Channels: S→A, M→A.`

## 3. Read the report

`halo_report` returns the diagnosis. For the trace above:

```md
**The trace supports L5 (Governed revision).**

| Channel | In this trace | Evidence |
|---|---|---|
| S→A (basic) | observed | e3→e5, e10→e11 |
| S→M | observed | e1→e2, e7→e8 |
| M→A | observed | e4→e5 |
| A→S | not observed |  |
| M→S | not observed |  |
| A→M | observed | e5→e6 |

One connected chain: e5 → e7 → e9 → e11 (action, outcome, revision, later action).
```

The trace supports L5 because every condition up to L5 appears in it. The preference kept on day 1 guides an action on day 2. The agent acted on its own, with trigger `self`. The outcome of that action is linked to it and used. A revision the user approved is used on day 3. [Analysis](/HALO/architecture/analysis/) gives the rule behind each row. The same report is available outside the client:

```bash
halo trace report demo
```

## Next

- [Plugin architecture](/HALO/architecture/) for how the parts fit together.
- [Agent instructions](/HALO/connect/instructions/) for a standing instruction that keeps an agent logging.
