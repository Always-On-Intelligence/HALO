# Vendored ABot-Claw code

- Repository: https://github.com/amap-cvlab/ABot-Claw
- Commit: 39c9ffc94a84f2e6baac431a9bff9771111f8539
- License: no license file at the repository root (`service_layer/VLAC/LICENSE` covers VLAC, which is not copied).

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `service_layer/SpatialMemory/app/__init__.py`, `config.py`, `schemas.py`, `embeddings.py`, `storage.py`, `api/__init__.py`, `api/routes.py`, `services/__init__.py`, `services/memory_service.py`, `services/task_service.py` | the shared memory service. The adapter builds the FastAPI app as `SpatialMemory/main.py:11-22` does and the agent's HTTP requests reach it through FastAPI's `TestClient`: routes, pydantic validation, `MemoryService`, `SqliteStore`, hash text embeddings |
| `openclaw_layer/MISSION.md`, `ROBOT.md`, `SERVICE.md` | workspace files in the agent's context. `ROBOT.md` and `SERVICE.md` get the operator fill-ins they ask for (base URLs, service host, local notes) at run time |
| `openclaw_layer/setup.sh` | read for the AGENTS.md session-checklist lines it inserts (its `insert_block`) |
| `openclaw_layer/skills/*/SKILL.md` (8 skills) | the skills, in the agent's context |

Not copied:

- The OpenClaw runtime. `setup.sh` installs it from openclaw.ai; it is a TypeScript application, not part
  of the repository. The adapter ports its agent loop (see `../README.md`).
- `service_layer/SpatialMemory/main.py` (imports `uvicorn`; its app construction is reproduced),
  `README.md`, `SERVICE_AGENT.md`, `pipelines/`, `test_smoke.py`.
- `service_layer/VLAC/` (InternVL2 through ms-swift and torch). Ported in the adapter: the service contract
  (`main.py:54-159`), the 'v3' prompt (`evo_vlac/utils/model_utils.py:74`), the system prompt
  (`model_utils.py:284`), the pairing of `get_trajectory_critic` for one reference and one current image
  (`model_utils.py:556-631`) and `critic_to_value_simple` (`model_utils.py:917-933`).
- `service_layer/YOLO/`, `service_layer/GraspAnything/` (GPU models). Requests to them get HTTP 503.
- `robot_layer/` (Piper agent server on ROS and MoveIt). The robots are simulated; their execution history
  keeps the last 10 executions and lists them newest first, as `code_executor.py:549-552, 641-643` and
  `routes/code_routes.py:325-333` do.
- `openclaw_layer/HEARTBEAT.md` (heartbeat polls, not task sessions), `docs/ABOTCLAW_SDK_DISCOVERY.md`,
  `skills/abotclaw-bundle/scripts/` and `references/` (not loaded), `README.md`, `tech_report/`.
