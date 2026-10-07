# Vendored M3-Agent code

- Repository: https://github.com/ByteDance-Seed/M3-Agent
- Commit: 0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c
- License: Apache-2.0 (`LICENSE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `m3_agent/memorization_memory_graphs.py` | `streaming_process_video`, `process_segment`: the memorization loop over clips |
| `m3_agent/control.py` | `consumer` (memory search per round), `system_prompt`, `instruction`, `eval_answer` (GPT-4o verifier) |
| `mmagent/videograph.py` | `VideoGraph`: face, voice, episodic and semantic nodes, identity matching, equivalences, text search |
| `mmagent/face_processing.py`, `mmagent/voice_processing.py` | load the clip's intermediate outputs and match faces and voices against the graph |
| `mmagent/memory_processing_qwen.py` | memorization prompt context (`generate_video_context`), `generate_memories`, `process_memories` |
| `mmagent/memory_processing.py` | `parse_video_caption` (entity ids in memories) |
| `mmagent/retrieve.py` | `search`, `translate`, `back_translate` |
| `mmagent/prompts.py` | `prompt_generate_memory_with_ids_sft`, `prompt_agent_verify_answer_referencing` |
| `mmagent/utils/chat_qwen.py` | `generate_messages` for the memorization model (its `get_response` is replaced) |
| `mmagent/utils/chat_api.py` | `generate_messages` for the verifier (its API calls are replaced) |
| `mmagent/utils/general.py` | `validate_and_fix_json`, `load_video_graph` |
| `mmagent/__init__.py`, `mmagent/utils/__init__.py`, `configs/__init__.py` | package files |
| `mmagent/utils/video_processing.py`, `mmagent/utils/video_verification.py`, `mmagent/src/face_extraction.py`, `mmagent/src/face_clustering.py` | imported by the modules above; the functions that decode video, detect and cluster faces are not called |
| `configs/processing_config.json`, `configs/memory_config.json`, `configs/api_config.json` | configuration; the first two are copied into the run directory unchanged (see README for `api_config.json` and the matching thresholds) |

Not copied: `m3_agent/memorization_intermediate_outputs.py` (face detection and diarization of real
videos; its outputs are scripted), `visualization.py`, `setup.sh`, figures, and the M3-Bench data.
The adapter reproduces the control loop of `control.py` lines 162-207 (the `__main__` block, which
runs vLLM batches) for one question at a time, calling the upstream `consumer` and `eval_answer`.
