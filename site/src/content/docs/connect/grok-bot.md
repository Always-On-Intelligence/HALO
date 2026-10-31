---
title: Grok Bot
description: Add HALO to Grok Bot as a custom MCP server, and what its first trace showed.
---

Grok Bot runs on its own cloud computer, and its desktop and mobile apps are clients for chat and approvals. Like a dot, it cannot reach `localhost`, so start HALO behind a tunnel first, as in [ChatGPT dots](/HALO/connect/chatgpt-dots/).

## Add the server in chat

Grok Bot has no settings field for a server address. You add a custom MCP server by asking for it in the bot's conversation:

```text
Add a custom MCP server called HALO at https://<name>.trycloudflare.com/<random>/mcp (no authentication).
```

Say "custom MCP server", or the bot may look for a catalog plugin with the same name instead. HALO needs no authentication, so no connect card follows. The bot confirms that it connected and found nine tools. It also warned that a quick tunnel's address changes when the tunnel restarts, and that it then needs the new address.

Attach HALO to a message by typing `@` and picking it, and give the bot the [agent instructions](/HALO/connect/instructions/). Custom servers are listed under **Settings**, **Plugins**, **Yours**, and they are available to every bot on the account. If a team admin restricts plugins, the address must be on the team's MCP allowlist.

## A first test

On 31 October 2026 we asked Grok Bot to log the most recent run of its daily paper digest, a routine the user had scheduled for 9:00 on weekdays, and what followed. It logged 14 events in two sessions, each marked as logged afterwards:

| Session | What it logged |
|---|---|
| 30 October, the digest run | the scheduled wake-up, an arXiv rate limit, a switch to other paper lists, ranking candidates by the research topics written in the routine, choosing 5 papers, building and checking 5 PDFs, keeping run notes in files, and sending the digest |
| 31 October, the delivery change | the user's report that another assistant had received no package and the request to write packages into a shared project, reading the project's delivery rules, a test write and its result, and a rewrite of the routine's saved prompt |

The report observed S→A, M→A, A→S, and A→M, and three evidence steps. The record: the chosen papers were kept (e13→e15). Attribution: the user's report about the sent digest (e17, about e16) led to the test write (e19). Revision: the bot rewrote the routine's saved prompt (e21), as an agent change the user approved. No outcome was kept in memory, and the revision has not been used yet, because the next run is on 2 November. Nothing kept in memory on the first day was used on the second, so the trace supports **L0**, although the conditions of L3 and L4 appear in it.

The survey places Grok Bot at L4 from its documentation. The two readings answer different questions. The survey's level says what the product is documented to do. The trace's level says what this slice of logged behavior shows, and it is a lower bound. This slice started after the routine and its research topics were set up, so the state the routine carries from day to day never appears in it as something remembered in one session and used in a later one.

The test also showed a gap in our instructions. The bot logged two choices inside the scheduled run, switching sources and choosing papers, with trigger `self`. Under the survey's definition these are requested: the user scheduled the run, and the bot only chose how to do it. We have since made the definition explicit in the tool descriptions and the [agent instructions](/HALO/connect/instructions/). Under it, those actions are `request`, and the L3 condition is not observed in this trace.
