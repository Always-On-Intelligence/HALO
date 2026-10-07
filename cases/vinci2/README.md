# Vinci2 / EgoMemo in HALO run mode

Vinci2 (paper arXiv 2607.11523; code SitongGong/EgoMemo, commit 0029a33) is EgoMemo, a
training-free streaming assistant for egocentric video. As the video streams in, it writes each
clip caption into a three-level temporal memory (clip captions, activity and session summaries)
with a knowledge graph and visual features, and at every step a reasoner decides whether to stay
silent, search memory, or give the user a proactive reminder. The configuration reviewed by the
survey is the streaming proactive configuration with GPT-5-mini reasoning.

## What runs

The adapter runs the upstream CLI entry `egomemo_demo/egomemo/run.py` (`main()`), which applies
its three patches (v2 reasoning, fast memory read, trimmed entity prompt) and calls
`StreamingPipeline.run_on_video`. Arguments: `--multi_level_caption --caption_window_minutes 1`
plus the video path and working directory; everything else is run.py's default
(`caption_model=qwen_vllm`, `reasoning_model_path=gpt-5-mini`, `datasets_type=egolife`,
`step_interval=5`, `caption_window=30`, `caption_window_hours=1`, `proactive_cooldown=5`,
`pipeline_mode=async`, no questions). The one-minute activity window is the CaptainCook4D EgoServe
setting and the `PipelineConfig` default; with run.py's five minutes no activity summary would fill
in these sessions. Session summaries (one hour) only appear when the stream ends.

For each 30-second window (six frames):

- memory (`MemoryBridge.build_step`): the caption model writes the clip caption; it is stored in
  the video-segment store, inserted into the text-chunk store and the knowledge graph
  (`ainsert_streaming_caption` -> `ego_op.streaming_extract_entities`), given a visual embedding,
  appended to the caption list, and every minute the clip captions are summarised into an activity
  caption;
- reasoning (`_reason_and_route` -> `pipeline_v2_patch._reason_proactive_v2`): the first pass sees
  the current caption, the recent activity caption, the caption time ranges, its own earlier
  reminders and search requests, and outputs `[silent]`, `[search] <query>` or `[respond] <reminder>`;
  a search reads memory (`memory_bridge_fast._fast_read`: rewritten queries, multi-level text
  retrieval, entity and visual retrieval, all limited to earlier windows) and a second pass decides
  again.

## What is replaced

| Upstream | Replacement |
|---|---|
| caption model, Qwen3-VL-8B through vLLM (`videorag/llm/qwen3vl_vllm.mllm_response`) | HALO backbone; each frame is given as its scripted text. It also writes the activity and session captions. |
| reasoning model, GPT-5-mini (`StreamingPipeline._call_api_reasoning`) | HALO backbone; earlier turns rendered as text |
| gpt-4o-mini (`videorag/_llm.gpt_4o_mini_complete`: entity and relation extraction, query rewriting) | HALO backbone |
| text-embedding-3-small (`videorag/_llm.openai_embedding`) | all-MiniLM-L6-v2, zero-padded to the 1536 dimensions the stores are built with (cosine similarity unchanged) |
| ImageBind (`vdb_nanovectordb`: `_get_embedder`, the pytorchvideo pre-processing, `encode_string_query`) | all-MiniLM-L6-v2 on the frames' scripted text and on the query, zero-padded to 1024 dimensions |
| tiktoken `o200k_base` (downloaded on first use; offline here) | a local word-and-punctuation tokenizer; token counts only gate truncation limits these sessions never reach |
| video decoding (`sample_frames_by_interval`) | placeholder images for the scripted frames |
| ollama, neo4j, hnswlib, xxhash, faster_whisper, qwen_vl_utils, moviepy, decord, cv2 | stubbed; only replaced or unused paths import them |
| `pipeline_mode=async` (memory thread may run ahead of reasoning, `streaming_pipeline.py:563-671`) | the same two loop bodies in lockstep (memory for window i, then reasoning for window i), so no later window leaks into an earlier decision and runs are reproducible |

The plain-function form of the replaced clients matters: `dataclasses.asdict` deep-copies the LLM
configuration, as with the upstream functions.

## Cut sites

| Channel | Site | What the cut does |
|---|---|---|
| S->M | `egomemo/memory_bridge.py:262, 313, 326, 337, 344` in `build_step` (`_store_frames`, `ainsert_streaming_caption` = `videorag/egograph_retrieval_optimize_.py:2994`, `_insert_visual_embedding`, `_captions.append`, `_accumulate_multi_level`) | the caption is still produced and reaches the reasoner as the current observation, but no store admits it, so there are no stored captions, graph, visual features or activity captions |
| M->A | `egomemo/pipeline_v2_patch.py:680-685, 688-697, 778` in `_reason_proactive_v2` | the reasoner reads an empty memory: no caption time ranges, no recent activity caption, and a search returns the store's empty-result message |
| A->M | `egomemo/pipeline_v2_patch.py:771-775, 850-856` | the reasoner's own reminders, search requests and their times (`_proactive_history`, `_last_proactive_search`, `_last_proactive_time_by_kind`) are not kept for later windows |

The survey labels S->M and M->A as reported; A->M is cut because the code keeps the reasoner's
own reminders and search requests and feeds them back into later decisions. The caption prompt
does not read memory (no M->S), and searches read stored memory only, never steering capture or
captioning (no A->S; caption reconstruction is disabled by the fast read). EgoMemo does not revise
its own mechanism, so no evidence step is cut.

## Inputs

`inputs/sessions.json`: four scripted sessions of four 30-second windows, six frames each (eggs on
a stove before leaving the house, a phone left on a cafe table, a second dose of a once-daily
tablet, a garden tap left running). In each, the right reminder depends on an earlier window, and
the last window shows the user dealing with it, so a repeated reminder is redundant. The `ideal`
field is shown only to the judge.

## Metrics

`reminders`, `searches`, `stored_captions`, `activity_captions`, `kg_nodes`. The run result also
keeps per-window decisions with search queries, the stored captions and the activity captions.

## Run

```bash
uv venv cases/vinci2/.venv -p 3.11
uv pip install -p cases/vinci2/.venv/bin/python -r cases/vinci2/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/vinci2 --items 1 --samples 1 --workers 2 --name smoke
```

One arm of one item makes about 18 backbone calls (4 captions, 4 graph extractions, 4 first
passes, 2 activity captions, 1 session caption at the end, and 3 per search). Arms share cached
replies wherever their prompts are identical.
