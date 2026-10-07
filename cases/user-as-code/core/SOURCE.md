# Vendored User as Code code

- Repository: https://github.com/19PINE-AI/user-as-code
- Commit: 3d473617a27e7ace8cbbde531b667d515864c21e
- License: Apache-2.0 (`LICENSE` and `NOTICE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `experiments/user_as_code_v5.py` | the two-phase memory: `ingest_session` (Phase 1 fact extraction, append-only fact list, Chroma fact index, raw archive), `structure` (Phase 2 typed-Python view), `retrieve` and `answer` (three-channel answering) |
| `experiments/run_active_service_v3.py` | the Active Service IR prompts and `generate_valid_ir` (three validated attempts with machine-feedback repair); the per-session body of its `run_uac_case` loop (lines 167-209) is what `Adapter._update` reproduces |
| `experiments/active_service_engine.py` | IR validation and the deterministic compiler that turns the IR into the executable constraint module |
| `experiments/run_active_service_v2.py` | `scenario_sessions` and `render_history` (user-only history), `validate_generated_source` (AST checks), `execute_generated_source` (isolated child process, 5 s timeout), `score_candidates` (frozen rubric), `load_protocol` |
| `experiments/active_service_sandbox.py` | the restricted child interpreter that executes a stored module (`-I -S`, restricted builtins and imports, CPU, memory, file-size and descriptor limits, 3 s alarm) |
| `evaluation/active_service_scenarios.json`, `evaluation/active_service_v2_protocol.json` | the authored scenarios and the frozen protocol (eligible cases, rubrics) the items are taken from |

Not copied: `experiments/krill_client.py` (the model client, replaced by a stub module that calls the
HALO backbone), the baselines, benchmarks, prototype and paper sources.
