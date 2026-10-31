---
title: Read mode
description: Three oversight agents read a work's sources and judge every channel and evidence step.
---

Read mode reviews a published work from its sources. Three oversight agents, coding agents with web access, each read the work's papers, documentation, and released code on their own, and judge every channel and every evidence step with a quote and a locator. A majority vote decides each cell.

## Labels

| | Labels |
|---|---|
| Channels S→M, M→A, A→S, M→S, A→M | `reported`, `absent` (the source explicitly excludes the flow), `insufficient` (the source leaves a needed link unknown) |
| Evidence steps | `stated` with a verbatim quote and a locator, or `not_stated` with a reason |

The basic S→A path is present in every agent system and is not reviewed. The full rules are in `halo/read/protocol/PROTOCOL.md`, and every review must validate against `halo/read/schema.json`.

## Run it

```bash
python scripts/clone_upstream.py                         # the code the agents read, at pinned commits
halo read --backend codex:gpt-6-astra --workers 6        # one oversight agent over all works
halo read --backend claude:claude-opus-5-5 --workers 6
halo read --backend claude:claude-fable-5-1 --workers 6
halo vote                                                # results/read/votes.json and disagreements.md
halo tables                                              # results/read/table.md, table.csv, counts.json
```

Models are called through local coding-agent CLIs, set with `HALO_CODEX_BIN` and `HALO_CLAUDE_BIN`, so no API key is stored in the repository.

## Results

The survey's read-mode table is split into [research systems](/HALO/results/research/) and [products](/HALO/results/products/).

## Read mode and the plugin

Read mode tells you what a product says it does. The plugin tells you what a running agent logged. For a closed product the two are the evidence available from outside, and they can disagree: a product may document a memory it never used in your trace, or log a check its documentation does not mention.
