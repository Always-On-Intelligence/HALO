# Vendored ProactiveAgent code (Environment Gym)

- Repository: https://github.com/thunlp/ProactiveAgent
- Commit: 3fcf9beebe256b86871659fbb12541c41c9381b9
- License: Apache-2.0 (`LICENSE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `gym/components/activeagent.py` | the Proactive Agent: proposal from the gathered history (`step`), execution after the user's verdict (`exec`) |
| `gym/components/environment.py` | environment simulator: scene setup, events for every activity (`step`), agent operations list |
| `gym/components/user.py` | user simulator: profile, next activity (`step`), verdict on a proposal (`judge`) |
| `gym/components/base.py` | `BasicComponet.gather`, the JSON view of the shared event store every component reads |
| `gym/channel.py`, `gym/config.py` | channel tags; codelinker client and event sink singletons, logging |
| `gym/models/env.py`, `gym/models/user.py` | pydantic schemas of the tool-call replies |
| `gym/__init__.py`, `gym/components/__init__.py`, `gym/models/__init__.py` | package files |
| `dataset/new_scenes_good.yaml` | the gym scene pool (environment and user configs); scenes 0, 13, 26 and 51 are used |
| `dataset/test_data/code_11.json`, `code_12.json`, `writing_11.json`, `writing_14.json` | recorded ProactiveBench traces whose events form the scripted event stream; their `task_status` labels feed one metric |

The `codelinker` package (PyPI 0.3.27, the event bus `EventSink`/`EventProcessor` and the request layer
`CodeLinker.exec`/`OBJGenerator`) is installed in the case venv and runs unchanged, except that its
`openai` request function is replaced by the adapter (`OBJGenerator.register_request_lib`).

Not copied: `gym/main.py` (the adapter reproduces `data_loop`, lines 35-57, without the adaptation phase at
lines 49-52 and without the jsonl dump), `gym/components/reward.py` (only used with `USE_ACTIVERM=True`, not the
gym default), `gym/example.yaml` (its environment equals scene 0), the real-world demo in `agent/` and `envs/`
(ActivityWatch watchers), the evaluation and dataset-building scripts, and the reward-model data.
