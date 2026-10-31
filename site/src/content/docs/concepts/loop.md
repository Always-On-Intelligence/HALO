---
title: The continuing loop
description: Modules, channels, and the chain of evidence for self-improvement, as HALO uses them.
---

HALO uses the terms of the survey *Always-On Personal Intelligence*. This page gives the definitions the plugin relies on. Read mode uses the same definitions, written out in `halo/read/protocol/PROTOCOL.md`.

## Three modules

An always-on personal service is a loop of three functional modules.

- **Sensing (S)** acquires and interprets current observations: user input, sensor streams, screen state, external events, and the observed state of the service's own execution.
- **Memory (M)** retains information across interactions.
- **Action (A)** selects the service's behavior: silence, communication, preparation, or execution.

Operations are assigned by function, not by component name. One model, tool, or shared context can play several roles, so an agent that reads a calendar, keeps a preference, and sends a reminder plays all three.

## Six channels

A coupling channel is a directed information flow in which one module supplies information that another module uses for its decisions or state updates.

| Channel | Information that flows |
|---|---|
| S→A | current input reaches Action. Every agent system has this basic path. |
| S→M | sensed or user-supplied evidence is admitted to Memory. |
| M→A | retained information guides an Action decision: timing, content, effector, commitment, or silence. |
| A→S | Action guides Sensing: what to observe next, or a check of whether an action had its expected effect. |
| M→S | retained priors guide Sensing: what to attend to, or how to interpret new input. |
| A→M | action context, records, or outcomes are kept in Memory. |

In the plugin, a channel X→Y appears when an event of module Y used an event of module X. [Event model](/HALO/architecture/events/) shows how agents state that.

## Five evidence steps

A service that improves itself changes its own mechanism: a prompt, rule, skill, policy, or model. The survey asks for a chain of evidence that runs from the service's own records to a revision it later uses. HALO judges each step on its own.

1. **Record.** The service keeps records of its own actions for later use.
2. **Outcome.** Later evidence about those actions, such as a reply, a rating, a correction, or a task result, is obtained and kept.
3. **Attribution.** An outcome is linked to the decision it concerns and used to check or correct assistance. An immediate check counts even if nothing is kept.
4. **Revision.** The service itself makes a durable change to its mechanism. Facts and preferences used by a fixed mechanism are content, not a revision, and changes written by users or developers are not revisions by the service.
5. **Later use.** Later steps run under the revised mechanism.

Channel coverage and the evidence chain are separate dimensions. The survey found that no reviewed work reporting every channel also reports a revision, and that works with a complete chain leave some channels unspecified. HALO therefore reports them in separate tables and does not combine them into a score.
