# Vendored ContextAgent code

- Repository: https://github.com/openaiotlab/ContextAgent
- Commit: f4674bf2a1385ce829c6a7f2ea9c53871dd1a8ce
- License: the repository has no LICENSE file; `setup.py` and `pyproject.toml` declare MIT.

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `src/icl/inference_api.py` | `run_single_sample` (reasoner call, parsing, `run_tools`, `summarize_with_llm_azure`), `load_prompt_base`, `build_system_prompt`, `parse_tool_spec`, `apply_mode`, `get_azure_client` |
| `src/utils.py` | `azure_inference`, `parse_proactive_agent_results`, `execute_tools_with_memory` (two-phase executor with `$RESULT(...)` placeholders), normalizers, `parse_time_phrase` |
| `src/tool_registry.py` | discovers the tools and dispatches calls (`process_function_call`) |
| `src/config.py` | global `MODE` (`sandbox` / `live`) read by the tools and the response step |
| `src/tools/*.py` | the 20 tools and `tools/__init__.py`; in sandbox mode each returns its in-repo fake value (`src/tools/config.py` is copied because `tools/__init__.py` imports every module in the folder) |
| `prompt/baselines/icl_fs.txt` | reasoner system prompt (tool set, `{Examples}` slot, output format) |
| `prompt/prompt_summarize.txt` | response-step system prompt |

Not copied: the SFT path (`src/sft/inference.py`, `prompt/prompt_sys.txt`, `LLaMA-Factory/`), weights, the
local-model ICL path (`src/icl/inference.py`, ollama), the scorer `src/calculate_scores.py`, the shell
scripts, `data/tools/*` (read only by the tools' live branches), and the datasets. The five CAB-Lite records
the run uses and the ten CAB-train demonstrations are copied unchanged into `../inputs/` (see the notes there).
