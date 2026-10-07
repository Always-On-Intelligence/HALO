# ProAct in HALO run mode

ProAct (Anticipate and Learn: Unleashing Idle-Time Compute in Proactive Agents; AgentACE-AI/ProAct at
commit 7ac78fd) uses the time between user messages. Future-State Prediction (FSP) predicts what the user
will need next; Idle-Time Exploration (ITE) searches for it, stores what it finds in memory, and a delivery
policy decides whether to push it to the user now. The survey reviewed "Directed Idle: full Future-State
Prediction plus Idle-Time Acquisition and delivery policy with the persistent memory layer", which the
paper calls Full-single-idle.

## What runs

Each item is a short day for one ProActEval scenario: a morning message, an idle gap of hours, and a later
message. The adapter drives the upstream `ProactiveBenchAdapter` the way `ProactiveBenchRunner.run_single`
does (`experiments/ProactiveBench/eval/runner.py:182-428`):

1. `run_ablation_turn(turn)` (`eval/adapter.py:396-597`): FSP (`fsp_module.py`: memory critic, research
   predictor, value evaluator, cold-start cap) fills the intent queue; when the idle time reaches the
   trigger, ITE (`ite_module.py`) searches the queued intent through `SearchService.search`, admits the
   results to memory, scores the push with `PushScoreAgent`, and applies the direct-push gates.
2. A direct push is recorded with `record_direct_push` (`eval/adapter.py:614-619`), as the runner does.
3. `send_message(text)` (`eval/adapter.py:621-661`) runs `ChatHandler.handle`
   (`server/handlers/chat_handler.py:146-291`): topic monitor, planning with memory context, reactive
   search when memory is insufficient, the reply, and the incremental profile extraction.

Condition and limits follow the README/RUN_COMMANDS command: `Full-single-idle`, `max_queries_per_search=1`,
`max_intents_per_idle=3`, `idle_trigger_seconds=5`, `max_total_searches=999`, seed 42, and the adapter's own
config (in-conversation prediction and deep research off). The scripted messages replace the LLM user
simulator, and the HALO judge replaces the coverage judge.

## Replacements

| Upstream | Replacement |
|---|---|
| `tools/llm_client.py` `LLMClient` (OpenAI: gpt-4o for assistant, memory critic and search planner; gpt-4o-mini for the rest) | subclass whose `chat()` sends every call to the HALO backbone; `chat_json()` and its JSON parsing are upstream's. No JSON response mode; temperature, seed and `max_tokens` are not passed on. |
| chromadb's default embedding function (ONNX all-MiniLM-L6-v2, downloaded by chromadb on first use) | chromadb's `SentenceTransformerEmbeddingFunction` with the locally cached all-MiniLM-L6-v2 on CPU, normalized, for the memory vector store and the external fact store; chromadb telemetry off |
| simulated idle seconds (`adapter._idle_rng`: 1-3 s for turns 1-2, 5-10 s later; `eval/adapter.py:405-409`) | the scripted gap between the two messages (hours), so ITE runs in the idle period before the second message. With the upstream draw, ITE would first run before a third message. |
| `load_dotenv()` (`core/config.py:14`) | no-op, so no `.env` file is read; API-key variables are removed from the worker's environment |
| storage in `experiments/ProactiveBench/runtime` | a temporary folder under `cases/proact/.work`, deleted after each run |

## Cut sites (receiving end)

