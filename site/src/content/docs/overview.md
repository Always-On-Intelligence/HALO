---
title: Overview
description: What HALO is, what the plugin adds, and how it relates to read mode and run mode.
---

HALO, the Harness for Always-On Loop Oversight, is a diagnostic tool that assesses the loop completeness of always-on assistants. It follows the framework of the survey [*Always-On Personal Intelligence*](https://always-on-intelligence.github.io/Always-On_Personal_Intelligence.pdf): an always-on assistant runs a continuing loop of three functional modules, Sensing, Memory, and Action, connected by six directed coupling channels, and self-evolution extends this loop when the assistant revises how it works from its own operating experience. A claim of self-evolution that rests on outcome feedback needs a chain of evidence with five steps: record, outcome, attribution, revision, and later use. [The continuing loop](/HALO/concepts/loop/) defines these terms.

## Three ways to use HALO

| | Read mode | Run mode | The plugin |
|---|---|---|---|
| Looks at | a system's papers, documentation, and code | a system's released code, run on fixed inputs | a running agent, through the steps it logs |
| Answers | does the source report each channel and evidence step? | does cutting a channel or step change the output? | which channels and steps appear in what the agent did? |
| Needs | the sources | the code and an adapter | an MCP connection |
| Works for products | yes, from their documentation | only with released code | yes, while the product runs |

Read mode and run mode are the two modes of the survey. The plugin is the third way, and these docs are mostly about it. It attaches HALO to an agent that is already running, such as a ChatGPT dot or Grok Bot, without access to the agent's code.

## Why HALO works this way

Testing a personal agent runs into two problems.

1. **Many agents are black boxes.** Products rarely release their code, so their internals can be judged only from the outside, end to end.
2. **A test changes what it tests.** A personal agent keeps state about its user. Every test input enters its memory and can change what it does later, and state durability is one of the properties under test. An A/B test run on the user's own agent therefore changes that agent and the user's later use of it.

HALO's three ways therefore differ in how much they touch the agent:

| | Touches the agent | Shows |
|---|---|---|
| Read mode | not at all | what the sources say the agent does |
| The plugin | no, it only records ordinary use | what the agent did, but not what caused it |
| Run mode | yes, but only a copy | whether a channel or evidence step changes the output |

Run mode never intervenes on the agent a user relies on. For released code it runs a copy in a sandbox. For a closed product it needs a separate test identity, as [Run mode](/HALO/modes/run/) describes. A test identity has none of the user's history, so it tests the mechanism, not what the agent has learned about this user. That part can only be observed, which is the plugin's job.

## A protocol, not a service

No single service can connect to every personal agent, and many of the agents that matter are closed products or devices. HALO is therefore a shared protocol that the makers and users of those agents attach themselves. It has three parts:

- **The events.** Six kinds of steps, observe, remember, recall, act, outcome, and revise, each naming the earlier steps it used. [Event model](/HALO/architecture/events/) defines them.
- **The ways in.** An agent can log its steps through MCP or plain HTTP, or the code that runs each step can write the same events directly. A system that already records its steps, for example in OpenTelemetry, a common format for runtime traces, or through agent hooks, which are scripts that run at each step, could instead have those records converted into HALO events, so that its maker does not log twice. HALO does not convert them yet. [The connection protocol](/HALO/connect/protocol/) shows which way in fits which agent.
- **The report.** The rows of the survey's tables: six channels, five evidence steps, and a level.

Who attaches HALO decides how strong the evidence is.

| Who | Attaches HALO to | Evidence |
|---|---|---|
| A device or product maker | its own system, from the code that runs each step | the strongest: each step is logged by the code that performs it, and the maker can test copies of its own system |
| A developer | an agent they build, or a product they use through its MCP or plugin support | the agent's own log of its steps, which read mode can check against the product's documentation |
| A researcher | many systems at once | reports in the same terms for every system |

For a person who uses an agent, a report shows what the agent keeps, what it has changed about its own way of working, and whether that person approved the change.

Whether makers and developers need this can be checked cheaply. Convert the records of a system already in use, such as the hooks of OpenClaw or Hermes Agent, into HALO events, and see whether the report points to a problem that nobody had noticed.

## How the plugin works

The plugin is an MCP server. Once an agent is connected to it, the agent calls one tool for each step of its loop: `halo_observe` when it takes in something new, `halo_remember` and `halo_recall` for its memory, `halo_act` when it acts or decides to stay silent, `halo_outcome` when it learns how an action went, and `halo_revise` when it changes its own way of working. Each call names the earlier steps the new step used.

HALO keeps these steps in a ledger on your machine and reads the loop off the links between them. `halo_report` returns the result in the same terms as the survey's tables: the six channels, the five evidence steps, and the highest level the trace supports. [Plugin architecture](/HALO/architecture/) explains each part.

## What a report can claim

The agent logs its own steps, so a report shows what the agent says it did and how those steps link. HALO checks the links, not whether the steps happened. A channel or step that does not appear is reported as not observed, never as absent, and a level is a lower bound. [What a trace can show](/HALO/architecture/trust/) covers this in detail.
