---
title: Grok Bot
description: Add HALO to Grok Bot as a custom MCP server.
---

Grok Bot runs on its own cloud computer, and its desktop and mobile apps are clients for chat and approvals. Like a dot, it cannot reach `localhost`, so start HALO behind a tunnel first, as in [ChatGPT dots](/HALO/connect/chatgpt-dots/#1-give-the-server-a-public-address).

## Add the server in chat

Grok Bot has no settings field for a server address. You add a custom MCP server by asking for it:

```text
Add a custom MCP server called HALO at https://<name>.trycloudflare.com/<random>/mcp
```

Say "custom server" or "custom MCP server", or the bot may look for a catalog plugin with the same name instead. The bot shows the name and address and asks you to confirm. HALO needs no authentication, so no connect card follows, and the bot reports the number of tools it found, nine for HALO.

Then attach HALO to a task by typing `@` in the chat and picking it, and give the bot the [agent instructions](/HALO/connect/instructions/). Custom servers are listed under **Settings**, **Plugins**, **Yours**, and they are available to every bot on the account.

:::note
These steps follow a third-party guide from September 2026 and have not yet been checked against HALO. If a team admin restricts plugins, the address must be on the team's MCP allowlist.
:::
