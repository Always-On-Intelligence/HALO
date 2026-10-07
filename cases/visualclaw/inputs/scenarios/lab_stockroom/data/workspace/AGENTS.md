# Operating contract: weekly consumables stock check (Osei Lab)

Goal: keep this week's consumables stock record and Friday's reorder list correct for the lab manager.

Evidence available: the walkthrough clip of the consumables storage (keyframes in `_clip_frames/`),
`inventory.csv` (last month's export), `par_levels.csv`, and earlier outputs in `docs/`.

Counting rules (they override general habits):
1. On-hand stock counts sealed, unopened units only. An opened box, rack, bag or bottle is "in use" at
   the bench and is never counted as stock, however full it is.
2. For physical counts the walkthrough clip at the cited timestamp is authoritative. `inventory.csv` is
   last month's export and is not updated between checks.
3. An item is reordered when its on-hand count is below its par level in `par_levels.csv`.

Output protocol: write deliverables under `docs/`, use the JSON keys exactly as the request names them,
use the item names as written in `inventory.csv`, and cite visual evidence as `[clip @ MM:SS]`.
