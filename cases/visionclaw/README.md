# VisionClaw in HALO run mode

VisionClaw (Intent-Lab/VisionClaw, commit 82699ec, paper arXiv 2604.03486) is an always-on assistant for
Meta Ray-Ban glasses. The survey reviews it as a "Composed Gemini Live + OpenClaw system with connected
personal stores and delegated tools".

## What the code is at this commit

The paper describes Gemini Live on the phone with one `execute` tool routed to a local OpenClaw gateway. At
the pinned commit the same composition is split across three processes, and OpenClaw's role is served by a
hosted gateway that speaks the OpenClaw protocol in front:

- the phone app streams glasses video and audio into a LiveKit room (`samples/`, Swift and Kotlin);
- the voice worker, `agent/main.py` (Python), joins the room with a realtime model (Gemini Live by default)
  and the tools `execute`, `browse`, `quick_search`, `show_card`, `save_note`, `recall_notes`, `delete_note`;
- the gateway, `gateway/src/*.ts`, runs each delegated task as an Anthropic Managed Agents (CMA) session turn
  with the user's connected apps (Google Calendar through google_workspace_mcp, Notion, Slack, Gmail) as MCP
  tools, and keeps the user's notes, a task ledger that briefs the next call, and parked results that the
  next call relays when a task outlives its call.

The OpenClaw project itself is not in the repository. Run mode runs what is: the worker and the gateway.

## Always-on core

- Stream and requests to the agent: video frames reach the realtime model (1 fps while the user speaks);
  speech is the user turn. `execute(task, attach_view)` sends the task, and the current frame when the voice
  model judges it relevant (`main.py:822-840`), to `POST /v1/chat/completions` (`server.ts:139-324`), which
  runs one CMA turn with the image block and any queued context (`turn.ts:54-94`).
- Personal stores read and written: notes (`/notes`, `server.ts:529-589`) through `save_note`,
  `recall_notes`, `delete_note`; the task ledger (`recordTask`, `server.ts:72-82`), read into a briefing for
  the next call's first task (`server.ts:430-434`, `turn.ts:338-350`); parked results (`notify.ts:62-81`); the
  connected apps, through the action agent's MCP tools.
- Delegated results return as the tool result of `execute` (`_gateway_execute`, `main.py:382-398`), or, when
  the caller is gone, parked at the gateway (`server.ts:291-299`) or by the worker (`main.py:401-421`) and
  relayed at the start of the next call (`main.py:1260-1330`).

## What runs and what is replaced

| Component | In run mode |
|---|---|
| gateway (`core/gateway/src`) | executed unchanged under node 24 + tsx, one process per call, store file kept across calls |
| voice worker (`core/agent/main.py`) | imported unchanged; `entrypoint` and the tool functions run as in a call |
| `gateway/src/cma.ts` (Managed Agents client) | `shim/cma_stub.mjs` via a resolve hook (`shim/hooks.mjs`); every call goes to the adapter's bridge |
| CMA sessions and agent turns | the bridge: agent, vault and session bookkeeping; each turn is backbone calls with the gateway's `AGENT_SYSTEM_PROMPT` and a JSON tool protocol |
| connected apps (MCP) | simulated Google Calendar (`get_events`, `create_event`, `modify_event`, `delete_event`) and Notion (`notion-search`, `notion-fetch`, `notion-create-pages`, `notion-update-page`) over the item's stores; the CMA agent toolset (bash, files, web) is not offered; Slack disabled, Gmail not configured |
| Gemini Live inside `livekit.agents.AgentSession` | a fake AgentSession: each model turn is a backbone call with the worker's `INSTRUCTIONS`, tool declarations built from the worker's tool functions, the call's conversation and the latest frame as text; the adapter runs the tool functions it calls |
| LiveKit room, participant, media | fakes; frames and speech are scripted text; `encode_latest_frame` returns the frame description |
| `quick_search` (Gemini grounded search) | backbone call without web access |
| Browser Use (`browse`) | disabled, as without `BROWSER_USE_API_KEY` |
| phone app | the adapter posts `/livekit-token` at each call start, as `LiveKitSession.fetchTicket` does |

