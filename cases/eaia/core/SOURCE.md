# Vendored EAIA code

- Repository: https://github.com/langchain-ai/executive-ai-assistant
- Commit: 758db7174223da7864feea7c9f8d1aba12923037
- License: MIT (`LICENSE`, copied unchanged)

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `eaia/main/graph.py` | the main graph: routing after triage, `take_action`, `enter_after_human`, send/mark-read nodes; `graph` is run with the adapter's checkpointer and store |
| `eaia/main/draft_response.py` | drafting agent; reads `schedule_preferences`, `random_preferences`, `response_preferences` from the store (lines 102-125) |
| `eaia/main/rewrite.py` | tone rewrite; reads `rewrite_instructions` from the store (lines 38-49) |
| `eaia/main/human_inbox.py` | Agent Inbox interrupts (`send_message`, `send_email_draft`, `send_cal_invite`, `notify`), `save_email`, and the reflection runs started with `LGC.runs.create(None, "multi_reflection_graph", ...)` |
| `eaia/reflection_graphs.py` | `multi_reflection_graph` (`determine_what_to_update`) and `general_reflection_graph` (`update_general`, which writes the new prompt to the store at lines 90-93) |
| `eaia/schemas.py` | `State`, `RespondTo`, tool schemas, `email_template` |
| `eaia/main/config.py` | `get_config` (the case passes its full config through `configurable`) |
| `eaia/main/config.yaml` | upstream config for Harrison Chase; not loaded (kept as the structure `inputs/config.yaml` follows) |
| `eaia/main/triage.py`, `eaia/main/fewshot.py` | imported by `graph.py`; the triage node is not executed (emails enter as triaged `email`) |
| `eaia/main/find_meeting_time.py` | imported by `graph.py`; runs only if the drafting agent calls `MeetingAssistant` (no email in the scenario asks to meet) |
| `eaia/__init__.py`, `eaia/main/__init__.py` | package files |

Not copied:
- `eaia/gmail.py` (Gmail and Google Calendar through OAuth): replaced by in-memory fakes with the same
  function signatures (`send_email`, `mark_as_read`, `send_calendar_invite`, `get_events_for_days`),
  installed as the `eaia.gmail` module by the adapter.
- `eaia/cron_graph.py` (polls Gmail and starts one run per email on the LangGraph server): the adapter
  plays this part, with the same thread-id rule (cron_graph.py lines 22-24).
- `scripts/`, `langgraph.json`, `pyproject.toml`, `poetry.lock` (deployment and setup). The case venv
  follows the lock, except `langchain-core` (see `../requirements.txt`).
