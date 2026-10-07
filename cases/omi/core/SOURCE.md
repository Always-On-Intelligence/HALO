# Vendored Omi backend code

- Repository: https://github.com/BasedHardware/omi (sparse checkout of `backend/`)
- Commit: 5a46ab0467ce594c35fd04d72131421afd747259 (2026-10-07)
- License: MIT (`LICENSE`, copied unchanged)

158 files under `backend/`, copied unchanged at their upstream paths (byte-identical to the pinned
checkout). They are the module-level import closure of the four entry points below, minus the modules
that `omi_harness/fakes/` replaces (storage, model clients, delivery, executors) and the infrastructure
modules that are inert stubs (see the README). Files marked (i) are only imported in this run: their
module code (constants, enums, pydantic models, tool schemas) runs, none of their functions is called
by the scripted inputs.

| Path | Role in the run |
|---|---|
| `utils/app_integrations.py` | entry for live segments: `trigger_realtime_integrations`, mentor admission and rate limits, gate -> draft -> critic orchestration, context gathering (facts, goals, earlier notifications, vector and recent past conversations), delivery and write-back of the notification |
| `utils/mentor_notifications.py`, `utils/mentor_admission.py` | segment buffer that decides when the mentor evaluates; paid-plan admission |
| `utils/llm/proactive_notification.py` | the mentor's gate, draft and critic prompts and output models |
| `utils/notification_dispatch.py` | notification policy before the FCM transport (the transport is faked) |
| `utils/llms/memory.py` | user facts for prompts (`get_prompt_memories`) |
| `utils/conversations/process_conversation.py` | entry at conversation end: `process_conversation` (relevance, notes, persistence, vector metadata, memory extraction, task write-back, goal progress) |
| `utils/conversations/{relevance,relevance_rules,relevance_io,processing_trigger,duration,recovery,projection_payload,deterministic_minimum,subjects,owner_attribution,transcript_for_llm,wake_word,notes_task_context,summary_selection,episode_vacuity,memory_extraction_telemetry,action_item_identity}.py`, `utils/conversations/meeting_participants.py` (i) | keep/discard rules, transcript rendering with the speaker map, owner attribution, open-task lookup for extraction, task identity on write |
| `utils/llm/{conversation_processing,conversation_notes_prompts,conversation_prompt_context,conversation_prompt_prefix,meeting_notes_presentation,meeting_notes_validation,notes_observability,action_item_normalization,shaped_agent,prompt_cache,model_config,temporal}.py`, `utils/llm/{meeting_notes_rich_prompts,discard_parser,gateway_error_contract}.py` (i) | notes v2: one structured-notes call (title, overview, sections, tasks, events) and its presentation checks |
| `utils/llm/memories.py`, `utils/llm/working_observations.py` | canonical L1 memory extraction from the transcript |
| `utils/llm/chat.py` | vector metadata extraction for a stored conversation; the chat agent's system prompt |
| `utils/llm/goals.py` | goal progress from conversations and chat (the scripted user has no goals, so it returns early) |
| `utils/memory/{belief_model,decision_path_telemetry}.py`, `utils/memory/belief_source_policy.py` (i) | belief-model flags and capture-decision records used by extraction |
| `utils/task_intelligence/conversation_capture.py` | canonical fields of a written task |
| `database/vector_db.py` | Pinecone logic (ids, metadata, filters, thresholds, ranking); only its `index` handle is replaced |
| `database/document_ids.py` | deterministic document ids |
| `utils/retrieval/{graph,agentic,safety,chat_scope,tool_result_boundaries}.py`, `utils/retrieval/{web_search_gate,memory_evidence}.py` (i) | entry for chat questions: `execute_chat_stream` and the OpenAI-contract agent loop with tool execution |
| `utils/retrieval/tools/*.py` (24 files; `app_tools`, `conversation_tools`, `conversation_jit_gate`, `frame_request_tools` run, the rest (i)) | the core chat tools; their schemas are what the agent sees, and memory, conversation, task and preference tools run when called |
| `utils/conversations/{search,mcp_transcript_search,render,factory}.py`, `utils/chat_followup.py`, `utils/device_tools.py`, `utils/share_links.py`, `utils/journey_metrics_contract.py`, `utils/dev_cache.py`, `utils/release_probe.py`, `utils/jit_first_open_policy.py`, `utils/log_sanitizer.py`, `utils/llm/openglass.py` | keyword search over the conversation index, conversation rendering, follow-up chip parsing, small policies used on the paths above |
| `utils/retrieval/frame_request_{authority,policy,storage}.py`, `utils/conversation_continuity.py`, `utils/integration_telemetry.py`, `utils/other/list_budget.py`, `utils/proactivity_flags.py`, `utils/prompts.py`, `utils/llm/private_context.py` (all (i)) | imported by the modules above |
| `models/*.py` (41 files), `config/*.py` (7 files) | pydantic models and constants (data definitions) |
| `__init__.py` files of `config`, `models`, `utils`, `utils/llm`, `utils/memory`, `utils/retrieval/tools`, `utils/task_intelligence` | package files |

Not copied: every other backend module. In particular the Firestore modules under `database/`, the
model clients (`utils/llm/clients.py` and the gateway modules), the canonical memory service
(`utils/memory/memory_service.py` and the ledger), the listen websocket and pusher (`routers/`), the
FastAPI chat router (`routers/chat.py`, whose send-message sequence the adapter reproduces), audio
speaker resolution, and all telemetry, billing and rollout modules.
