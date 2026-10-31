---
title: Claude (Cowork and chat)
description: Add HALO to Claude as a custom connector and let a Cowork task log its steps.
---

Claude's connectors are MCP servers, and a custom connector can point at HALO. Claude's servers make the connection, so HALO needs a public address, as in [ChatGPT dots](/HALO/connect/chatgpt-dots/). Custom connectors need a paid plan, and the survey's Claude products, Cowork and Duet, both use the connectors of the account.

## Add the connector

1. In Claude, open **Customize**, then **Connectors**, choose **Add**, then **Add custom connector**.
2. Name it `HALO`, paste the plugin URL, and choose **Continue**. Claude checks the server and detects that it needs no sign-in.
3. Keep **No sign-in** and choose **Add**, then **Connect**.

Claude lists HALO's tools in two groups, three read-only tools and six that write. Each needs approval by default. During a task, Claude asks the first time it calls each tool: the read-only tools can be allowed always, and the logging tools for the current task only.

## A first test

On 31 October 2026 we gave a Cowork task a small job and asked it to log each step with HALO while it worked: write a three-sentence introduction to HALO, check it against "three sentences, no jargon", record the check as an outcome of the draft, and revise once if it failed. Unlike the earlier tests with a dot and Grok Bot, the steps were logged as they happened, within one minute:

| Id | Kind | Step | Uses |
|---|---|---|---|
| e22 | observe | the user's request | |
| e23 | observe | reads the HALO guide | e22 |
| e24 | act | writes the draft | e22, e23 |
| e25 | outcome | the self-check passes: three sentences, no jargon, about e24 | e24, e22 |
| e26 | act | delivers the draft unchanged | e24, e25 |

The report placed the trace at **L0**. It observed S→A and A→S (e25 checks e24), and attribution, because the check of the draft (e25, about e24) decided the delivery (e26). The conditions of L4 therefore appear, but nothing was kept in memory or used in a later session. Claude also pointed out that it read the guide before it logged anything, so e23 was logged later than it happened.

The client name Claude sends is `claude-code`, so give the agent a name of its own in the instructions, as this test did with `claude-cowork`.
