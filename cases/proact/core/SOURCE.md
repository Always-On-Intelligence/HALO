# Vendored ProAct code

- Repository: https://github.com/AgentACE-AI/ProAct
- Commit: 7ac78fde0524443ebeb9d3173b78498c25625f57
- License: MIT (`LICENSE`, `LICENSES.md`, copied unchanged)

All files are copied unchanged at their upstream paths. They are the import closure of
`experiments/ProactiveBench/eval/adapter.py` (the ProActEval system adapter) with package `__init__` files
bypassed.

| Files | Role in the run |
|---|---|
| `experiments/ProactiveBench/eval/adapter.py` | `ProactiveBenchAdapter`: `reset`, `run_ablation_turn` (Future-State Prediction, then Idle-Time Exploration when the idle time reaches the trigger), `record_direct_push`, `send_message` |
| `experiments/ProactiveBench/eval/fsp_module.py` | `BenchmarkFSP`: memory critic and research-topic predictor propose intents, the value evaluator approves them, pre-filters and the cold-start cap |
| `experiments/ProactiveBench/eval/ite_module.py` | `BenchmarkITE`: searches the queued intents, admits the results to memory, scores push value and cost, applies the direct-push gates and keeps the delivery record |
| `experiments/ProactiveBench/eval/ablation_config.py` | the conditions (`Full-single-idle` = FSP and ITE on) and the deduplicating intent queue |
| `experiments/ProactiveBench/eval/benchmark_search.py`, `external_fact_store.py` | the benchmark's search tool: a chromadb collection holding the scenario's fact sheet |
| `experiments/ProactiveBench/generation/models.py` | `Scenario` and its parts |
| `server/handlers/chat_handler.py` | `ChatHandler.handle`: topic monitor, planning, reactive search, reply, incremental profile extraction |
| `server/dependencies.py` | imported by `chat_handler.py` for a type |
| `agents/*.py` (11 files) | the LLM agents: topic monitor, planning, assistant, memory critic, research predictor and evaluator, push score, search planner, report generator, need predictor (inactive in this condition), base agent |
| `memory/*.py` (6 files) | `MemorySystem`: session buffer, chromadb vector store, SQLite knowledge index, profile and fact stores, conversation records, `MemoryUpdateAgent` (deduplication and merge) |
| `services/search_service.py` | `SearchService.search`: search planning, search, per-source summaries, admission to memory |
| `services/proactive/*.py`, `services/deep_research/*.py`, `services/push_service.py`, `services/report_service.py` | imported by the adapter and the chat handler; in-conversation prediction and deep research are switched off by the adapter's own config |
| `core/config.py`, `core/models.py`, `core/prompts.py` | configuration, data models and all prompts |
| `tools/llm_client.py` | the OpenAI client; the adapter subclasses it |
| `tools/search_tool.py`, `tools/web_fetcher.py` | imported by `server/dependencies.py`; never called (the benchmark search tool replaces them) |
| `experiments/ProactiveBench/data/scenarios/*.json` (5 files) | the ProActEval scenarios used by the items |

How the copied code is loaded:

- The packages `agents`, `core`, `memory`, `server`, `server.handlers`, `services`, `tools`, `experiments`,
  `experiments.ProactiveBench`, `experiments.ProactiveBench.eval` and `experiments.ProactiveBench.generation`
  are registered by path, so their `__init__` files (which import the FastAPI app, the web search tools and
  unused agents) are not copied or run. `services.deep_research` and `services.proactive` keep their
  `__init__` files, which the code imports by name.
- `dotenv.load_dotenv` is replaced by a no-op before `core/config.py` runs, so no `.env` file is read.
- `ProactiveBenchAdapter._build_config` is wrapped only to put storage in a temporary folder under
  `cases/proact/.work` instead of `experiments/ProactiveBench/runtime`.

Not copied: `experiments/ProactiveBench/eval/runner.py` (the adapter reproduces `run_single`'s turn loop,
lines 182-428, with scripted messages instead of the LLM user simulator and without the coverage judge), the
user simulator and coverage judge, the generation pipeline, the MemBench experiments, the FastAPI server and
its scheduler, the remaining 195 scenarios, and the tests.
