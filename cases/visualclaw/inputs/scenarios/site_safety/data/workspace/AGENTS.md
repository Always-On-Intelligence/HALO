# Operating contract: PPE walk (Riverside Block C site)

Goal: keep today's PPE record and the correction list correct for the site supervisor.

Evidence available: the walkthrough clip of the site walk (keyframes in `_clip_frames/`), `crew.csv` and earlier
outputs in `docs/`.

PPE rules (they override general habits):
1. A worker is PPE-compliant only if hard hat, hi-vis vest AND safety glasses are all worn. Glasses pushed up onto
   the hat or hanging from the vest are not worn.
2. Inside the yellow-hatched crusher zone, hearing protection (muffs or plugs) is also required.
3. Gloves are not part of this check.
4. For what each worker wears the clip at the cited timestamp is authoritative; `crew.csv` lists who is on shift.

Output protocol: write deliverables under `docs/`, use the JSON keys exactly as the request names them, identify
workers by their vest number (for example "#12"), and cite visual evidence as `[clip @ MM:SS]`.
