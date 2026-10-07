# LightMem-Ego in HALO run mode

LightMem-Ego (zjunlp/LightMem-Ego, commit 3c023df) is a self-hosted memory service for smart glasses
and phones. A realtime stream of frames and audio feeds three memory tiers: a rolling current window
(M_cur), short-term micro-events (M_st), and a consolidated long-term memory (M_lt, built by EM2Mem).
The wearer asks questions and gets answers grounded in that memory. Survey configuration: "Phone/glasses
client with hierarchical event memory and experience QA".

## What runs

The adapter drives the vendored backend (`core/src/backend`, 140 unchanged files, see `core/SOURCE.md`)
in one process, in the order the API server and the worker processes run it:

1. stream start in `frame_audio_stream` mode (the calls of `api_server._start_stream_session`);
2. `ingest_frame` for every frame and `ingest_audio_chunk` for every 1 s audio chunk
   (`online_pipeline/realtime_ingest.py`): M_cur update, OpenCV event boundaries, M_st micro-events,
   rolling ASR windows;
3. ASR tasks through `process_stream_asr_task` (transcript backfill into M_cur and M_st), each window
   once the frame event around it has closed (10 s after the window ends);
4. `refine_session` (VLM caption of every micro-event), `build_episodic_from_mst` (30 s episodes),
   `IncrementalMemoryAppender.append_ready_episodes` (M_lt: multiscale rewrite, OpenIE, semantic delta);
5. two questions through `query_session`, as the query worker calls it: routing, interaction cache
   and coreference resolver, M_st and M_lt retrieval, evidence packing, answer.

Each run uses its own temporary project root (sessions, task queues, em2mem caches), so arms never
share state. About 13 model calls per arm: 5 refines, 1 episode, 3 multiscale rewrites, 2 OpenIE, 2 answers.

## Replacements

| Upstream | In this run |
|---|---|
| OpenAI-compatible LLM/VLM (`gpt-5.4`: refine, episodic builder, OpenIE, multiscale rewrite, event selector, answers) | `openai.OpenAI`/`AsyncOpenAI` replaced by a client that sends the chat messages to the HALO backbone; JSON mode returns the bare JSON object |
| attached images | the scripted text of the frame. em2mem's `OpenAIModel.encode_image` (`src/em2mem/llm/openai_gpt.py:486`) passes the frame file through instead of re-encoding it, so the client stub can look the frame up |
| camera frames | 320x240 JPEGs in a per-scene colour (so the upstream detector splits scenes) with the frame index coded in a corner; their content is the scripted text |
| Xfyun/WhisperX ASR and ffmpeg window assembly (`online_streaming/stream_asr_processor.py:204`, `:399`) | the scripted speech that starts in the ASR window |
| Qwen3-Embedding-4B text embeddings | all-MiniLM-L6-v2 on CPU through the upstream `Qwen3EmbeddingModel` wrapper (`EM2MEM_TEXT_EMBED_MODEL`) |
| VLM2Vec visual embeddings | off (`EM2MEM_VISUAL_BACKEND=mock`, `EM2MEM_AUTO_VISUAL_EMBEDDING=0`), as in the Docker default without model weights |
| `decord` (video decoding in em2mem's client) | an empty stub; this run sends no video prompts |

Settings changed from the Docker `.env`: `EM2MEM_ANSWER_LANGUAGE=en` (default `zh`; the sessions are in
English), `EM2MEM_MCUR_STALE_SECONDS=1000000` (M_cur goes stale 60 s after the last frame by wall
clock; here the questions follow the last frame in stream time while memory building takes minutes of
wall time), `EM2MEM_INCREMENTAL_HIPPORAG_REFRESH_SUBPROCESS=0` (run the cache refresh in-process
instead of a subprocess). `import torch` happens before the backend import, because faiss and torch
load conflicting OpenMP runtimes on macOS.

Upstream behaviour kept as is: the HippoRAG cache refresh after each append fails with
`NameError: name 'em2mem_memory' is not defined` (`online_memory_incremental/hipporag_cache.py:452`
assigns `world_memory`, line 457 reads `em2mem_memory`). The appender catches it and marks the cache
lagging; the query path uses EM2Mem's dense episodic index and does not need that cache.

## Cut sites

| Channel | Site (core/src/backend) | What is withheld |
|---|---|---|
| S->M | `online_short_term/mst_store.py:164` `MSTStore.append_events`, `:206` `backfill_transcript_segments` | frames and transcripts are not admitted to M_st, so nothing reaches M_lt; M_cur (the current window, S->A) still updates |
| M->A | `online_query/query_engine.py:2783` `_generate_answer_from_evidence`, `:3737` `_build_short_term_llm_prompt`, `online_query/coreference_resolver.py:46` `CoreferenceResolver.resolve` | M_st, M_lt and interaction-cache evidence and their keyframes are removed from the answer prompt (M_cur evidence and current frames stay); the cache is not used to rewrite the question |
| A->M | `online_query/interaction_cache.py:177` `InteractionCache.update_from_query_result` | the answered turn (question, answer, entities, time ranges, evidence ids) is not written to the interaction cache that the next question's resolver and retrieval boost read |

The survey labels A->M as not reported; the code realizes it through the interaction cache, so it is
cut here. M->S and A->S have no site: memory does not steer what is sampled or how frames are
interpreted (refine sees only the event's own keyframes and transcript), and answers do not change
capture. LightMem-Ego does not revise its own mechanism, so no evidence step is cut.

## Inputs

`inputs/sessions.json`: five 44 s sessions (home morning, pharmacy and cafe, office, car park and mall,
supermarket call), one text frame every 2 s over four scenes, one or two speech lines. Two questions at
the end with the capture still running. Q1 needs something from the first 12 s, outside M_cur's 30 s
window. Q2 is a follow-up whose pronoun ("she", "it", "those") resolves only through the first exchange.
`summary` and `expect` go to the judge and the metrics only.

Outputs: `output` (answer to Q1), `output_q2` (answer to Q2), `context_q2` (judge context with the first
exchange), `trace` (route, sources, selected evidence, resolved question). Metrics: `mst_events`,
`mst_refined`, `mlt_episodes`, `q1_fact_recall`/`q2_fact_recall` (share of expected keywords in the
answer), `q2_followup_resolved` (the resolver treated Q2 as a follow-up), `model_calls`.

## Run

```bash
uv venv cases/lightmem-ego/.venv -p 3.11
uv pip install -p cases/lightmem-ego/.venv/bin/python -r cases/lightmem-ego/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/lightmem-ego --items 1 --samples 1 --workers 2 --name smoke
```
