---
title: Products in the survey
description: How HALO can attach to each personal-intelligence product the survey reviews, from each maker's documentation.
---

We checked how HALO can attach to each product the survey reviews, from the makers' public documentation on 31 October 2026. Products change quickly, so treat this as a starting point and check the linked documentation before you rely on a row. "Unconfirmed" means the documentation does not say.

A product falls into one of three groups:

- **Plugin.** The product's agent can add HALO as a custom MCP server and log its own steps.
- **Bridge.** The product sends or exposes its own events, through webhooks, an event stream, an API, or an MCP server of its own, and HALO can read them. A bridge records what the product did without relying on the agent's report. HALO does not ship bridges yet: each is a small adapter that turns a product's events into HALO events.
- **Outside only.** Nothing reaches HALO. [Read mode](/HALO/modes/read/) and an A/B test at the product's boundary under a [test identity](/HALO/modes/run/) are what remain.

## Plugin

| Product | How HALO attaches | Notes |
|---|---|---|
| ChatGPT dots | a custom MCP server, created as a personal plugin | [tested on 31 October 2026](/HALO/connect/chatgpt-dots/) |
| Grok Bot | ask the bot in chat to add a custom MCP server | [tested on 31 October 2026](/HALO/connect/grok-bot/) |
| Claude (Cowork, Duet) | Customize, Connectors, Add custom connector | [tested with Cowork on 31 October 2026](/HALO/connect/claude/). Paid plans. Scheduled tasks can use connectors. Duet reuses connected apps, but custom connectors are unconfirmed |
| Manus | Connectors, Create, Add MCP by URL | whether scheduled tasks can call a custom server is unconfirmed |
| OpenClaw | `openclaw mcp add`, stdio or HTTP | self-hosted. A separate test agent, which keeps tests out of the main agent's memory, needs its own model credentials |
| Hermes Agent | `mcp_servers` in `~/.hermes/config.yaml` | self-hosted. Cron jobs can name the server |
| Vellum | `assistant mcp add` | the hosted platform closes on 2 November 2026, and the self-hosted runtime stays |
| Pally | send the server's address in chat | whether automations can call it is unconfirmed |
| Town | Integrations, Add an integration, server URL | routines can use it on paid plans |
| folk | connected apps | the steps for a custom server are unconfirmed |
| HeyClicky | a custom MCP connection by URL or command | macOS only |
| Gemini (scheduled actions, Tasks) | Connected Apps, Custom apps, in developer mode | US. Needs OAuth. Whether scheduled actions call custom apps is unconfirmed |
| Alexa+ | an MCP add-on through Alexa+ for Builders | developer preview, meant for brands rather than users |

## Bridge

| Product | Events HALO could read | Notes |
|---|---|---|
| EAIA | a webhook after each LangGraph run or cron run, and LangSmith traces | the repository was archived in July 2026 |
| Omi | webhooks for live transcripts, new memories, and a daily summary, and Omi's own MCP server | developer mode |
| Bee | a real-time event stream that can be forwarded to a webhook, a REST API, and a local MCP server | developer mode, integrations need Bee Pro |
| Memoket Gem | webhooks after each recording and summary, and a read-only MCP server | |
| Inbox Zero | a "Call webhook" rule action, and a REST API | |
| Muse | custom connectors that Muse builds in chat | MCP support is unconfirmed |
| Kindroid | a REST API that HALO would poll | |
| Looki L1 | a REST API | access by approval |
| Leon | skills, and a local HTTP API | the API is undocumented |
| Soulog Sense | its own MCP server, read only | Max plan |
| Sony aibo | a Web API whose states HALO would poll | aibo's memory is not exposed |
| Lio | robot APIs for partners | details unconfirmed |
| Windows Recall | snapshot export | EEA only |
| Siri on macOS 27 | the App Intents of a HALO app | only actions run through that app |

## Outside only

| Domain | Products |
|---|---|
| Digital | Gemini Daily Brief, Today, Brea, Orchid, Instinct, Catch, Caddy |
| Phones and watches | Pixel Magic Cue, Samsung Now Nudge, Huawei Xiaoyi Suggestions, vivo Xiao V Suggestions, OPPO Xiaobu, Apple Watch Smart Stack hints |
| Wearables | Oura Advisor, RayNeo iO, Even Realities G2, MemoMind One |
| Home and companion robots | ElliQ, Amazon Astro, Casio Moflin, Loona Deskmate, Hyodol |

Instinct's terms forbid automated use and benchmarking, so check them before any test.

## Research systems

Research systems with released code connect through [run-mode](/HALO/modes/run/) adapters rather than the plugin. An adapter runs a copy of the system's code and cuts its channels from inside. The repository has adapters for 20 of the works the survey reviews, and [Research systems](/HALO/results/research/) shows their read-mode results.
