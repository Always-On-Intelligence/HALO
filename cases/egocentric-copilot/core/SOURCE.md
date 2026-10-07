# Vendored Egocentric Co-Pilot code

- Repository: https://github.com/YoungSeng/Egocentric-Co-Pilot
- Commit: 4bdc1c49f72d6b20e3daf0d35ce06b6b5ca2ee43
- License: the repository has no top-level license file at this commit (only the third-party
  `External-Tools-Support/android-mcp/` folder carries one, and it is not vendored here).

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `LLM-Orchestrated-Neuro-Symbolic-Execution/main.py` | the orchestrator: websocket handler, frame buffer (`CustomQueue`, `image_queue`), ASR call, intent routing (`prompt_refine`, `analyze_text`), branch actions (memory query, frame-rate modes, VLM answer), TTS reply, `send_text_parameters` |
| `LLM-Orchestrated-Neuro-Symbolic-Execution/llm_intent.py` | `LLMInferenceUnified`: intent templates and their embeddings, rule and semantic matching, LLM help/vision judgement |
| `LLM-Orchestrated-Neuro-Symbolic-Execution/api_providers.py` | `openai_API` and `siliconflow_API`, imported by main.py (the piece-tracking branch calls `openai_API`) |
| `Egocentric-Reasoning-Core/Egolife/scripts/eval_guide.py` | HCC: event-history loading (captions and SRT transcripts), query-aware hourly summaries of older events, 50 most recent events, answer |
| `Egocentric-Reasoning-Core/Egolife/config.py` | default paths imported by eval_guide.py |

main.py runs from its unchanged source with one top-level statement skipped (lines 214-215,
`if not Using_remote_server: load_local_models()`), which loads the Whisper, F5-TTS and Qwen models that
the adapter replaces. Its `try` import of `chess_engine`, `llm_intent` and `api_providers` stops at
`chess_engine` (YOLO weights, `ultralytics`, and the chessdb.cn cloud API are not available), so the
adapter supplies `LLMInferenceUnified`, `openai_API` and `siliconflow_API` from the vendored modules,
and `INTENT_EMBEDDINGS` as main.py's `__main__` block sets it.

Not copied: `chess_engine.py` and `vision_core.py` (board assistant: YOLO/FastSAM weights and a network
move database), `WebRTC/`, `External-Tools-Support/` (MCP examples: the multi-server client's system
prompt file `multiserver_prompt.txt` is not in the repository, and nothing in main.py calls MCP), the
Android front end (its frame interval and quality handling is reproduced in the adapter), and the
reasoning core's fine-tuning and HD-EPIC benchmark scripts. `Proactive-Multimodal-Intent-Disambiguation/`
holds only a README that points to a separate repository; the clarifier code is not at this commit.
