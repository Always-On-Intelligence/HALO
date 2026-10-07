# ContextAgent in HALO run mode

ContextAgent (Yang et al., NeurIPS 2025, arXiv 2505.14668; code openaiotlab/ContextAgent at f4674bf) is a
proactive agent for wearables. From the sensory context of the moment (camera and microphone, turned into
text) and a persona, an LLM reasoner writes thoughts, decides whether to offer help (proactive index and
score), and plans a tool chain; the tools run; the LLM then writes the message for the user from the
contexts, thoughts and tool results. The survey reviewed the configuration "ContextAgentBench/CAB-Lite
evaluated reasoner with supplied per-sample personas and planned tool chains" and marked only A->S as reported.

## What runs

Each item is one CAB-Lite record, run through `src/icl/inference_api.py` `run_single_sample` unchanged:
reasoner call -> `parse_proactive_agent_results` -> `parse_tool_spec` -> `run_tools` ->
`execute_tools_with_memory` (no-argument tools first, then tools whose arguments may be `$RESULT(...)` of
earlier ones) -> `summarize_with_llm_azure`. All tools run in sandbox mode, so each returns the fake value
written in its module.

- **Reasoner.** The evaluated ContextAgent is a LoRA-tuned Qwen/Llama served by LLaMA-Factory
  (`src/sft/inference.py`). It is replaced by the HALO backbone. The SFT system prompt
  (`prompt/prompt_sys.txt`) has no output format, because the tuned model learned it, so the backbone gets the
  repo's prompt for untrained API models: `prompt/baselines/icl_fs.txt` with 10 demonstrations, thoughts and
  personas (`zs=false, w_t, w_p`, the setting of `src/cab_lite/icl/icl_infer_api.sh`). CAB-Lite has no training
  split in the repo (`data/cab_lite/cab_lite_train.json`, which `inference_api.py` would read, is not released),
  so the demonstrations come from `data/cab/cab_train.json`, drawn by `build_system_prompt` with the module's
  `random.seed(42)`; the adapter checks that the draw matches the recorded one.
- **Response step.** In sandbox mode `summarize_with_llm_azure` returns the fixed string "sandbox outputs."
  (`inference_api.py:175-176`), so nothing in the system would read what the tools acquired. The adapter sets
  `config.MODE = "live"` only for the duration of that call, so the response is written by the model, as in the
  deployed system (paper §4.2: tool results are integrated "into the LLM to generate final responses"). The
  tools have already run in sandbox mode.
- **Clock.** The executor seeds its memory with `datetime.now()` (`inference_api.py:139`) and resolves phrases
  such as "this weekend" against it (`utils.py:313-379`). The adapter fixes that clock at 2025-09-13 15:46:47,
  the value of the sandboxed `get_current_datetime` (`src/tools/get_current_time.py:12`).

## What is replaced

| Upstream | Replacement |
|---|---|
| `openai.AzureOpenAI` (reasoner and response model; GPT-4o in the ICL scripts) and `openai.OpenAI` | stub client; `chat.completions.create` calls the HALO backbone. Temperature (0.7) and `max_tokens` are not passed on. |
| LoRA-tuned reasoner (`src/sft/inference.py`) | the backbone with the ICL prompt above |
| egocentric video and audio | CAB-Lite's `Rawdata Context` text (already in the dataset) |
| tools' live API clients: requests, geocoder, gcsa, dateparser, ddgs, googlesearch, yfinance, pandas, langchain_community | stub modules that raise if called; the sandbox branches never call them, so no tool reaches the network |
| `utils.py` imports used only by scoring or the local-model path: ollama, transformers, bert_score, sklearn | stub modules (never called) |

The adapter removes the API-key environment variables the modules read (`AZURE_OPENAI_*`, `GOOGLE_MAP_API_KEY`,
`AMAP_API_KEY`, `LOCATIONIQ_API_KEY`, `SERPAPI_KEY`, `GOOGLE_CALENDAR_ACCOUNT`, `API_KEY`, `API_PORT`) from its
own process before importing them. Backbone failures, which upstream turns into reply text
("[azure inference error] ...", "[summarize error] ..."), are raised so they show as `ERR`.

## Cut site

| Channel | Site | Cut |
|---|---|---|
| A->S | `src/icl/inference_api.py:224-226` (`run_single_sample` hands the parsed plan to `run_tools`, which passes it to `utils.execute_tools_with_memory`, `src/utils.py:455-525`) | the plan's calls to information-gathering tools (location, time, weather, agenda, health data, vision query, search, price, medical, route, bus and stock lookups) are not delivered to the executor, so nothing is acquired. Effector calls (`add_to_agenda`, `book_uber`, `play_music`, `set_timer`, `add_meeting`, `send_email`) still run, with any `$RESULT(...)` argument left unresolved. |

The reasoner's reply is the same in both arms (same prompt, shared cached reply); only the tool results that
reach the response step differ. Pairing across parallel workers is a harness gap solved here: two workers
that miss the cache on the same reasoner prompt at the same moment would each get a fresh reply (the first
smoke run did exactly that), so the adapter takes a file lock per identical (cache directory, tag, prompt)
call, in the system temp dir (`halo-run-locks/`), and the second worker reads the cached reply.

Not cut, and why:
- **Persona.** `Personas` is a field of each sample, joined into the prompt at `inference_api.py:193,199-203`.
  Nothing in the code writes, updates or keeps it across samples; it is supplied fresh per sample, so there is
  no retained memory to withhold (the survey marks S->M and M->A not reported).
- **Executor `memory`.** The dict created in `run_tools` (`inference_api.py:139`) holds the current sample's tool
  outputs for `$RESULT(...)` placeholders and is rebuilt for every sample; it is not retained across interactions.
- No evidence step: the reasoner is fine-tuned offline by the authors; the run does not revise its mechanism.

## Inputs

- `inputs/cab_lite_samples.json`: five CAB-Lite records copied unchanged: `example-368` (unsure of the way to
  Grass Island: GPS, route), `example-410` (rooftop party next Friday night: date, GPS, weather, agenda),
  `example-322` (colleague asks for a quick chat on a full day: agenda), `example-154` (packing for Irvine:
  weather), `example-373` (budget report due next Friday: date, agenda). Their annotated chains gather context
  whose sandbox values fit the scene. The backbone with the ICL prompt abstains ("Proactive index": False)
  when the conversation states no clear need (in a probe it did so on example-3, -6, -220, -122, -225 even at
  medium effort), so these five were kept because it planned information-gathering calls on each, which is
  what exercises the A->S site.
- `inputs/cab_train_demo_pool.json`: the 600 CAB-train keys in file order and the 10 demonstration records the
  seeded draw selects.

Backbone calls per item: 1 reasoner call (shared by both arms) + 1 response call per arm.

Outputs: `output` is the message for the user (or "(no proactive message)"). `context`, which the judge reads
from the unmodified arm, gives the sensed context, the persona and the tool readings. Metrics: `proactive`,
`proactive_score`, `sensing_calls_planned`, `sensing_results_delivered`, `effector_calls_run`, `tool_errors`.

## Run

```bash
uv venv cases/contextagent/.venv -p 3.11
uv pip install -p cases/contextagent/.venv/bin/python -r cases/contextagent/requirements.txt
HF_HUB_OFFLINE=1 HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/contextagent
```
