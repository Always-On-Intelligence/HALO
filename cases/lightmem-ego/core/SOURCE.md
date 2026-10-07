# Vendored LightMem-Ego code

- Repository: https://github.com/zjunlp/LightMem-Ego
- Commit: 3c023dfec301bb2f9624f82cee76007ac3ac0646
- License: MIT (`LICENSE` at the repository root, `src/backend/LICENSE`, and the vendored HippoRAG
  subset's `src/backend/src/HippoRAG/LICENSE`, all copied unchanged)

The 140 Python files under `src/backend/` are copied unchanged at their upstream paths. The list is
the set of upstream modules that a full run of the adapter imports (recorded from `sys.modules`
after running every arm on every input, plus every file opened under the backend). The em2mem
prompt templates (`src/em2mem/llm/templates/*.py`) are the complete directory, because
`PromptTemplateManager` imports every file in it.

| Upstream path (under `src/backend/`) | Role in the run |
|---|---|
| `online_pipeline/realtime_ingest.py`, `frame_stream.py`, `audio_stream.py`, `stream_timeline.py`, `runtime_state.py`, `rokid_*.py`, `active_session.py`, `backpressure.py`, `file_lock.py`, `live_*.py`, `stream_status.py` | frame and audio ingest (`ingest_frame`, `ingest_audio_chunk`), rolling ASR window bookkeeping |
| `online_current/*` | M_cur: rolling 30 s current window, current-scene prompt |
| `online_short_term/frame_stream_event_builder.py`, `frame_diff_detector.py`, `mst_store.py`, `schemas.py`, `stream_chunk_manager.py`, `transcript_aligner.py`, `refine_lease.py`, `refine_status.py` | M_st: OpenCV-based event boundaries, micro-event store, 30 s window readiness |
| `online_streaming/stream_asr_processor.py`, `partial_transcript_store.py`, `transcript_backfill.py` | ASR task processing and transcript backfill into M_cur and M_st |
| `refine_mst_micro_events.py`, `online_short_term/micro_event_refiner.py` | M_st refinement (VLM caption of each micro-event) |
| `online_short_term/mst_to_episodic.py`, `episodic_window_builder.py`, `consolidation_state.py` | consolidation of refined micro-events into 30 s episodes |
| `online_memory_incremental/*`, `online_memory/*`, `online_mst_*` helpers | M_lt incremental append: caption roots, multiscale windows (3 min, 10 min, 1 h), OpenIE graph delta, semantic delta, snapshots, HippoRAG cache refresh |
| `src/em2mem/**` | EM2Mem long-term memory: OpenAI client wrapper, prompt templates, OpenIE, episodic (dense, graph-aware) and semantic retrieval, event selector |
| `src/HippoRAG/src/hipporag/**` | imported by em2mem's episodic memory and the cache refresh |
| `online_query/*`, `eval/query_rag.py`, `online_retrieval_scheme.py`, `online_llm_config.py` | question answering: routing, interaction cache and coreference resolver, M_st/M_lt retrieval, fusion, evidence packing, answer generation |
| `online_visual/*`, `online_preprocess/*`, `online_memory_edit/lock.py` | imported helpers (visual index stays off; task queue; I/O) |

Not copied: the FastAPI server (`api_server.py`), whose stream-start sequence (`_start_stream_session`,
line 2909) the adapter reproduces in `Adapter._start_stream`; the worker loops (`online_*_worker.py`),
whose task-processing calls the adapter makes directly in the same order; the model servers (Qwen3
embedding, VLM2Vec); the Android app, web frontend, Docker files, research code, and tests.
