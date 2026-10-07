# Operating contract: morning dock inspection (Pedal Commons bike share)

Goal: keep this morning's fleet record and the shop-van list correct for the operations lead.

Evidence available: the walkthrough clip of the four campus docks (keyframes in `_clip_frames/`), `fleet.csv` and
earlier outputs in `docs/`.

Inspection rules (they override general habits):
1. A bike is ride-ready only if all three checks pass in the clip: both tyres firm (no visible sag or flat), the
   front light lit, and the bell present. A bike that fails any one check goes in the van to the shop.
2. Empty dock slots are ignored.
3. For the state of each bike the clip at the cited timestamp is authoritative; `fleet.csv` is last week's export.

Output protocol: write deliverables under `docs/`, use the JSON keys exactly as the request names them, write bike
numbers as on the frame tag (for example "#102"), and cite visual evidence as `[clip @ MM:SS]`.
