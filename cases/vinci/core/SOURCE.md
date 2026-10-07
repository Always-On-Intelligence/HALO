# Vendored Vinci code

- Repository: https://github.com/OpenGVLab/vinci
- Commit: a3b9dfabc184ded110d5f28daa4f132e5bdcebaa
- License: the repository has no license file and its README states none.

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `vinci-inference/app/models/internvl.py` | the inference service: `chat` (entry point), `IntervlChat.chat_unsafe_silent` (periodic description stored with its timestamp), `IntervlChat.chat_unsafe` (answering), `add_history` (history prompt), `get_history` (last ten entries), `get_timestamp` (session clock) |
| `vinci-inference/app/models/__init__.py` | package file; imports `chat` and `stream_chat` |
| `vinci-inference/app/global_var/cache.py`, `global_var/__init__.py` | `FIFOSafeCache`, the per-session history store |
| `vl_open.py` | `Chat` (model holder: transform, generation config), `dynamic_preprocess`, `build_transform` |

Not copied: the FastAPI layer (`vinci-inference/app/main.py`, `service/`, `data.py`, `util/`,
`exception/`), which decodes frames and wraps replies; the Gradio demo (`demovl.py`); the SEINE
video generation (`generation/`); and the `vinci-local` docker stack, whose backend (`vinci-be`,
wake word, speech recognition, periodic silent requests) is a prebuilt image with no source here.
The adapter makes the backend's requests: a silent request at every scripted moment and an
answering request for every question.