Timing and environment, all documented in `adapter.py`:
- `QUICK_ANSWER_S` (`main.py:350`) is raised and the worker's gateway HTTP timeouts are lifted, so a delegated
  result always returns inside its turn; the hang-up item ends the call explicitly instead.
- The gateway's clock reads the scripted call time (`shim/clock.mjs`), so notes, ledger and briefing texts are
  identical across arms.
- The store's temp-file writes are serialized (`shim/serial_store.mjs`). `saveStore` always writes
  `<store>.json.tmp` (`store.ts:99-105`); overlapping saves race on it. On the hang-up path two un-awaited saves
  start together (`server.ts:289` and `295`), one rename fails, and node exits on the unhandled rejection;
  at call start the drain and the app check collide the same way. Without the serializer, arms would differ
  by IO timing. This is an upstream race, reported here, not a run-mode change of logic.

## Cut sites

| Cut | Site (file:line in `core/`) | What is withheld |
|---|---|---|
| S->M | `main.py:547-578` -> `server.ts:529-548`; simulated app writes | notes from `save_note` never reach the store (answered 201); calendar and Notion writes by the action agent are not kept |
| M->A | `main.py:581-600` -> `server.ts:550-561`; `main.py:444-456, 1260`; `server.ts:433` -> `turn.ts:75-85`; simulated app reads | `recall_notes` gets no notes; no parked results are drained; the task-ledger briefing is dropped from the action agent's turn; calendar and Notion reads return nothing |
| A->M | `server.ts:72-82, 289, 291-299`, `notify.ts:62-71`; `main.py:407-421` | the task ledger and parked results written during a call are cleared before the next call (the gateway restarts per call, so no reader sees them); the worker's own parking is not stored |
| A->S | `main.py:822-840` -> `server.ts:242` -> `turn.ts:65-74` | the frame attached by `execute(attach_view=True)` does not reach the action agent |

Within-call context (the realtime model's conversation and the action agent's session history in the same
call) is working context and is not cut. M->S is not realized: frame sampling and attachment do not read
retained state. VisionClaw does not revise its own mechanism, so no evidence step is cut.

## Inputs

`inputs/days.json` holds four scripted days. Each is one user over two calls with personal stores:
- `conference_poster`: a talk from a poster goes into the calendar through `execute` with the frame attached,
  a badge number goes to notes; the second call asks for both.
- `pharmacy_label`: dosing instructions from a label go to notes, a refill reminder goes into the calendar;
  the next evening's call asks for both with no label in view.
- `hardware_store`: the user asks to save a bulb box to a Notion page and hangs up while the task runs; the
  gateway parks the result and the next call relays it, then answers a follow-up.
- `grocery_list`: shopping-list notes added from the fridge and pantry, recalled and edited at the store.

## Outputs

`output` is the final call's transcript (user turns, spoken replies, cards on screen). The judge sees the
user, connected apps, the stores before the first call, every call's camera views and requests, and the facts
the final call should get right. Metrics: `final_facts_stated` (share of expected facts in the final call's
speech and cards), `notes_saved`, `app_writes_attempted`, `app_writes_kept`, `ledger_entries`,
`parked_relayed`, `delegated_turns`, `frames_attached`, `voice_model_calls`, `agent_calls`. Results also carry
all calls' transcripts, the action agent's turns (task, attached frame, context, tools, reply) and the stores
after the day.

## Run

```bash
uv venv cases/visionclaw/.venv -p 3.11 && uv pip install -p cases/visionclaw/.venv/bin/python -r cases/visionclaw/requirements.txt
(cd cases/visionclaw && npm ci)        # the gateway's pinned packages, from the upstream package-lock.json
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex \
PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/visionclaw --items 1 --samples 1 --workers 2 --name smoke
```

`HALO_NODE_BIN` overrides the node binary (default: `node` on PATH, else `~/.local/bin/node`). Set
`HALO_VISIONCLAW_KEEP=1` to keep each run's store, gateway log and traces in the temp dir. All traffic is
local: the gateway, the bridge and the worker talk over 127.0.0.1; only the backbone leaves the machine.
