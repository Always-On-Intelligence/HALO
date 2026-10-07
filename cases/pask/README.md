# PASK in HALO run mode

PASK (Xie et al., arXiv 2604.08000; code xzf-thu/Pask at d54646c) proposes DD-MM-PAS: a streaming
demand-detection model (IntentFlow) decides at each turn of a live conversation whether to stay silent,
answer at once, or consult memory first; a hierarchical memory (Pask-MM) models the user; and a runtime
(PAS) carries out the help. The survey reviewed the configuration "IntentFlow demand detection with
PASK-MM and PASK-PAS" and marked S->M and M->A as reported.

## What runs

The repository releases the LatentNeeds-Bench construction pipeline (`bench/`) and its evaluation
(`eval/`). It does not release the IntentFlow Demand Detector or MemLoader weights, the Pask-MM
user/workspace/global store or its post-session maintenance, the `<full_assistance>` retrieval path, or
the PAS runtime. The run therefore executes the released DD-MM loop of the benchmark protocol
(paper §6.1.1), unchanged:

1. **Memory write (Pask-MM stand-in).** At the boundary between two parts of one conversation,
   `bench/03c_memory.py` `run()` writes a memory document "that the AI assistant would have from
   observing the prior conversation", for the AI serving the primary user. This is the `memory` field
   that the evaluated IntentFlow read (`03c_memory.jsonl` -> `03d_annotate.py` -> `LatentNeeds-Bench.jsonl`).
   The writer runs before the later part streams, so `build_memory_prompt` takes its own
   "(no preview available)" branch (`03c_memory.py:76-80`); the benchmark build gave it a five-turn
   preview of the next part, which an online system would not have.
2. **Demand detection (IntentFlow stand-in).** For every turn of the later part, `eval/run.py`
   `build_tasks` / `eval_model` / `parse_response` with `eval/prompts.py` `build_prompt` at the
   `neutral` level (IntentFlow's reported run, `eval/results/intentflow_neutral.jsonl`) gives the model
   the scene, the memory, the part's dialogue so far, and the current turn. The model returns either a
   proactive response or `[NO_DEMAND]`. As in the benchmark, one call both decides and writes the help,
   which matches the paper's fast-intervention path; the three-token decision and PAS execution are not
   in the release.

## What is replaced

| Upstream | Replacement |
|---|---|
| `openai.OpenAI` / `AsyncOpenAI` (IntentFlow served by vLLM, gpt-5.2 for the memory writer) | stub module; `chat.completions.create` sends the messages to the HALO backbone (`self.llm`) |
| temperature 0.3 / 0.2, `max_tokens`, `reasoning_effort` | not passed on; the CLI backends do not expose them |
| speech (ASR of live audio) | scripted, speaker-attributed text turns (`inputs/streams.json`) |

The stub's async `create` finishes the backbone call without yielding, so the 60 s `asyncio.wait_for`
in `eval/run.py:103-106` cannot cancel a 20-120 s backbone call. A retry of an identical prompt
(`complete_json` after a JSON parse failure, `call_one` after an API error) gets a `|retryN` tag so it
is a new backbone call. Backbone failures that the upstream retry loops would turn into silence or an
empty memory are re-raised, so they show as `ERR` in the harness. The adapter removes the API-key and
endpoint variables that `bench/llm_client.py` and `eval/config.py` read at import (`OPENAI_*`,
`OPENROUTER_*`, `VLLM_BASE_URL`) from its own process before importing them.

## Cut sites

| Channel | Site | Cut |
|---|---|---|
| S->M | `bench/03c_memory.py:141-151` (`run()` looks up the prior part and passes its turns to `build_memory_prompt`, lines 55-98) | the earlier part is not delivered to the memory writer, so `run()` takes its "no prior part found" branch and the memory stays `""` |
| M->A | `eval/prompts.py:95,118-119` (`build_prompt` reads `session["memory"]` into the `[Memory from earlier conversation]` block) | `session["memory"] = None`, so the block is left out |

Both sites lie on one serial path (one writer, one reader), so the two cut arms send identical
demand-detection prompts and share cached replies; the S->M arm also skips the memory-writing call.

Pairing across parallel workers (a harness gap solved here): arms are paired by sharing the cached reply
to an identical call, but two workers that miss the cache at the same moment would each get a fresh
reply. The adapter takes a file lock per identical (cache directory, tag, prompt) call, in the system
temp dir (`halo-run-locks/`), so the second worker waits and reads the cached reply.
No evidence step is cut: the released code does not revise its own mechanism (IntentFlow is trained
offline, and Pask-MM's post-session updates change memory content, not the mechanism).

## Inputs

`inputs/streams.json`: five conversations (meeting, tutoring, dinner planning, migration planning,
investor prep) across the W, L and D categories. Each has an earlier part (6-7 turns) and a later part
(4 turns); turn 3 of the later part is where something said only in the earlier part (a compliance
sign-off date, repeated measures, a peanut allergy, a maintenance window, a one-time revenue item) makes
a need detectable. Backbone calls per arm and item: 1 memory write + 4 demand-detection calls.

Outputs: `output` lists the decision at each later turn (`T1: (silent)` or the response). Metrics:
`interventions`, `need_turn_hit_rate` (responded at the need turn), `need_turn_uses_earlier_rate`
(that response states a fact found only in the earlier part, matched by the item's `cues` patterns,
none of which matches the scene or the later part), `other_turn_interventions`,
`memory_chars_delivered`. `memory_written` keeps the memory document.

The scene header (people and roles) reaches demand detection in every arm, as in the benchmark, so
an arm without memory can still guess at a generic risk; the cue metric separates such guesses from
use of earlier facts.

## Run

```bash
uv venv cases/pask/.venv -p 3.11
uv pip install -p cases/pask/.venv/bin/python -r cases/pask/requirements.txt
HF_HUB_OFFLINE=1 HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/pask
```
