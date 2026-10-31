---
title: Run mode
description: Run a system's own code twice, once as released and once with a channel or evidence step cut, and compare.
---

Run mode works like an A/B test. HALO runs a system's released code on fixed inputs, once unmodified and once with selected channels or evidence steps cut, and compares the outputs. Only the model clients are replaced, by one backbone that stays fixed across the two runs, and a blind judge compares the outputs without knowing which run produced which.

## Why an A/B test

A source can show that a channel is implemented, but not that it matters. In the survey, AiGet passes the user profile to Action by two paths. Cutting either path alone left the judge without a clear preference, and cutting both made it prefer the original suggestions. Cutting channels singly and together is the only way to see such effects without trusting the system's description of itself.

## Cut sites

A case declares where each channel or evidence step passes through the system's code and cuts it at the receiving end:

- a channel cut withholds what crosses the channel, for example by emptying the retrieved memory that reaches Action (M→A);
- an evidence-step cut follows the EAIA case: the revision step does not see the actions (record), receives no feedback (outcome), gets feedback attached to the wrong action (attribution), or runs without writing its result (revision, which also covers later use).

## Run it

```bash
uv venv cases/aiget/.venv -p 3.11
uv pip install -p cases/aiget/.venv/bin/python -r cases/aiget/requirements.txt
halo run cases/aiget --workers 4
```

The harness writes every run's output, the judge's verdicts, and a summary to `runs/<case>/<name>/`. [Developers](/HALO/developers/) explains how to add a case.

## Results

The survey's run-mode tests are on [AiGet](/HALO/results/research/#run-mode-aiget), a research system, and on [EAIA](/HALO/results/products/#run-mode-eaia), a product with released code.

## Closed products

A product without released code cannot be cut inside. The same design still works at the product's boundary: run the same scripted inputs with a control the product exposes switched on and off, such as memory, a connected plugin, or feedback, and let the judge compare. [What a trace can show](/HALO/architecture/trust/) describes how this combines with the plugin.
