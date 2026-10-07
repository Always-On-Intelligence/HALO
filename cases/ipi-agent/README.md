# IPI-Agent in HALO run mode: not runnable at the pinned commit

Survey configuration (`case.yaml`): "Full IPI-Agent with Interaction-Control Policy, Memory Tool and
Temporal-Gating Mechanism (Qwen3-VL-8B component-ablation configuration)". Repository: lijinzhao30/IPI,
commit 2c96ea8 (`.upstream/ipi-agent`).

## Why there is no adapter

The agent is not in the repository. The README's status list says so directly:

> 🚧 **IPI-Agent code**: coming soon.

What the commit contains:

| Path | Content |
|---|---|
| `Benchmark/` | IPIBench annotations (9 task files, e.g. 972 samples in `Proactive_Timing.json`) |
| `Src/Qwen3_VL_8B/<group>/<task>.py` | the reference **baseline**: plain Qwen3-VL-8B inference, one script per task |
| `Evaluate/<group>/<task>.py` | scoring scripts for the baseline's result files |

The `Src/` scripts are the benchmark's baseline loop, not IPI-Agent. Each script steps through
annotated times; at every step it rebuilds the prompt from the benchmark question and the last
`--max_frames` (16) frame files of the clip, asks Qwen3-VL-8B, and reads `<attention>` or `<silence>` from
the reply (`Src/Qwen3_VL_8B/Proactive_Monitoring/Proactive_Timing.py:40-49` `extract_result`, `:113-212` the step loop). The interleaved
tasks re-send the model's own earlier answers (`ans1`, `ans2`) as assistant turns in the next chat
(`Src/Qwen3_VL_8B/Interleaved_Reactive_Proactive/Reactive_under_Proactive.py:129-211`). There is no
interaction-control policy, no memory tool, and no temporal-gating mechanism anywhere in the repository
(no Python file in the repository mentions memory, gating, or a policy).

Running `Src/` with the backbone would therefore measure the paper's Qwen3-VL-8B baseline under the name
of the agent. The channels the survey labels for this configuration (S->M, M->A, A->S, M->S reported)
belong to the agent's components, so none of their cut sites exists in the released code: frames are
re-read from disk each step rather than retained (no S->M or M->S site), nothing is retrieved beyond the
sliding frame window and the benchmark-scripted chat (no M->A memory tool), and the gating that would
decide what to sense next (A->S) is not implemented.

## What would make it runnable

Release of the IPI-Agent code (interaction-control policy, memory tool, temporal gating). With it, the
plan from the brief applies: run the agent loop with Qwen3-VL replaced by the backbone and frames as
text, and cut S->M, M->A, A->S and M->S at their receivers.
