# Operating contract: walk-in cooler closing check (Casa Ortega)

Goal: keep tonight's closing record and discard list correct for the chef.

Evidence available: the walkthrough clip of the walk-in cooler (keyframes in `_clip_frames/`), `prep_log.csv`
(what was prepped today) and earlier outputs in `docs/`.

Labelling rules (they override general habits):
1. A container is properly labelled only if its label shows BOTH a prep date and a use-by date. A label with only a
   name, only a prep date or only a use-by date counts as unlabelled.
2. Every container that is not properly labelled goes in the discard bin at close, whatever it holds.
3. For what is on the shelves and how it is labelled, the clip at the cited timestamp is authoritative; `prep_log.csv`
   records what was made, not how it was labelled.

Output protocol: write deliverables under `docs/`, use the JSON keys exactly as the request names them, name
containers as the label or the prep log names them, and cite visual evidence as `[clip @ MM:SS]`.
