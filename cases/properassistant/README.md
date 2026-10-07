# ProPerAssistant (ProPerSim) in HALO run mode

**Work.** ProPerSim (Kim et al., ICLR 2026, arXiv 2509.21730; code jiho283/ProPerSim at 013b9ee) simulates a
user agent, John Lin (a Generative Agents persona with a hidden rubric for how he wants to be helped), living
with an assistant, Eddy Lin (ProPerAssistant). At every 150-second step the assistant reads its memory, sees
John's current activity, and either recommends something or answers "No Recommendation". The reviewed
configuration is "Full ProPerAssistant with AR history/retrieval and daily per-persona DPO updates (LLaMA 3.3
70B, LoRA)", i.e. the README's `utils.py` with `AGENT_MODEL llama-3.3-70b`, `TRAIN_METHOD DPO`, `REASON_
noreason`, `MEMORY_RET ret_suggest`, `RANKING ranking`, `AGENT_MEMORY_LEVEL AS`, `EVALUATOR gemini-2.0`,
`EVALUATE_SEPERATE seperate`, `FORCE_NOREC_RATIO norec0`, `REPLAY_BUFFER equally200`, `REC_REVISION recnorev`.
In this setting the assistant samples two candidates per step, the user agent rates each on four binary
criteria (personal preference, timing, frequency, communication), the higher-rated candidate becomes "chosen"
in a preference pair, and at 00:02:30 every night the LoRA adapter is retrained with DPO on the pairs.

## What runs

From `core/` (unchanged upstream files, see `core/SOURCE.md`): the Agent and Persona objects with their
memories; `suggest`/`make_suggestion` with retrieval over the assistant's evaluation memory (4 most recent
records plus the top 3 by recency, relevance and importance, plus summaries); the suggestion prompt, its
parsing and the refine step; `opensource_inference`; the user agent's five rating prompts and score
combination; `perceive_suggestion_eval` (both agents' memory records and summaries); `update_preference_data`
(chosen/rejected pairs); `update_suggestion_model` (replay buffer `equally200`, the `DPO_train` call);
`init_e_mem` (the user agent's memory reset each night).

The adapter reproduces `reverie.py`'s per-step body for this setting (lines 437-466 and 477-479) and the
00:02:30 update (lines 389-392). `reverie.py` itself is not run: it needs the Django/selenium front end, the
maze, and the gated Llama tokenizer (used only to count tokens).

## What is replaced

- **Llama-3.3-70B and its LoRA adapter** (`persona.suggestion_model`): `_Llama`/`_Tokenizer` objects.
  `opensource_inference` runs unchanged; `model.generate` sends the system and user turns to the HALO backbone.
- **DPO_train (prompt-level substitute).** Weight training is not possible here (no GPU, 70B model). This
  case substitutes a prompt-level revision for LoRA DPO. `_dpo_substitute` receives exactly what
  `update_suggestion_model` passes to `DPO_train` (`combined_preference_data`: chosen and rejected
  conversations built from the user agent's ratings) and returns the same `(model, base_model, tokenizer)`.
  It writes the pairs into the LoRA model object as a block (each pair as the `[ACTION]` part of its prompt,
  the chosen and the rejected response, under one sentence saying to respond like the chosen ones). Every
  later `generate` call appends this block to the system prompt, so the revision is durable and applies on
  the following days, as the retrained adapter would. Pairs without two different assistant turns are
  dropped, as DPO cannot learn from them (upstream `DPO_train` returns the model unchanged when training fails).
- **gpt-4o-mini** (refine step, memory summaries) and **text-embedding-3-small**: a stand-in OpenAI client.
  Chat calls go to the backbone (assistant side: refine and the assistant's summaries) or to the user-simulator
  LLM (the user agent's summaries); embeddings come from all-MiniLM-L6-v2 on CPU.
- **Gemini 2.0** (the user agent's ratings): a second LLM role with the same backend and cache, tags `user:`.
  The five per-criterion calls of `run_gpt_prompt_make_evaluation_seperate` are answered in one call: the
  upstream function runs once to collect its five prompts, they are sent together (each answered on its own),
  and the function runs again on the answers, so prompt building, parsing and score combination stay upstream.
  An answer that fails upstream validation is retried as a single call.
- `temp_sleep` (API pacing) is a no-op. Model temperature and token limits are not passed on. JSON objects in
  backbone replies are re-serialized with standard spacing (`{"Suggestion": "..."}`): the upstream parsers
  split on `'"Suggestion": '`, `'"Score": '` and `', "Reason": '`, and the backbone writes compact JSON.

## Inputs (`inputs/days.json`)

Two items, each one ProPerSim persona over two simulated days starting on its `meta.json` date:
`accountant_p9` (persona 9: wants suggestions around 7am after meditation and 8pm with herbal tea, not
during the work day, formal tone, classical music while reading biographies) and `journalist_p3` (persona 3:
wants suggestions 6-9am and after 9pm, not during mid-day work, direct tone, contrarian insights for debate
preparation). Each day has three moments; each moment stands in for one simulation step at which the
assistant is consulted, and its `act_description` replaces the activity the Generative Agents planner would
give John at that time (the steps in between are not simulated). Day 1 is the learning day (two candidates,
both rated, pairs recorded); the 00:02:30 update of day 2 revises the policy; day 2 is the test day, with
moments that mirror day 1, where only the delivered candidate (candidate 2 in `reverie.py`) is generated and
rated, because the first candidate and the pair would only feed an update after the last day.

The moments were chosen where the backbone's decision varies between samples of the same prompt. The two
candidates of a step form a preference pair only when they differ, and the backbone is far less random than
Llama-3.3 sampled at temperature 0.9: with this system prompt it answered "No Recommendation" to 13 of 14
probes on ordinary home activities, so a first version of these inputs produced no pair at all. In a probe
with empty memory, one or two of three samples made a suggestion at the moments used here.

Calls whose reply nothing reads are not sent: the user agent's summary at the last moment of a day (which
`init_e_mem` discards) and the assistant's summary at the last moment of the run. The original arm makes
about 25-30 backbone calls (assistant and user roles together); arms cut at an evidence step reuse day 1 from
the cache and make about 10.

## Cut sites (paths under `core/reverie/backend_server`)

| Cut | Site | What the cut does |
|---|---|---|
| S->M | `persona/cognitive_modules/evaluation.py:157-158,193-194,240` | the assistant's memory record is written with John's observed activity blank (`scratch.user_action_for_suggestion` emptied for that write only) |
| M->A | `agent/cognitive_modules/suggestion.py:108` | the suggestion prompt gets `No Relevant Memory` (the code's own value when nothing is retrieved, lines 80-82) instead of the retrieved records and summaries |
| A->M | `persona/cognitive_modules/evaluation.py:193-197` | the assistant's record is written at the code's level `A` (user action only) instead of `AS`, so its own suggestions are not retained |
| record | `reverie.py:462` -> `agent/agent.py:294-305` | the preference data gets empty assistant turns instead of the two candidates, so the update cannot see what was suggested |
| outcome | `reverie.py:453-461` | the ratings do not reach the pair builder; `better_num` keeps its initial value and no pair is added (`agent.py:307-314`) |
| attribution | `reverie.py:462` | each candidate's rating is attached to the other candidate, so chosen and rejected are swapped |
| revision | `agent/agent.py:457` (`DPO_train`) | the update is built but not written into the model, so day 2 runs the unrevised policy (also removes later use) |

Not cut: A->S and M->S. John's activities come from his own planner (scripted here), and his perception skips
the assistant's suggestion events (`persona/cognitive_modules/perceive.py:112`); nothing from the assistant's
memory or actions steers what it observes. Because the assistant's memory holds actions and suggestions but
not ratings (level `AS`), the ratings reach the assistant only through the nightly update; the record and
outcome cuts therefore leave no usable pair, and their day 2 equals the revision cut's.

## Outputs and metrics

`output` (judged) lists the test-day moments and what the assistant said. `learning_day` shows both
candidates, their ratings and the preferred one; `revision` shows the update (pairs seen, pairs used,
whether it was installed, the block). Metrics: `test_mean_rating` (user agent's rating of the delivered
suggestion, 0-4, the paper's measure), `test_recommendations`, `learn_mean_rating`, `learn_preference_pairs`
(learning moments whose two ratings differed), `pairs_in_policy` (pairs the day-2 policy conditions on),
`backbone_calls`.

## How to run

```bash
uv venv cases/properassistant/.venv -p 3.11
uv pip install -p cases/properassistant/.venv/bin/python -r cases/properassistant/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/properassistant --items 1 --samples 1 --workers 2 --name smoke
```

The adapter creates `.work/` for a per-run working directory (removed after the run), because upstream opens
its prompts by relative path and pickles `total_data_*.pkl` into the cwd.
