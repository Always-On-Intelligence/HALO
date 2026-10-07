# EAIA (Executive AI Assistant) in HALO run mode

EAIA (langchain-ai/executive-ai-assistant, commit 758db71) is LangChain's reference "ambient" email
agent. A cron job feeds new Gmail messages to a LangGraph graph that triages each email, drafts a reply
(asking the user questions through the Agent Inbox when it lacks information), rewrites the draft in the
user's tone, and waits for the user to accept, edit, ignore, or answer. When memory is on, every user
response starts a background run of a reflection graph that rewrites the prompts the drafting and
rewrite steps read from the LangGraph store. EAIA therefore revises its own mechanism (its prompts) from
user feedback, and the run tests the evidence steps of that loop as well as the channels.

## What runs

The run executes the upstream graphs from `core/` (copied unchanged, see `core/SOURCE.md`):
`eaia/main/graph.py` with `draft_response.py`, `rewrite.py`, `human_inbox.py`, `schemas.py`,
`config.py`, and `eaia/reflection_graphs.py`. The adapter supplies what EAIA gets from its deployment:

- **Server and cron.** One LangGraph thread per email (thread id as in `cron_graph.py` lines 22-24), an
  in-memory checkpointer (`InMemorySaver`) and store (`InMemoryStore`) attached to the compiled graphs.
  The reflection run that `human_inbox.py` starts with `LGC.runs.create(None, "multi_reflection_graph", ...)`
  is a separate background run on the server. Here it is queued and runs as a top-level invocation of the
  vendored `multi_reflection_graph` as soon as the main graph pauses at the next interrupt or ends, so a
  draft produced right after a question reads the prompts from before that question's reflection, as it
  would on the server.
- **Agent Inbox.** Interrupts are answered by a simulated user (below) with the upstream response types
  (`edit`, `accept`, `response`, `ignore`) and resumed with `Command(resume=[response])`.
- **Triage is not run.** Every email in the scenario needs a reply, so each enters its thread through
  `update_state(..., as_node="triage_input")` with `RespondTo(response="email")`; the upstream
  `route_after_triage` then sends it to `draft_response`. Triage few-shot memory is therefore not exercised.

## What is replaced

| Upstream | Replacement |
|---|---|
| `ChatOpenAI` (draft_response.py:85, rewrite.py:35, triage.py:48, find_meeting_time.py:69, reflection_graphs.py:65 o1, :151) and `ChatAnthropic` (reflection_graphs.py:152) | `HaloChat`, a LangChain `BaseChatModel` that sends each request to the HALO backbone (`self.llm`). `bind_tools` and `with_structured_output` (LangChain's own implementation and parsers) work by asking the backbone for one JSON object `{"tool": ..., "args": ...}`, parsed into `AIMessage.tool_calls`. Messages are rendered as a transcript; tool schemas and the JSON instruction go in the system part. Temperature and model names are not forwarded. Missing required arguments get empty values, as tool-calling APIs return schema-valid calls. Tool-call ids are a hash of the call, so trajectories (which `get_trajectory_clean` prints with ids) are reproducible and arms can share cached replies. A reply that does not parse is retried twice with a note. |
| `eaia/gmail.py` (Gmail, Calendar, OAuth) | in-memory fakes with the same signatures: an outbox, a read list, an invite list, and `get_events_for_days` returning "No events" |
| `langgraph_sdk.get_client()` (`human_inbox.LGC`) | in-process client whose `runs.create` queues the reflection run (see above) |
| `langchain.agents.react.agent.create_react_agent` (find_meeting_time.py:5) | `langgraph.prebuilt.create_react_agent`. The upstream call `create_react_agent(llm, [tool])` has that function's signature; LangChain's classic function of this name requires a prompt and would raise. Only reached through `MeetingAssistant`, which no scenario email calls for. A stub `langchain` package holds this module. |
| store index `openai:text-embedding-3-small` (langgraph.json) | none: the index serves only the triage few-shot search, which is not run |
| LangSmith tracing (`@traceable`) | disabled (`LANGSMITH_TRACING=false`) |

Dependencies follow the upstream `poetry.lock` except `langchain-core` 0.3.68 instead of 0.3.74: the
lock's pair langgraph 0.5.0 / langchain-core 0.3.74 fails at import (inconsistent MRO in
`PregelProtocol`), and 0.3.68 is the newest release that imports.

## Scenario (inputs/)

The fictional user and emails are those of the EAIA run reported in the survey (Section 7.2).

- `config.yaml`: EAIA's config for Alex Rivera (CEO of Lumen) in the upstream structure; the rewrite
  rules are upstream's with the name changed; `response_preferences` starts empty.
- `scenario.json`: Alex's five hidden rules (R1 no greeting; R2 at most three sentences; R3 end with
  "Thanks, Alex" on its own line; R4 never commit to a date, say Alex will confirm the timeline by Friday;
  R5 partnership/sponsorship/co-marketing goes to Jordan Lee, jordan@lumen.dev), the simulated user's
  prompts, and three items.
- `emails.json`: five learning emails (t1-t5) and four test emails (e1-e4), copied unchanged.

| item | learning emails (in order) | test emails |
|---|---|---|
| order-a | t1 SDK fix timing, t2 webinar, t3 thanks note | e1 SSO date, e2 demo-day sponsors |
| order-b | t5 summit sponsorship, t4 pricing comments by Wednesday, t3 thanks note | e4 co-marketing, e3 thank-you |
| order-c | t2 webinar, t4 pricing comments, t5 summit sponsorship | e1 SSO date, e3 thank-you |

