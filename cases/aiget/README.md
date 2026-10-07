# AiGet

AiGet (Synteraction-Lab, [arXiv 2501.16240](https://arxiv.org/abs/2501.16240)) is a smart-glasses
assistant that watches what the user looks at and shows short pieces of knowledge chosen for that
user. It reads a user profile, keeps the suggestions it has shown, and avoids repeating them.

- **Domain:** wearable
- **Code:** [Synteraction-Lab/AiGet](https://github.com/Synteraction-Lab/AiGet) at `92b17f8`
- **Read mode:** the configuration reviewed is the Gemini-based prototype with the participant's
  profile, the focus and familiarity rules, and the interaction history (`case.yaml`).

## What runs

The adapter calls AiGet's own pipeline, `get_llm_response` in `core/src/Module/LLM/LLMPipeline.py`,
the way the timer path of AiGet's front end calls it (`src/Frontend.py`, lines 391-421):

1. **Perception.** The five frames of a moment and the request go to the perception prompt
   (`context_description`), which contains the user profile.
2. **History retrieval.** `find_most_relevant_history` selects earlier suggestions (all-MiniLM-L6-v2).
3. **Generation.** The context description, the profile in `knowledge_generation_filter`, and the
   suggestion history go to the generation call (the Gemini path, AiGet's default).
4. **Novelty filter.** `filter_new_items` drops suggestions too close to the history (cosine 0.75).
5. **Output processing.** The `process_output` call and the location call run as upstream.
6. **Record.** The shown suggestions extend the suggestion history, as `Frontend.process_response`
   does (lines 476-492). The adapter then visits the same moment a second time.

The upstream files that run are copied unchanged into `core/` (see `core/SOURCE.md`).

## What is replaced

| Upstream | In this case | Why |
|---|---|---|
| Gemini, GPT, and Groq clients (`Gemini.py`, `GPTVision.py`, `Groq.py`) | stubs that send the same system instruction and content to the HALO backbone | no API keys; one fixed backbone for every arm |
| camera frames | five text frames per moment (`inputs/scenes.json`) | the backbone is text-only |
| Tk front end | `Adapter._visit` and `Adapter._record` | the run is headless |

The stubs keep Gemini's message layout: frames first, then the notes and the request, and the
history as an earlier model turn. Temperature and token limits are not passed on.

## Cut sites

| Cut | Site | What the cut does |
|---|---|---|
| M→S | `[USER_PROFILE_PLACEHOLDER]` in `task_description/context_description` | perception runs without the user profile |
| M→A | `[USER_PROFILE_PLACEHOLDER]` in `task_description/knowledge_generation_filter` | generation runs without the user profile |
| A→M | the history write in `Frontend.process_response` (lines 483 and 492) | suggestions shown on the first visit are not written to the history |

AiGet does not revise its own mechanism, so no evidence step is cut.

## Inputs and comparison

`inputs/scenes.json` holds six moments in Singapore. Each is five text frames with the gaze
position, a location, and a timestamp. The `design` field says why the scene was chosen and is
never sent to a model.

- **M→S, M→A, and both:** the judge compares the first-visit suggestions with the user profile and
  the location in view.
- **A→M:** the judge compares the second-visit suggestions and also sees what was shown on the
  first visit.
- **Metrics:**
  - `shown` and `shown_revisit`: the number of suggestions shown on each visit;
  - `revisit_repeats`: second-visit suggestions within AiGet's own 0.75 similarity threshold of a
    first-visit suggestion;
  - `revisit_mean_max_similarity`: the mean, over second-visit suggestions, of the highest
    similarity to any first-visit suggestion.

## Run

```bash
uv venv cases/aiget/.venv -p 3.11
uv pip install -p cases/aiget/.venv/bin/python -r cases/aiget/requirements.txt
export HALO_CODEX_BIN=/path/to/codex
PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/aiget --workers 4   # add HF_HUB_OFFLINE=1 once MiniLM is cached
```
