# Vendored VisualClaw code

- Repository: https://github.com/UCSC-VLAA/VisualClaw
- Commit: f6de05bb8f03e8ba44ec5ee458961cd70002a6d5
- License: MIT (`LICENSE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `benchmark/visualclawarena/runner.py` | `main`: the arena loop (staging, keyframes, skill and memory injection, scoring, within-day and end-of-scenario evolution, failure buffer); `run_round_with_agent`, `_store_round_memory`, `_prepend_memory` |
| `benchmark/visualclawarena/engines/base.py`, `engines/codex_cli.py`, `engines/__init__.py` | `CodexCliEngine.run_agent`: file-op instructions, workspace snapshot, keyframe attachment, write-block application |
| `benchmark/visualclawarena/work_copy.py` | workspace staging, keyframe staging, update application |
| `benchmark/visualclawarena/access_logger.py` | per-round access log |
| `benchmark/visualclawarena/eval/*.py` | multiple-choice and exec_check scorers |
| `benchmark/skill_wire.py` | `SkillWire`: evolver wiring, memory-to-evolver context, F1/F2 bank hygiene, qa_types sidecar |
| `benchmark/vlm_client.py` | imported by `runner.py`; its clients are only used by the `single` backend, which this run does not use |
| `benchmark/__init__.py`, `benchmark/visualclawarena/__init__.py` | package files |
| `visualclaw/modules/skill/manager.py`, `evolver.py`, `__init__.py` | skill bank loading, template retrieval, hybrid hot/cold injection; LLM evolver prompt, parsing, F1 dedup, bank writes |
| `visualclaw/modules/memory/*.py` (manager, store, retriever, policy, policy_store, policy_optimizer, consolidator, embeddings, metrics, models, telemetry, `__init__`) | the per-scenario episodic memory store (sqlite, keyword retrieval) |
| `visualclaw/config.py`, `config_store.py`, `env.py`, `config/defaults.yaml`, `__init__.py` | configuration loading |
| `visualclaw/gateway/types.py`, `gateway/__init__.py`, `visualclaw/modules/__init__.py` | shared types and package files |
| `visualclaw/skills_seed/seed_universal_mc/**` | the seed skill bank used by `scripts/run_visualclawarena_self_evolve.sh` |

Not copied:
- `visualclaw/claude_code_client.py` (the evolver's model client) and the `codex exec` process that
  `engines/codex_cli.py` starts: the adapter replaces both with the HALO backbone.
- `benchmark/visualclawarena/cascade_frames.py` and the other frame selectors: they decode the mp4 with
  OpenCV. The adapter supplies the keyframes the cascade forwards as text (`inputs/scenarios/*/data/keyframes.json`).
- `benchmark/visualclawarena/engines/claude_code.py` (the Claude Code backend), the gateway app, the live,
  proxy, RL, governance and scheduler modules, the iOS apps, and the VisualClawArena dataset.
