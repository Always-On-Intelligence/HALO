---
title: The connection protocol
description: One set of events for every agent, and the way in that fits what the agent supports.
---

Every agent connects to HALO in the same way. It records each step of its loop as an event, and HALO reads the loop off the links between the events. Agents differ only in how their events reach HALO, which depends on what each agent supports.

## The events

An event is one step of the loop, of one of six kinds: observe, remember, recall, act, outcome, or revise. Each event lists in `uses` the earlier events that the step relied on. An act also says whether a request started it, an outcome names the act it is about, and a revision says what changed, who changed it, and whether the user approved. [Event model](/HALO/architecture/events/) defines every field. Every way in below carries these same events and checks them by the same rules, so every agent gets its report in the same terms.

## Choosing a way in

| What the agent supports | Way in | Cases |
|---|---|---|
| custom MCP servers | add HALO as an MCP server, at a public address for an agent in the cloud, or as a local command for a host on your machine such as Claude Code or Codex | [ChatGPT dots](/HALO/connect/chatgpt-dots/), [Grok Bot](/HALO/connect/grok-bot/), [Claude](/HALO/connect/claude/) |
| web requests, but no MCP | the agent sends each event as JSON to HALO's [HTTP address](/HALO/reference/http/) | [Muse](/HALO/connect/muse/), not yet run |
| code you can change | the code that runs each step writes the event, through the Python library or the HTTP address | [your own agent](/HALO/connect/local-agents/#your-own-agent) |
| only events of its own, such as webhooks, an event stream, or traces | a bridge: a small adapter that turns each of the product's events into a HALO event and sends it over HTTP | none yet, see the [candidates](/HALO/connect/coverage/#bridge) |
| none of these | nothing reaches HALO, which leaves [read mode](/HALO/modes/read/) and an A/B test under a [test identity](/HALO/modes/run/) | most phone, wearable, and robot products |

In the first two rows, the agent logs its own steps, following the [instructions](/HALO/connect/instructions/) it is given. In the next two, code logs them. Code gives stronger evidence, because each step is recorded by the code that performs it rather than by the agent's account of it.

## No framework around the agent

HALO does not wrap an agent or change how it works, so connecting one needs no new framework. An agent with MCP needs HALO's address and the instructions. An agent without MCP needs only a way to send a web request, which it has if it can run commands, write code, or build its own connectors. A product that only emits events of its own needs a bridge, which maps each of the product's event types to an event kind and is usually a few dozen lines of code.

## After connecting

Every way in writes to the same ledger and leads to the same report, from `halo_report` over MCP, from `GET /report` over HTTP, or from `halo trace report` on the command line. Give each agent one name, and each conversation or wake-up one session label, so that the report can tell sessions apart.
