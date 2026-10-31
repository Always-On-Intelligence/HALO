---
title: Report
description: The sections of a HALO report and how to read each cell.
---

`halo_report` and `halo trace report` return the same Markdown. It has four parts.

1. **Header.** The number of events and sessions, the time span, and the level the trace supports.
2. **Channels.** One row per channel. S→A is marked basic because every agent system has it.
3. **Evidence for self-evolution.** One row per evidence step, then one connected chain if the trace has one: an action, an outcome about it, a revision that used the outcome, and a later action that used the revision.
4. **Levels.** One row per level from L0 to L5, with the events that meet each condition, or what the level still needs. A last line names what the next level needs.

## Cells

| Value | Meaning |
|---|---|
| `observed` | the trace contains links that meet the condition |
| `not observed` | the trace contains no such links, which does not mean the agent lacks the flow |

## Evidence notation

| Notation | Meaning |
|---|---|
| `e3→e5` | event e5 used event e3 |
| `e5⇠e7→e9` | outcome e7 is about action e5, and e9 used e7 |
| `e9` | the event itself |

At most three examples are listed per cell.

## Example

The report of the dot in [ChatGPT dots](/HALO/connect/chatgpt-dots/), abridged:

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
