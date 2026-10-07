# Vendored AssistantX code

- Repository: https://github.com/AssistantX-Agent/AssistantX
- Commit: 35ab2715f7371d935d78907d90dc4131e414fcb7
- License: the repository has no license file at this commit.

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `OfficeAssistant/main.py` | the always-on loop, run as `__main__`: WeChat message intake (`onmessage`), perception, planning, action, action parsing and execution, Stop branch, reflection |
| `OfficeAssistant/prompt_test.py` | the prompt builders `main.py` imports (lines 21 and 164), and `read_prior_knowledge` (the relational graph file) |
| `OfficeAssistant/chat.py` | the system prompts of each role (`init_*_chat`) and `add_response` |
| `common/global_var.py` | loop state (`count`, `locker_info`, chat buffers); its contact dicts are replaced at run time by the simulated office |

`main.py` keeps the upstream's hard-coded API URL and token (lines 130-133). They are never used: the
adapter replaces `inference_chat`, so no request leaves the machine except the HALO backbone call.

Not copied:

- `OfficeAssistant/api.py`: the GPT-4o/Claude/GLM/Qwen clients, replaced by the HALO backbone.
- `common/wechat.py`: the WeChat socket server, replaced by a stub that delivers scripted messages. (At this
  commit it imports `img_encode` from `common/LockApi.py`, which no longer defines it.)
- `common/LockApi.py`: QR-code generation and the door-magnet watcher. Its `ocSelect` is commented out
  (lines 64-85); the simulated locker follows that code, with scans scripted instead of read from the door.
- `common/robot_api.py`, `common/andro_operation.py`, `OfficeAssistant/controller.py`: robot sockets and
  Android phone automation. `Forward_file_on_Wechat` (andro_operation.py:105-108) only returns a success
  string; the stub returns the same string.
- `OfficeAssistant/prompt.py`, `prompt_init.py` and the compiled variants in `__pycache__/`: prompt variants
  that `main.py` does not import.
- Modules `main.py` imports that are not in the repository: `handing`, `socket_server_dabai`,
  `socket_server_armcar`, `handle_dabai`, `handle_armcar`, `OfficeAssistant/prompt_assx.py` (only a
  `.pyc` for Python 3.10 exists) and `MobileAgent/api.py` (imported by `chat.py`). The adapter installs
  stubs for them; see `../README.md`.
