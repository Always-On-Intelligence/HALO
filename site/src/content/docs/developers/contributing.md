---
title: Contributing
description: How to change HALO and these docs.
---

## Changing the rules

The analysis follows the definitions of the survey and of `halo/read/protocol/PROTOCOL.md`. A change to how channels, steps, or levels are read should cite the definition it follows, change `halo/mcp/analysis.py`, add a case to `tests/test_mcp.py`, and update [Analysis](/HALO/architecture/analysis/).

## Adding a tool

Keep the event model small. A new kind of event needs a module of the loop or a step of the evidence chain to belong to, and a rule in the analysis that reads it. Tool descriptions are read by agents, so they say when to call the tool in plain words.

## These docs

The docs are an Astro Starlight site in `site/`.

```bash
cd site
npm install
npm run dev        # http://localhost:4321/HALO/
npm run build      # static files in site/dist
```

Pages are Markdown in `site/src/content/docs/`. The theme is `site/src/styles/theme.css`, and the header tabs and sidebar are the components in `site/src/components/`.
