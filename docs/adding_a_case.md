# Adding a case to HALO run mode

A case connects one system to the HALO run-mode harness. The harness runs every input item
through the system unmodified (the *original* arm) and again with selected sites cut (the *test*
arms). Inputs and the backbone model stay fixed across arms, so a difference between arms comes
from the cut. Outputs are compared by a blind pairwise judge and by numeric metrics.

`cases/aiget/` is the reference case. Read it before writing a new one.

## The framework in brief

- **Sensing (S)** acquires and interprets current observations. **Memory (M)** retains
  information across interactions. **Action (A)** selects behavior: silence, communication,
  preparation, or execution.
- Five coupling channels are tested: S→M, M→A, A→S, M→S, A→M. Their definitions are in
  `halo/read/protocol/PROTOCOL.md`. The basic S→A path is present in every system and is not cut.
- A system that revises its own mechanism (prompts, rules, skills, code, or weights) also has
  the five evidence steps of the self-evolving loop: `record`, `outcome`, `attribution`,
  `revision`, and `later_use`.

## Layout of a case

```
cases/<case>/
├── case.yaml          # metadata used by read mode (already present for every reviewed work)
├── README.md          # what the work is, what runs, what is replaced, cut sites, how to run
├── core/              # the upstream code the run executes, copied unchanged
│   └── SOURCE.md      # repository, commit, license, and the list of copied files
├── adapter.py         # class Adapter(BaseAdapter)
├── run.yaml           # backbone, judge, samples, tests, rubrics
├── inputs/            # scripted input items
└── requirements.txt   # what the case venv needs (CPU only)
```

## Rules

1. **Run the upstream code.** Copy into `core/` only what the run executes: the loop that keeps
   the system always on (memory writes and reads, triggers, the decision whether and how to act,
   reflection or other self-revision), together with the prompts and small data files it loads.
   Keep upstream relative paths and copy files unchanged. Do not copy weights, datasets, or
   front ends. Call upstream functions from the adapter instead of rewriting their logic.
2. **Replace only the model clients.** Every model call (OpenAI, Gemini, Anthropic, Qwen or
   another local VLM or LLM) goes to `self.llm(system, user, tag)`, the HALO backbone. Install a
   stub module in `sys.modules` before the upstream import, or patch the client class, as
   `cases/aiget/adapter.py` does. Images, video, and audio become text descriptions in the
   scripted inputs. An embedding model that needs a GPU or an API key is replaced by
   `sentence-transformers/all-MiniLM-L6-v2` on CPU. Write every replacement in the README.
3. **Cut at the receiving end.** Each cut site blocks or neutralizes one channel or one evidence
   step where the receiver reads it, and leaves the rest of the run unchanged. Name the upstream
   file and line of every site in the adapter docstring and the README.
   - A channel cut withholds what crosses the channel, for example by emptying the retrieved
     memory that reaches Action (M→A) or by not writing the action record to memory (A→M).
   - An evidence-step cut follows `cases/eaia/`:
     - `record`: the revision step does not see the system's own actions;
     - `outcome`: no feedback reaches the revision step;
     - `attribution`: feedback is attached to the wrong action;
     - `revision`: the revision runs but is not written, so later steps use the old mechanism
       (this cut also covers `later_use`).
4. **Keep arms paired.** The `tag` passed to `self.llm` names the item, the sample, and the stage,
   but not the arm. Arms whose prompts are identical then share the cached reply, so a comparison
   differs only where the cut changes a prompt.
5. **Write the inputs.** Use 4 to 6 short, realistic items that exercise every cut site. Each item
   is a dict with an `id` and a `judge_context`, the situation the judge sees. Systems that learn
   need a learning phase followed by a test phase inside one item.
6. **Return what the judge compares.** `run()` returns a JSON-serializable dict. Put the text the
   judge compares under `output` (or under another field named in `run.yaml`) and numbers under
   `metrics`.

## run.yaml

```yaml
models:
  backbone: {backend: "codex:gpt-6-astra", effort: low}
  judge: {backend: "codex:gpt-6-astra", effort: high}
samples: 3
rubric: >-
  What the judge should prefer, stated for this system's users.
tests:
  - cut: [M->A]
  - cut: [A->M]
    field: output_revisit          # optional: the output field to compare (default: output)
    context_field: context_revisit # optional: a field of the original run used as judge context
    rubric: >-                     # optional: a rubric for this test
      ...
```

## Environment and commands

```bash
uv venv cases/<case>/.venv -p 3.11
uv pip install -p cases/<case>/.venv/bin/python -r cases/<case>/requirements.txt
export HALO_CODEX_BIN=/path/to/codex          # or HALO_CLAUDE_BIN for claude:<model> backends
PYTHONPATH=. .venv/bin/python -m halo.run.harness cases/<case> --items 1 --samples 1 --workers 2 --name smoke
```

The harness writes `runs/<case>/<name>/` with `arms.jsonl`, `judge.jsonl`, `report.json`, and
`report.md`, and caches model replies in `runs/<case>/cache/`. Worker errors go to
`runs/<case>/worker.stderr.log`.
