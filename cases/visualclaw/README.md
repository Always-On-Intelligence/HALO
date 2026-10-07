# VisualClaw in HALO run mode

VisualClaw (UCSC-VLAA/VisualClaw, commit f6de05b, paper arXiv 2606.16295) is a multimodal agent stack that
adds keyframe selection, skill injection, episodic memory and failure-driven skill evolution around a coding
agent. VisualClawArena runs the agent on scenarios that pair a walkthrough clip with a workspace of documents,
multiple-choice checks and file tasks scored by executable checks.

## Configuration

The survey reviews two configurations: VisualClawArena with Claude Code (Sonnet 4.6) and with Codex (GPT-5.5),
both "Cascade-8 + FullEvo Cat.". In run mode the HALO backbone replaces the agent backend, so one configuration
suffices. The run uses the Codex bridge, `CodexCliEngine` (`benchmark/visualclawarena/engines/codex_cli.py`):
it is the backend a text-only model can drive with the upstream code unchanged (snapshot and keyframe images
up front, `visualclawarena_write_file` blocks applied after the call). The Claude Code configuration differs
only in its native tool loop (reads, edits and checks inside the agent), which needs Claude Code itself.

Flags are those of `scripts/run_visualclawarena_self_evolve.sh` for `BACKEND=codex`, with the paper's Cat.
memory-to-evolver variant: `--keyframe-mode cascade --max-keyframes 8`, `--skills-mode inject` from
`seed_universal_mc`, `--memory --memory-top-k 5 --memory-max-chars 4000`, `--schema-file-preflight`,
`--evolve` into a writable bank, `--skills-cross-scenario-buffer`, `--memory-evolver-fusion
--memory-evolver-context-mode simple_concat`. One change: `--skills-evolve-every 2` instead of the script's 5,
so a five-round learning phase evolves at least once within about 25 backbone calls per arm.

## What runs

`Adapter.run` stages one scenario in the VisualClawArena release layout and calls
`benchmark.visualclawarena.runner.main` twice with the same output dir, run id, skill bank and failure buffer:
first on the learning rounds (q1-q5), then on the test rounds (q6-q9). All of the arena loop runs from the
vendored code: workspace staging, keyframe staging, skill retrieval and hybrid injection, memory retrieval and
storage, the Codex engine's prompt and write application, scoring, within-day evolution, F1 dedup, the
failure buffer. See `core/SOURCE.md` for the file list.

Two invocations are needed because, at this commit, skills evolved within a run never reach later rounds of
the same run: `runner.py:1428` assigns `skill_wire.evolver.manager`, while `SkillEvolver` writes through
`self._manager` (`evolver.py:269`), so the runner's own `SkillManager` keeps the bank it loaded at startup
(`runner.py:1374-1376`). The bank on disk carries evolved skills to the next invocation, which loads it; the
episodic memory (`<output-dir>/<run-id>/memory_data`) carries over too. The workspace is staged clean for each
invocation (`work_copy.py:58-67`), as the paper's §4.2 describes for each evolve step.

## Replacements

| Upstream | In run mode |
|---|---|
| `codex exec` started by `CodexCliEngine.run_agent` (`codex_cli.py:209`) | one backbone call with the engine's own stdin prompt; the method itself runs unchanged |
| keyframe images attached with `--image` (`codex_cli.py:159, 188-189`) | their text descriptions, placed before the prompt |
| `ClaudeCodeChatClient.chat_complete` (evolver client, `skill_wire.py:167-168`, `--evolver-backend claude-code`) | backbone call with `SkillEvolver`'s own prompt |
| `SkillEvolver._notify_rl` (POST to the local gateway) | no-op |
| `cascade_frames.cascade_extract_keyframes` (OpenCV over the mp4) | scripted Cascade-8 output: `data/keyframes.json`, at most 8 frames, staged as `_clip_frames/<MM_SS>.jpg` holding text |
| `cv2` import in `runner.py` | empty stub (only the mp4 paths use it) |

The paper's evolver model (Claude Haiku 4.5 or gpt-5.2) and agent models (Sonnet 4.6, GPT-5.5) are all the
backbone here. Memory uses the default config (sqlite, keyword retrieval), as the public runner does.

## Cut sites

