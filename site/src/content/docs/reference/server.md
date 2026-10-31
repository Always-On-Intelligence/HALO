---
title: Server and ledger
description: Transports, addresses, host checks, and the ledger file.
---

## Transports

| Command | Transport | Address |
|---|---|---|
| `halo serve` | stdio | started by the client |
| `halo serve --http` | Streamable HTTP | `http://127.0.0.1:8765/mcp` |
| `halo serve --http --public-host HOST` | Streamable HTTP behind a tunnel or proxy | `https://HOST/<token>/mcp` |

## Options

| Option | Default | Meaning |
|---|---|---|
| `--db PATH` | `$HALO_LEDGER`, else `~/.halo/ledger.sqlite` | the ledger file |
| `--agent NAME` | the client's name | the agent name for every event of this server |
| `--http` | off | serve Streamable HTTP instead of stdio |
| `--host` | `127.0.0.1` | interface to listen on |
| `--port` | `8765` | port to listen on |
| `--public-host HOST` | none | the public host name of a tunnel in front of the server. Turns on the secret path and allows that Host header |
| `--token TOKEN` | `$HALO_TOKEN`, else random | the secret path segment |

## Host and path checks

The server rejects requests whose Host header is not `127.0.0.1`, `localhost`, or the `--public-host`, which protects a local server from DNS rebinding. With `--public-host`, the plugin is served only under `/<token>/mcp`, and every other path returns 404. Keep the token stable with `--token` or `HALO_TOKEN` when a host has the address saved.

## The ledger

The ledger is one SQLite table, `events`, with one row per logged event:

| Column | Content |
|---|---|
| `seq` | the event number, shown as `e<seq>` |
| `ts` | UTC time the event was logged |
| `agent`, `session` | who logged it and in which session |
| `kind`, `summary`, `uses` | the event, its summary, and the ids it used, as JSON |
| `trigger`, `form`, `about`, `target`, `made_by`, `governance` | the fields of acts, outcomes, and revisions |
| `client` | the MCP client's name |

The server only appends. To start a new trace, give the agent a new name or point `--db` at a new file.
