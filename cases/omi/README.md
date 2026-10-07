# Omi in HALO run mode

Omi (BasedHardware/omi) is a wearable pendant with a personal backend. The pendant streams audio; the
backend transcribes it, labels who is speaking with the user's enrolled speech profile and stored people,
turns each finished conversation into notes, tasks and memories, runs the built-in proactive
notification app (the "mentor") while a conversation is going on, and answers questions in an agentic
chat that retrieves the user's memories and conversations. Configuration reviewed by the survey
(`case.yaml`): wearable capture with enrolled speech profile, retained personal backend, authorized
agentic chat tools and a proactive-notification app; rollout-gated desktop JIT features excluded.

## What runs

The upstream backend code in `core/backend/` (158 files, unchanged; see `core/SOURCE.md`), driven by
`adapter.py` through three entry points, in scenario time:

| Event | Upstream entry | What happens |
|---|---|---|
| each transcribed segment | `utils/app_integrations.trigger_realtime_integrations` (as `routers/pusher.py:135` calls it) | the mentor buffers segments; after 10 new messages it admits an evaluation and runs gate -> draft -> critic with the user's facts, goals, earlier notifications and past conversations; an approved notification is delivered and written to the mentor's chat |
| end of a conversation (after 120 s of silence) | `utils/conversations/process_conversation.process_conversation(trigger=CAPTURE_END)` | relevance rules, notes v2 (one call: title, overview, tasks, events, given related open tasks), persistence, vector metadata call and conversation vector, canonical memory extraction (one call), task write-back |
| chat question | `routers/chat.py` send-message sequence (lines 446-600), reproduced in `Adapter._chat` around `utils/retrieval/graph.execute_chat_stream` | the human turn is stored, the cache-aligned history read, the agent loop (`utils/retrieval/agentic.py`) calls the upstream tools (conversation search, memories, tasks, preferences, ...) and answers; the answer is stored |

A finalization that raises (the notes reply cannot be parsed) is retried up to three times, as the
durable finalization job would, each time as a fresh model sample.

## Replacements

- **Model clients** (`utils/llm/clients.py`, fake in `omi_harness/fakes/utils/llm/clients.py`): every
  `get_llm(feature)` is a LangChain chat model (`omi_harness/llm_bridge.py`) that sends the rendered
  messages to the HALO backbone (`self.llm`), tag `item|sample|stage|feature`. Ported because the
  backbone is text in, text out: OpenAI structured output (the pydantic JSON schema is appended to the
  prompt and the reply validated, with one repair turn) and OpenAI function calling for the chat agent
  (the tool schemas are appended; a reply `{"tool_calls": [...]}` becomes `AIMessage.tool_calls`).
  Upstream prompts, parsers and loops are unchanged.
