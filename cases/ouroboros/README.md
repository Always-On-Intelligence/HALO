# Ouroboros in HALO run mode

**Work.** Ouroboros (razzant/ouroboros, commit 4b37f96, release 7.6.0; technical report arXiv 2608.08311) is a
self-modifying coding agent that serves one owner, keeps durable memory, and changes its own implementation
through reviewed commits. **Configuration** (`case.yaml`): "Hope live deployment with reviewed experience-driven
core evolution", the paper's advanced mode. Survey labels: S->M, M->A, A->S, A->M reported, M->S not reported;
all five evidence steps marked.

**Status: runs.** The upstream Python code of memory, post-task experience review, promotion, the evolution
campaign, plan review and the commit review gate runs unchanged from `core/`; the tool loop is ported (see below).

## What one item does

An item is one owner who talks to Ouroboros in its Main room about four of the owner's repositories under `~/src`
(`inputs/items.yaml`, four items: release notes, database migrations, decision records, feature flags). The owner's
organization keeps its default contributing guide in its organization-level `.github` repository, checked out at
`~/src/.github/CONTRIBUTING.md`. GitHub applies that file to every repository without a guide of its own, and none
of the four repositories has one, so exploring a repository does not reveal the rules. Each repository has at least
one rule that neither tool defaults nor the existing files reveal (for example a ticket line that older migrations
predate). `make check` enforces each repository's section of the guide and its failure message names the section;
it is simulated from declarative rules (fail-fast, first failing rule reported), and nothing is executed.

1. **Learning, L1 and L2.** The owner's request is logged to the room, Ouroboros works in the repository with four
   tools over up to `OUROBOROS_MAX_ROUNDS=12` rounds plus the upstream `[ROUND_LIMIT]` forced final, and its reply is
   logged. The guide is not mentioned in the requests, so a first attempt usually fails `make check`. Then the
   upstream post-task stages run in upstream order: `_run_memory_fallback_draft`, `_run_scratchpad_consolidation`,
   `_run_reflection` (trigger, Light experience review, `task_reflections.jsonl`, Pattern Register),
   `_apply_reflection_memory_actions`, `_update_improvement_backlog` (with semantic dedup), and
   `post_task_evolution.maybe_promote` (cadence `every_n:2`, so the decision runs after L2).
2. **Supervisor tick.** `apply_pending_request` turns the durable promotion request into a campaign
   (`start_evolution_campaign`); `enqueue_evolution_task_if_needed` builds the cycle task
   (`begin_evolution_transaction`, `build_evolution_task_text`). Only its queue admission and owner notices are
   captured instead of performed.
3. **Evolution cycle.** The cycle task runs in the same loop with `read_file`, `edit_text`, `write_file`,
   `plan_task`, `commit_reviewed` and `request_restart` on a per-run sandbox copy of Ouroboros's own repository:
   `prompts/SYSTEM.md` and the ten BIBLE P9 release carriers may change; BIBLE.md is protected; the two reference
   books (`docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md` and their 27 chapters), `docs/DESIGN.md` and
   `docs/CHECKLISTS.md` are there to read. Code is not in the sandbox, so no generated code can run. `plan_task` is
   upstream `_handle_plan_task` on the triad rows; a self-modification plan carries BIBLE.md and the composed
   Architecture book (W3), about 930 KB per reviewer call. `commit_reviewed` runs
   `release_sync.sync_release_metadata`, the upstream `_preflight_check` (P9 release metadata), the upstream triad
   packet (constitutional head with BIBLE.md, the Repo Commit Checklist, the change-class governance chapters selected
   by `governance_context`, touched-file pack with the span-only carrier cut, staged diff, review history, rebuttal;
   about 650-750 KB) and `_dispatch_unified_review` in blocking mode with two packet reviewer rows (quorum 2). At most
   `OUROBOROS_REVIEW_MAX_CYCLES=2` paid reviews (shipped default). A passing commit lands: the staged files are copied
   into the sandbox repository and the linked backlog item is closed (`close_backlog_items`).