| Cut | Site (upstream file:line) | What is withheld |
|---|---|---|
| S->M | `runner.py:1020-1025` -> `_store_round_memory` `752-797` (content line 775) | the round's request text in the memory unit |
| M->A | `runner.py:925-931` (`_prepend_memory`, `610-615`) | the rendered memory block in the agent prompt; skill injection (`859-907`) is unchanged |
| A->M | `runner.py:1020-1025` -> `752-797` (lines 777, 795) | the agent's conclusion and the pass/fail outcome in the memory unit |
| M->S | `codex_cli.py:159` (`_collect_keyframe_images`, `532-537`) | keyframe attachment triggered only by memory text that names `_clip_frames/` |
| record | `evolver.py:414-441` (input built at `runner.py:1793-1828`) | the agent's answers in the evolver's failure samples |
| outcome | same receiver (`runner.py:1805-1810`, `1817`) | the verdict: the evolver gets every round since its last call, without reference line, reward 0.0 |
| attribution | same receiver | each failure is shown with the answer of the previous failure in its batch |
| revision | `evolver.py:260-270` | `SkillManager.add_skill` writes nothing, so the test invocation loads the unchanged bank (covers later_use) |

A->S is not realized: the Codex bridge is noninteractive, so the agent cannot request a read. The survey marks
A->S absent for this configuration and reported for Claude Code, whose tool loop run mode cannot reproduce.

M->S is realized in the code, though not by design: the engine attaches every keyframe when the whole message
contains `_clip_frames/` (`codex_cli.py:159`), and the message includes the prepended memory and skill cards.
A remembered conclusion or an evolved skill card that names a frame path therefore gives a round without a
clip citation the frames. The M->S cut withholds only the memory trigger; skill cards are mechanism and are
covered by the revision cut. `keyframes_attached_by` in each result records which text triggered it.

## Upstream behaviors that shape the results

- The evolver sees each failure as the last 600 characters of its prompt text and the first 500 of the answer
  (`evolver.py:434-441`). The runner puts the question and reference first and a 2500-character prompt tail
  after them, so the evolver never sees the question or the reference in the Arena path.
- In Cat. mode the memory-to-evolver context is empty: `build_related_evolver_memory_context` returns "" unless
  the mode is `related_prefix` (`runner.py:1506-1512`).
- The runner's qa_types filter (`runner.py:873-898`) does not accept the tag `"all"` that the evolver prompt
  suggests, so a card tagged `["all"]` is never injected.
- The Codex snapshot drops `AGENTS.md` and `IDENTITY.md` (`codex_cli.py:58-64`), so the scenario's operating
  contract reaches the agent only through feedback.
- The self-evolve script's default evolver for Codex runs is `openai`, for which `SkillWire` passes no model to
  `SkillEvolver` (`skill_wire.py:188-201`); without `SKILL_EVOLVER_MODEL` set, evolution silently produces
  nothing (`evolver.py:146-165, 356-358`). Run mode selects the `claude-code` client instead; either client
  receives the same evolver prompt, and both are replaced by the backbone.

## Inputs

`inputs/scenarios/<id>/` are four handwritten scenarios in the VisualClawArena release layout
(`spec/questions.json`, `spec/scripts/check_*.py`, `data/workspace/`), with `data/keyframes.json` in place of
`clip.mp4`: a lab stock check (count sealed units only), a walk-in cooler closing check (a label needs both
dates), a bike-share dock inspection (tyres, light and bell), and a construction PPE walk (hat, vest, glasses,
hearing protection in the crusher zone). Each has five learning rounds (four multiple choice, one file task)
and four test rounds; in the test, q6-q7 cite the clip and q8-q9 do not, so their facts must come from memory
(or from frames attached because retained text names a frame path). `halo.json` holds the round split and
the expected results shown to the judge.

## Outputs

`output` lists the test rounds: chosen options with the end of each reply, and the files each file task wrote.
The judge sees the stakeholder request, the operating contract, the keyframe descriptions, the workspace
documents and the expected results. Metrics: `test_pass_rate`, `learn_pass_rate` (upstream scorers),
`evolver_calls_learning`, `skills_written_learning`, `evolved_skill_injections_test`, `memory_hits_test`,
`test_rounds_with_frames_from_retained_text`. Results also carry the evolved cards, the evolver's proposals
(`v3_evolution_history.jsonl`), and per-round logs.

## Run

```bash
uv venv cases/visualclaw/.venv -p 3.11 && uv pip install -p cases/visualclaw/.venv/bin/python -r cases/visualclaw/requirements.txt
HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false HALO_CODEX_BIN=/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex \
PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/visualclaw --items 1 --samples 1 --workers 2 --name smoke
```

Set `HALO_VISUALCLAW_KEEP=1` to keep each run's staged scenario, logs and bank in the temp dir.
