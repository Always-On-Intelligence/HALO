# Vendored ProPerSim code (ProPerAssistant)

- Repository: https://github.com/jiho283/ProPerSim
- Commit: 013b9eefd618b075875a2ce0ce6089138c30c82f
- License: Apache-2.0 (`LICENSE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `reverie/backend_server/agent/agent.py` | the assistant (Eddy Lin): `suggest`, `update_preference_data` (preference pairs from ratings), `update_suggestion_model` (nightly update, replay buffer, `DPO_train` call), `update_total_records` |
| `reverie/backend_server/agent/cognitive_modules/suggestion.py` | `suggest` / `make_suggestion`: memory retrieval and the [MEMORY] block |
| `reverie/backend_server/agent/cognitive_modules/retrieve.py` | `new_retrieve_agent` over the evaluation memory (recency, relevance, importance) |
| `reverie/backend_server/agent/prompt_template/run_gpt_prompt.py` | `run_gpt_prompt_make_suggestion`: prompt, parsing, refine step |
| `reverie/backend_server/agent/prompt_template/gpt_structure.py` | `opensource_inference` / `opensource_safe_generate_response` (Llama path), `safe_generate_response_sugg` (refine) |
| `reverie/backend_server/agent/prompt_template/v1/system_prompt_suggestion_wo_r.txt`, `refine_suggestion.txt` | the assistant's prompts for this setting |
| `reverie/backend_server/persona/persona.py` | the user agent (John Lin): `eval_suggestion`, `init_e_mem` |
| `reverie/backend_server/persona/cognitive_modules/evaluation.py` | rating of both candidates, `perceive_suggestion_eval` (memory records and summaries of both agents) |
| `reverie/backend_server/persona/cognitive_modules/retrieve.py` | `new_retrieve` for the user agent's memory |
| `reverie/backend_server/persona/prompt_template/run_gpt_prompt.py` | `run_gpt_prompt_make_evaluation_seperate`, hourly summaries |
| `reverie/backend_server/persona/prompt_template/gpt_structure.py` | `safe_generate_response`, `safe_generate_response_gemini20`, `get_embedding` |
| `reverie/backend_server/persona/prompt_template/v1/scoring_evaluation_w_mem_five_criteria_personalized_rubric_*.txt` | the five rating prompts |
| `reverie/backend_server/persona/prompt_template/v1/summarization_*.txt`, `agent_summ_*.txt` | memory summary prompts (user agent, assistant) |
| `reverie/backend_server/{agent,persona}/memory_structures/*.py` | evaluation, associative and spatial memory, scratch |
| `reverie/backend_server/{agent,persona}/cognitive_modules/{converse,execute,perceive,plan,reflect}.py`, `*/prompt_template/print_prompt.py`, `global_methods.py`, `path_finder.py`, `opensource_inference.py`, `opensource_training_methods.py` | imported by the modules above (module-level code only, except `opensource_inference` as noted) |
| `environment/frontend_server/storage/base_the_ville_persona_{9,21}/` | `reverie/meta.json` (start date, step length, persona order) and the bootstrap memory of John Lin (persona profile and rating rubric) and Eddy Lin |

Not copied: `reverie/backend_server/reverie.py` (Django/selenium front-end loop, maze, Llama tokenizer used only
to count tokens); the adapter reproduces its per-step body for this setting (lines 437-466 and 477-479) and the
00:02:30 update (lines 389-392). Also not copied: the maze and front end, the other 30 personas, unused prompt
templates, `training_test.py`, `mmlu_eval.py`, `evaluation.ipynb`.

Not run, replaced in the adapter: Llama-3.3-70B and its LoRA adapter (`llm_model_upload`, `peft_lm_model_upload`
in `opensource_inference.py`, model and tokenizer objects), `DPO_train` (`opensource_training_methods.py`), the
OpenAI and Gemini clients, and `temp_sleep`.
