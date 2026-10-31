---
title: Muse
description: Connect Meta's Muse to HALO over plain HTTP, through a custom connector that Muse builds itself.
---

Meta's documentation for Muse does not mention MCP. Muse has its own computer, with a file system, a terminal, and a full web browser ([How We Designed Muse](https://introducing.muse.ai/)), and when asked in chat, it creates a custom connector for a service that has an API ([Meta Help Center](https://www.meta.com/help/artificial-intelligence/1687253048996149/)). HALO's [HTTP address](/HALO/reference/http/) is such an API, and `GET /guide` explains it in plain text, so Muse can read the guide and build its own connector to HALO. A [third-party guide](https://parallel.ai/articles/meta-muse-custom-integrations) reports that Muse can also connect a remote MCP server this way, which we have not tried.

Muse runs in Meta's cloud, so HALO needs a public address, set up as for [ChatGPT dots](/HALO/connect/chatgpt-dots/).

## Connect

1. Start the plugin behind a tunnel, as for ChatGPT dots. The server prints the plain HTTP address next to the MCP address, `https://HOST/<token>/events`, with the guide at `https://HOST/<token>/guide`.
2. In a Muse chat, ask Muse to build the connector:

```text title="Message to Muse"
Create a custom connector for HALO, a service that records the steps of your own work. How to use
it is at https://HOST/<token>/guide, and it needs no credentials. Then, from now on in this chat, log
each step of your work to HALO while you do it, with agent "muse" and one session label per
conversation. Log only what really happened, and leave out secrets and private text.
```

3. Muse may ask you to approve the connector's requests before it sends them.

## Test

This case has not been run yet. To test it, give Muse one small task, as in [the Claude test](/HALO/connect/claude/), and read the report at `GET /report?agent=muse`.
