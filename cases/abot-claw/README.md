# ABot-Claw in HALO run mode

ABot-Claw (AMAP CV Lab, arXiv 2604.10096) runs one OpenClaw agent over a robot fleet (Agilex Piper arm,
Unitree G1 humanoid, Unitree Go2 quadruped). The fleet shares a spatial and visual memory service
(SpatialMemory) and a progress critic (VLAC, a vision-language reward model). The survey configuration is
"ABot-Claw OpenClaw orchestration with shared multi-robot spatial/visual memory and online critic".

## What runs, what is ported, what is simulated

| Part | How it runs |
|---|---|
| SpatialMemory service (`core/service_layer/SpatialMemory/app/`) | **executed**, unchanged: the app is built as `SpatialMemory/main.py:11-22` builds it and reached through FastAPI's `TestClient`, so the agent's requests go through the real routes, pydantic schemas, `MemoryService` and `SqliteStore` |
| OpenClaw workspace (`MISSION.md`, `ROBOT.md`, `SERVICE.md`, 8 `SKILL.md`, the AGENTS.md checklist lines from `setup.sh`) | **used verbatim** as the agent's context; `ROBOT.md`/`SERVICE.md` get the fill-ins they ask the operator for (base URLs, service host, local notes) |
| OpenClaw agent loop | **ported**: the runtime is a TypeScript application installed by `setup.sh`, not part of the repository. One backbone call per turn; context = a short runtime note + the workspace files + the skills; the agent acts only through HTTP requests (the curl calls the skills show), written as one JSON object per turn; up to 10 requests per turn; a session ends with a reply or at its turn cap. Each request opens a new session; memory and robot state persist |
| VLAC critic service | **ported**: contract of `VLAC/main.py:54-159`; prompt 'v3' (`model_utils.py:74`) with `[image: <description>]` in place of each `<image>`; system prompt `model_utils.py:284`; `image_list=[reference, current]` as in `get_trajectory_critic` (`model_utils.py:556-631`); `critic_to_value_simple` (`model_utils.py:917-933`) |
| Robots (Go2, G1, Piper) | **simulated**: a skill API per robot (`/skill/navigate`, `/observe`, `/pick`, `/place`, Piper's `/insert`, `/health`, `/stop`, `/code/result`, `/code/history`, plus a guide and SDK page). Detections include people. Idle mobile robots return to the dock between sessions. The repository ships only the Piper code-execution server (ROS/MoveIt); the paper's unified embodiment interface (§2.2) maps robot functions to such skills. `/code/history` keeps the last 10 executions and lists them newest first, as `code_executor.py:549-552, 641-643` and `routes/code_routes.py:325-333` do |
| YOLO, GraspAnything | not run (GPU models); requests to them get HTTP 503 |

Replacements:

- The agent's model and the VLAC model (InternVL2) are the HALO backbone. The critic's system prompt gets
  one added sentence giving the fine-tuned model's answer format (a signed percentage; the service manual
  shows `critic_list: [-40.0]` and `critic_to_value_simple` divides by 100), which the backbone does not know.
- Images are text. `observe` stores a frame description under an `image_path` (`/data/frames/...jpg`),
  which SpatialMemory and VLAC accept like the local paths they accept upstream. SpatialMemory's
  `decode_image_input` resolves those paths, its image embedding (colour statistics, `embeddings.py:60-76`)
  embeds the description with the upstream `text_embedding` (`embeddings.py:47-57`), and evidence is kept
  as text under `/data/memory/images/<id>.jpg`.
- The agent sees structured observation results (detections with poses and supporting surface), as
  generated robot code would print them, not the frames.
- For paired arms: the memory service's clock is the scripted clock, its UUIDs are derived from the item,
  the sample and a counter, its data directory appears as `/data/memory`, and the critic reports a fixed
  `latency_ms`.

## Cut sites