**Learning phase** (memory on). The simulated user is a second `halo.run.llm.LLM` with the backbone's
backend and cache, effort medium, tags prefixed `user:`. It knows R1-R5. It answers each `Question`
in one or two sentences consistent with its rules, and edits each draft to follow the rules
(changing as little as possible, adding Jordan as a recipient when R5 applies). A draft whose lines
come back unchanged is accepted (line breaks count, since R3 asks for a one-line sign-off). A third
question gets "Please draft the reply now." and a fourth is ignored; a calendar invite gets a fixed
"No calendar invite" answer. EAIA's own inbox nodes turn the answers and edits into reflection runs.

**Test phase** (memory off, so test emails do not learn from each other). Every question gets the same
neutral answer ("I have nothing to add here. Please draft the reply yourself."). The draft waits in the
inbox and is read from the interrupt. The judge sees R1-R5 and the test emails (`judge_context`); EAIA
never sees the rules.

Each arm makes 14-26 backbone calls (smoke test: original 22, outcome 14, record 26): per learning
email a draft, a rewrite, a memory choice and 1-3 prompt updates, about three more per question, and
per test email a draft and a rewrite. `metrics.backbone_calls` reports it (cache hits included).

## Cut sites

All cuts act where the receiver reads; the rest of the run is unchanged.

| cut | site | effect |
|---|---|---|
| `record` | reflection input built at human_inbox.py:105-116, 171-182, 215-229, read by `get_trajectory_clean` at reflection_graphs.py:153 and :72; cut in `Adapter._reflection_run` | assistant messages (its draft, its tool calls) are removed; reflection sees the email, the user's answers, and the feedback |
| `outcome` | EAIA's `memory` switch (config.yaml:52; read at human_inbox.py:76, :142) set false during learning | branches at human_inbox.py:103, :169, :212, :232 skip `save_email` and the reflection run: no feedback reaches reflection |
| `attribution` | `input["messages"]` replaced in `Adapter._reflection_run` before reflection_graphs.py:153 and :72 | each feedback is paired with the previous learning email's trajectory; the first email's feedback runs after the last learning email, paired with that email's trajectory |
| `revision` (covers `later_use`) | `StoreView(drop=True)` on the reflection graph discards `update_general`'s write at reflection_graphs.py:90-93 | reflection runs, but later drafts read the original prompts at draft_response.py:102-125 and rewrite.py:38-49 |
| `A->S` | the interrupt request built at human_inbox.py:79-89 (`action_request.args` holds the question) | the simulated user sees the email but not the question; only learning-phase answers change |
| `M->A` (not in run.yaml) | `StoreView(mask=True)` on the main graph: the reads at draft_response.py:102-125 and rewrite.py:38-49 find nothing and fall back to the config defaults (their default write only initializes a missing key) | the store still learns, drafting ignores it. The test drafts then get exactly the prompts of the `revision` arm, so this test would duplicate it. `later_use` is an alias. |

Channels at the same site as a step: `S->M` (Alex's answers and edits reaching the reflection input)
is cut by `outcome`, and `A->M` (the assistant's own draft and tool calls reaching it) by `record`; both
names are accepted as aliases. `M->S` is not realized: no stored information shapes how a new email is
read (the triage few-shot examples would count as M->A, and triage is not run).

## Output and metrics

`output` holds the test drafts with the recipients each adds; the judge compares it with the rubric in
`run.yaml`. Also returned: `prompts_at_test` (the four stored prompts when the test starts), `learning`
(per email: questions and answers, draft, Alex's edit, each reflection run with its feedback, prompt
types, and prompt writes kept or discarded), `test`, and `errors`. Metrics: heuristic rule checks on the
test drafts (`no_greeting`, `signoff_thanks_alex`, `confirm_by_friday` on e1, `jordan_handoff` on e2/e4,
`rule_checks_passed`), `prompts_changed` (of the four prompts), `reflection_runs`, `backbone_calls`,
`user_calls`, `errors`.

## Smoke test (order-a, 1 sample, backbone effort low)

The judge preferred the original arm against `record`, `outcome`, `attribution`, and `revision`, and
called `A->S` a tie. In the original arm the reflection rewrote `random_preferences` (Jordan's role and
address) and `rewrite_instructions` (no greeting, one-line sign-off), and both test drafts kept R1 and
R3. In no arm did the test drafts confirm by Friday (R4) or add Jordan (R5): the reflection treated
"by Friday" as specific to one email, and EAIA's drafting prompt adds recipients only when Alex asks
explicitly, while Jordan was stored only as background. `outcome` and `revision` leave the same
original prompts at test time, so their test drafts are identical by construction (they share cached
replies); they differ only in the learning phase. Under `A->S` the user's untargeted answers still
carried the rules, so learning was much the same.

## Pairing across parallel workers

The tag of a backbone call names item, sample, phase, email, and LangGraph node, never the arm. Arms
running at the same time in different workers would otherwise both miss the cache on a shared request
(for example the first learning email, identical in every arm) and get different replies. The adapter
takes a file lock per request (in the system temp folder) around `self.llm`, so the second arm waits
and reads the cached reply.

## Run

```bash
uv venv cases/eaia/.venv -p 3.11
uv pip install -p cases/eaia/.venv/bin/python -r cases/eaia/requirements.txt
HALO_CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex PYTHONPATH=. \
  .venv/bin/python -m halo.run.harness cases/eaia --items 1 --samples 1 --workers 2 --name smoke
```
