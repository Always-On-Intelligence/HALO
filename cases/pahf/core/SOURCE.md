# Vendored PAHF code

- Repository: https://github.com/facebookresearch/PAHF
- Commit: 7a11213360a82d5f437a035e3a31c92d6307f8cf
- License: MIT (`LICENSE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `agents/base.py` | `BasePersonalAgent`: memory retrieval and summary for the action prompt (`retrieve_memory_context`), the pre-action clarification loop and its Q&A memory note (`handle_pre_feedback`), action parsing |
| `agents/embodied_agent.py` | `EmbodiedAgent`: `run_study` -> `run_exp` -> `get_test_predictions`, the per-task loop (ground truth, retrieval, action, clarification, post-action feedback, feedback-to-memory update) |
| `memory/banks.py` | `SQLiteMemoryBank` (per-person rows in one SQLite file) and the `DragonPlusEmbedding` class that the adapter replaces |
| `memory/utils.py`, `memory/__init__.py` | `simple_memory_retrieval` and the memory helpers |
| `prompts/embodied_prompts.py`, `prompts/__init__.py` | all prompts of the embodied agent (also imported by `memory/utils.py`) |
| `utils/agent_utils.py`, `utils/json_utils.py`, `utils/__init__.py` | `initialize_memory_banks`, `get_mc_dataset` (option generation), `process_mc_raw` |
| `data/embodied/personas/original_persona.py`, `evolved_persona.py`, `__init__.py`; `data/__init__.py`, `data/embodied/__init__.py` | persona prompts of the simulated users (both persona files are imported by `embodied_agent.py`; only the original ones are used) |
| `data/embodied/scenarios/original_scenarios_A.json`, `original_scenarios_B.json` | PAHF's phase-1 (learning) and phase-2 (evaluation) tasks; the items pick tasks from these files |

How the copied code is loaded:

- `memory/banks.py` does not parse at this commit: `FAISSMemoryBank` has an IndentationError (lines 580-581
  and 639-650). The adapter executes the unchanged lines 1-413 of the file (everything before
  `class FAISSMemoryBank`) as module `memory.banks` and adds a `FAISSMemoryBank` placeholder that raises.
  The SQL configuration never constructs it.
- `agents/__init__.py` is not copied: it imports the shopping agent as well. The adapter registers the
  `agents` package path directly and imports `agents.embodied_agent`.

Not copied: `utils/llm.py` (the OpenAI client; the adapter installs a stub module `utils.llm` whose
`LLMClient` calls the HALO backbone), `run_agent.py` (the adapter calls `EmbodiedAgent.run_study` the way
`run_full_study` does for phases 1 and 2, with `run_embodied_agent`'s defaults), the shopping agent, its
prompts and data, the evolved scenarios (phases 3-4), `agents/shopping_agent_old.py`, and the teaser image.
