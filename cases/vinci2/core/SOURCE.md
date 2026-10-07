# Vendored EgoMemo code (Vinci2)

- Repository: https://github.com/SitongGong/EgoMemo
- Commit: 0029a33fd83bb93cb6a7bb012bbdd3477b4c6b35
- License: MIT (`LICENSE`, copied unchanged)

Files copied unchanged from `egomemo_demo/`, at their paths under it (the import closure of the
CLI entry `egomemo/run.py`, plus `egomemo/prompt_templates_v2.py`, which the v2 reasoner imports
when it runs):

| Files | Role in the run |
|---|---|
| `egomemo/run.py` | CLI entry: applies the v2 reasoning, fast-read and trimmed-entity-prompt patches, builds the config, runs the pipeline |
| `egomemo/streaming_pipeline.py` | `StreamingPipeline.run_on_video`, `_reason_and_route`, `_call_reasoning_vlm`, step grouping |
| `egomemo/pipeline_v2_patch.py` | `_reason_proactive_v2`: the proactive decision ([silent] / [search] / [respond]) and the second pass after retrieval |
| `egomemo/memory_bridge.py`, `egomemo/memory_bridge_fast.py` | `MemoryBridge.build_step` (caption, text chunks, knowledge graph, visual embedding, activity and session captions) and the fast memory read |
| `egomemo/prompt_templates*.py`, `egomemo/entity_prompt_trim.py` | prompts (caption, activity and session summaries, proactive passes) and the trimmed entity-extraction prompt |
| `egomemo/action_router.py`, `question_queue.py`, `working_memory.py`, `output_recorder.py`, `config.py`, `entity_extraction.py`, `__init__.py` | action parsing, state, the decision trajectory |
| `videorag/egograph_retrieval_optimize_.py` | `VideoGraphSeparated`: the memory stores, `ainsert_streaming_caption`, `load_caption_model` |
| `videorag/ego_op.py`, `videorag/streaming_op_fast.py`, `videorag/streaming_op.py` | entity and relation extraction, retrieval-query rewriting, multi-level retrieval |
| `videorag/_storage/*` | JSON key-value, NanoVectorDB (text and visual), NetworkX graph stores |
| `videorag/_llm.py`, `_utils.py`, `base.py`, `_op.py`, `_splitter.py`, `videorag.py`, `__init__.py`, `video_processing.py`, `_videoutil/*`, `llm/qwen_vl.py`, `llm/qwen3vl_api.py` | configuration classes, helpers, and modules imported on the way (their model-loading and video-decoding functions are not called) |
| `videorag/*prompt*.py` | prompt tables (`ego_prompt_.py` is the one used, `datasets_type=egolife`) |

Not copied: `videorag/llm/qwen3vl_vllm.py` (the vLLM caption client, replaced by the HALO
backbone), the web front end (`egomemo/web/`), the vLLM launch script, the benchmark scripts at the
repository root, the evaluation suite and the annotation code.
