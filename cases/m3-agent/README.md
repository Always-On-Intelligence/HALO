# M3-Agent in HALO run mode

M3-Agent (ByteDance-Seed/M3-Agent, commit 0e3e419, paper arXiv 2508.09736) watches a long video
in 30-second clips, keeps an entity-centric memory graph of faces, voices, episodic and semantic
memories, and answers questions by searching that graph over several rounds. The configuration
reviewed by the survey is the long-video QA setting: memory-7b-sft for memorization, control-32b-rl
for control, and the external multimodal graph.

## What runs

- Memorization: `m3_agent/memorization_memory_graphs.streaming_process_video` over the scripted
  clips. For each clip, `process_voices` and `process_faces` load the clip's intermediate outputs
  (the cache files the upstream code reads when present) and match each voice and face against
  the graph; `generate_memories` builds the memorization prompt
  (`prompt_generate_memory_with_ids_sft`) with the clip, the face crops and the voice transcripts;
  `process_memories` inserts the episodic and semantic memories, links them to the face and voice
  nodes and reinforces repeated semantic memories; `refresh_equivalences` merges faces and voices
  into characters; the graph is pickled.
- Control: the loop of `m3_agent/control.py` lines 162-207 for one question at a time (the
  upstream `__main__` block batches questions through vLLM). The control model answers or asks
  for a search; `control.consumer` loads the pickled graph and calls `mmagent/retrieve.search`;
  the fifth round must answer. `control.eval_answer` (the upstream GPT-4o verifier) scores each
  answer against the reference.

## What is replaced

| Upstream | Replacement |
|---|---|
| memory-7b-sft (Qwen2.5-Omni thinker, `utils/chat_qwen.get_response`) | HALO backbone. The clip is its scripted text; each face crop is shown as a text description of the face. The prompt asks for the key `video_description` but the code reads `video_descriptions` (the fine-tuned model emits the latter), so the adapter renames that key and adds an empty list for a missing key. |
| control-32b-rl (vLLM, `control.py:141,176-188`) | HALO backbone; the conversation is rendered as text with earlier turns marked |
| GPT-4o verifier (`control.get_response`) | HALO backbone in a second role, tag prefix `gpt4o-verifier` |
| text-embedding-3-large (`utils/chat_api.parallel_get_embedding`, `get_embedding_with_retry`) | all-MiniLM-L6-v2 on CPU |
| insightface (RetinaFace + ArcFace), Gemini diarization, ERes2NetV2 speaker embedding | not run; their outputs are the scripted intermediate outputs, with the MiniLM embedding of a fixed face text and voice text per person |
| face and voice matching thresholds 0.3 / 0.6 (`configs/memory_config.json`, calibrated for ArcFace and ERes2NetV2) | 0.95 for both: the same person's text scores 1.0 and different people in the inputs score at most 0.88 |
| video decoding (`utils/video_processing.process_video_clip`) | returns placeholder frames and face-crop images, so the upstream image code runs, and the clip text for the model |
| `configs/api_config.json` (left empty upstream, filled by users) | filled with placeholder endpoints in the run directory; `control.py` builds an Azure client from it at import that is never called |

Clips are processed in clip-id order (the order of the stream); upstream lists them with `glob`,
whose order depends on the filesystem. Insightface, speakerlab, hdbscan, cv2, moviepy,
qwen_omni_utils and vllm are stubbed in `sys.modules` because only the replaced steps use them.

## Cut sites

| Channel | Site | What the cut does |
|---|---|---|
| S->M | `m3_agent/memorization_memory_graphs.py:66-67` (`process_memories`) | the clip's episodic and semantic memories are not inserted into the graph |
| M->S | `mmagent/face_processing.py:160`, `mmagent/voice_processing.py:205` (`VideoGraph.search_img_nodes`, `search_voice_nodes`, `mmagent/videograph.py:614-670`) | matching sees only the nodes created in the current clip, so faces and voices kept from earlier clips no longer identify the people in a new clip |
| M->A | `m3_agent/control.py:117-131` (`search`) | no memories are returned to the control model; it sees `Searched knowledge: {}` |

A->S and A->M are not cut. Control only reads the graph. Its own earlier turns stay in the
conversation within one question, which is task-local context rather than retained memory (one
read-mode review marked it A->M; the survey's vote did not). M3-Agent does not revise its own
mechanism, so no evidence step is cut.

## Inputs

`inputs/videos.json`: four scripted videos (kitchen dinner, office handover, home with a robot,
bike shop) of three or four clips each, with faces, diarized speech and two questions with
reference answers. Names are only spoken. Most questions need people kept across clips (who said
six and who said seven, which of two women with black bobs gave an instruction), which exercises
M->S; all need memory, which exercises S->M and M->A.

## Metrics

`correct` (share of answers the upstream verifier accepts), `control_rounds`, `empty_searches`,
`text_memories`, `characters` (after equivalence merging), `identities_reused` (faces or voices
matched to a node from an earlier clip).

## Run

```bash
uv venv cases/m3-agent/.venv -p 3.11
uv pip install -p cases/m3-agent/.venv/bin/python -r cases/m3-agent/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/m3-agent --items 1 --samples 1 --workers 2 --name smoke
```

One arm of one item makes about 10-16 backbone calls (one per clip, up to five control rounds
per question, one verifier call per answer).
