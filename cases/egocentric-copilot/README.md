# Egocentric Co-Pilot in HALO run mode

Egocentric Co-Pilot (YoungSeng/Egocentric-Co-Pilot, commit 4bdc1c4) is a smart-glasses assistant: the
glasses stream frames and speech to a backend that routes each utterance by intent and answers with a
VLM; a reasoning core answers questions over a long event history (HCC). Survey configuration:
"Smart-glasses assistant with event/query history, HCC, MCP tools, and clarifier". Status: **partial**.
The orchestrator and HCC run. The clarifier and the MCP tools cannot (see the end).

## What runs

**Orchestrator** (`LLM-Orchestrated-Neuro-Symbolic-Execution/main.py`, unchanged source minus the local
model loading at lines 214-215). The adapter plays the glasses front end against the real
`websocket_handler`: one JPEG every `imageAnalysis_interval` ms (default 200) at
`imageAnalysis_quality` (default 25), and utterances as audio messages. `process_audio` does ASR,
intent routing (`prompt_refine` on the intent templates, then `LLMInferenceUnified.analyze_input`:
rules, semantic similarity, LLM judgement), the branch action, and the TTS reply. The front end applies
the interval and quality that `send_text_parameters` sends, as `MainActivity.kt:246-253` does.

Each item has four turns in a 60 s session:
1. "记住这三个棋子的位置。" ("Remember the positions of these three pieces") enters high-frame-rate
   mode and sends 200 ms / quality 25;
2. "I've finished moving." exits it, sends 500 ms / quality 80, and returns the hard-coded tracking
   placeholder ("The pieces from left to right are Red Chariot, Black Cannon, and Red Horse");
3. a question about small print held up to the camera, answered from the latest frame;
4. "Where did I put my ...?", about something put away 30-40 s earlier.

**HCC** (`Egocentric-Reasoning-Core/Egolife/scripts/eval_guide.py`, run through its own `main()`): the
day's event history from 08:00 to 10:00 (a caption per 30 s clip plus SRT transcripts, 243 events, in
the EgoLife layout the script reads). Above 200 events it summarizes each older hour with a query-aware
prompt, keeps the 50 most recent events, and answers a multiple-choice question about the early morning.

About 7 model calls per arm: turn 3 and turn 4 each take an intent judgement and a VLM answer, and HCC
takes two hourly summaries and an answer.

## Replacements

| Upstream model | In this run |
|---|---|
| Qwen2-VL (`main.inference_llm`, images and frame lists) | HALO backbone; each frame becomes its scripted text |
| Qwen2.5 intent LLM (`LLMInferenceUnified.generate_response`) | HALO backbone |
| `paraphrase-multilingual-MiniLM-L12-v2` (intent template embeddings) | all-MiniLM-L6-v2 on CPU (the only cached model); it maps most Chinese characters to `[UNK]`, so Chinese utterances match only templates with the same token pattern |
| Whisper ASR (`main.ASR_model`) | returns the scripted utterance carried in the audio message |
| F5-TTS (`main.process_tts`) | the front end receives the reply text |
| Qwen2.5 in the HCC script (`AutoModelForCausalLM`/`AutoTokenizer` in eval_guide) | a tokenizer/model pair that sends each chat to the backbone |
| `api_providers.openai_API` (gpt-4o) | `openai.OpenAI` replaced by a backbone client (only the piece-tracking "this" branch uses it) |
| camera | scripted segments; small print is legible only at JPEG quality >= 50, a stand-in for quality 80 versus 25 |

`cached_path` (TTS checkpoint download) is an inert stub. Generation limits (`max_new_tokens=50` for the
VLM) are not passed on, as the CLI backends do not expose them.

## Cut sites

| Channel | Site | What is withheld |
|---|---|---|
| S->M | `main.py:337` `CustomQueue.put` (frames arrive at `:830`); `eval_guide.py:84` `load_and_merge_all_data` | the frame buffer keeps only the newest frame (the latest-frame answers, S->A, are unchanged); the HCC event history admits no events |
| M->A | `main.py:346` `CustomQueue.get_all` (read by the memory branch at `:741`); `eval_guide.py:162` `get_answer_from_llm` | the memory branch receives no retained frames; the HCC answer receives no summaries or recent events |
| A->S | front end receiving `send_text_parameters` (`main.py:675`, sent at `:752` and `:761`; `MainActivity.kt:246-253`) | the glasses keep 200 ms / quality 25 instead of switching to 500 ms / quality 80 |

The survey also lists M->S and A->M as not reported; one reviewer found both in the board-game tool
(`vision_core.ChessboardMemory`, `chess_engine` strategy log), which needs YOLO weights and the
chessdb.cn API and is not run. No self-revision, so no evidence step is cut.

## Upstream behaviour the run exposes

- The memory-query branch (`main.py:739-747`, the survey's M->A locator) is unreachable in local mode.
  `prompt_refine` scores the utterance against `text_based_llm.INTENT_EMBEDDINGS`, built from
  llm_intent.py's templates, whose memory intent is spelled `Memorization_required`, then looks the
  winner up in main.py's own `INTENT_TEMPLATES`, which spells it `memorization_required`. A matching
  memory question raises `KeyError` inside `process_audio` (caught, no reply). English memory questions
  never match the Chinese-only memory templates and go to the latest-frame VLM answer instead (turn 4),
  so the S->M and M->A cuts change nothing in the orchestrator; they act on HCC.
- llm_intent.py's high-frame-rate templates are Chinese only. With the replacement embedder, "Enter high
  frame rate mode." matches the English exit template ("Exit high frame rate mode.", 0.85) and does
  nothing, so turn 1 uses the Chinese template sentence.
- The piece-tracking result after leaving high-frame-rate mode is a fixed placeholder string, so the
  frame rate itself has no effect on any answer; quality does (turn 3).

## Not run

- Clarifier (`Proactive-Multimodal-Intent-Disambiguation/`): only a README pointing to
  YoungSeng/plug-and-play-clarifier; no code at this commit, and that repository is not available here.
- MCP tools (`External-Tools-Support/simple-mcp`): `mcp_client.process_with_multiserver_mcp` reads a
  system prompt file (`multiserver_prompt.txt`) that is not in the repository, needs Qwen3-8B tool calls
  over LangChain MCP adapters, and is not called by main.py; the memory server is a standalone example.
- Board-game assistant (`chess_engine.py`, `vision_core.py`): YOLO/FastSAM weights and a network move
  database.

## Inputs and outputs

`inputs/sessions.json`: four items (home medicine box, office parcel, kitchen recipe card, hotel boarding
pass), each with the live session (segments with `view`, optional `fine` small print, utterances) and
the morning's history (activity blocks, key captions, speech, one question with four options).

Outputs: `output` (turn 3 reply, small print), `output_memory` (turn 4 reply), `output_hcc` (HCC choice),
`context_memory`, `context_hcc`, `log` (utterances, parameter messages and whether the front end applied
them, replies). Metrics: `final_quality`, `buffer_frames`, `label_fact_recall`, `memory_fact_recall`,
`hcc_correct`, `replies`, `model_calls`.

## Run

```bash
uv venv cases/egocentric-copilot/.venv -p 3.11
uv pip install -p cases/egocentric-copilot/.venv/bin/python -r cases/egocentric-copilot/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/egocentric-copilot --items 1 --samples 1 --workers 2 --name smoke
```
