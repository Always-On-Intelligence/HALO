---
title: HTTP API
description: The plain HTTP routes, for agents without MCP and for bridges.
---

The HTTP server that serves MCP also serves four plain routes. They take and return the same events as the [MCP tools](/HALO/reference/tools/) and check them by the same rules. With `--public-host`, every route sits under the secret path, for example `https://HOST/<token>/events`. On a local server they sit at `http://127.0.0.1:8765/events` and so on.

| Route | What it does |
|---|---|
| `POST /events` | logs one event, sent as JSON with `Content-Type: application/json` |
| `GET /events?agent=NAME` | lists the agent's events, oldest first. Optional `session`, and `limit` (default 50, at most 500) |
| `GET /report?agent=NAME` | returns the [report](/HALO/reference/report/) as Markdown. Optional `session` |
| `GET /guide` | returns the instructions for logging over HTTP as plain text, with this server's address filled in |

## Logging an event

```bash
curl -s https://HOST/<token>/events \
  -H 'Content-Type: application/json' \
  -d '{"agent": "muse", "session": "2026-11-01 errand", "kind": "act",
       "summary": "drafted the reply", "uses": ["e3"],
       "trigger": "request", "form": "preparation"}'
```

```json title="Reply, status 201"
{"id": "e4", "agent": "muse", "session": "2026-11-01 errand", "note": "Logged e4 (Action, act). Channels: S→A."}
```

| Field | Needed for | Value |
|---|---|---|
| `agent` | every event | the agent's name, the same every time |
| `kind` | every event | `observe`, `remember`, `recall`, `act`, `outcome`, or `revise` |
| `summary` | every event | what happened, in a few words |
| `uses` | every event that relied on earlier ones | the ids of those events, such as `["e3"]` |
| `session` | optional | a label for the conversation or wake-up |
| `trigger` | act | `request` or `self` |
| `form` | act, optional | `silence`, `communication` (the default), `preparation`, or `execution` |
| `about` | outcome | the id of the act the outcome is about |
| `target`, `made_by`, `governance` | revise | what changed, `agent` or `user`, and `approved`, `bounded`, or `none` |

[Event model](/HALO/architecture/events/) gives the meaning of each field.

## Errors

An event that cannot be stored returns status 400 with `{"error": ...}`, which says what to fix, for example `act needs trigger` or `unknown event id(s) e9`. A body sent without the JSON content type returns 415, and a request with an unknown Host header returns 421.

The routes send no CORS headers, and `POST /events` accepts only a JSON content type, so a web page on another site cannot write to a server running on your machine.
