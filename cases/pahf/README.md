# PAHF in HALO run mode

PAHF (Learning Personalized Agents from Human Feedback, facebookresearch/PAHF at commit 7a11213) keeps a
per-user memory of preference notes. Before acting, the agent may ask the user one clarifying question; after
acting, it receives the user's feedback. Answers and feedback are summarized into notes that later actions
retrieve. The survey reviewed "Full pre-action plus post-action PAHF with GPT-4o and the default SQLite
per-user memory, in feedback-enabled learning/adaptation phases".

## What runs

The run uses PAHF's embodied (household robot) agent and benchmark. Each item is one short session with one
persona from PAHF's own data:

1. **Learning request**: one task from `original_scenarios_A.json`, run as phase 1 runs it, with pre-action
   clarification and post-action feedback (`EmbodiedAgent.run_study`, `enable_pre_feedback=True`,
   `enable_post_feedback=True`).
2. **Two later requests**: tasks from `original_scenarios_B.json`, run as phase 2 runs them, without feedback
   and with the no-ask action prompt. Request 1 is the phase-2 version of the learning task (same situation,
   new wording and scene). Request 2 is a different situation whose scene contains the learned object.

Everything per task is upstream code: option generation (`utils/agent_utils.py:28-46`), the LLM ground-truth
judge (`agents/embodied_agent.py:123-138`), memory retrieval and summary (`agents/base.py:45-79`), action
(`embodied_agent.py:179-197`), clarification (`base.py:81-145`), the simulated user's feedback
(`embodied_agent.py:226-236`), and the feedback-to-memory update (`embodied_agent.py:242-306`) into a fresh
SQLite memory made by `initialize_memory_banks` (`utils/agent_utils.py:69-128`).

Settings follow `run_agent.py --agent embodied`: SQLite memory, both feedback types in learning, none in
evaluation. Departures: one learning task in one iteration (the CLI default runs every phase-1 task three
times), and two evaluation tasks.

Why the embodied agent and not the shopping agent: a first version used the shopping benchmark. With one
learning task the agent learns one feature preference, and the shopping action prompt buys only when every
feature of an option is confirmed, so the run with memory declined both later purchases while the run
without memory fell back to the prompt's default pick. That measures the size of the learning phase, not the
channels. Embodied tasks turn on one object per situation, so one learning task can decide a later request.

## Replacements

| Upstream | Replacement |
|---|---|
| `utils/llm.py` `LLMClient` (OpenAI, GPT-4o for agent and simulated user) | stub module `utils.llm` with the same `generate()` interface. Agent calls go to the HALO backbone. The simulated user's calls (`use_human_model=True` at `base.py:132`; the post-action call with the persona as system prompt at `embodied_agent.py:229-236`, which upstream sends to the agent model) go to a second backbone role tagged `user:`. The benchmark's option generator and ground-truth judge are tagged `env:` and `gt:`. Temperature (1.0) and `max_tokens` (512) are not passed on. |
| `DragonPlusEmbedding` (`memory/banks.py:20-94`, facebook/dragon-plus query and context encoders, not in the local cache) | all-MiniLM-L6-v2 on CPU, normalized embeddings, so the bank's dot product stays a cosine similarity |
| `memory/banks.py` (does not parse: `FAISSMemoryBank` IndentationError at lines 580-581, 639-650) | the unchanged lines 1-413 are executed as `memory.banks`; `FAISSMemoryBank` is a placeholder that raises (unused by the SQL configuration) |
| `faiss` (imported at `banks.py:14`, `embodied_agent.py:21`) | empty stub module, since only the FAISS bank uses it |
| `pdb.set_trace()` (`embodied_agent.py:174`, reached only on malformed generated options) | raises instead of blocking the worker on its stdin |

## Cut sites (receiving end)

| Channel | What is withheld | Site |
|---|---|---|
| S->M | user answers and post-action feedback are not admitted to memory | `SQLiteMemoryBank.add` / `update_memory` (`memory/banks.py:309`, `:270`) drop the write, for the Q&A note (`agents/base.py:135-143`) and the feedback note (`agents/embodied_agent.py:244-306`) |
| M->A | retrieved notes do not reach Action | `simple_memory_retrieval` as called in `retrieve_memory_context` (`agents/base.py:66`) returns nothing, so the summary appended to the action prompt (`embodied_agent.py:186-193`) is PAHF's own empty-memory summary |
| A->S | the robot's question does not reach the user | `handle_pre_feedback` runs its own no-answer branch (`base.py:119-124`, "[No answer provided]") instead of the simulated-user call (`base.py:126-133`); the question is still generated (`base.py:113-115`) and Action still offers "Ask human" |
| A->M | the robot's question is withheld from the memory note writer | the Q&A prompt (`base.py:137`) reaches the model without its `Question: ...` line, so the note is written from the user's reply alone |

M->S is not realized: no memory reaches question generation or the simulated user. PAHF does not revise its
own mechanism (memory holds per-user preference notes, which are content), so no evidence step is cut. The
chosen option itself is never written to memory; the only action content that reaches memory is the
robot's question.

## Inputs

`inputs/items.json`: six personas (Alex, Raven, Nova, Finn, Casey, Ethan). Each learning situation has a
counterintuitive preference (drowsy -> herbal tea, stressed -> black coffee, hot -> hot herbal tea, morning ->
chamomile tea, tired -> warm orange juice, sick -> cold orange juice). The judge sees the earlier request, the
persona's own preference line for the later request, and the object the persona wants (`context_same`,
`context_other`).

## Judged outputs and metrics

- `output`: decision and reasoning on later request 1 (same situation); `output_other`: on request 2
  (different situation). `run.yaml` lists every cut twice, once per field; the second run of a cut reads
  every reply from the cache.
- Metrics: `test1_correct`, `test2_correct`, `test_accuracy` (PAHF's own correctness against its LLM
  ground-truth judge), `learn_correct`, `learn_asked`, `notes_after_learning`, `backbone_calls`.

## Run

```bash
uv venv cases/pahf/.venv -p 3.11 && uv pip install -p cases/pahf/.venv/bin/python -r cases/pahf/requirements.txt
cd HALO && HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  HALO_CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/pahf --items 1 --samples 1 --workers 2 --name smoke
```

Backbone calls per arm: about 20 in the original arm (options, ground truth, retrieval and action for each
of three tasks; question, answer, Q&A note, second action, feedback and feedback check in learning). Six of
them (options and ground truth) are identical in every arm and come from the cache.

## Smoke result (alex_drowsy, 1 sample)

The learned notes were "Alex prefers herbal tea over an energy drink or black coffee" and "Alex prefers
herbal tea", without the drowsy condition. With memory the robot brought herbal tea for the drowsy request
(right) and also for "my favorite drink" (wrong, black coffee). Cutting S->M or M->A reversed both. A->S and
A->M left both decisions unchanged: under A->S the post-action feedback still taught the preference.
