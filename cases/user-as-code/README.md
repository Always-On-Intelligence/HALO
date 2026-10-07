# User as Code in HALO run mode

User as Code (19PINE-AI/user-as-code; paper arXiv 2606.16707) keeps a personal assistant's memory as
executable Python. Configuration reviewed by the survey (`case.yaml`): two-phase executable personal
memory with the Active Service constraint pipeline. Phase 1 extracts every fact of a session into an
append-only list (with a Chroma fact index and a raw-session archive); Phase 2 regenerates a typed
Python view of the facts; questions are answered from the view, retrieved facts and archive excerpts.
The Active Service, after every update, has the model write the user's state and explicit constraints as
a validated JSON IR, compiles it with trusted code into a constraint module, stores the module, and runs
it in an isolated sandbox at the update date, so a conflict or deadline can raise an alert without
being asked for.

## What runs

Upstream code in `core/` (unchanged; see `core/SOURCE.md`), driven by `adapter.py`. One item is one
eligible Active Service scenario from the upstream suite (user-authored sessions with dates; the last is a
cue-free update) plus one follow-up question. For every session:

1. `UserAsCodeV5.ingest_session` (`experiments/user_as_code_v5.py:65-89`): Phase 1, one model call.
2. The per-session body of `run_uac_case` (`experiments/run_active_service_v3.py:167-209`), reproduced in
   `Adapter._update` around the upstream calls: retained history (`v2.render_history`), `generate_valid_ir`
   (one call, up to two repair calls), `engine.compile_constraint_module`, module written to the run's
   programs directory, `v2.validate_generated_source`, and `v2.execute_generated_source` on the stored
   module at the session date (child process `python -I -S experiments/active_service_sandbox.py`, 5 s
   timeout, sandbox CPU/memory/file/descriptor limits, inside a per-run temporary directory that is
   deleted afterwards).

Then `UserAsCodeV5.answer` (`user_as_code_v5.py:269-296`): Phase 2 `structure()` (one call) and the
three-channel retrieval, then the answer (one call). About 7-9 backbone calls per arm.

## Replacements

- `krill_client.krill_call` (GPT-5.6 Luna through Krill) -> the HALO backbone via a stub module, same
  system/user split; `KrillModelGenerator` -> a generator over the same backbone. Thinking budgets and
  temperature were already ignored by the Krill client and are not passed on.
- Chroma's default embedder, which downloads an ONNX copy of all-MiniLM-L6-v2, -> the same model from the
  local sentence-transformers cache (injected when `user_as_code_v5.py` creates its collections).
- Chroma itself (1.5.7, as recorded in the paper; anonymized telemetry off) and the sandbox run unchanged.
- Outbound network is refused inside the worker process; the backbone runs in its own subprocess.

## Cut sites

| Cut | Site (upstream `file:line`) |
|---|---|
| S->M | user sessions are not retained: Phase-1 writes `user_as_code_v5.py:79` (fact list), `:83` (fact index) and `:156` (archive) are dropped, and the session is not added to the retained history at `run_active_service_v3.py:168`, so each IR update sees only the current session |
| M->A | retained memory does not reach the answer: the retrieval read at `user_as_code_v5.py:277` (structured view, facts, archive excerpts) returns nothing |
| revision | the compiled constraint module is generated but not written at `run_active_service_v3.py:184`; the execution at `:198` runs the newest stored module, so later updates run without the new constraints (this covers later_use) |

The service keeps no record of its alerts and receives no feedback on them, so record, outcome and
attribution have no site. A->S, M->S and A->M are not realized in this code. Each run reports `withheld`.

## Inputs

`inputs/items.json`: five eligible scenarios (`travel_03`, `finance_02`, `schedule_07`, `deadline_03`,
`deadline_07`: single-entry visa already used, card limit, wedding vs. long run, lease notice deadline,
inspection contingency deadline), each with one follow-up question. The judge sees the user's updates
and the scenario author's expected alert. Outputs: `output` (alerts after each update plus the answer;
S->M), `output_answer` (M->A), `output_alerts` (revision). Metrics: the frozen rubric on the last update's
alerts (`trigger_rubric_passed`), alerts before and at the last update, answer keyword hits, facts and
modules stored, update errors.

## Run

```bash
uv venv cases/user-as-code/.venv -p 3.11 && uv pip install -p cases/user-as-code/.venv/bin/python -r cases/user-as-code/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=... PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/user-as-code --items 1 --samples 1 --workers 2 --name smoke
```
