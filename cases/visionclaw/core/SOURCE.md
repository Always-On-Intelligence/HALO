# Vendored VisionClaw code

- Repository: https://github.com/Intent-Lab/VisionClaw
- Commit: 82699eca917c0062516c14b99affa34ea230ecd7
- License: `LICENSE` (Meta Wearables developer terms, copied unchanged); the code carries no other license file.

Files copied unchanged, at their upstream paths:

| File | Role in the run |
|---|---|
| `agent/main.py` | the voice worker: `entrypoint` (call start: parked-result drain and relay, app check, tool wiring), the tools `execute`, `browse`, `quick_search`, `show_card`, `save_note`, `recall_notes`, `delete_note`, their gateway calls, `_run_delegated`, `Tracer` |
| `agent/requirements.txt` | the worker's dependencies, for reference (the run stubs livekit, google-genai, openai and Pillow) |
| `gateway/src/server.ts` | the gateway: `/v1/chat/completions` (delegated turns, task ledger, parking when the caller is gone), `/livekit-token` (session rotation and briefing), `/notes`, `/pending-notifications`, `/apps`, `/trace` |
| `gateway/src/turn.ts` | `runTurn`: one Managed Agents session turn with the attached image and queued context |
| `gateway/src/provision.ts` | `AGENT_SYSTEM_PROMPT`, `ensureShared`, `ensureUser` (agent, vault and per-call session) |
| `gateway/src/store.ts`, `notify.ts`, `trace.ts` | the JSON store (notes, ledger, parked results), notifications and parking, the study trace |
| `gateway/src/apps.ts`, `connect.ts`, `health.ts`, `auth.ts`, `browse.ts`, `config.ts` | connected-app registry and listing, app health, accounts, Browser Use (disabled here), configuration |
| `gateway/package.json`, `package-lock.json`, `tsconfig.json` | the gateway's pinned dependencies; `npm ci` installs them into `cases/visionclaw/node_modules` from the copies at the case root |

Not copied:
- `gateway/src/cma.ts` (`export const anthropic = new Anthropic()`, the Managed Agents client): at run time
  `./cma.js` resolves to `../shim/cma_stub.mjs`, which forwards the same calls to the adapter's bridge.
- The iOS and Android apps (`samples/`), the LiveKit and Gemini Live services, the OpenClaw project (not in
  this repository), the gateway's provisioning and trace CLIs, deploy files, and the public pages.