4. **Test, T1 and T2.** Two tasks in repositories that follow other sections of the same guide (the lesson "read
   the organization guide first" transfers; copying L1/L2's format does not). Their contexts read
   `prompts/SYSTEM.md` from the sandbox repository, so a landed revision is in effect (the restart). No post-task
   stages run in the test phase.

In the smoke run an arm made 22-27 backbone calls without an evolution cycle and 26-34 with one, plus 0-4
reviewer calls (two for a plan review, two per paid commit review).

## Replacements

| Upstream | In this run |
|---|---|
| `ouroboros.llm.LLMClient` (every Main and Light call: task rounds, reflection, Pattern Register, dedup, promotion, the cycle) | `Backbone`, which sends system + user text to the HALO backbone (`self.llm`). Optional tools of the Light reflection call (knowledge_read etc.) are not offered, so it answers in one call. |
| reviewer rows of the commit triad (`review_multi_model._handle_multi_model_review` -> review substrate) | a second HALO LLM role with the same backend and cache, tag prefix `reviewer|`, fed upstream's exact api-row messages (`triad_api_messages`); replies parsed by upstream `parse_model_response` |
| reviewer rows of `plan_task` (`plan_review_runtime.run_plan_review_slots` -> review substrate) | the same reviewer role, fed upstream's `build_plan_review_messages`; rows built by upstream `_plan_row_from_actor` |
| `run_llm_loop` (`loop.py`) and the 124-tool registry | a ported round loop: up to `get_max_rounds()` rounds with tools, then the upstream `[ROUND_LIMIT]` text as the forced final (task turns only); tools are upstream schemas (`tools/core.py`, `shell.py`, `git.py`, `control.py`, `plan_review.py`) with arguments that do not apply removed; calls are a JSON object in the reply (a call object whose closing brackets are unbalanced is repaired before parsing, since upstream's native tool calls always carry valid JSON) |
| context assembly (`context._capture_context_core`, `context_fit._system_blocks`) | the same upstream builders in the same order (SYSTEM.md, BIBLE.md; identity, WORLD and story; knowledge index and Pattern Register, room, scratchpad, runtime, backlog digest for the cycle, execution reflections). The reference books are named, not inlined (one note says so), and the runtime block is a short port |
| git (`git show`, `rev-parse`) on the commit path | answered from the sandbox: HEAD is the landed copy, the index is the cycle's working copy; no git process runs |
| a real commit and restart | file copy into the sandbox repository; later contexts read it |
| owner settings | environment variables read by the upstream config getters: `OUROBOROS_RUNTIME_MODE=advanced`, `OUROBOROS_POST_TASK_EVOLUTION=true`, cadence `every_n:2`, `OUROBOROS_REVIEW_ENFORCEMENT=blocking`, `OUROBOROS_REVIEWER_SLOTS` (two `api_chat` packet rows), `OUROBOROS_MAX_ROUNDS=12` (shipped default: no limit), `OUROBOROS_TASK_REVIEW_MODE=off` |
| wall clock and uuid4 | frozen per step (freezegun, scripted instants) and seeded per step, so the rendered memory, campaign ids and prompts are identical across arms and processes (verified), and arms share cached replies |
| `memory/WORLD.md` (host profile) | a scripted neutral profile, so no host facts reach a prompt |

Not run, with the reason: the advisory pre-review (no advisory route; upstream records an audited bypass), scope
review (its rows read the repository with tools), task acceptance review (an extra reviewer panel), and the
pre-commit test battery (the sandbox holds no code or tests). The markdown parser (`tree-sitter`,
`tree-sitter-language-pack`) is installed with upstream's version bounds: without it upstream composes no reference
book, so `plan_task` refuses every self-modification plan (W3) and the cycle stops there. The action contexts name
the books instead of inlining them (upstream's max mode would add the 870 KB Architecture book to every call). The
context-fit route lookup imports the web gateway (`ouroboros.gateway.settings`, not vendored); upstream catches
that and keeps the capacity unknown, so prompts are sent whole (the warning in `worker.stderr.log` is this).

## Cut sites

Line numbers are in `core/` (unchanged upstream files).

| Cut | Where the receiver reads the flow | What the cut does (adapter method) |
|---|---|---|
| S->M | `supervisor/message_bus.py:1370` `log_chat` (owner rows) -> `ouroboros/memory_view.py:524` `_lanes` | the owner's messages are not written to the chat log, so the room never holds the owner's words (`_owner_says`) |
| M->A | `ouroboros/context.py:593,758,866`, `ouroboros/memory_view.py:826,920`, `ouroboros/improvement_backlog.py:456`, composed as in `context.py:1059-1290` / `context_fit.py:352` | no memory block reaches any action context (tasks and the cycle); SYSTEM.md, BIBLE.md, runtime and task text remain (`_context`) |
| A->M | `log_chat` (Ouroboros rows), `ouroboros/reflection.py:874` `append_reflection_routed`, `ouroboros/post_task_synthesis.py:301` `_apply_reflection_memory_actions` | replies, execution reflections, the Pattern Register update and scratchpad/knowledge actions are not written; the backlog and the promotion (the revision path) still run (`_task`, `_post_task`) |
| record | `post_task_synthesis.py:696` `_run_reflection` -> `reflection.py:181` trigger, `reflection.py:527` `generate_reflection` | the review keeps the results but loses the calls, their arguments, the agent's notes and the sealed final answer (`_evidence`) |
| outcome | same | every result and status is removed, so the trigger and the review see a clean run (`_evidence`) |
| attribution | same | results arrive one task late: L1's review gets none, L2's gets L1's results on L2's calls (`_evidence`) |
| revision (+ later_use) | `context.py:1072` reads `prompts/SYSTEM.md` from the repository | the cycle runs and is reviewed, but the passing commit is not copied into the sandbox repository, so the test tasks use the original prompt (`_commit_reviewed`) |

A->S is realized by the tool loop (the agent's reads and `make check` runs choose what it observes) and is not cut,
per the brief. A lesson reaches T1/T2 by two paths: memory (A->M, then M->A; in the smoke run the execution
reflections carried it, since the outcome cut, which leaves no reflection, removed it) and the reviewed revision. `run.yaml` therefore also cuts each evidence step and the
revision together with A->M, so that only the revision path is left; `[A->M, revision]` is the arm in which nothing
learned in L1/L2 can reach the test tasks.

## Outputs

`output` (judged): for T1 and T2, the request, the actions, the diff delivered (other checkouts under `~/src` only
if edited), the host's `make check` result on the delivered state, and the final message. Also returned: `learning`
(L1/L2 in the same form), `reflections`, `objective`, `evolution` (task text, calls, plan reviews, each review
attempt with verdict and findings), `proposal_reviewed`, `revision_landed` (the landed diff), `backbone_calls`
(tags). Metrics: `test_ci_pass`, `test_first_check_pass`, `test_failed_checks`, `learn_ci_pass`,
`learn_failed_checks`, `reflections`, `promoted`, `plan_reviews`, `review_attempts`, `review_passed`,
`revision_landed`, `backbone_calls`, `reviewer_calls`.

## Run

```bash
uv venv cases/ouroboros/.venv -p 3.11
uv pip install -p cases/ouroboros/.venv/bin/python -r cases/ouroboros/requirements.txt
HALO_CODEX_BIN=/path/to/codex PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/ouroboros --items 1 --samples 1 --workers 2 --name smoke
```

`HALO_KEEP_RUN=1` keeps each run's temporary tree (drive, sandbox repository, checkouts) for inspection.

## Known issue in the full run

One of the 144 runs fails: the M→A cut on `feature_flags`, sample 2. In that run the tool loop accumulates a
fetched web page, and one backbone prompt reaches 1,372,413 characters, above the Codex CLI's input limit of
1,048,576. Upstream keeps prompts within the model's window through `context_fit.py`, but its route lookup
imports `ouroboros.gateway.settings`, a web-server module that is not vendored. Without it the capacity
stays unknown (the warning "Consolidation route metadata unavailable" in the worker log) and nothing is
compacted. The run is reported as failed, so the M→A comparison has 11 pairs instead of 12. A fix would
stub the route lookup with the backbone's limits, but that changes the prompts of every run that grows
large, so it needs a full rerun of the case.
