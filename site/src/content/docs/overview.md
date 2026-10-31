---
title: Overview
description: What HALO is, what the plugin adds, and how it relates to read mode and run mode.
---

HALO, the Harness for Always-On Loop Oversight, checks how an always-on personal service closes its loop. It follows the framework of the survey *Always-On Personal Intelligence*: a service is a loop of three modules, Sensing, Memory, and Action, connected by information-flow channels, and a service that improves itself also needs a chain of evidence that runs from its own records to a revision it later uses. [The continuing loop](/HALO/concepts/loop/) defines these terms.

## Three ways to use HALO

| | Read mode | Run mode | The plugin |
|---|---|---|---|
| Looks at | a system's papers, documentation, and code | a system's released code, run on fixed inputs | a running agent, through the steps it logs |
| Answers | does the source report each channel and evidence step? | does cutting a channel or step change the output? | which channels and steps appear in what the agent did? |
| Needs | the sources | the code and an adapter | an MCP connection |
| Works for products | yes, from their documentation | only with released code | yes, while the product runs |

Read mode and run mode are the two modes of the survey. The plugin is the third way, and these docs are mostly about it. It attaches HALO to an agent that is already running, such as a ChatGPT dot or Grok Bot, without access to the agent's code.

## How the plugin works

The plugin is an MCP server. Once an agent is connected to it, the agent calls one tool for each step of its loop: `halo_observe` when it takes in something new, `halo_remember` and `halo_recall` for its memory, `halo_act` when it acts or decides to stay silent, `halo_outcome` when it learns how an action went, and `halo_revise` when it changes its own way of working. Each call names the earlier steps the new step used.

HALO keeps these steps in a ledger on your machine and reads the loop off the links between them. `halo_report` returns the result in the same terms as the survey's tables: the six channels, the five evidence steps, and the highest level the trace supports. [Plugin architecture](/HALO/architecture/) explains each part.

## What a report can claim

The agent logs its own steps, so a report shows what the agent says it did and how those steps link. HALO checks the links, not whether the steps happened. A channel or step that does not appear is reported as not observed, never as absent, and a level is a lower bound. [What a trace can show](/HALO/architecture/trust/) covers this in detail.