| Cut | Site | What the cut does |
|---|---|---|
| S->M | memory admission, `memory_service.py:64-183` (`upsert_object`, `upsert_place`, `ingest_semantic_frame`, `ingest_keyframe_batch`) | writes backed by sensed evidence run against a scratch store: the agent gets the service's normal reply (ids included), but later queries do not see them. Backed means an observed frame as the image; for an object, a detection of that object within 2 m; for a place, a robot pose the robots reported within 1 m |
| A->M | the same admission site, and the robot execution history | writes without sensed backing (the agent's own action context: where it put something, what it did) go to the scratch store the same way; robots keep no execution history |
| M->A | query routes, `routes.py:44-70` -> `memory_service.py:224-278` | query results reach the agent empty |
| A->S | critic task text, `VLAC/main.py:126-141` -> the `<task>` slot of `model_utils.py:74` | the agent's task description, which conditions how the critic reads the frames, becomes "the current task" |
| M->S | critic reference image, `VLAC/main.py:132` | a reference image that comes from memory evidence (progress-critic SKILL.md, "Integration with Memory") becomes a blank grey frame |
| attribution (evidence step) | critic current image, `VLAC/main.py:131` | the current image becomes the same robot's frame from before its latest action, so the score concerns a state that is not that action's result |

ABot-Claw does not revise its own mechanism, so `record`, `outcome` and `revision` are not cut;
attribution is cut because the critic's check of an action's result is the system's own feedback site.

## Inputs

`inputs/fleet.json`: seven named places, three robots, eight objects, place anchors seeded into memory,
and four items:

| Item | Sessions | What it exercises |
|---|---|---|
| `first_aid` | Go2 patrols the kitchen and meeting room B and saves what it sees (6 turns); later, bring the first-aid kit to the entrance (7 turns) | S->M (patrol writes), M->A (where the kit was seen) |
| `toolbox_back` | G1 moves the toolbox to the storage shelf (6 turns); later, bring it back to the workbench (7 turns). Memory holds yesterday's toolbox pose | A->M (record of the move, execution history) |
| `meeting_setup` | set up meeting room B "like last time" (9 turns); last time exists only as a semantic frame in memory | M->A, M->S (memory frame as critic reference), A->S |
| `plug_in` | Piper plugs a USB cable into the hub (8 turns); the first insertion rests on the housing; detections look the same either way, only the frames differ | A->S, attribution |

Backbone calls per arm: at most the sum of the turn caps plus the critic calls (at most about 15).

An object counts as brought to a place when it lies there or a robot standing there holds it; a goal that
names a surface (the meeting-room table) needs it placed there.

## Output and metrics

`output` is the record the judge compares: per session the human's request, each robot action and
observation, each memory read and write, each critic score, the agent's reply, and the end state of the
requested objects. Metrics: `task_success`, `robot_actions`, `observations`, `memory_writes`,
`memory_queries`, `critic_calls`, `turns`, `failed_requests`, `replied`.

## Run

```bash
uv venv cases/abot-claw/.venv -p 3.11
uv pip install -p cases/abot-claw/.venv/bin/python -r cases/abot-claw/requirements.txt
HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/abot-claw --items 1 --samples 1 --workers 2 --name smoke
```

## Known limits

- The memory skill's examples do not match the service schema (`name` instead of `object_name`, no
  `robot_pose`; the semantic example has no `image`), so the agent's first writes usually fail with 422 and
  it corrects them from the error detail. This is upstream behaviour and costs a turn.
- The S->M / A->M split at admission is a rule about the write's backing (frame or detection versus
  neither), not a label the system itself keeps.
- OpenClaw's own system prompt, tools and memory files are not reproduced; only the ABot-Claw workspace is.
- In one-sample checks of all four items the agent never wrote a record of its own actions to memory and read
  `/code/history` once (an earlier `meeting_setup` run, looking for the previous setup). In `toolbox_back` it
  found the moved toolbox by searching, so A->M changed nothing there; the full run will show how often it matters.
  `first_aid` (the smoke item) makes no critic call, so the critic cuts tie there; `meeting_setup` and `plug_in`
  call the critic, and `meeting_setup` used the memory frame as its reference.
- The robots' skill API, place names on the shared map, and the people and objects are this case's
  assumptions (see `inputs/fleet.json`).
