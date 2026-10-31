---
title: Tools
description: The nine MCP tools of the HALO plugin, their parameters, and their replies.
---

Every logging tool takes `summary`, `uses`, `session`, and `agent`. The table under each tool lists only the parameters it adds. The six logging tools are marked as writes that change nothing outside HALO, and the three reading tools as read-only.

## Shared parameters

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `summary` | string, required | | What happened, in a few words, without secrets or raw personal data. |
| `uses` | array of ids | `[]` | Earlier events this step relied on, such as `["e3", "e7"]`. |
| `session` | string | the MCP session | A label for the conversation or wake-up. |
| `agent` | string | `--agent`, then the client's name | The agent's name. |

## Logging tools

### `halo_observe`

Sensing: something the agent takes in now. Include an earlier action in `uses` when that action made the agent look.

### `halo_remember`

Memory: something the agent keeps for later interactions. Include what it keeps in `uses`: an observation, an action, or an outcome.

### `halo_recall`

Memory: the agent looks up something it kept earlier. Include the `remember` events it retrieved in `uses`.

### `halo_act`

Action: something the agent does for the user, or a decision to stay silent.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `trigger` | `request` or `self`, required | | `request` if the user asked for it or set it up, including steps inside a run the user scheduled. `self` only if nothing the user asked or scheduled started it and the agent decided on its own whether to act |
| `form` | `silence`, `communication`, `preparation`, or `execution` | `communication` | what kind of action it was |

### `halo_outcome`

Sensing: how one of the agent's earlier actions went.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `about` | event id, required | | the earlier `act` event the outcome is about |

### `halo_revise`

Mechanism: a durable change to how the agent works, which later runs reuse.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `target` | string, required | | what changed: a prompt, rule, skill, schedule policy, or similar |
| `made_by` | `agent` or `user`, required | | who made the change |
| `governance` | `approved`, `bounded`, or `none`, required | | whether the user approved it, it stays within limits the user set, or neither |

### Reply

A logging tool replies with the new event, or with an error that says how to fix the call:

```json
{ "id": "e5", "agent": "demo", "session": "day2", "note": "Logged e5 (Action, act). Channels: S→A, M→A." }
```

```json
{ "error": "unknown event id(s) e42 for agent 'demo'; call halo_trace to see the ids of your earlier events" }
```

## Reading tools

### `halo_trace`

Lists the agent's recent events with their ids, so later steps can name them.

| Parameter | Type | Default |
|---|---|---|
| `limit` | integer from 1 to 200 | `20` |
| `session` | string, empty for all | `""` |
| `agent` | string | as above |

```text
e4 [day2] act: reminded at 9:30 (uses e3) {trigger=self, form=communication}
```

### `halo_report`

The diagnosis of the agent's trace, or of one session, as Markdown. [Report](/HALO/reference/report/) describes its sections.

### `halo_guide`

Returns the instructions for agents, the same text the server sends as its MCP instructions. It takes no parameters.
