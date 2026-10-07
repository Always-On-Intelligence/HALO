"""Per-run workspace staging for VisualClawArena scenarios.

The agent (Claude Code, OpenClaw, …) operates on an isolated *work copy* of the
scenario's `workspace/` directory. This prevents one run from polluting another
and prevents the source `benchmark/data/<scenario>/workspace/` from drifting.

Multimodal extension: walkthrough keyframes are extracted from the scenario's
clip and dropped into `<work_copy>/_clip_frames/<MM_SS>.jpg` so the agent's
native Read tool can load them as image content blocks (this is how text-only
CLI agents access images — see SCHEMA_ALIGNMENT_PROPOSAL.md / engine docstrings).

Forked structurally from ClawArena `src/clawarena/data_handlers/openclaw/work_copy.py`,
stripped to single-scenario / no-framework-overlay mode.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkCopy:
    """Staged per-run workspace for one scenario run."""

    run_dir: Path                       # runs/<scenario>/<run_id>/
    workspace: Path                     # <run_dir>/workspace/ — agent's cwd
    clip_frames_dir: Path               # <workspace>/_clip_frames/
    scenario_dir: Path                  # source: benchmark/data-spec/<scenario>/
    data_dir: Path                      # source: benchmark/data/<scenario>/
    agent_log_dir: Path                 # <run_dir>/agent_logs/  (per-round logs)
    keyframe_labels: list[str] = field(default_factory=list)


def stage_workspace(
    *,
    scenario_dir: Path,
    data_dir: Path,
    run_dir: Path,
) -> WorkCopy:
    """Create an isolated working copy of the scenario's workspace.

    Layout produced:
        <run_dir>/
            workspace/                      ← deep copy of <data_dir>/workspace/
                _clip_frames/               ← populated by stage_keyframes()
                (scenario files)
            sessions/                       ← copy of <data_dir>/sessions/
            updates/                        ← copy of <data_dir>/updates/  (deferred apply)
            agent_logs/                     ← per-round stdout/stderr
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    ws = run_dir / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    src_ws = data_dir / "workspace"
    if src_ws.exists():
        shutil.copytree(src_ws, ws)
    else:
        ws.mkdir(parents=True, exist_ok=True)
        logger.warning("no source workspace at %s; created empty", src_ws)

    # Sessions + updates passthrough (engines may stage further per-round)
    for sub in ("sessions", "updates"):
        src = data_dir / sub
        dst = run_dir / sub
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)

    clip_frames_dir = ws / "_clip_frames"
    clip_frames_dir.mkdir(parents=True, exist_ok=True)

    agent_log_dir = run_dir / "agent_logs"
    agent_log_dir.mkdir(parents=True, exist_ok=True)

    return WorkCopy(
        run_dir=run_dir,
        workspace=ws,
        clip_frames_dir=clip_frames_dir,
        scenario_dir=scenario_dir,
        data_dir=data_dir,
        agent_log_dir=agent_log_dir,
    )


def stage_keyframes(
    *,
    work_copy: WorkCopy,
    keyframes: list[bytes],
    keyframe_labels: list[str],
) -> list[Path]:
    """Write the extracted keyframes into the workspace as `_clip_frames/<MM_SS>.jpg`.

    Filename convention: 'MM:SS' label → 'MM_SS.jpg' (colons are filesystem-fragile).
    The agent will reference them via Read('_clip_frames/00_18.jpg').
    """
    paths: list[Path] = []
    for label, jpeg in zip(keyframe_labels, keyframes):
        fname = label.replace(":", "_") + ".jpg"
        out = work_copy.clip_frames_dir / fname
        out.write_bytes(jpeg)
        paths.append(out)
    work_copy.keyframe_labels = list(keyframe_labels)
    return paths


def apply_updates_to_workcopy(
    *,
    work_copy: WorkCopy,
    update_ids: list[str],
) -> list[dict[str, Any]]:
    """Apply update_ids to the staged workspace by copying files from
    <data_dir>/updates/<update_id>/ into <workspace>/. Mirrors the existing
    runner.apply_updates logic but operates on the staged copy."""
    applied: list[dict[str, Any]] = []
    if not update_ids:
        return applied
    updates_root = work_copy.data_dir / "updates"
    if not updates_root.exists():
        return applied
    for uid in update_ids:
        src_dir = updates_root / uid
        if not src_dir.is_dir():
            logger.warning("update %s: source dir not found at %s", uid, src_dir)
            continue
        for src in src_dir.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(src_dir)
            # Skip update_manifest.json — it's metadata, not workspace content
            if rel.name == "update_manifest.json":
                continue
            dst = work_copy.workspace / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            applied.append({"update_id": uid, "target": str(rel), "action": "new"})
            logger.info("update %s: staged workspace/%s", uid, rel)
    return applied
