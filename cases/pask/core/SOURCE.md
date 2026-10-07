# Vendored PASK code

- Repository: https://github.com/xzf-thu/Pask
- Commit: d54646c52b1555232ce4ab39103768d7f65b8267
- License: the repository's `LICENSE` file is Apache-2.0 (copied unchanged); its README states CC BY-NC-SA 4.0.

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `bench/03c_memory.py` | `run()`, `MEMORY_SYSTEM`, `build_memory_prompt`: writes the memory document for a later part from the earlier part (the memory field of LatentNeeds-Bench) |
| `bench/llm_client.py` | `AsyncLLMClient.complete` / `complete_json` used by the memory writer; `_pick_credentials` imported by `eval/run.py` |
| `eval/run.py` | `build_tasks`, `eval_model`, `call_one`, `parse_response`: the per-turn demand-detection loop |
| `eval/prompts.py` | `build_prompt`, `SYSTEM_PROMPTS` (neutral level), `CATEGORY_HINTS`: the demand-detection prompt (scene, memory, dialogue so far, current turn) |
| `eval/config.py` | `NO_DEMAND_TOKEN`, `MODELS` |
| `eval/__init__.py` | package file (empty) |

Not in the repository, so not run: the IntentFlow Demand Detector and MemLoader weights, Pask-MM's
user/workspace/global store and its post-session maintenance, the `<full_assistance>` retrieval path,
and the PAS runtime. Not copied: the other benchmark-construction steps (`bench/01*` to `bench/06*`,
which filter, split, rewrite and annotate recorded sessions), the offline scorer `eval/score.py`,
`eval/report.py`, the result files, `latex/`, and `docs/`.