| Channel | What is withheld | Sites |
|---|---|---|
| S->M | memory admits nothing sensed | the session buffer drops the user's message (`MemorySystem.add_message`, `memory/memory_system.py:614`, called at `chat_handler.py:236`); acquired search results are not admitted (`submit_update` of `ADD_KNOWLEDGE`, `services/search_service.py:346` -> `memory_system.py:393`), for idle-time and reactive searches; the incremental extraction (`chat_handler.py:849-953`) gets the turn without the user's message |
| M->A | Action reads an empty memory | FSP inputs (`eval/adapter.py:430-432`; `fsp_module.py:316-317, 349-350, 384, 414`), the push scorer's interests and context (`ite_module.py:266-268, 334`), the planner's memory context (`agents/planning_agent.py:61`, handed to the reply at `chat_handler.py:272-276`) and the reply's profile (`agents/assistant_agent.py:62-63`) all receive what an empty memory returns |
| A->S | acquisition gets no target | `SearchService.search` (`services/search_service.py:105`) receives an empty topic and purpose instead of the FSP intent (`ite_module.py:224-233`) or the planner's query (`chat_handler.py:247-250`); the search planner then plans from the profile alone |
| M->S | Sensing gets no memory | the topic monitor gets no current topic, history or stored topics (`chat_handler.py:222-228`, `agents/topic_monitor.py:37`); the search planner gets no user profile (`services/search_service.py:133-137`, `agents/search_planner.py:37`) |
| A->M | memory admits nothing the assistant did | the session buffer drops replies and direct pushes (`chat_handler.py:279`; `eval/adapter.py:614-619`); the incremental extraction gets the turn without the reply (`chat_handler.py:849-953`); ITE keeps no delivery record (`ite_module.py:419-438`) |

The M->A cut hands each Action component a view of memory whose reads return what an empty memory returns
(`"No relevant memory available"`, an empty profile, an empty session); writes pass through. ProAct does not
revise its own mechanism (memory holds knowledge, profile, facts and conversation records), so no evidence
step is cut. Each day has one idle period, so ITE's delivery record (A->M) is not read again within an item.

## Inputs

`inputs/days.json`: five scenarios (`health_medication_routine_01`, `relocate_city_01`,
`rent_move_in_logistics_02`, `parent_school_week_01`, `travel_business_02`). The morning message names the
situation without asking for a fact; the later message asks for a need that the scenario marks as
predictable from it. The judge sees the profile, both messages with their times, and the scenario's true
facts for the later need.

## Judged output and metrics

- `output`: any unprompted note from the idle period, the later message, and the reply.
- Metrics: `pushed`, `idle_intents`, `idle_facts_stored`, `reply_searched` (reactive search in the later
  turn), `key_fact_recall` (share of each true fact's content words found in the note plus the reply; a
  lexical check, not ProActEval's coverage judge), `backbone_calls`.

## Run

```bash
uv venv cases/proact/.venv -p 3.11 && uv pip install -p cases/proact/.venv/bin/python -r cases/proact/requirements.txt
cd HALO && HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  HALO_CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/proact --items 1 --samples 1 --workers 2 --name smoke
```

Backbone calls per arm: 18 to 37 in the smoke run (original 34). Most come from `SearchService`: one summary
call per retrieved source (`services/search_service.py:321-346`), and a "comprehensive" search plan adds
three queries (`search_service.py:258-259`), so one search can summarize up to 12 sources. FSP adds one
evaluator call per candidate intent (up to six). Calls that are identical across arms come from the cache.

## Smoke result (med_day, 1 sample)

| cut | judge | metrics (original -> cut) |
|---|---|---|
| S->M | original | facts stored in idle 6 -> 0; key-fact recall 0.48 -> 0.34 |
| M->A | original | FSP produced no intent, nothing stored in idle; recall 0.48 -> 0.34 |
| A->S | cut | idle 6 -> 0 facts; recall 0.48 -> 0.51 |
| M->S | cut | direct push 0 -> 1; recall 0.48 -> 0.79 |
| A->M | cut | direct push 0 -> 1; recall 0.48 -> 1.00 |

In the original arm the morning message already triggered a reactive search, and the reply named the
medication. During idle, FSP's memory critic asked for the prescription instructions; ITE stored six facts but
did not push them, because the delivery gate found them overlapping the assistant's earlier reply. The lunch
reply then missed the missed-dose rule. Under A->M the session holds no assistant lines, so FSP predicted from
the user's message alone and the gate let a push through that contained the missed-dose rule. Under M->S
the topic monitor renamed the topic, which changed the critic's input. Under A->S the search planner,
given no topic, planned broadly from the profile; in this closed-world fact store any broad search returns
the user's own facts. One sample does not separate these effects from sampling noise.