- **Embeddings**: text-embedding-3-large -> all-MiniLM-L6-v2 (CPU). A long query (a whole transcript in
  `find_similar_action_items` or the mentor's past-conversation search) is also embedded per ~40-word
  window and scored by its best window, because MiniLM reads only 256 word pieces where the upstream
  model reads 8k tokens; upstream thresholds (0.6 for related open tasks) are applied unchanged.
- **Storage**: Firestore modules under `database/` are function-level fakes over an in-memory store
  (`omi_harness/store.py`): users and people, notification settings, goals, chat and app messages,
  conversations, tasks, Redis keys, the TTL cache. The canonical memory service
  (`utils/memory/memory_service.py`) is a fake that keeps the rows extraction writes and returns them to
  reads at once (upstream short-term promotion, ledger and consolidation do not run). The
  conversation-lifecycle transactions (`utils/conversations/lifecycle.py`) write to the store.
  `database/vector_db.py` runs unchanged over an in-memory Pinecone index (`omi_harness/pinecone_fake.py`);
  `utils/conversations/search.py` runs unchanged over an in-memory Typesense client
  (`omi_harness/typesense_fake.py`, prefix word match on title and overview).
- **Speech**: scripted transcripts (`inputs/days.json`). Each segment has a diarization cluster and the
  scripted result of the voice match (`voice`: the enrolled user, a stored person, or nobody), which the
  adapter applies to the segment as `routers/listen/transcripts.py:1339-1350` does.
- **Delivery and threads**: FCM delivery is recorded (`fakes/utils/notifications.py`); thread pools run
  inline in submission order (`fakes/utils/executors.py`).
- **Plan, rollout and integrations**: the user is on a paid plan (mentor admitted, no paywall), has no
  marketplace apps, folders, goals, calendar or Google integration, and is not in the desktop JIT
  rollout (`fakes/utils/{subscription,managed_compute,apps,jit_rollout}.py`, `fakes/database/folders.py`).
  LangSmith is unreachable, so the chat uses the inline system prompt that upstream ships for that case.
- **Stubs**: any other upstream module a vendored module imports (telemetry, metrics, billing, shadow
  evaluations, audio speaker resolution, meeting context, task sync, webhooks) is an inert placeholder.
  Calls into placeholders are counted per run in `stub_calls`; all observed calls are no-ops in this
  configuration (no speaker-resolution rewrite is needed because scripted clusters are already
  conversation-scoped; meeting context is absent because no calendar is connected).
- **Network**: outbound connections are refused inside the worker (`omi_harness/netguard.py`); the
  backbone runs in its own subprocess. A web tool the agent might call (fetch_url, Perplexity) returns
  upstream's tool error.
- **Determinism**: vendored modules see a scenario clock (`datetime.now`, `time.time`) and per-call-site
  deterministic `uuid4`, so arms build byte-identical prompts until a cut changes one.
- Flags set: `CONVERSATION_NOTES_V2_ENABLED=true` (production since 2026-09-01), `MENTOR_PIPELINE=legacy`
  (default). Not reproduced: speaker identification from audio, folder assignment (one more call per
  conversation; the user has no folders), the external task sync and webhooks.

## Cut sites

Each cut withholds the channel where the receiver reads it or where the store is written (upstream
`file:line` of the withheld call; the fake that implements it in parentheses):

| Cut | Site |
|---|---|
| S->M | processed conversation `utils/conversations/process_conversation.py:3157` (lifecycle fake); conversation vector `process_conversation.py:2365` -> `database/vector_db.py:151` (Pinecone ns1 upsert); extracted memories `process_conversation.py:2053` (memory-service fake); human chat turn `routers/chat.py:513` (`Adapter._chat` -> chat fake) |
| M->A | reads made while the mentor or the chat agent decides return nothing: facts `utils/app_integrations.py:785` -> `utils/llms/memory.py:205`; goals `app_integrations.py:791`, `utils/llm/chat.py:593`; earlier notifications `app_integrations.py:802`; past conversations `app_integrations.py:851-864` (`vector_db.py:247`); chat history `routers/chat.py:524-528`; chat tools `memory_tools.py:269,443`, `conversation_tools.py:322,613,618`, `action_item_tools.py:270` |
| A->S | open tasks do not reach the extraction of a new transcript: `database/vector_db.py:988` (Pinecone ns4 query while Sensing), read by `utils/conversations/notes_task_context.py:33` for the notes prompt at `process_conversation.py:758` |
| M->S | the enrolled speech profile and stored people are not applied: speaker labels (`routers/listen/transcripts.py:1339-1350`, `Adapter._segments`) and `get_people_by_ids` at `process_conversation.py:3077`, `utils/llm/memories.py:185` |
| A->M | action records are not written: mentor notification `utils/app_integrations.py:1187` (`add_app_message`); chat answer `routers/chat.py:595`; extracted tasks `process_conversation.py:2218` and `vector_db.py:908`; chat-tool writes `action_item_tools.py:467`, `preference_tools.py:148` |

Omi does not revise its own mechanism in this configuration, so no evidence step is cut. Each run
reports `withheld` (how often each site fired) and `stub_calls`.

## Inputs

`inputs/days.json`: one user (Alex, Pacific time, people Maya, Sam, Jordan, Priya) and five two-day
items. Each item has two conversations (12 or 8 segments, over 100 words so the relevance rules keep
them without a model call) and one or two chat questions; the second day contains a conflict with, or a
follow-up on, the first (shellfish allergy vs. a sushi booking, a dentist slot vs. a meeting, a running
limit vs. a trail run, a reply deadline and salary misremembered, a reminder created in chat). About
10-14 backbone calls per arm.

Outputs: `output` (notifications pushed and chat answers; judged for S->M, M->A, A->M), `output_tasks`
with `context_tasks` (tasks created on the last day vs. tasks already open; A->S), `output_capture` with
`context_capture` (notes, tasks and facts per conversation; M->S). Metrics: notifications, repeated
notifications (MiniLM >= 0.75), chat keyword hits, memories written, tasks and duplicate tasks on the
last day, backbone calls, failed conversations.

## Run

```bash
uv venv cases/omi/.venv -p 3.11 && uv pip install -p cases/omi/.venv/bin/python -r cases/omi/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=... PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/omi --items 1 --samples 1 --workers 2 --name smoke
```
