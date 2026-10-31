---
title: Event model
description: The six kinds of events an agent logs, their fields, and the rules HALO checks.
---

Every call to a logging tool stores one event. An event belongs to one module of the loop, or it is a revision of the agent's own mechanism.

| Tool | Kind | Module | Log it when the agent |
|---|---|---|---|
| `halo_observe` | observe | Sensing | takes in something new: a user message, a page, a sensor reading, a tool result |
| `halo_outcome` | outcome | Sensing | learns how one of its earlier actions went: a reply, a rating, a dismissal, a correction, a result |
| `halo_remember` | remember | Memory | keeps something for later interactions: a fact, a preference, a record of what it did |
| `halo_recall` | recall | Memory | looks up something it kept earlier |
| `halo_act` | act | Action | does something for the user, or decides to stay silent |
| `halo_revise` | revise | none | changes its own way of working: a prompt, rule, skill, or policy it will reuse |

## Fields

| Field | On | Meaning |
|---|---|---|
| `summary` | all | What happened, in a few words. No secrets, passwords, or raw personal data. |
| `uses` | all | Ids of earlier events this step relied on, such as `["e3", "e7"]`. |
| `session` | all | A label for the conversation or wake-up, the same for each step in it. |
| `agent` | all | The agent's name. Empty means the server's `--agent` value, then the name the client sent. |
| `trigger` | act | `request` if the user asked for it or set it up, including every step inside a run the user requested or scheduled, even when the agent chooses how to do it. `self` only if no request or schedule of the user started it and the agent decided by itself, between requests, whether to act or to stay silent. |
| `form` | act | `silence`, `communication`, `preparation`, or `execution`. |
| `about` | outcome | The id of the earlier `act` event the outcome is about. |
| `target` | revise | What changed: the prompt, rule, skill, or policy. |
| `made_by` | revise | `agent` if the agent made the change, `user` if a user or developer wrote it. |
| `governance` | revise | `approved` if the user approved it, `bounded` if it stays within limits the user set, `none` otherwise. |

HALO adds an id (`e1`, `e2`, ...), a UTC timestamp, and the client name.

## Rules HALO checks

- Every id in `uses` must be an earlier event of the same agent. Ids are global, but one agent cannot link to another agent's events.
- `about` must be the id of one of the agent's own `act` events.
- `summary` must not be empty.

A call that breaks a rule is not stored. The reply says what to fix, for example `unknown event id(s) e42 for agent 'demo'; call halo_trace to see the ids of your earlier events`.

## What to link

The `uses` links are what HALO reads, so they should name what the step actually relied on.

- An action names the observations and memories its decision used.
- A memory names what it keeps: an observation, an action, or an outcome.
- An observation names an earlier action when that action made the agent look, for example to check whether a sent message arrived. That link is the channel A→S.
- An observation names a memory when the memory shaped what the agent looked for or how it read the input. That link is M→S.
- A revision names the outcomes that led to it, and a later action names the revision it follows.
