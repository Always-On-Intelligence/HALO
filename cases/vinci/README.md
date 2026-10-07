# Vinci in HALO run mode

Vinci (OpenGVLab/vinci, commit a3b9dfa, paper arXiv 2412.21080) is an assistant for head-mounted
or phone cameras. The configuration reviewed by the survey is the paper's wearable assistant
served by `vinci-inference`: while the stream runs, the backend asks the model every few seconds
to describe the user's action, and the service stores each description with its timestamp; after
the wake word, the user's question is answered from the current frames and that history. No
chat-history backend is assumed (`Chat.use_chat_history` stays False; answers are never stored).

## What runs

The adapter calls the service's entry point `vinci-inference/app/models/internvl.chat` the way
the backend does:

- at every scripted moment, `chat(..., silent=True)`: `IntervlChat.chat_unsafe_silent` builds the
  prompt "Frame1: <image> ... 现在视频到了 X 秒处. 简单的描述视频中我的动作." and appends
  `(timestamp, description)` to the session history in `history_cache`;
- for every question, `chat(question, ..., silent=False)`: `IntervlChat.chat_unsafe` prefixes the
  timestamp and calls `add_history` with the last ten history entries (`get_history`), then asks
  the model.

Frame pre-processing (`vl_open.dynamic_preprocess`, `build_transform`), the session clock
(`get_timestamp`), the history cache and all prompts run from the upstream code. The service's
prompts are Chinese whatever the language setting (`add_history` is called without the language
argument in the branch used), so answers with history come back in Chinese.

## What is replaced

| Upstream | Replacement |
|---|---|
| Vinci-8B (InternVL chat model: `AutoModel.from_pretrained`, `model.chat`, `vl_open.py:111-127`) | HALO backbone; each `FrameN: <image>` placeholder is filled with that frame's scripted text. The frames themselves are small placeholder images, so the pre-processing runs. |
| tokenizer (`AutoTokenizer.from_pretrained`) | not loaded; only the replaced model used it |
| `IntervlChat` per CUDA device, streaming (`internvl.py:236-246`, `stream = True`) | one `IntervlChat` on `cpu` with `stream=False`. Both branches of `chat_unsafe` build the same prompt (`internvl.py:205-234`); with `stream=True` the silent calls would also push their text into the shared `TextIteratorStreamer`, which the next streamed answer reads first. |
| `.cuda()` on pixel tensors (`internvl.py:141,174`) | a no-op (`torch.Tensor.cuda`), CPU only |
| wall clock (`internvl.py:249-257`) | follows the scripted moment times |
| FastAPI layer (`main.py`, `service/`, `util/`) and the `vinci-be` backend (wake word, speech recognition, periodic requests; a prebuilt docker image) | not run; the adapter issues the backend's requests |

## Cut sites

| Channel | Site | What the cut does |
|---|---|---|
| S->M | `vinci-inference/app/models/internvl.py:146` (`history.append` in `chat_unsafe_silent`) and `:279` (`history_cache.put`) | the silent description is produced but not added to the session history |
| M->A | `vinci-inference/app/models/internvl.py:206` (`add_history`) | `add_history` receives an empty history, so the answer prompt carries no earlier descriptions |

No other channel is realized: the silent prompt does not read the history (no M->S), answers
are not stored (no A->M, `sep_chat` is False), and questions do not steer the descriptions (no
A->S). Vinci does not revise its own mechanism, so no evidence step is cut. Because the history
is written only by sensing and read only by answering, the two cuts give the same answer prompt.

## Inputs

`inputs/streams.json`: four scripted egocentric streams (leaving home, cooking pasta, a grocery
run, an office afternoon) of six to eight moments with four text frames each, and two questions
per stream whose answers depend on earlier moments (where the keys went, whether the water was
salted, which list item is missing, where the USB drive is).

## Metrics

`history_entries` (entries stored at the end), `history_entries_at_question` (entries that
reached the answer prompt), `answer_chars`.

## Run

```bash
uv venv cases/vinci/.venv -p 3.11
uv pip install -p cases/vinci/.venv/bin/python -r cases/vinci/requirements.txt
HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/vinci --items 1 --samples 1 --workers 2 --name smoke
```

One arm of one item makes 8-10 backbone calls (one per moment, one per question).
