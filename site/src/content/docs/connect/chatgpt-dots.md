---
title: ChatGPT dots
description: Add HALO to ChatGPT as a personal plugin from a custom MCP server and let a dot use it.
---

A dot is ChatGPT's always-on agent. It runs in the cloud and can use the plugins installed and enabled for your account. HALO becomes such a plugin when you add it as a custom MCP server.

## 1. Give the server a public address

A dot runs in OpenAI's cloud, so it cannot reach `localhost`. Start the plugin behind a tunnel. With a Cloudflare quick tunnel, which needs no account:

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

Note the `https://<name>.trycloudflare.com` address it prints, then start HALO with that host name:

```bash
halo serve --http --port 8765 --public-host <name>.trycloudflare.com
```

```text
HALO plugin URL: https://<name>.trycloudflare.com/<random>/mcp
```

The random path segment keeps the server private to whoever has the full address. Every other path returns 404. A quick tunnel gets a new name each time it starts, so the plugin's address changes with it. A named tunnel or your own HTTPS host keeps it fixed.

## 2. Add HALO as a custom MCP server

1. Open [chatgpt.com/plugins](https://chatgpt.com/plugins), choose **Add**, then **Add custom MCP server**.
2. Name it `HALO`, paste the plugin URL, and set authentication to **No authentication**.
3. Read the risk notice, confirm it, and choose **Create as plugin**. ChatGPT connects to the server and lists its tools.
4. In the **Connect HALO** dialog, choose **Connect**. The dialog says that ChatGPT may share relevant memories and chat content with the plugin.

HALO now appears under **Personal** on the plugins page.

## 3. Ask the dot to use it

Open the dot's conversation, type `@` and pick **HALO**, then give it the [agent instructions](/HALO/connect/instructions/). A dot that has the instructions in its memory keeps logging in later conversations and in the actions it starts by itself.

## A first test

On 31 October 2026 we connected HALO to a dot that sends a daily countdown to a conference deadline, a reminder the user had set up. We asked the dot to log the most recent run of that reminder and to call `halo_report`. It logged seven events and marked each as logged afterwards, with the actual time:

| Id | Kind | Step | Uses |
|---|---|---|---|
| e1 | observe | the scheduled countdown run starts | |
| e2 | observe | reads the official dates | e1 |
| e3 | recall | looks back for new feedback from the user, finds none | e1 |
| e4 | act | computes the time left and prepares suggestions | e1, e2, e3 |
| e5 | act | sends the countdown | e1 to e4 |
| e6 | outcome | the message tool accepts the send, about e5 | e5 |
| e7 | remember | keeps the dates, the time of the reminder, and the send record | e2, e4, e5, e6 |

The report placed the trace at **L0**. It observed S→A, S→M, M→A, A→S (e6 checks e5), and A→M (e7 keeps e5), and the record and outcome steps. It did not observe M→S, attribution, or a revision. The dot explained why the trace stays low. Everything happened in one session, so nothing shows memory used in a later session, which L1 needs. The reminder was set up by the user, so both actions are logged with trigger `request`, which rules out L3 as well. That is the reading the survey gives a reminder the user scheduled.

A trace from a few days of ordinary use, with the instructions in the dot's memory, is the next step.
