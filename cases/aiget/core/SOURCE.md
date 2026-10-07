# Vendored AiGet code

- Repository: https://github.com/Synteraction-Lab/AiGet
- Commit: 92b17f82a4e54965fc40ce9ea21e919a753ab6b7
- License: MIT (`LICENSE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `src/Module/LLM/LLMPipeline.py` | `get_llm_response`: perception, history retrieval, generation, novelty filter, output processing |
| `src/Module/LLM/task_description/*` | the prompts, including `user_profile` and the `[USER_PROFILE_PLACEHOLDER]` sites |
| `src/Storage/reader.py`, `src/Utilities/constant.py` | prompt loading |
| `src/Utilities/process_json.py` | `detect_json` |
| `src/Utilities/sentence_similarity.py` | `find_most_relevant_history`, `filter_new_items` (all-MiniLM-L6-v2) |
| `src/**/__init__.py` | package files (empty) |

Not copied: the model clients (`Gemini.py`, `GPTVision.py`, `Groq.py`), which the adapter replaces with the
HALO backbone, and the Tk front end (`src/Frontend.py`), whose history write (lines 476-492) and timer
request (lines 391-421) the adapter reproduces in `Adapter._record` and `Adapter._visit`.
