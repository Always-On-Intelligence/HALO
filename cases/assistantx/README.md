# AssistantX in HALO run mode

AssistantX (Sun et al., arXiv 2409.17655) is an office robot: a mobile base with a QR-locked locker,
driven over WeChat by a loop of perception, planning, decision and reflection model calls (PPDR4X). People
send it requests on WeChat; it messages people, sends them QR codes that open its locker, and drives to
them. The survey configuration is "PPDR4X office robot with persistent relational graph; transient task
buffers excluded from retention".

## What runs

`core/OfficeAssistant/main.py` runs unchanged as `__main__` (via `runpy`), with the upstream prompt
builders (`prompt_test.py`), chat helpers (`chat.py`) and state module (`global_var.py`); see
`core/SOURCE.md`. Robot `大白1号` is used, the `main.py:163` branch that has the planning step. One item
is one WeChat request. The loop runs until the model chooses `Stop`, for at most 5 iterations
(3 backbone calls each, plus the Stop-branch planning call: at most 16 calls per arm). When the loop
ends, the office plays out the robot's last instructions (it arrives, people scan) before the outcome is read.

The persistent relational graph is the text file `prompt_txt/priori_knowledge.txt`, which
`read_prior_knowledge()` (`prompt_test.py:385-388`) reads at every iteration (`main.py:165`). The
repository does not include it; `inputs/office.json` supplies one (people, desks, who holds what, who is
on duty where, who supervises whom, who borrowed what, who is away).

## What is replaced

| Upstream | Replacement |
|---|---|
| `OfficeAssistant.api.inference_chat` (GPT-4o over HTTP) | HALO backbone through `self.llm`; tag = item, sample, step, stage |
| reflection call, `main.py:405-411` | a fixed reply, no backbone call: `reflect_flag` is never `True` (`main.py:180, 417`), so `main.py` only prints the reply |
| `OfficeAssistant.prompt_assx.to_witch_robot` (missing source) | always routes to `大白1号`, keeping the message text |
| `common.wechat.WechatServer` | stub: delivers the scripted request through `main.onmessage`, hands the robot's messages and QR images to the simulated office, and delivers people's replies through `onmessage` |
| `socket_server_dabai.send_dabai_command` | simulated chassis: `move_marker` drives to a named marker; `monitor_move_status` reports arrival |
| `handing.ocSelect`, `img_encode` (missing module) | simulated locker; `ocSelect` follows the commented-out `common/LockApi.py:64-85` and writes `global_var.locker_info` in the same words (line 83) |
| `common.andro_operation.Forward_file_on_Wechat` | same success string as upstream (`andro_operation.py:105-108`); the office records the forwarded file |
| `global_var.chat_name`, `room_name` | the simulated office's contacts. Lookups ignore case and quotes; an unknown name gives `None` (upstream raises `KeyError` and the program stops) and the message is recorded as undelivered |
| `datetime`, `time`, `threading` in `main.py`'s namespace | scripted clock (+2 min per iteration), no-op `sleep`, a thread that runs its target on `start()` |

People answer by fixed rules (`inputs/office.json`): a question gets every fact whose keywords it mentions (up to three),
an absent person sends one away-notice, someone asked for an item they lack says so, the printer
attendant asks for the file, someone asked about the locker after scanning says what they did, a person
who has received what they asked for confirms once, and a QR code is scanned when the robot stands at
the holder's or recipient's desk. No model plays the people.

## Cut sites

| Cut | Site | What the cut does |
|---|---|---|
| M->S | `main.py:190-192` passes the graph to `get_perception_prompt`, inserted at `prompt_test.py:414-416` | perception gets an empty graph |
| M->A | `main.py:222-225` (planning) and `main.py:231-235` (action) pass the graph to `prompt_test.py:463` and `prompt_test.py:20-22` | planning and action get an empty graph (the Stop-branch planning call, `main.py:359-362`, uses the same builder) |
| A->S | (1) the robot's own messages, written to the chat buffers as `Assitant(yourself)` lines at `main.py:277, 281, 285, 297, 301, 305`, reach perception (`main.py:190-192`, `prompt_test.py:418-431`), which must judge whether each person "has done what you asked him to do" (`prompt_test.py:435, 442`). (2) Send QR code hands its (person, item) to `ocSelect` (`main.py:316-321`), which labels the locker door event with them (`LockApi.py:83`) in `global_var.locker_info`, read at `main.py:191` and `235` | (1) perception gets the buffers without the robot's own lines (planning and action still see them); (2) the locker reports only "the locker door was opened and closed" |

Not cut:

- **S->M and A->M.** The only write to the graph is the Stop branch (`main.py:357-370`), which appends
  the planning model's "Items location" to `priori_knowledge`. `main.py:165` re-reads the file at the
  start of the next iteration, and in between only the discarded reflection prompt reads it, so the
  write never reaches a later decision. The run records it as `graph_update_discarded`. Sensed messages
  and the robot's own actions go only to the chat and action buffers, which `main.py:377-397` clears at
  Stop and the survey configuration excludes from retention.
- **Evidence steps.** Reflection (`main.py:405-416`) compares the action with the scene before and after,
  but its Y/N answer is parsed only inside `if reflect_flag == True` (`main.py:417-455`), which never
  runs, so the attribution check does not reach `error_flag` or `reflect_history`. Nothing revises the
  mechanism.

## Inputs

`inputs/office.json`: one office graph, six people, nine map markers, and four requests:

| Item | Request | What the graph decides |
|---|---|---|
| `spare_charger` | Wu needs a charger that fits his laptop | Zheng has a spare USB-C charger; Chen has a MagSafe one and is away |
| `form_signature` | Zheng's form must be signed by "my supervisor" and returned | Prof. Gao supervises Zheng, office Room 412 |
| `print_slides` | print the slides Wu sent and bring the printout | Huang is on duty at the printer in Room 305 |
| `return_remote` | Lin wants the projector remote back from "whoever borrowed it" | Zheng borrowed it |

## Output and metrics

`output` is the record the judge compares: the request, each iteration's parsed action and its effects
(messages, QR codes, moves), people's replies and scans, and the outcome (where each requested item
ended). `trace` keeps each iteration's perception, planning and action replies. Metrics:
`task_success`, `stopped`, `steps`, `messages_sent`, `qr_codes_sent`, `qr_codes_unused`, `moves`,
`undelivered`.

## Run

```bash
uv venv cases/assistantx/.venv -p 3.11
uv pip install -p cases/assistantx/.venv/bin/python -r cases/assistantx/requirements.txt
HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/assistantx --items 1 --samples 1 --workers 2 --name smoke
```

## Known limits

- Upstream bugs run as they are: only the first `Inform` and the first `Ask` of an action are executed
  (`re.search`); if "Office Work" appears anywhere in the action, an `Inform` or `Ask` to a person is
  sent to `room_name[person]` and is lost (`main.py:274-306`); the `Wait` parser overwrites the
  instruction counter (`main.py:349`). A run whose counter drops to 0 without Stop ends as "stalled".
- Instructions avoid "/" and stay short, because `main.py:372` writes `Result/gpt4o/<instruction>.txt`
  (in a temporary working directory).
