# Proactive Agent (Environment Gym) in HALO run mode

**Work.** Proactive Agent (Lu et al., arXiv 2410.12361; code thunlp/ProactiveAgent at 3fcf9be). The
reviewed configuration is "Section 3.4 Proactive Agent in the Environment Gym, including retained
event/dialogue history and simulated accepted-task execution". In the gym (`gym/`), three components share a
codelinker event bus: the environment simulator turns each activity into events, the user simulator acts
and judges the agent's proposals, and the ProactiveAgent watches the events, proposes a task or stays silent,
and after the user's verdict executes the task with its operations; each executed action is again an
activity that the environment turns into events. Every component reads the shared event store through
`gather()`, so the agent's proposal prompt contains its retained event and dialogue history.

## What runs

From `core/` (unchanged, see `core/SOURCE.md`): the three gym components with their prompts and pydantic
schemas, and the installed `codelinker` package (event bus, `CodeLinker.exec`, tool-call schemas, schema
validation and JSON fixes). The adapter reproduces `gym/main.py`'s `data_loop` (lines 35-57) with a fresh
event store per run, and two changes to the driver:
- the environment-adaptation dialogue between the two simulators (lines 49-52) is not run;
- the user simulator takes its next step once the bus is idle, called by the adapter. In the gym, `user.step`
  re-fires on every event batch and waits for the agent (`user.py:51`, `88-112`); with instant cached
  replies its timers race and the next activity can arrive before the agent's verdict cycle. `action_times=0`
  switches the re-firing off, and the adapter calls `user.step` once per scripted step, the order the gym
  intends.

The real-world demo in `agent/` and `envs/` (ActivityWatch watchers, desktop toasts) is not run; the
reviewed configuration is the gym.

## What is replaced

Only codelinker's `openai` request function (`codelinker/request/openai.py`), through
`OBJGenerator.register_request_lib`. `Adapter._request` answers:
- **from the scripted episode** (`inputs/episodes.json`): the environment's scene expansion
  (`expand_scene_description`, built from the scene's description, operations and entities, with the trace
  start time), the user's profile (`update_info`), the user's next activity (`generate_activities`), and the
  environment's events for a user activity (`refine_events` with `<From User>`): the recorded ProactiveBench
  trace events, verbatim, with deltas from the trace timestamps. So the event stream is scripted.
- **with the HALO backbone**: the agent's proposal (`activeagent.py:126-130`) and its execution steps
  (`activeagent.py:70-74`).
- **with a second LLM on the same backend and cache** (tags `user:` and `env:`): the user simulator's verdict
  (`user.py:136-141`), the environment's events for the agent's executed actions (`environment.py:141-146`
  with `<From ProactiveAgent>`), and codelinker's schema-fix requests.

A forced tool call becomes an instruction appended to the system prompt (function name, description, JSON
schema of the arguments); the reply is returned as the tool call's arguments and validated by codelinker as
usual. Before that, the reply is made valid JSON as the API would return it: a code fence is removed,
backslashes that are not JSON escapes are escaped (the backbone copies code such as the Ruby regex `/\A./` into
JSON strings verbatim), and brackets left open at the end of long nested replies are closed. A reply that
still does not parse goes to codelinker's own schema-fix request, as it would with the original client. Multi-turn messages
become one transcript with `[user]`/`[assistant]` labels. Temperature is not passed on. `env.step` samples
five `events_example` lines with an unseeded `random`; the adapter seeds `random` per item and sample so all
arms draw the same samples. The gym's DEBUG logging is lowered to ERROR.

## Inputs (`inputs/episodes.json`)

Four items, each a gym scene from `dataset/new_scenes_good.yaml` paired with a recorded ProactiveBench trace
from `dataset/test_data` whose task matches the scene's user goal: `ruby_capitalize` (scene 0, `code_11`),
`java_palindrome` (scene 13, `code_12`), `fashion_brands` (scene 26, `writing_11`), `remote_work_tools`
(scene 51, `writing_14`). Each trace is split into four steps of 2 to 7 events; each step has a scripted
user activity. The trace's `task_status` annotation of a step's last event (does the user need help here)
is used only for the `label_agreement` metric. One arm makes about 8 to 16 model calls, depending on how
often the agent proposes and how many actions it executes.

## Cut sites (paths under `core/gym`)

| Cut | Site | What the cut does |
|---|---|---|
| S->M | `components/activeagent.py:111-115` and `67-68` (`agent.gather` over the event store) | events the agent has already answered (those before its last own entry) are not kept; the current events, its own proposals and actions, and the user's verdicts remain |
| M->A | `components/activeagent.py:111-129` | the proposal prompt gets no history: `hist` stays empty, so the messages are the system prompt and the current `Observations` (events, verdict and action results since the last proposal); the operations list sent at setup is part of the dropped history. Execution (lines 67-74) is unchanged |
| A->S | `components/environment.py:61,121-154` | the environment does not take up the agent's executed action (`env.step` returns for an activity whose source is ProactiveAgent), so no event reports what the agent did |

With scripted user activities, executed actions are the only route from the agent's actions to later
observations. The gym's other route, the user simulator's next activity reacting to proposals and verdicts
(`user.py:102-112`), is replaced by the script. No evidence-step cuts: nothing in the gym revises the agent's
prompts, rules or weights during a run; training happens offline on logged data
(`dataset/build_agent_trainset.py`).

## Outputs and metrics

`output` (judged) lists, per step, the agent's proposal and message to the user, or silence, and the actions
it executed. `steps` has the details (verdicts, events produced by the agent's actions). Metrics:
`proposals`, `accepted` (by the user simulator), `acceptance_rate`, `label_agreement` (share of steps where
proposing or staying silent matches the trace annotation), `executed_actions`, `observed_action_events`,
`failed_steps` (steps where the agent's reply could not be parsed, so the gym logged an error and moved on),
`backbone_calls`.

## How to run

```bash
uv venv cases/proactive-agent/.venv -p 3.11
uv pip install -p cases/proactive-agent/.venv/bin/python -r cases/proactive-agent/requirements.txt
HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/proactive-agent --items 1 --samples 1 --workers 2 --name smoke
```

`inputs/codelinker.toml` is the `private.toml` that `gym/config.py` reads (through `CODELINKER_CFG`); no
request goes through its keys.
