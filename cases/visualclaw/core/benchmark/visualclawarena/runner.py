#!/usr/bin/env python3
"""
runner.py — VisualClawArena scenario runner.

Outer orchestrator: loads a scenario, stages a per-run workspace (deep copy of
the scenario's data/workspace/ + extracted keyframes), runs the 25 rounds
sequentially against the chosen *backend*, scores each round, and writes
results.json + per-round logs.

Three backends are supported today (--backend):

    single        J1 baseline — one VLM call per round; workspace + sessions
                  inlined into the prompt; expects \\bbox{X} or
                  '### WRITE_FILE: path' markup back from the model.

    claude-code   J2 — per-round invocation of `claude_agent_sdk.query()`
                  with the staged workspace as cwd. The agent uses native
                  Read/Write/Edit/Bash/Glob/Grep tools. Keyframes are written
                  to <workspace>/_clip_frames/<MM_SS>.jpg and the agent's
                  Read tool returns them as image content blocks.

    codex         Per-round invocation of `codex exec` with the staged
                  workspace as cwd. Codex reads via CLI tools and emits
                  machine-readable file operations that the engine applies;
                  keyframes are staged under _clip_frames/.

On the claude-code backend the VisualClaw stack is opt-in via flags (route B,
direct module import — no gateway): --keyframe-mode lightweight/bitcost (J3),
--skills-mode inject (J4), --memory (J5), --evolve (J6). See
docs/visualclawarena/STATUS_2026_05_22.md.

The canonical doc is `docs/visualclawarena/RUNNER.md`. See PITFALLS.md Part C for
agent-backend-specific gotchas (claude CLI auth, --max-turns, etc.).

Usage
-----
    # Smoke test (no VLM, no agent, mock responses):
    python -m benchmark.visualclawarena.runner \\
        --scenario-dir benchmark/data-spec/mmt_s1 \\
        --output-dir /tmp/_smoke --dry-run --max-rounds 3

    # Single-call VLM baseline:
    python -m benchmark.visualclawarena.runner \\
        --scenario-dir benchmark/data-spec/mmt_s1 \\
        --provider openai --model gpt-5.2 \\
        --max-keyframes 8

    # Agent-as-tool via Claude Code SDK (real tool use, ~30-120s/round):
    python -m benchmark.visualclawarena.runner \\
        --scenario-dir benchmark/data-spec/mmt_s1 \\
        --backend claude-code \\
        --agent-timeout 600 --agent-max-turns 30

Output layout
-------------
    runs/<scenario>/<run_id>/
        workspace/                  (staged copy; agent's cwd, persists across rounds)
            _clip_frames/<MM_SS>.jpg  (keyframes, Read-able by agents as images)
        sessions/                   (copy of source sessions)
        updates/                    (copy of source updates; staged on trigger)
        agent_logs/<qid>/           (agent backends only)
            prompt.txt
            answer.txt
            transcript.json
        access_logs/<qid>.jsonl
        results.json
        diagnostic.json

Dependencies
------------
    single        OpenCV + a VLM provider SDK (handled by benchmark/vlm_client.py)
    claude-code   pip install claude-agent-sdk    (+ `claude login` on host)
    codex         codex CLI authenticated on host
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncio

import cv2  # type: ignore

from visualclaw.env import load_dotenv
from benchmark.vlm_client import VLMClient, create_vlm_client
from benchmark.visualclawarena.access_logger import AccessLogger
from benchmark.visualclawarena.eval import score_mc_round, score_ec_round
from benchmark.visualclawarena.work_copy import (
    WorkCopy,
    apply_updates_to_workcopy,
    stage_keyframes,
    stage_workspace,
)

logger = logging.getLogger(__name__)


def resolve_scenario_layout(
    scenario_dir: Path,
    data_dir: Path | None,
) -> tuple[str, Path, Path, str]:
    """Resolve scenario id, data dir, eval dir, and eval agent id.

    Historical repo layout:

        benchmark/data-spec/<scenario_id>
        benchmark/data/<scenario_id>

    Hugging Face release layout:

        scenarios/<scenario_id>/spec
        scenarios/<scenario_id>/data

    Exec-check commands usually use `${eval_dir}/${agent_id}/scripts/...`.
    For the HF layout, `eval_dir` is the `spec/` directory and `agent_id` is
    `.` so the existing commands resolve to `spec/./scripts/...`.
    """
    if scenario_dir.name == "spec" and (scenario_dir.parent / "data").exists():
        scenario_id = scenario_dir.parent.name
        resolved_data_dir = data_dir or (scenario_dir.parent / "data")
        eval_dir = scenario_dir
        return scenario_id, resolved_data_dir, eval_dir, "."

    scenario_id = scenario_dir.name
    resolved_data_dir = data_dir or (scenario_dir.parent.parent / "data" / scenario_id)
    eval_dir = scenario_dir.parent
    return scenario_id, resolved_data_dir, eval_dir, scenario_id


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are the agent in an VisualClawArena scenario.

You have access to:
- A workspace at `workspace/` containing reference files (listed below).
- A walkthrough clip (visible as supplied frames).
- Prior rounds' outputs you have written to `workspace/` are persistent.

When citing evidence, use these formats:
- Video frame: `[clip @ MM:SS]`
- Document: `[doc:filename]`
- Image: `[image:filename]`
- PDF: `[pdf:filename]`
- Audio: `[audio:filename @ MM:SS]`
- Chat: `[chat:speaker @ HH:MM]`

If the scenario's narrative framing of the walkthrough seems to contradict
what you see in the keyframes (e.g. the narrative says "store interior" but
the frames show a residential room), trust the keyframes for specific
timestamp-cited visual facts. The narrative is a story layered on top of a
real walkthrough — when a question cites `[clip @ MM:SS]`, the visual content
at that frame is authoritative regardless of how the overall walkthrough is
framed elsewhere.

For multi-choice rounds, output your final letter answer as `\\bbox{X}` on
its own line.

For exec_check rounds (which ask you to produce a file), output the file
content in this exact form on its own line, then a fenced code block:

    ### WRITE_FILE: relative/path/in/workspace.ext
    ```
    ... file content ...
    ```

You may emit multiple WRITE_FILE blocks. The benchmark will write each to
the workspace before scoring.
"""


def list_workspace_files(workspace: Path) -> list[Path]:
    """All files under workspace/ (recursively, excluding hidden)."""
    if not workspace.exists():
        return []
    return sorted(
        p for p in workspace.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.parts)
    )


def workspace_summary(workspace: Path, char_budget: int = 20_000) -> str:
    """Inline-bundle workspace text/markdown into the prompt."""
    files = list_workspace_files(workspace)
    if not files:
        return "(workspace is empty)"
    chunks: list[str] = []
    used = 0
    for f in files:
        rel = f.relative_to(workspace)
        suffix = f.suffix.lower()
        if suffix in {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".py", ".jsonl"}:
            try:
                body = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                chunks.append(f"### {rel}\n(binary, {f.stat().st_size}B — not inlined)")
                continue
            remaining = char_budget - used
            if remaining <= 200:
                chunks.append(f"### {rel}\n(truncated — char budget exhausted)")
                break
            body = body[:remaining - 100]
            chunks.append(f"### {rel}\n```\n{body}\n```")
            used += len(body) + 100
        else:
            chunks.append(f"### {rel}\n(non-text, {f.stat().st_size}B)")
    return "\n\n".join(chunks)


def session_summary(sessions_dir: Path, char_budget: int = 10_000) -> str:
    """Inline the JSONL session histories."""
    if not sessions_dir.exists():
        return "(no sessions)"
    chunks: list[str] = []
    used = 0
    for s in sorted(sessions_dir.glob("*.jsonl")):
        try:
            body = s.read_text(encoding="utf-8")
        except OSError:
            continue
        remaining = char_budget - used
        if remaining <= 200:
            break
        body = body[:remaining - 100]
        chunks.append(f"### session: {s.name}\n```\n{body}\n```")
        used += len(body) + 100
    return "\n\n".join(chunks) if chunks else "(no sessions)"


# ---------------------------------------------------------------------------
# Clip frame extraction
# ---------------------------------------------------------------------------


def extract_uniform_frames(
    clip_path: Path, max_keyframes: int = 4
) -> tuple[list[bytes], list[str]]:
    """Sample max_keyframes evenly across the clip. Returns (jpeg_bytes, mmss_labels)."""
    if not clip_path.exists():
        return [], []
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return [], []
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or total <= 0:
        cap.release()
        return [], []
    duration = total / fps
    frames: list[bytes] = []
    labels: list[str] = []
    for k in range(max_keyframes):
        t = duration * (k + 0.5) / max_keyframes
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            continue
        ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok2:
            continue
        frames.append(buf.tobytes())
        m = int(t // 60); s = int(round(t - m * 60))
        labels.append(f"{m:02d}:{s:02d}")
    cap.release()
    return frames, labels


# ---------------------------------------------------------------------------
# Update application (L4 dynamic updates)
# ---------------------------------------------------------------------------


def apply_updates(
    update_ids: list[str],
    data_dir: Path,
    workspace: Path,
) -> list[dict[str, Any]]:
    """Apply L4 update_manifest.json actions for each triggered update_id.
    Returns the list of applied action records."""
    applied: list[dict[str, Any]] = []
    for uid in update_ids:
        manifest_path = data_dir / "updates" / uid / "update_manifest.json"
        if not manifest_path.exists():
            logger.warning("update %s manifest missing at %s", uid, manifest_path)
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for action in manifest.get("files", []):
            verb = action.get("action")
            target = workspace / action.get("target", "")
            source = (data_dir / "updates" / uid / action.get("source", "")) if action.get("source") else None
            if verb == "new" or verb == "replace":
                if source and source.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    applied.append({"update_id": uid, "action": verb, "target": str(target.relative_to(workspace))})
                else:
                    logger.warning("update %s: source %s missing", uid, source)
            elif verb == "delete":
                if target.exists():
                    target.unlink()
                    applied.append({"update_id": uid, "action": "delete", "target": str(target.relative_to(workspace))})
    return applied


# ---------------------------------------------------------------------------
# Agent file-write parsing (EC support without true tool-use)
# ---------------------------------------------------------------------------

WRITE_FILE_RE = re.compile(
    r"###\s*WRITE_FILE:\s*([^\n]+?)\s*\n```[a-zA-Z]*\n(.*?)```",
    re.DOTALL,
)


def apply_agent_writes(response: str, workspace: Path) -> list[str]:
    """Parse ``### WRITE_FILE: path`` blocks and write them into workspace.
    Returns list of relative paths written."""
    written: list[str] = []
    for m in WRITE_FILE_RE.finditer(response):
        rel = m.group(1).strip().lstrip("/")
        if ".." in Path(rel).parts:
            logger.warning("skipping write outside workspace: %s", rel)
            continue
        body = m.group(2)
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        written.append(rel)
    return written


# ---------------------------------------------------------------------------
# Round execution
# ---------------------------------------------------------------------------


def build_round_prompt(
    rnd: dict[str, Any],
    workspace: Path,
    sessions_dir: Path | None,
    keyframe_labels: list[str],
) -> str:
    """Compose the user prompt for the round (image content is supplied
    separately via the VLM's image input)."""
    parts: list[str] = []
    parts.append(f"# Round {rnd.get('id')} ({rnd.get('type')})")
    parts.append(f"## Question\n{rnd.get('question','')}")

    if rnd.get("type") == "multi_choice":
        options = rnd.get("eval", {}).get("options", {})
        if options:
            opt_lines = [f"- **{k}**: {v}" for k, v in options.items()]
            parts.append("## Options\n" + "\n".join(opt_lines))
        parts.append("Reply with reasoning then `\\bbox{X}` on its own line.")
    else:
        parts.append(
            "This is an exec_check round. Produce the requested file(s) using "
            "`### WRITE_FILE: path` blocks per the system prompt."
        )

    if keyframe_labels:
        parts.append(
            "## Clip frames supplied\nIn-call image attachments (uniform sample): "
            + ", ".join(f"`clip @ {lbl}`" for lbl in keyframe_labels)
        )

    parts.append("## Workspace contents\n" + workspace_summary(workspace))
    if sessions_dir and sessions_dir.exists():
        parts.append("## Sessions history\n" + session_summary(sessions_dir))

    return "\n\n".join(parts)


def run_round(
    rnd: dict[str, Any],
    *,
    scenario_dir: Path,
    data_dir: Path,
    workspace: Path,
    vlm: VLMClient | None,
    keyframes: list[bytes],
    keyframe_labels: list[str],
    access_logger: AccessLogger,
    eval_dir: Path | None = None,
    eval_agent_id: str | None = None,
    dry_run: bool = False,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Run one round end-to-end."""
    qid = rnd.get("id", "?")
    access_logger.begin_round(qid)

    # Apply any updates that fire at this round
    update_ids = rnd.get("update_ids") or []
    applied_updates = apply_updates(update_ids, data_dir, workspace) if update_ids else []
    if applied_updates:
        for au in applied_updates:
            access_logger.log("text", f"workspace/{au['target']}", "update_apply",
                              update_id=au["update_id"], action=au["action"])

    # Log clip access (uniform sample, no cascade in J1)
    if keyframes:
        access_logger.log_clip_access(
            "clip.mp4",
            keyframes_forwarded=keyframe_labels,
            via="uniform_sample",
        )
    # Log workspace reads (we inline everything for J1; record one entry per file)
    for f in list_workspace_files(workspace):
        rel = f.relative_to(workspace)
        if f.suffix.lower() in {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".jsonl"}:
            access_logger.log_text_read(f"workspace/{rel}")
        else:
            access_logger.log("text", f"workspace/{rel}", "list_only")

    prompt = build_round_prompt(rnd, workspace, data_dir / "sessions", keyframe_labels)

    # Agent call
    t0 = time.monotonic()
    if dry_run or vlm is None:
        # Mock response that produces predictable scoring
        if rnd.get("type") == "multi_choice":
            answers = rnd.get("eval", {}).get("answer", ["A"])
            response = f"(dry-run mock)\n\n\\bbox{{{answers[0] if answers else 'A'}}}"
        else:
            response = "(dry-run mock — no file writes)"
        usage = {"input_tokens": 0, "output_tokens": 0}
    else:
        images_b64 = [base64.b64encode(k).decode("ascii") for k in keyframes]
        response = vlm._call_sync(
            question=prompt,
            images_b64=images_b64,
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
        )
        usage = dict(vlm.usage_stats)
    latency = round(time.monotonic() - t0, 3)

    # Persist prompt + response per round (unified with claude-code's agent_logs/<qid>/)
    # so we can diagnose format-follow failures, MC parse failures, etc.
    try:
        log_dir = workspace.parent / "agent_logs" / qid
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (log_dir / "answer.txt").write_text(response or "", encoding="utf-8")
    except Exception:
        pass  # logging is best-effort; never break the round on a log write

    # EC: write any WRITE_FILE blocks the agent emitted
    files_written: list[str] = []
    if rnd.get("type") == "exec_check":
        files_written = apply_agent_writes(response, workspace)
        for rel in files_written:
            access_logger.log("text", f"workspace/{rel}", "agent_write")

    # Score
    if rnd.get("type") == "multi_choice":
        mc = score_mc_round(rnd, response)
        result = {
            "id": qid, "type": "multi_choice",
            "passed": mc.passed, "score": mc.score,
            "extracted": mc.extracted, "expected": mc.expected,
            "parse_method": mc.parse_method,
            "latency_sec": latency,
        }
    else:
        scenario_id_v = scenario_id or scenario_dir.name
        score_eval_dir = eval_dir or scenario_dir.parent
        score_agent_id = eval_agent_id or scenario_id_v
        ec = score_ec_round(rnd, score_eval_dir, score_agent_id, workspace)
        result = {
            "id": qid, "type": "exec_check",
            "passed": ec.passed, "score": ec.score,
            "exit_code": ec.exit_code,
            "stdout_tail": ec.stdout_tail, "stderr_tail": ec.stderr_tail,
            "command_executed": ec.command_executed,
            "expect_exit": ec.expect_exit,
            "files_written_by_agent": files_written,
            "parse_notes": ec.parse_notes,
            "latency_sec": latency,
        }

    result["applied_updates"] = applied_updates
    result["response_chars"] = len(response or "")
    result["usage"] = usage
    access_logger.end_round()
    return result


# ---------------------------------------------------------------------------
# Agent-backend round runner (Claude Code, OpenClaw, ...)
# ---------------------------------------------------------------------------


_CLIP_CITE_RE = __import__("re").compile(r"\[clip\s*@\s*\d{1,2}:\d{2}(?::\d{2})?\]")


def build_agent_round_prompt(
    rnd: dict[str, Any],
    workspace: Path,
    keyframe_labels: list[str],
    *,
    schema_file_preflight: bool = False,
) -> str:
    """Minimal prompt for an agent with native file/shell tools.

    Contrast with `build_round_prompt`: that function INLINES workspace + sessions
    into the prompt for single-call VLMs. Here we point at the workspace and
    let the agent use its native tools — that's the whole reason we use an
    agent backend.

    Keyframes are referenced ONLY when the round's question / feedback actually
    cites `[clip @ MM:SS]`. Listing keyframes on rounds that don't need them
    measurably hurt accuracy (agent gets distracted by irrelevant visual
    content and writes worse files on doc-only EC rounds). Empirical:
    audit of 47 clip-lost rounds across 9 CLIP_HURTS scenarios showed 39/47
    (83%) had no clip citation. See detect_text_only_solvable.py history.
    """
    qid = rnd.get("id", "?")
    rtype = rnd.get("type", "?")
    parts: list[str] = [f"# Round {qid} ({rtype})", "## Task", rnd.get("question", "")]

    # Does this round actually want the agent to look at the clip?
    cite_text = (rnd.get("question", "") or "") + " " + str(rnd.get("feedback", ""))
    wants_clip = bool(keyframe_labels) and bool(_CLIP_CITE_RE.search(cite_text))

    if rtype == "multi_choice":
        opts = rnd.get("eval", {}).get("options") or {}
        if opts:
            parts.append("## Options")
            parts.extend(f"- **{k}**: {v}" for k, v in opts.items())
        if wants_clip:
            parts.append(
                "Decide using the workspace files + walkthrough keyframes "
                "(see _clip_frames/ below). End your final response with "
                "`\\bbox{X}` on its own line — that's the only output the scorer reads."
            )
        else:
            parts.append(
                "Decide using the workspace files. End your final response with "
                "`\\bbox{X}` on its own line — that's the only output the scorer reads."
            )
    else:
        if schema_file_preflight:
            preflight = _build_exec_preflight(rnd, workspace)
            if preflight:
                parts.append(preflight)
        if wants_clip:
            parts.append(
                "This is an exec_check round. Read whatever inputs you need from "
                "the current directory (workspace files, sessions/, _clip_frames/<MM_SS>.jpg "
                "keyframes) and write the output file(s) requested by the task into the "
                "workspace. The runner will validate by inspecting workspace state after "
                "you exit — do not only print the file content; actually create or edit "
                "the requested file(s)."
            )
        else:
            parts.append(
                "This is an exec_check round. Read whatever inputs you need from "
                "the current directory (workspace files, sessions/) and write the "
                "output file(s) requested by the task into the workspace. The runner "
                "will validate by inspecting workspace state after you exit — do not "
                "only print the file content; actually create or edit the requested file(s)."
            )

    if wants_clip:
        frame_refs = ", ".join(
            f"`_clip_frames/{lbl.replace(':','_')}.jpg`" for lbl in keyframe_labels
        )
        parts.append(
            "## Walkthrough keyframes\n"
            f"Uniform sample of the walkthrough video, on disk at: {frame_refs}. "
            "Inspect them with your image/file-reading tools before answering "
            "timestamp-grounded visual questions."
        )

    # Brief top-level workspace listing so the agent knows what's there without us
    # inlining the contents. (Agent uses Read/Glob to dive deeper.)
    try:
        top_entries = sorted(
            p.name for p in workspace.iterdir() if not p.name.startswith(".")
        )
        if top_entries:
            parts.append("## Workspace top-level\n" + "\n".join(f"- {n}" for n in top_entries))
    except FileNotFoundError:
        pass

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Route-B memory injection (J5) — direct import of visualclaw's memory module
# ---------------------------------------------------------------------------


def _prepend_memory(memory_block: str, prompt: str) -> str:
    """Prepend retrieved memory to a round prompt (route-B injection)."""
    return (
        "## Relevant memory from earlier rounds of this scenario\n\n"
        f"{memory_block}\n\n---\n\n{prompt}"
    )


_PATH_REF_RE = re.compile(
    r"`((?:docs|schemas|workspace|sessions|updates|audio)/[^`\s]+)`|"
    r"\[(?:doc|pdf|audio|image):([^\] @]+)",
)


def _normalize_workspace_ref(path_ref: str) -> str:
    rel = path_ref.strip().strip("`").strip()
    if rel.startswith("workspace/"):
        rel = rel[len("workspace/"):]
    return rel


def _extract_path_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in _PATH_REF_RE.finditer(text or ""):
        ref = match.group(1) or match.group(2) or ""
        ref = _normalize_workspace_ref(ref)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _infer_output_paths(question: str) -> list[str]:
    """Best-effort extraction of files the round asks the agent to write."""
    outputs: list[str] = []
    for ref in _extract_path_refs(question):
        if ref.startswith("docs/") and ref not in outputs:
            outputs.append(ref)
    for match in re.finditer(
        r"\b(?:write|create|produce|save|emit|update)\s+"
        r"((?:docs/)[A-Za-z0-9_./-]+)",
        question or "",
        flags=re.IGNORECASE,
    ):
        ref = match.group(1).rstrip(".,;:)")
        if ref not in outputs:
            outputs.append(ref)
    return outputs


def _schema_required_summary(schema_path: Path) -> str:
    try:
        data = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        return "(schema unreadable)"

    bits: list[str] = []
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        bits.append(f"title={title.strip()}")
    required = data.get("required")
    if isinstance(required, list) and required:
        bits.append("required=" + ", ".join(str(x) for x in required[:12]))
    props = data.get("properties")
    if isinstance(props, dict) and props:
        bits.append("properties=" + ", ".join(list(props.keys())[:14]))
    items = data.get("items")
    if isinstance(items, dict):
        item_required = items.get("required")
        if isinstance(item_required, list) and item_required:
            bits.append("item_required=" + ", ".join(str(x) for x in item_required[:12]))
        item_props = items.get("properties")
        if isinstance(item_props, dict) and item_props:
            bits.append("item_properties=" + ", ".join(list(item_props.keys())[:14]))
    return "; ".join(bits) if bits else "(no top-level required/properties summary)"


def _infer_schema_paths(question: str, workspace: Path, output_paths: list[str]) -> list[str]:
    schemas: list[str] = []
    for ref in _extract_path_refs(question):
        norm = _normalize_workspace_ref(ref)
        if norm.startswith("schemas/") and norm.endswith(".json") and norm not in schemas:
            schemas.append(norm)

    schema_dir = workspace / "schemas"
    if schema_dir.exists():
        output_stems = {
            Path(p).stem.lower()
            .replace("_v1", "")
            .replace("_v2", "")
            .replace("_v3", "")
            .replace(".schema", "")
            for p in output_paths
        }
        for path in sorted(schema_dir.glob("*.json")):
            rel = path.relative_to(workspace).as_posix()
            stem = path.stem.lower().replace(".schema", "")
            if rel in schemas:
                continue
            if any(s and (s in stem or stem in s) for s in output_stems):
                schemas.append(rel)
        if not schemas and "schema" in (question or "").lower():
            for path in sorted(schema_dir.glob("*.json"))[:6]:
                schemas.append(path.relative_to(workspace).as_posix())
    return schemas


def _build_exec_preflight(rnd: dict[str, Any], workspace: Path) -> str:
    question = str(rnd.get("question", "") or "")
    output_paths = _infer_output_paths(question)
    schema_paths = _infer_schema_paths(question, workspace, output_paths)
    if not output_paths and not schema_paths:
        return ""

    lines = ["## v3.1 file/schema preflight"]
    lines.append("Before finalizing this exec_check round, verify:")
    if output_paths:
        lines.append("- Required output file(s): " + ", ".join(f"`{p}`" for p in output_paths))
    else:
        lines.append("- Required output file(s): infer from the task, then create every requested artifact.")
    if schema_paths:
        lines.append("- Schema file(s) to inspect before writing:")
        for rel in schema_paths:
            lines.append(f"  - `{rel}`: {_schema_required_summary(workspace / rel)}")
    lines.extend([
        "- JSON artifacts must use the expected top-level type and required keys exactly.",
        "- Do not leave requested artifacts missing, empty, or only described in prose.",
        "- For visual claims, include required P2 citations such as `[clip @ MM:SS]`.",
    ])
    return "\n".join(lines)


def _rounds_reference_clip(rounds: list[dict[str, Any]]) -> bool:
    """Return True if selected rounds cite clip timestamps."""
    clip_re = re.compile(r"\[clip\s*@\s*\d{1,2}:\d{2}(?::\d{2})?\]")
    for rnd in rounds:
        for key in ("question", "feedback"):
            val = rnd.get(key)
            if clip_re.search(json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val or "")):
                return True
    return False


def _store_round_memory(
    memory_mgr: Any, scope_id: str, session_id: str, question: str, answer: str,
    round_type: str = "", round_passed: bool | None = None,
) -> int:
    """Store one round's outcome as an episodic memory unit for later rounds.

    Content is built directly rather than via extract_from_qa: that helper
    truncates the answer to its first 200 chars, which on VisualClawArena rounds is
    just the agent's preamble ("All inputs reviewed. Now I'll analyze...") —
    noise. We keep the full question + the tail of the answer (the conclusion).

    v4 Fix 0: ``round_passed`` is plumbed through into MemoryUnit.outcome so
    retrieval can warn future rounds about failed prior reasoning. Pass
    None when the round outcome is unknown (e.g., scoring crashed)."""
    import uuid
    from visualclaw.modules.memory.models import MemoryType, MemoryUnit, utc_now_iso

    q = (question or "").strip()
    a = (answer or "").strip()
    if not q:
        return 0
    tail = a[-700:].strip()
    label = f"Round {session_id}" + (f" ({round_type})" if round_type else "")
    content = f"{label} — Q: {q}"
    if tail:
        content += f"\nConclusion: {tail}"
    now = utc_now_iso()
    outcome = ""
    if round_passed is True:
        outcome = "passed"
    elif round_passed is False:
        outcome = "failed"
    unit = MemoryUnit(
        memory_id=str(uuid.uuid4()),
        scope_id=scope_id,
        memory_type=MemoryType("episodic"),
        content=content,
        summary=q[:200],
        source_session_id=session_id,
        importance=0.55,
        confidence=0.70,
        created_at=now,
        updated_at=now,
        outcome=outcome,
    )
    return memory_mgr._persist_units(scope_id, session_id, [unit])


async def run_round_with_agent(
    rnd: dict[str, Any],
    *,
    engine: Any,
    work_copy: WorkCopy,
    scenario_dir: Path,
    eval_dir: Path,
    eval_agent_id: str,
    scenario_id: str,
    access_logger: AccessLogger,
    agent_timeout: float,
    skill_manager: Any = None,
    memory_mgr: Any = None,
    memory_max_chars: int = 0,
    memory_failure_handling: str = "neutral",
    memory_top_k: int = 0,
    schema_file_preflight: bool = False,
) -> dict[str, Any]:
    """Run one round using an agent engine (Claude Code SDK / OpenClaw / ...).
    Workspace state is the source of truth; we never parse `### WRITE_FILE:`
    blocks — the agent uses its native Write tool."""
    qid = rnd.get("id", "?")
    rtype = rnd.get("type", "?")
    access_logger.begin_round(qid)

    # Apply updates that fire at this round
    update_ids = rnd.get("update_ids") or []
    applied = apply_updates_to_workcopy(work_copy=work_copy, update_ids=update_ids)
    for au in applied:
        access_logger.log("text", f"workspace/{au['target']}", "update_apply",
                          update_id=au["update_id"], action=au["action"])

    # Log clip access (uniform sample, staged to disk)
    if work_copy.keyframe_labels:
        access_logger.log_clip_access(
            "clip.mp4",
            keyframes_forwarded=work_copy.keyframe_labels,
            via="uniform_sample_staged",
        )

    prompt = build_agent_round_prompt(
        rnd,
        work_copy.workspace,
        work_copy.keyframe_labels,
        schema_file_preflight=schema_file_preflight,
    )

    # J4 runner-side skill injection: retrieve relevant skills for this round's
    # question, prepend formatted text to the prompt. Same SkillManager / same
    # skill bank the gateway would have used; just injected at a different stage.
    #
    # v3 fix (2026-05-22): qa_types.json filtering. SkillManager.retrieve() does
    # not honor qa_types.json — only SkillWire.get_system_prompt does. The
    # runner has historically called bare retrieve() and got the unfiltered
    # bank, so MC-only seed skills like `answer-format-completion` leaked into
    # EC rounds and degraded EC accuracy (~−4pp across s1/s7/s12 in the v3
    # calib sweep). We now honor qa_types.json explicitly here: skills with no
    # tag are universal; skills with a tag list are kept only when this
    # round's type is in that list.
    injected_skills: list[str] = []
    if skill_manager is not None:
        try:
            skills = skill_manager.retrieve(rnd.get("question", ""))
            if skills:
                # Load qa_types sidecar for the active bank and filter by round type.
                qa_type = rnd.get("type", "")
                # SkillManager exposes the bank dir as the private `_skills_dir`
                # attribute (no public alias). Caught here on 2026-05-22 after
                # a smoke that returned 0 skills on ALL rounds because
                # `skill_manager.skills_dir` raised AttributeError silently
                # under the surrounding try/except.
                _bank_dir = getattr(skill_manager, "_skills_dir", "")
                qa_tags_path = Path(_bank_dir) / "qa_types.json" if _bank_dir else None
                if (
                    (
                        os.environ.get("VISUALCLAW_ARENA_DISABLE_SKILL_HYGIENE")
                        or os.environ.get("MM_ARENA_DISABLE_SKILL_HYGIENE")
                    )
                    != "1"
                    and qa_type
                    and qa_tags_path is not None
                    and qa_tags_path.exists()
                ):
                    try:
                        qa_tags = json.loads(qa_tags_path.read_text(encoding="utf-8"))
                    except Exception:
                        qa_tags = {}
                    if qa_tags:
                        filtered = []
                        for s in skills:
                            name = getattr(s, "name", None) or (
                                s.get("name", "") if isinstance(s, dict) else ""
                            )
                            tags_for_skill = qa_tags.get(name)
                            # Untagged skills are universally applicable;
                            # tagged skills inject only on matching qa_type.
                            if tags_for_skill is None or qa_type in tags_for_skill:
                                filtered.append(s)
                        skills = filtered
                if skills:
                    skill_text = skill_manager.format_for_injection_hybrid(skills)
                    prompt = (
                        "## Reasoning skills relevant to this round\n\n"
                        + skill_text
                        + "\n\n---\n\n"
                        + prompt
                    )
                    injected_skills = [getattr(s, "name", "?") for s in skills]
                    access_logger.log("text", "skill_bank", "retrieve_inject",
                                      skills=injected_skills)
        except Exception as e:
            logger.warning("skill injection failed for %s: %s", qid, e)

    # J5 runner-side memory injection: retrieve memories stored by earlier
    # rounds of this scenario (scope_id = scenario_id → per-scenario isolation).
    # v4 Fix 0 + Fix 1: render_for_prompt now accepts max_chars (length cap)
    # and failure_handling (failure-aware retrieval). See
    # docs/visualclawarena/V4_MEMORY_FIXES_DESIGN.md §2.
    mem_hits = 0
    if memory_mgr is not None:
        try:
            hits = memory_mgr.retrieve_for_prompt(rnd.get("question", ""),
                                                  scope_id=scenario_id,
                                                  top_k=memory_top_k or None)
            mem_hits = len(hits)
            mem_block = memory_mgr.render_for_prompt(
                hits,
                max_chars=memory_max_chars,
                failure_handling=memory_failure_handling,
            )
            if mem_block:
                prompt = _prepend_memory(mem_block, prompt)
                access_logger.log("text", "memory", "memory_inject", n_hits=mem_hits)
        except Exception as e:
            logger.warning("memory injection failed for %s: %s", qid, e)

    t0 = time.monotonic()
    agent_result = await engine.run_agent(
        message=prompt,
        workspace=work_copy.workspace,
        timeout=agent_timeout,
        extra_env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
    )
    latency = round(time.monotonic() - t0, 3)

    # Persist per-round agent log
    log_dir = work_copy.agent_log_dir / qid
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (log_dir / "answer.txt").write_text(agent_result.answer or "", encoding="utf-8")
    if agent_result.transcript:
        (log_dir / "transcript.json").write_text(
            json.dumps(agent_result.transcript, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if agent_result.raw is not None:
        (log_dir / "raw.json").write_text(
            json.dumps(agent_result.raw, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    if agent_result.error:
        (log_dir / "error.txt").write_text(agent_result.error, encoding="utf-8")
        error_tail = (agent_result.error or "")[-1000:].strip()
        logger.error(
            "agent_error qid=%s status=%s returncode=%s: %s",
            qid,
            agent_result.status,
            agent_result.returncode,
            error_tail,
        )
        if (
            os.environ.get("VISUALCLAW_ARENA_ABORT_ON_AGENT_ERROR")
            or os.environ.get("MM_ARENA_ABORT_ON_AGENT_ERROR")
            or "0"
        ) == "1":
            raise RuntimeError(
                f"agent error in round {qid} "
                f"(status={agent_result.status}, returncode={agent_result.returncode}): "
                f"{error_tail}"
            )

    # Score
    if rtype == "multi_choice":
        mc = score_mc_round(rnd, agent_result.answer or "")
        result: dict[str, Any] = {
            "id": qid, "type": "multi_choice",
            "passed": mc.passed, "score": mc.score,
            "extracted": mc.extracted, "expected": mc.expected,
            "parse_method": mc.parse_method,
            "latency_sec": latency,
        }
    else:
        ec = score_ec_round(rnd, eval_dir, eval_agent_id, work_copy.workspace)
        result = {
            "id": qid, "type": "exec_check",
            "passed": ec.passed, "score": ec.score,
            "exit_code": ec.exit_code,
            "stdout_tail": ec.stdout_tail, "stderr_tail": ec.stderr_tail,
            "command_executed": ec.command_executed,
            "expect_exit": ec.expect_exit,
            "parse_notes": ec.parse_notes,
            "latency_sec": latency,
        }

    result["applied_updates"] = applied
    result["agent_status"] = agent_result.status
    result["agent_error"] = agent_result.error
    result["response_chars"] = len(agent_result.answer or "")
    if isinstance(agent_result.raw, dict) and isinstance(agent_result.raw.get("file_ops"), dict):
        file_ops = agent_result.raw["file_ops"]
        result["file_ops_found_block"] = bool(file_ops.get("found_block"))
        result["file_ops_applied"] = len(file_ops.get("applied") or [])
        result["file_ops_errors"] = list(file_ops.get("errors") or [])
    if injected_skills:
        result["injected_skills"] = injected_skills
    if memory_mgr is not None:
        # Store this round's Q&A immediately so the next round can retrieve it.
        # v4 Fix 0: tag the memory with this round's pass/fail outcome so
        # retrieval can warn future rounds about failed prior reasoning.
        try:
            n_stored = _store_round_memory(
                memory_mgr, scenario_id, qid,
                rnd.get("question", ""), agent_result.answer or "",
                round_type=rtype,
                round_passed=bool(result.get("passed")),
            )
        except Exception as e:
            logger.warning("memory store failed for %s: %s", qid, e)
            n_stored = 0
        result["memory_hits"] = mem_hits
        result["memory_stored"] = n_stored
    access_logger.end_round()
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="VisualClawArena scenario runner")
    parser.add_argument("--scenario-dir", type=Path, required=True,
                        help="Path to data-spec/<scenario>/ (questions.json, scripts/)")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="Path to data/<scenario>/ (clip, workspace/, sessions/, updates/). "
                             "Defaults to <scenario-dir>/../../data/<scenario_name>")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Base output dir. Run produces <output-dir>/<run_id>/")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Override run id (default: timestamp-provider-model)")
    parser.add_argument("--max-keyframes", type=int, default=4,
                        help="Max clip frames per round")
    parser.add_argument("--keyframe-mode",
                        choices=["uniform", "lightweight", "bitcost", "cascade", "blockwise", "uniform_anchor", "sb_cascade"],
                        default="cascade",
                        help="DEFAULT changed to cascade on 2026-05-28 — text-only audit "
                             "showed "
                             "uniform-default unfairly suppressed clip-with-cited-timestamp "
                             "rounds. Pass --keyframe-mode uniform to reproduce pre-2026-05-28 "
                             "behavior. Choices below: "
                             "uniform = N evenly-spaced frames (legacy J1/J2 default); "
                             "lightweight = dHash + LightweightEncoder + ChangeGate "
                             "event-boundary selection (J3; 'cascade' is a legacy alias); "
                             "bitcost = codec packet-size / GOP cost selection "
                             "(codec-metadata selector); "
                             "blockwise = divide clip into N temporal blocks, pick "
                             "best frame within each (combines uniform's coverage with "
                             "cascade's smart pick); "
                             "uniform_anchor = uniform-N midpoints, with each block's "
                             "midpoint replaced by the nearest [clip @ MM:SS] citation "
                             "in that block; "
                             "sb_cascade = streaming bit-cost cascade: O(N) buffer with "
                             "adaptive block widening, citation stickiness, 60s ring "
                             "buffer for on-query re-emission. The only edge-streaming-"
                             "compatible selector in this set "
                             "(see docs/visualclawarena.md).")
    parser.add_argument("--sb-cascade-w-init", type=float, default=20.0,
                        help="sb_cascade: initial block width W (seconds). Default 20s.")
    parser.add_argument("--sb-cascade-ring-window-s", type=float, default=60.0,
                        help="sb_cascade: rolling buffer retention window. Default 60s.")
    parser.add_argument("--sb-cascade-cite-cache",
                        choices=["on", "off"], default="on",
                        help="sb_cascade: persistent citation cache. ON = any "
                             "cite seen during stream is retrievable post-stream "
                             "(small memory cost, ~50KB×Ncites). OFF = legacy "
                             "ring-window only (drops mid-clip cites on long "
                             "sessions). Default ON.")
    parser.add_argument("--cascade-sample-fps", type=float, default=1.0,
                        help="frame sampling rate for lightweight/cascade mode "
                             "(default 1.0 fps)")
    parser.add_argument("--cascade-tau-major", type=float, default=0.30,
                        help="cosine-distance threshold for cascade MAJOR-decision "
                             "(0.10–0.40 typical; lower = more keyframes)")
    parser.add_argument("--cascade-force-dedup-gap-s", type=float, default=5.0,
                        help="v4 Tier B.3: min temporal gap (s) between citation-"
                             "anchored forced keyframes. Two cited timestamps within "
                             "this gap collapse to the earlier. Default 5.0; reduce "
                             "to 2.0 to keep more near-adjacent citations.")
    parser.add_argument("--bitcost-quota-bytes", type=int, default=0,
                        help="Bit-cost mode: packet-byte quota per group. "
                             "0 = auto total_pkt_size / --max-keyframes.")
    parser.add_argument("--bitcost-pick-policy",
                        choices=["peak_motion", "first_iframe", "middle"],
                        default="peak_motion",
                        help="Bit-cost mode: representative frame chosen from each "
                             "quota/GOP group. Default peak_motion.")
    parser.add_argument("--blockwise-signal",
                        choices=["bitcost", "cosine", "uniform_mid"],
                        default="bitcost",
                        help="Block-wise mode: signal used to pick the best frame "
                             "within each block. 'uniform_mid' = block midpoint "
                             "(reproduces pure uniform sampling).")
    parser.add_argument("--blockwise-tiebreak",
                        choices=["peak_motion", "first", "latest", "median"],
                        default="peak_motion",
                        help="Block-wise mode: when multiple [clip @ MM:SS] citations "
                             "land in the same block, which one wins. Default peak_motion.")
    parser.add_argument("--pin-cited-timestamps", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Auto-pin every `[clip @ MM:SS]` timestamp cited in "
                             "questions.json so cascade includes them in the keyframe set. "
                             "DEFAULT changed to ON on 2026-05-28 per text-only audit "
                             "(see docs/visualclawarena.md). Pass "
                             "--no-pin-cited-timestamps to disable (reproduces pre-audit "
                             "behavior; s38 pilot showed pins crowded out uniform coverage "
                             "on rounds without citations, but on the full corpus the gain "
                             "is large and consistent).")
    parser.add_argument("--provider", type=str, default=None,
                        help="VLM provider: gemini / openai / bedrock (auto if unset)")
    parser.add_argument("--model", type=str, default=None,
                        help="Model override")
    parser.add_argument("--dry-run", action="store_true",
                        help="No VLM calls; returns mock responses (always picks first answer for MC)")
    parser.add_argument("--allow-missing-clips", action="store_true",
                        help="Allow running without clip mp4s even when questions cite "
                             "`[clip @ MM:SS]`. Intended only for text-only leakage audits.")
    parser.add_argument("--max-rounds", type=int, default=0,
                        help="If >0, run only the first N rounds (smoke test)")
    parser.add_argument("--round-ids", type=str, default="",
                        help="Comma-separated round ids to run, e.g. q2,q17. "
                             "Applied before --max-rounds; preserves questions.json order.")
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="Max output tokens for single-backend VLM calls "
                             "(default 8192; needed because EC rounds emit file content + "
                             "reasoning. vlm_client.py's own default of 1024 truncates "
                             "mid-reasoning; 4096 still truncates large EC writes.)")
    parser.add_argument("--backend", choices=["single", "claude-code", "codex"], default="single",
                        help="single = J1 single-call VLM with inlined workspace (default); "
                             "claude-code = agent-as-tool via claude_agent_sdk; "
                             "codex = agent-as-tool via codex exec")
    parser.add_argument("--agent-timeout", type=float, default=600.0,
                        help="Per-round timeout for agent backends (seconds, default 600)")
    parser.add_argument("--agent-max-turns", type=int, default=30,
                        help="Max tool-use turns per round for agent backends (default 30)")
    parser.add_argument("--agent-effort", choices=["low", "medium", "high", "xhigh", "max"], default=None,
                        help="Claude Code reasoning effort for agent backends that support it")
    parser.add_argument("--gateway-url", type=str, default=None,
                        help="If set, route claude-code's Anthropic API calls through "
                             "the VisualClaw gateway at this URL "
                             "(e.g., http://127.0.0.1:30100). When set, the gateway "
                             "transparently injects skill/memory/cascade per its config. "
                             "See docs/visualclawarena/GATEWAY_WIRING_PLAN.md. "
                             "Default: direct to api.anthropic.com.")
    parser.add_argument("--gateway-api-key", type=str, default=None,
                        help="Auth token for the gateway. If unset, gateway must accept "
                             "the default ANTHROPIC_API_KEY pass-through.")
    parser.add_argument("--skills-mode", choices=["off", "inject"], default="off",
                        help="off (default) = no skill priming; "
                             "inject = retrieve relevant skills from "
                             "visualclaw.modules.skill.SkillManager per round and "
                             "prepend to the agent prompt (J4 runner-side fallback "
                             "to gateway routing — same skill bank, same retrieval, "
                             "injected directly in the prompt rather than via gateway "
                             "pre-pipeline). Only meaningful with agent backends.")
    parser.add_argument("--skills-dir", type=str, default=None,
                        help="Override the skill bank directory for --skills-mode inject "
                             "(default: config skill.skills_dir). Point at "
                             "visualclaw/skills_seed/seed_visualclawarena for the EC-discipline bank.")
    parser.add_argument("--memory", action="store_true",
                        help="J5 — enable VisualClaw memory v2 (route B, direct import). "
                             "Each round's Q&A is stored to a per-run, per-scenario memory "
                             "scope; memories relevant to the question are retrieved and "
                             "prepended to each later round's prompt. Agent backends only.")
    # v4 (J6+): memory failure-awareness + length cap.
    # See docs/visualclawarena/V4_MEMORY_FIXES_DESIGN.md §2.
    parser.add_argument("--memory-max-chars", type=int, default=0,
                        help="v4 Fix 1 — total-character cap on the rendered memory "
                             "block. Hits are sorted by retrieval score before "
                             "truncation. 0 = no cap (default; matches v3 behavior). "
                             "Recommended for VisualClawArena: 4000.")
    parser.add_argument("--memory-failure-handling",
                        choices=["warn", "exclude", "neutral"], default="neutral",
                        help="v4 Fix 0 (infrastructure available; empirically not "
                             "recommended). 'warn' prefixes failed-round memories "
                             "with a warning so the agent doesn't replicate the "
                             "reasoning. 'exclude' drops failed memories. "
                             "'neutral' (default) = v3 behavior. EMPIRICAL NOTE: "
                             "the s11 retry (2026-05-23) showed 'warn' produces the "
                             "expected prefixes but does NOT lift accuracy — the "
                             "cascade pattern is correlative, not causative; the "
                             "real failure mode is categorical confusion under "
                             "context load, not memory replication. See "
                             "docs/visualclawarena/J6_FINDINGS_2026_05_22.md §9.")
    parser.add_argument("--memory-top-k", type=int, default=0,
                        help="v3.1 — cap retrieved memory hits before rendering. "
                             "0 = policy default (v3 behavior). Recommended v3.1 "
                             "value for VisualClawArena m8 is 5, matching the observed "
                             "sweet spot before mem6+ degradation.")
    parser.add_argument("--schema-file-preflight", action="store_true",
                        help="v3.1 — prepend an exec_check checklist inferred from "
                             "the task: requested docs/* outputs, referenced schemas, "
                             "and schema required-key summaries. Off by default to "
                             "preserve v3 runs.")
    parser.add_argument("--evolve", action="store_true",
                        help="J6 — enable skill self-evolution. After the scenario, failed "
                             "rounds are fed to the skill evolver (gpt-5.2), which writes new "
                             "skills into the working bank. Offline — new skills benefit later "
                             "runs. Requires --skills-mode inject; needs OPENAI_API_KEY in env.")
    parser.add_argument("--evolve-bank-dir", type=str, default="runs/_skill_bank",
                        help="Writable skill bank for --evolve (seeded once from --skills-dir; "
                             "persists across runs so evolved skills carry across scenarios).")
    # v3 (J6+): cross-scenario buffer + memory fusion + F2 prune via SkillWire.
    # See docs/visualclawarena/J6_FINDINGS_2026_05_22.md §6 for motivation.
    parser.add_argument("--skills-cross-scenario-buffer", type=Path, default=None,
                        help="v3 — JSONL file persisting failure samples across scenarios. "
                             "When set, the evolver pools failures from all prior scenarios "
                             "(via this file) with the current scenario's failures, then evolves "
                             "from the union. Fixes the v2 limitation where evolve never fired "
                             "because per-scenario buffers reset between Python processes.")
    parser.add_argument("--skills-buffer-n", type=int, default=10,
                        help="v3 — min total buffered failures (across-scenario) required "
                             "to trigger an evolve call. Default 10. With cross-scenario buffer "
                             "this is reachable after a handful of scenarios.")
    parser.add_argument("--skills-evolve-every", type=int, default=5,
                        help="v3 within-day — fire the evolver every N within-scenario "
                             "failures. "
                             "Newly-evolved skills are written to the skill bank and become "
                             "visible to LATER rounds in the SAME scenario, so accuracy should "
                             "ideally rise as the 'day' progresses. Default 5 (up to ~5 fires "
                             "per 25-round scenario). Set to 0 to disable within-day evolve "
                             "(legacy end-of-scenario-only behavior, useful for reproducing "
                             "Phase4B-style sequential warm-bank runs).")
    parser.add_argument("--memory-evolver-fusion", action="store_true",
                        help="v3 — feed successful-pattern context from memory to the evolver "
                             "(in addition to failures). Requires --memory + --evolve. "
                             "Mirrors the VisualClaw V-MME working config: "
                             "evolver sees BOTH what went wrong AND what's been going right.")
    parser.add_argument("--memory-evolver-context-mode",
                        choices=["success_blocks", "related_prefix", "simple_concat"],
                        default="success_blocks",
                        help="v3.1 ablation — how --memory-evolver-fusion builds "
                             "extra context for skill evolution. success_blocks "
                             "preserves v3.1 behavior: append up to 10 successful "
                             "answer excerpts. related_prefix retrieves memory "
                             "relevant to the failures and prefixes that bounded "
                             "context into the evolver prompt. simple_concat "
                             "retrieves the same bounded memory but concatenates it "
                             "into the standard evolver prompt without prefix guidance.")
    parser.add_argument("--memory-evolver-related-top-k", type=int, default=0,
                        help="v3.1 ablation — retrieved-memory top-k for "
                             "--memory-evolver-context-mode=related_prefix. "
                             "0 falls back to --memory-top-k, then 5.")
    parser.add_argument("--memory-evolver-related-max-chars", type=int, default=0,
                        help="v3.1 ablation — total character cap for retrieved "
                             "evolver-memory context. 0 falls back to "
                             "--memory-max-chars, then 4000.")
    parser.add_argument("--evolver-model", type=str, default=None,
                        help="v3 — override evolver model (e.g. us.anthropic.claude-sonnet-4-6). "
                             "Default: skill.evolver_model from config (gpt-5.2).")
    parser.add_argument("--evolver-backend", choices=["bedrock", "openai", "claude-code"], default=None,
                        help="v3 — backend for the skill evolver. Default preserves the existing "
                             "Bedrock route. Use claude-code to route evolution through Claude Code auth.")
    parser.add_argument("--evolver-effort", choices=["low", "medium", "high", "xhigh", "max"], default=None,
                        help="v3 — Claude Code effort level when --evolver-backend=claude-code.")
    parser.add_argument("--utility-prune", action="store_true",
                        help="v3 — enable F2 utility-prune via SkillWire. After every "
                             "--utility-prune-every questions, drop skills whose accuracy is "
                             "more than --utility-prune-margin below the bank mean. "
                             "This is what lifted v2 calib s22 (+12pp) and s30 (+8pp).")
    parser.add_argument("--utility-prune-every", type=int, default=15,
                        help="v3 — F2 prune cadence in questions (default 15 — about one "
                             "prune fire per scenario at 25 rounds).")
    parser.add_argument("--utility-prune-margin", type=float, default=0.05,
                        help="v3 — F2 prune margin: drop skills with accuracy < bank_mean − margin.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    scenario_dir = args.scenario_dir
    if not (scenario_dir / "questions.json").exists():
        print(f"[FAIL] {scenario_dir}/questions.json not found", file=sys.stderr)
        return 2

    scenario_id, data_dir, eval_dir, eval_agent_id = resolve_scenario_layout(
        scenario_dir, args.data_dir
    )
    if args.data_dir is None:
        logger.info("data-dir auto-resolved to %s", data_dir)
    logger.info(
        "scenario id resolved to %s; eval dir: %s; eval agent id: %s",
        scenario_id, eval_dir, eval_agent_id,
    )
    if not data_dir.exists():
        logger.warning("data-dir %s does not exist — runs will lack clip/workspace/sessions",
                       data_dir)

    output_base = args.output_dir or Path("runs") / scenario_id
    provider_label = args.provider or "auto"
    model_label = args.model or "default"
    run_id = args.run_id or datetime.utcnow().strftime("%Y%m%dT%H%M%S") + f"-{provider_label}-{model_label}"
    if args.dry_run:
        run_id += "-dry"
    out_dir = output_base / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("run dir: %s", out_dir)

    # Stage the workspace (deep copy + _clip_frames/ + agent_logs/)
    work_copy = stage_workspace(
        scenario_dir=scenario_dir, data_dir=data_dir, run_dir=out_dir,
    )
    workspace = work_copy.workspace
    logger.info("staged workspace: %s", workspace)

    # Set up access logger
    al = AccessLogger(run_id=run_id, access_logs_dir=out_dir / "access_logs")

    # Set up backend
    vlm: VLMClient | None = None
    engine: Any = None
    skill_manager = None
    if args.evolve and args.skills_mode != "inject":
        print("[FAIL] --evolve requires --skills-mode inject", file=sys.stderr)
        return 3
    agent_backends = {"claude-code", "codex"}
    if (args.memory or args.evolve) and args.backend not in agent_backends:
        print("[FAIL] --memory / --evolve require an agent backend (claude-code or codex)",
              file=sys.stderr)
        return 3
    if args.skills_mode == "inject":
        from visualclaw.config import load_config as _load_cfg
        from visualclaw.modules.skill.manager import SkillManager
        _mm_cfg = _load_cfg()
        active_skills_dir = args.skills_dir or str(_mm_cfg.skill.skills_dir)
        if args.evolve:
            # Evolution mutates the bank — never the version-controlled seed.
            # Use a persistent working copy seeded once from --skills-dir.
            # Robust against pre-created-but-empty BANK_DIR (e.g. launch
            # scripts that `mkdir -p` the path before calling the runner —
            # see fix in scripts/launch_v3_evolve_calib_2026_05_22.sh).
            bank = Path(args.evolve_bank_dir)
            needs_seed = (
                not bank.exists()
                or not any(bank.rglob("SKILL.md"))
            )
            if needs_seed:
                if bank.exists():
                    # Empty / partially-populated dir: copy seed contents in place.
                    for item in Path(active_skills_dir).iterdir():
                        dst = bank / item.name
                        if item.is_dir():
                            shutil.copytree(item, dst, dirs_exist_ok=True)
                        else:
                            shutil.copy2(item, dst)
                else:
                    shutil.copytree(active_skills_dir, bank)
                logger.info("evolve: seeded working skill bank %s from %s",
                            bank, active_skills_dir)
            active_skills_dir = str(bank)
        skill_manager = SkillManager(_mm_cfg.skill, _mm_cfg.vision_retrieval,
                                     skills_dir=active_skills_dir)
        skill_manager.load()
        logger.info("skills-mode=inject: SkillManager loaded from %s (top_k=%d)%s",
                    active_skills_dir, _mm_cfg.skill.top_k,
                    " [+evolve]" if args.evolve else "")

    # v3 (J6+): SkillWire wrapper — enables F2 utility-prune, memory-evolver
    # fusion, and the cross-scenario failure buffer. See
    # docs/visualclawarena/J6_FINDINGS_2026_05_22.md §6 (recommendation B+).
    # Active only when any v3 flag is set; otherwise the legacy direct
    # SkillEvolver path runs below (collab's existing wiring stays untouched
    # so old run scripts keep behaving identically).
    skill_wire = None
    if args.skills_mode == "inject" and (
        args.utility_prune
        or args.memory_evolver_fusion
        or args.skills_cross_scenario_buffer is not None
    ):
        from benchmark.skill_wire import SkillWire
        _evolver_backend = (
            args.evolver_backend
            or os.environ.get("VISUALCLAW_ARENA_EVOLVER_BACKEND")
            or os.environ.get("MM_ARENA_EVOLVER_BACKEND")
            or "bedrock"
        )
        if _evolver_backend == "claude-code":
            _evolver_model = (
                args.evolver_model
                or args.model
                or os.environ.get("VISUALCLAW_ARENA_CLAUDE_MODEL")
                or os.environ.get("MM_ARENA_CLAUDE_MODEL")
                or "sonnet"
            )
        else:
            _evolver_model = args.evolver_model or "us.anthropic.claude-sonnet-4-6"
        skill_wire = SkillWire(
            skills_dir=active_skills_dir,
            bedrock_model=_evolver_model,
            use_bedrock=(_evolver_backend == "bedrock"),
            evolver_backend=_evolver_backend,
            claude_effort=args.evolver_effort,
            injection_mode="hybrid",
            hybrid_top_k=3,
            utility_prune=args.utility_prune,
            utility_prune_every=args.utility_prune_every,
            utility_prune_margin=args.utility_prune_margin,
            history_path=str(Path(active_skills_dir) / "v3_evolution_history.jsonl"),
        )
        # Share the runner's SkillManager so retrieve()/inject() stay in sync
        # with F2 tracking. We track activation manually (see results loop)
        # because the runner does its own retrieval+formatting and SkillWire
        # only sees the outcomes we feed via record_result().
        skill_wire.manager = skill_manager
        skill_wire.evolver.manager = skill_manager
        logger.info(
            "v3 SkillWire: F2=%s prune_every=%d margin=%.2f evolver=%s backend=%s effort=%s fusion=%s buffer=%s",
            args.utility_prune, args.utility_prune_every, args.utility_prune_margin,
            _evolver_model, _evolver_backend, args.evolver_effort or "(default)",
            args.memory_evolver_fusion,
            str(args.skills_cross_scenario_buffer) if args.skills_cross_scenario_buffer else "off",
        )

    # v3: load cross-scenario failure buffer (failures pooled from prior scenarios)
    # so the evolver can fire even when a single scenario yields too few failures.
    prior_failures: list[dict] = []
    if args.skills_cross_scenario_buffer and args.skills_cross_scenario_buffer.exists():
        try:
            for line in args.skills_cross_scenario_buffer.read_text(
                encoding="utf-8"
            ).splitlines():
                if not line.strip():
                    continue
                prior_failures.append(json.loads(line))
            logger.info("v3 buffer: loaded %d prior failure(s) from %s",
                        len(prior_failures), args.skills_cross_scenario_buffer)
        except Exception as e:
            logger.warning("v3 buffer: failed to load %s: %s",
                           args.skills_cross_scenario_buffer, e)

    if args.backend == "claude-code":
        from benchmark.visualclawarena.engines.claude_code import ClaudeCodeEngine
        engine = ClaudeCodeEngine(
            model=args.model,
            effort=args.agent_effort,
            max_turns=args.agent_max_turns,
            permission_mode="bypassPermissions",
            gateway_url=args.gateway_url,
            gateway_api_key=args.gateway_api_key,
            scenario_id=scenario_id,
        )
        if args.gateway_url:
            logger.info("backend: claude-code via gateway %s (model=%s, max_turns=%d, timeout=%.0fs)",
                        args.gateway_url, args.model or "(default)",
                        args.agent_max_turns, args.agent_timeout)
        else:
            logger.info("backend: claude-code direct (model=%s, effort=%s, max_turns=%d, timeout=%.0fs)",
                        args.model or "(default)", args.agent_effort or "(default)",
                        args.agent_max_turns, args.agent_timeout)
    elif args.backend == "codex":
        from benchmark.visualclawarena.engines.codex_cli import CodexCliEngine
        engine = CodexCliEngine(model=args.model)
        logger.info("backend: codex CLI (model=%s, timeout=%.0fs)",
                    args.model or "(codex-config-default)", args.agent_timeout)
    elif not args.dry_run:
        try:
            vlm = create_vlm_client(
                provider=args.provider, model=args.model, max_tokens=args.max_tokens,
            )
            logger.info("VLM: %s / %s (max_tokens=%d)", vlm.provider, vlm.model, args.max_tokens)
        except Exception as e:
            print(f"[FAIL] could not init VLM ({e}); use --dry-run for smoke", file=sys.stderr)
            return 3

    # Route-B memory injection (J5) — direct module import, no gateway.
    memory_mgr: Any = None
    if args.memory:
        from visualclaw.config import load_config as _load_cfg_mem
        from visualclaw.modules.memory.manager import MemoryManager
        memory_mgr = MemoryManager.from_gateway_config(
            _load_cfg_mem(),
            data_dir=str(out_dir / "memory_data"),
            scope_id=scenario_id,       # memory namespaced per scenario
        )
        logger.info("memory injection ON (route B): scope=%s, store=%s",
                    scenario_id, out_dir / "memory_data")

    def build_related_evolver_memory_context(
        failure_records: list[dict],
        label: str,
    ) -> str:
        """Retrieve bounded, failure-related memory for skill evolution."""
        if (
            not args.memory_evolver_fusion
            or args.memory_evolver_context_mode != "related_prefix"
            or memory_mgr is None
            or not failure_records
        ):
            return ""
        query_lines: list[str] = []
        for fr in failure_records[:12]:
            question = str(fr.get("question") or "").strip()
            if not question:
                continue
            qa_type = str(fr.get("qa_type") or "").strip()
            reference = str(fr.get("reference") or "").strip()
            query_lines.append(
                f"[qa_type={qa_type}] {question}"
                + (f"\nReference: {reference}" if reference else "")
            )
        query_text = "\n\n".join(query_lines).strip()
        if not query_text:
            return ""
        top_k = args.memory_evolver_related_top_k or args.memory_top_k or 5
        max_chars = (
            args.memory_evolver_related_max_chars
            or args.memory_max_chars
            or 4000
        )
        try:
            hits = memory_mgr.retrieve_for_prompt(
                query_text,
                scope_id=scenario_id,
                top_k=top_k,
            )
            block = memory_mgr.render_for_prompt(
                hits,
                max_chars=max_chars,
                failure_handling=args.memory_failure_handling,
            )
        except Exception as e:
            logger.warning("v3 fusion related-prefix retrieval failed (%s): %s", label, e)
            return ""
        if not block:
            logger.info("v3 fusion related-prefix (%s): no retrieved memory", label)
            return ""
        logger.info(
            "v3 fusion related-prefix (%s): %d hit(s), top_k=%d, cap=%d, chars=%d",
            label,
            len(hits),
            top_k,
            max_chars,
            len(block),
        )
        return block

    # Load questions
    questions_data = json.loads((scenario_dir / "questions.json").read_text(encoding="utf-8"))
    rounds = questions_data.get("rounds") or []
    if args.round_ids.strip():
        wanted = {x.strip() for x in args.round_ids.split(",") if x.strip()}
        rounds = [r for r in rounds if str(r.get("id", "")).strip() in wanted]
        missing = wanted - {str(r.get("id", "")).strip() for r in rounds}
        if missing:
            print(f"[FAIL] --round-ids not found in questions.json: {sorted(missing)}", file=sys.stderr)
            return 2
    if args.max_rounds > 0:
        rounds = rounds[: args.max_rounds]
    logger.info("scenario %s — %d rounds to run", scenario_id, len(rounds))

    # Extract uniform clip frames once (J1: no cascade gate) + stage to disk so
    # agent backends can Read them as image content blocks.
    clip_candidates = (
        list((data_dir / "clip").glob("*.mp4")) if (data_dir / "clip").exists() else []
    )
    keyframes: list[bytes] = []
    keyframe_labels: list[str] = []
    if clip_candidates:
        clip_path = clip_candidates[0]
        if args.keyframe_mode in {"lightweight", "cascade", "bitcost", "blockwise", "uniform_anchor", "sb_cascade"}:
            selector_mode = "lightweight" if args.keyframe_mode == "cascade" else args.keyframe_mode
            # Tier B.3 (opt-in via --pin-cited-timestamps): extract every
            # [clip @ MM:SS] reference from questions/feedback and pass these
            # to the frame selector as priority anchor points.
            cited_timestamps_s: list[float] = []
            if getattr(args, "pin_cited_timestamps", False):
                clip_cite_re = re.compile(r"\[clip\s*@\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\]")
                for r in rounds:
                    text = " ".join(str(r.get(k, "")) for k in ("question", "feedback"))
                    for m in clip_cite_re.finditer(text):
                        a, b, c = m.group(1), m.group(2), m.group(3)
                        ts = (
                            int(a) * 60 + int(b)
                            if c is None
                            else int(a) * 3600 + int(b) * 60 + int(c)
                        )
                        cited_timestamps_s.append(float(ts))
                cited_timestamps_s = sorted(set(cited_timestamps_s))
            if cited_timestamps_s:
                logger.info(
                    "%s citation-anchoring: %d unique cited timestamps from questions: %s",
                    selector_mode,
                    len(cited_timestamps_s),
                    [f"{int(t//60):02d}:{int(t%60):02d}" for t in cited_timestamps_s],
                )
            if selector_mode == "lightweight":
                from benchmark.visualclawarena.cascade_frames import cascade_extract_keyframes

                keyframes, keyframe_labels = cascade_extract_keyframes(
                    clip_path,
                    max_keyframes=args.max_keyframes,
                    sample_fps=args.cascade_sample_fps,
                    tau_major=args.cascade_tau_major,
                    force_include_timestamps=cited_timestamps_s or None,
                    force_dedup_gap_s=args.cascade_force_dedup_gap_s,
                )
                logger.info(
                    "lightweight clip: %s → %d keyframes at %s (τ=%.2f, sample %.1f fps, forced=%d)",
                    clip_path.name, len(keyframes), keyframe_labels,
                    args.cascade_tau_major, args.cascade_sample_fps,
                    len(cited_timestamps_s),
                )
            elif selector_mode == "bitcost":
                from benchmark.visualclawarena.bitcost_frames import bitcost_extract_keyframes

                quota_bytes = args.bitcost_quota_bytes if args.bitcost_quota_bytes > 0 else None
                keyframes, keyframe_labels = bitcost_extract_keyframes(
                    clip_path,
                    max_keyframes=args.max_keyframes,
                    quota_bytes=quota_bytes,
                    pick_policy=args.bitcost_pick_policy,
                    force_include_timestamps=cited_timestamps_s or None,
                    force_dedup_gap_s=args.cascade_force_dedup_gap_s,
                )
                logger.info(
                    "bitcost clip: %s → %d keyframes at %s (quota=%s, policy=%s, forced=%d)",
                    clip_path.name, len(keyframes), keyframe_labels,
                    quota_bytes if quota_bytes is not None else "auto",
                    args.bitcost_pick_policy,
                    len(cited_timestamps_s),
                )
            elif selector_mode == "blockwise":
                from benchmark.visualclawarena.blockwise_frames import blockwise_extract_keyframes

                keyframes, keyframe_labels = blockwise_extract_keyframes(
                    clip_path,
                    max_keyframes=args.max_keyframes,
                    signal=args.blockwise_signal,
                    citations=cited_timestamps_s or None,
                    citation_tiebreak=args.blockwise_tiebreak,
                )
                logger.info(
                    "blockwise clip: %s → %d keyframes at %s (signal=%s, tiebreak=%s, citations=%d)",
                    clip_path.name, len(keyframes), keyframe_labels,
                    args.blockwise_signal, args.blockwise_tiebreak,
                    len(cited_timestamps_s),
                )
            elif selector_mode == "uniform_anchor":
                from benchmark.visualclawarena.uniform_anchor_frames import uniform_anchor_extract_keyframes

                keyframes, keyframe_labels = uniform_anchor_extract_keyframes(
                    clip_path,
                    max_keyframes=args.max_keyframes,
                    citations=cited_timestamps_s or None,
                )
                logger.info(
                    "uniform_anchor clip: %s → %d keyframes at %s (citations=%d)",
                    clip_path.name, len(keyframes), keyframe_labels,
                    len(cited_timestamps_s),
                )
            else:  # sb_cascade
                from benchmark.visualclawarena.sb_cascade_frames import sb_cascade_extract_keyframes

                keyframes, keyframe_labels = sb_cascade_extract_keyframes(
                    clip_path,
                    max_keyframes=args.max_keyframes,
                    citations=cited_timestamps_s or None,
                    w_init=args.sb_cascade_w_init,
                    ring_window_s=args.sb_cascade_ring_window_s,
                    enable_cite_cache=(args.sb_cascade_cite_cache == "on"),
                )
                logger.info(
                    "sb_cascade clip: %s → %d keyframes at %s (w_init=%.1f, "
                    "ring=%.0fs, cite_cache=%s, citations=%d)",
                    clip_path.name, len(keyframes), keyframe_labels,
                    args.sb_cascade_w_init, args.sb_cascade_ring_window_s,
                    args.sb_cascade_cite_cache,
                    len(cited_timestamps_s),
                )
        else:
            keyframes, keyframe_labels = extract_uniform_frames(clip_path, args.max_keyframes)
            logger.info("uniform clip: %s → %d keyframes at %s",
                        clip_path.name, len(keyframes), keyframe_labels)
        # Stage to <workspace>/_clip_frames/<MM_SS>.jpg so the agent's Read tool
        # can load them as image content blocks. Harmless for single-call mode
        # (workspace_summary skips non-text files).
        staged = stage_keyframes(
            work_copy=work_copy, keyframes=keyframes, keyframe_labels=keyframe_labels,
        )
        logger.info("staged %d keyframes to %s", len(staged), work_copy.clip_frames_dir)
    else:
        if _rounds_reference_clip(rounds) and not args.allow_missing_clips:
            print(
                f"[FAIL] no clip mp4 found under {data_dir}/clip/ but questions reference "
                "`[clip @ MM:SS]`. Use --allow-missing-clips only for text-only audits.",
                file=sys.stderr,
            )
            return 4
        logger.warning("no clip mp4 found under %s/clip/", data_dir)

    # Run rounds
    results: list[dict[str, Any]] = []
    # v3 within-day evolve: track which round we last fired the evolver after,
    # so subsequent fires only see failures accumulated since.
    last_evolve_at_round = -1
    for i, rnd in enumerate(rounds):
        logger.info("[%d/%d] round %s (%s)",
                    i + 1, len(rounds), rnd.get("id"), rnd.get("type"))
        try:
            if args.backend in agent_backends:
                res = asyncio.run(run_round_with_agent(
                    rnd,
                    engine=engine,
                    work_copy=work_copy,
                    scenario_dir=scenario_dir,
                    eval_dir=eval_dir,
                    eval_agent_id=eval_agent_id,
                    scenario_id=scenario_id,
                    access_logger=al,
                    agent_timeout=args.agent_timeout,
                    skill_manager=skill_manager,
                    memory_mgr=memory_mgr,
                    memory_max_chars=args.memory_max_chars,
                    memory_failure_handling=args.memory_failure_handling,
                    memory_top_k=args.memory_top_k,
                    schema_file_preflight=args.schema_file_preflight,
                ))
            else:
                res = run_round(
                    rnd,
                    scenario_dir=scenario_dir,
                    data_dir=data_dir,
                    workspace=workspace,
                    vlm=vlm,
                    keyframes=keyframes,
                    keyframe_labels=keyframe_labels,
                    access_logger=al,
                    eval_dir=eval_dir,
                    eval_agent_id=eval_agent_id,
                    dry_run=args.dry_run,
                    scenario_id=scenario_id,
                )
        except Exception as e:
            logger.exception("round %s crashed: %s", rnd.get("id"), e)
            res = {"id": rnd.get("id"), "type": rnd.get("type"),
                   "passed": False, "score": 0.0, "error": str(e)}
        results.append(res)
        status = "PASS" if res.get("passed") else "FAIL"
        logger.info("  → %s (score=%.1f)", status, res.get("score", 0.0))
        # v3 F2 tracking: credit/blame the skills that were injected this round,
        # then fire utility-prune if cadence reached. Mirrors V-MME's working
        # SkillWire path. No-op when skill_wire is None (legacy / off).
        if skill_wire is not None:
            injected = res.get("injected_skills") or []
            skill_wire._last_injected = list(injected)
            try:
                skill_wire.record_result(bool(res.get("passed")))
            except Exception as e:
                logger.warning("v3 F2 record_result failed: %s", e)

        # v3 within-day evolve: fire the evolver mid-scenario when enough
        # failures have accumulated since the last fire. New skills are
        # written to disk + injected into skill_manager via add_skill, so
        # LATER rounds in this same scenario see them on retrieve.
        # Keep in-loop evolution tied to the round stream.
        if (
            args.evolve
            and skill_wire is not None
            and skill_manager is not None
            and args.skills_evolve_every > 0
        ):
            new_fails_since = [
                j for j, r in enumerate(results)
                if not r.get("passed") and j > last_evolve_at_round and j < len(rounds)
            ]
            if len(new_fails_since) >= args.skills_evolve_every:
                from benchmark.skill_wire import BenchmarkSample
                in_loop_samples: list[BenchmarkSample] = []
                in_loop_failure_records: list[dict] = []
                for j in new_fails_since:
                    r = results[j]
                    qid_j = r.get("id", "?")
                    qa_dir_j = work_copy.agent_log_dir / qid_j
                    answer_j = ""
                    prompt_seen_j = ""
                    if (qa_dir_j / "answer.txt").exists():
                        answer_j = (qa_dir_j / "answer.txt").read_text(encoding="utf-8")
                    if (qa_dir_j / "prompt.txt").exists():
                        prompt_seen_j = (qa_dir_j / "prompt.txt").read_text(encoding="utf-8")
                    question_j = rounds[j].get("question", "")
                    qa_type_j = rounds[j].get("type", "")
                    ref_j = r.get("expected") or r.get("parse_notes") or ""
                    prompt_tail_j = prompt_seen_j[-2500:] if prompt_seen_j else ""
                    composed_j = (
                        f"[qa_type={qa_type_j}]\n"
                        f"Question: {question_j}\n"
                        + (f"Reference: {ref_j}\n" if ref_j else "")
                        + (f"\n[Agent context tail]\n{prompt_tail_j}\n"
                           if prompt_tail_j else "")
                    )
                    in_loop_samples.append(BenchmarkSample(
                        prompt_text=composed_j,
                        response_text=answer_j,
                        reward=-1.0,
                    ))
                    in_loop_failure_records.append({
                        "scenario_id": scenario_id,
                        "qid": qid_j,
                        "qa_type": qa_type_j,
                        "question": question_j,
                        "answer": answer_j,
                        "prompt_tail": prompt_tail_j,
                        "reference": ref_j,
                        "run_id": run_id,
                    })
                if in_loop_samples:
                    logger.info(
                        "v3 within-day evolve @ round %d/%d: %d new failures since "
                        "last fire (threshold=%d) → SkillWire.evolve_on_failures",
                        i + 1, len(rounds), len(in_loop_samples),
                        args.skills_evolve_every,
                    )
                    in_loop_memory_context = ""
                    in_loop_memory_context_position = "before_instructions"
                    in_loop_memory_title = None
                    in_loop_memory_intro = None
                    if args.memory_evolver_context_mode in {"related_prefix", "simple_concat"}:
                        in_loop_memory_context = build_related_evolver_memory_context(
                            in_loop_failure_records,
                            label=f"within-day@round-{i + 1}",
                        )
                        if (
                            args.memory_evolver_context_mode == "related_prefix"
                            and in_loop_memory_context
                        ):
                            in_loop_memory_context_position = "prefix"
                            in_loop_memory_title = "Related Memory Prefix for Skill Evolution"
                            in_loop_memory_intro = (
                                "This memory was retrieved against the failed round "
                                "questions. Use it as selective, local context for "
                                "evolving skills; avoid importing unrelated scenario "
                                "details into general skills."
                            )
                        elif in_loop_memory_context:
                            in_loop_memory_title = "Concatenated Memory Context"
                            in_loop_memory_intro = (
                                "The following memory was retrieved against the failed "
                                "round questions and concatenated into the normal skill "
                                "evolution prompt. Treat it as auxiliary context, not as "
                                "a targeted prefix or instruction override."
                            )
                    try:
                        new_skills_inloop = asyncio.run(
                            skill_wire.evolve_on_failures(
                                in_loop_samples,
                                force=True,
                                memory_context=in_loop_memory_context,
                                memory_context_position=in_loop_memory_context_position,
                                memory_context_title=in_loop_memory_title,
                                memory_context_intro=in_loop_memory_intro,
                            )
                        )
                        logger.info(
                            "v3 within-day evolve: %d new skill(s) added to live bank: %s",
                            len(new_skills_inloop),
                            [s.get("name", "?") if isinstance(s, dict) else str(s)
                             for s in new_skills_inloop],
                        )
                    except Exception as e:
                        logger.error("v3 within-day evolve failed: %s", e)
                    last_evolve_at_round = i

    # J6 self-evolution. Two paths:
    #   (v3) When skill_wire is bound, route through SkillWire.evolve_on_failures
    #        — pools cross-scenario buffer, applies F1 dedup + F2 prune, and
    #        optionally fuses memory-derived success patterns into the evolver
    #        prompt. This is the path v3 calibration uses.
    #   (legacy) Otherwise: collab's direct SkillEvolver call (unchanged).
    new_skills: list = []
    if args.evolve and skill_manager is not None and skill_wire is not None:
        from benchmark.skill_wire import BenchmarkSample
        # Build richer failure samples — full agent prompt + full answer + the
        # reference answer when available. Evolver needs the same evidence
        # the agent saw to evolve workspace-grounded skills, not text-only ones.
        current_failures: list[BenchmarkSample] = []
        current_failure_records: list[dict] = []  # for cross-scenario buffer persist
        for i, res in enumerate(results):
            if res.get("passed") or i >= len(rounds):
                continue
            qid_i = res.get("id", "?")
            qa_dir = work_copy.agent_log_dir / qid_i
            answer = ""
            prompt_seen = ""
            if (qa_dir / "answer.txt").exists():
                answer = (qa_dir / "answer.txt").read_text(encoding="utf-8")
            if (qa_dir / "prompt.txt").exists():
                prompt_seen = (qa_dir / "prompt.txt").read_text(encoding="utf-8")
            question = rounds[i].get("question", "")
            qa_type = rounds[i].get("type", "")
            # Reference answer / expected output, if discoverable from the
            # scored result (MC: expected option; EC: expect_exit or notes).
            ref = res.get("expected") or res.get("parse_notes") or ""
            # Compose a workspace-grounded prompt_text: question + qa_type +
            # reference + a small snippet of what the agent actually saw.
            # We cap the prompt-seen tail at 2500 chars to keep evolver context
            # tractable (Sonnet 4.6 handles much more, but a tail-only view
            # focuses on the round's specific instructions, not boilerplate).
            prompt_tail = prompt_seen[-2500:] if prompt_seen else ""
            composed_prompt = (
                f"[qa_type={qa_type}]\n"
                f"Question: {question}\n"
                + (f"Reference: {ref}\n" if ref else "")
                + (f"\n[Agent context tail]\n{prompt_tail}\n" if prompt_tail else "")
            )
            current_failures.append(BenchmarkSample(
                prompt_text=composed_prompt,
                response_text=answer,
                reward=-1.0,
            ))
            current_failure_records.append({
                "scenario_id": scenario_id,
                "qid": qid_i,
                "qa_type": qa_type,
                "question": question,
                "answer": answer,
                "prompt_tail": prompt_tail,
                "reference": ref,
                "run_id": run_id,
            })
        # v3: union with prior-scenario buffer (replayed from the JSONL).
        for fr in prior_failures:
            current_failures.append(BenchmarkSample(
                prompt_text=(
                    f"[qa_type={fr.get('qa_type', '')}]\n"
                    f"Question: {fr.get('question', '')}\n"
                    + (f"Reference: {fr.get('reference', '')}\n"
                       if fr.get('reference') else "")
                    + (f"\n[Agent context tail]\n{fr.get('prompt_tail', '')}\n"
                       if fr.get('prompt_tail') else "")
                ),
                response_text=fr.get("answer", ""),
                reward=-1.0,
            ))
        # v3: build memory_context from successful patterns this scenario produced.
        memory_context = ""
        if args.memory_evolver_fusion:
            if args.memory_evolver_context_mode in {"related_prefix", "simple_concat"}:
                memory_context = build_related_evolver_memory_context(
                    current_failure_records,
                    label="end-of-scenario",
                )
            else:
                success_blocks: list[str] = []
                for i, res in enumerate(results):
                    if not res.get("passed") or i >= len(rounds):
                        continue
                    qid_i = res.get("id", "?")
                    q = rounds[i].get("question", "")
                    ans_path = work_copy.agent_log_dir / qid_i / "answer.txt"
                    ans = ans_path.read_text(encoding="utf-8") if ans_path.exists() else ""
                    # Trim each successful answer to keep evolver prompt bounded;
                    # the goal is pattern reinforcement, not full transcripts.
                    success_blocks.append(
                        f"### [qa_type={rounds[i].get('type', '')}] {q[:300]}\n"
                        f"Successful answer (excerpt): {ans[:600]}"
                    )
                    if len(success_blocks) >= 10:
                        break
                if success_blocks:
                    memory_context = "\n\n".join(success_blocks)
                    logger.info("v3 fusion: %d successful-pattern blocks (%d chars)",
                                len(success_blocks), len(memory_context))
        # Trigger the evolver if we cleared the v3 buffer threshold.
        n_total_failures = len(current_failures)
        if n_total_failures >= args.skills_buffer_n:
            logger.info(
                "v3 evolve: %d failures (this-scenario=%d, buffer=%d) → SkillWire.evolve_on_failures (force=True)",
                n_total_failures, len(current_failure_records), len(prior_failures),
            )
            try:
                memory_context_position = "before_instructions"
                memory_context_title = None
                memory_context_intro = None
                if args.memory_evolver_context_mode == "related_prefix" and memory_context:
                    memory_context_position = "prefix"
                    memory_context_title = "Related Memory Prefix for Skill Evolution"
                    memory_context_intro = (
                        "This memory was retrieved against the failed round questions. "
                        "Use it as selective, local context for evolving skills; avoid "
                        "importing unrelated scenario details into general skills."
                    )
                elif args.memory_evolver_context_mode == "simple_concat" and memory_context:
                    memory_context_title = "Concatenated Memory Context"
                    memory_context_intro = (
                        "The following memory was retrieved against the failed round "
                        "questions and concatenated into the normal skill evolution "
                        "prompt. Treat it as auxiliary context, not as a targeted "
                        "prefix or instruction override."
                    )
                new_skills = asyncio.run(
                    skill_wire.evolve_on_failures(
                        current_failures,
                        force=True,                # we already gated on n_total_failures
                        memory_context=memory_context,
                        memory_context_position=memory_context_position,
                        memory_context_title=memory_context_title,
                        memory_context_intro=memory_context_intro,
                    )
                )
                logger.info("v3 evolve: generated %d new skill(s): %s",
                            len(new_skills),
                            [s.get("name", "?") if isinstance(s, dict) else s
                             for s in new_skills])
                # v3: tag the newly-evolved skills with qa_types from the
                # failures that triggered them — so later retrieval only
                # surfaces them on similar question types (Idea-1 routing).
                if new_skills:
                    qa_types_seen = sorted({
                        fr["qa_type"] for fr in current_failure_records
                        if fr.get("qa_type")
                    } | {
                        fr.get("qa_type", "") for fr in prior_failures
                        if fr.get("qa_type")
                    })
                    skill_names = [
                        (s.get("name", "") if isinstance(s, dict) else str(s))
                        for s in new_skills
                    ]
                    try:
                        skill_wire.tag_recently_evolved(skill_names, qa_types_seen)
                        logger.info("v3 tag: %d skills tagged with qa_types=%s",
                                    len(skill_names), qa_types_seen)
                    except Exception as e:
                        logger.warning("v3 tag_recently_evolved failed: %s", e)
            except Exception as e:
                logger.error("v3 evolve failed: %s", e)
        else:
            logger.info(
                "v3 evolve: %d failures (buffer threshold=%d) — skipping; "
                "failures will be persisted to cross-scenario buffer for later run",
                n_total_failures, args.skills_buffer_n,
            )
        # v3: persist this scenario's failures to the cross-scenario buffer so
        # subsequent runs can pool them. Always append (regardless of whether
        # evolve fired) — keeps the buffer the canonical failure ledger.
        if args.skills_cross_scenario_buffer and current_failure_records:
            try:
                args.skills_cross_scenario_buffer.parent.mkdir(parents=True, exist_ok=True)
                with args.skills_cross_scenario_buffer.open("a", encoding="utf-8") as f:
                    for fr in current_failure_records:
                        f.write(json.dumps(fr, ensure_ascii=False) + "\n")
                logger.info("v3 buffer: appended %d failure(s) to %s",
                            len(current_failure_records),
                            args.skills_cross_scenario_buffer)
            except Exception as e:
                logger.warning("v3 buffer: append failed: %s", e)
    elif args.evolve and skill_manager is not None:
        # Legacy collab path (unchanged). Used when no v3 flag is set.
        from benchmark.skill_wire import BenchmarkSample
        from visualclaw.modules.skill.evolver import SkillEvolver
        from visualclaw.config import load_config as _load_cfg_evo
        failures = []
        for i, res in enumerate(results):
            if res.get("passed") or i >= len(rounds):
                continue
            qid_i = res.get("id", "?")
            ans_path = work_copy.agent_log_dir / qid_i / "answer.txt"
            answer = ans_path.read_text(encoding="utf-8") if ans_path.exists() else ""
            failures.append(BenchmarkSample(
                prompt_text=rounds[i].get("question", ""),
                response_text=answer,
                reward=-1.0,
            ))
        if failures:
            logger.info("evolve (legacy): %d failed rounds → running skill evolution",
                        len(failures))
            evolver = SkillEvolver(skill_cfg=_load_cfg_evo().skill, manager=skill_manager)
            current_skills = {
                "general_skills": skill_manager.skills.get("general_skills", []),
                "task_specific_skills": skill_manager.skills.get("task_specific_skills", {}),
                "common_mistakes": skill_manager.skills.get("common_mistakes", []),
            }
            try:
                new_skills = asyncio.run(evolver.evolve(failures, current_skills))
                logger.info("evolve (legacy): generated %d new skill(s): %s",
                            len(new_skills),
                            [s.get("name", "?") if isinstance(s, dict) else s
                             for s in new_skills])
            except Exception as e:
                logger.error("evolve (legacy): evolution failed: %s", e)
        else:
            logger.info("evolve (legacy): 0 failed rounds — nothing to evolve")

    # Aggregate
    n = len(results)
    n_passed = sum(1 for r in results if r.get("passed"))
    outcome_acc = n_passed / n if n else 0.0
    per_q = {r["id"]: {k: v for k, v in r.items() if k != "id"} for r in results}
    if args.backend == "claude-code":
        provider_field = "claude-code"
        model_field = args.model or "(sdk-default)"
    elif args.backend == "codex":
        provider_field = "codex"
        model_field = args.model or "(codex-config-default)"
    elif vlm:
        provider_field, model_field = vlm.provider, vlm.model
    else:
        provider_field, model_field = "dry-run", "dry-run"
    summary = {
        "run_id": run_id,
        "scenario": scenario_id,
        "backend": args.backend,
        "provider": provider_field,
        "model": model_field,
        "agent_effort": args.agent_effort,
        "n_rounds": n,
        "n_passed": n_passed,
        "outcome_accuracy": round(outcome_acc, 4),
        "keyframe_mode": args.keyframe_mode,
        "per_question": per_q,
    }
    if args.skills_mode == "inject":
        summary["skills"] = {"mode": "inject", "skills_dir": active_skills_dir}
    if memory_mgr is not None:
        summary["memory"] = {"scope_id": scenario_id}
    if args.evolve:
        summary["evolution"] = {
            "bank_dir": args.evolve_bank_dir,
            "new_skills": [s.get("name", "?") if isinstance(s, dict) else str(s)
                           for s in new_skills],
        }
        if skill_wire is not None:
            # v3 stats: F2 prune counters, evolved-skill totals, fusion/buffer state.
            try:
                summary["evolution"]["v3"] = {
                    **skill_wire.stats,
                    "memory_evolver_fusion": bool(args.memory_evolver_fusion),
                    "memory_evolver_context_mode": args.memory_evolver_context_mode,
                    "memory_evolver_related_top_k": (
                        args.memory_evolver_related_top_k
                        or args.memory_top_k
                        or None
                    ),
                    "memory_evolver_related_max_chars": (
                        args.memory_evolver_related_max_chars
                        or args.memory_max_chars
                        or None
                    ),
                    "cross_scenario_buffer": (
                        str(args.skills_cross_scenario_buffer)
                        if args.skills_cross_scenario_buffer else None
                    ),
                    "prior_failures_replayed": len(prior_failures),
                    "f2_prune_enabled": bool(args.utility_prune),
                    "evolver_model": (
                        args.evolver_model
                        or (
                            args.model
                            if (
                                args.evolver_backend
                                or os.environ.get("VISUALCLAW_ARENA_EVOLVER_BACKEND")
                                or os.environ.get("MM_ARENA_EVOLVER_BACKEND")
                            ) == "claude-code"
                            else "us.anthropic.claude-sonnet-4-6"
                        )
                    ),
                    "evolver_backend": (
                        args.evolver_backend
                        or os.environ.get("VISUALCLAW_ARENA_EVOLVER_BACKEND")
                        or os.environ.get("MM_ARENA_EVOLVER_BACKEND")
                        or "bedrock"
                    ),
                    "evolver_effort": args.evolver_effort,
                }
            except Exception as e:
                logger.warning("v3 stats serialization failed: %s", e)
    results_path = out_dir / "results.json"
    results_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("wrote %s", results_path)

    # Minimal diagnostic
    diag = {
        "run_id": run_id,
        "scenario": scenario_id,
        "diagnostic_metrics": {
            "rounds_executed": n,
            "outcome_accuracy": round(outcome_acc, 4),
        },
        "note": (f"backend={args.backend}, keyframe_mode={args.keyframe_mode}, "
                 f"skills_mode={args.skills_mode}, "
                 f"memory={'on' if memory_mgr is not None else 'off'}, "
                 f"evolve={'on' if args.evolve else 'off'}"),
    }
    (out_dir / "diagnostic.json").write_text(
        json.dumps(diag, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print()
    print(f"  Run: {run_id}")
    print(f"  Scenario: {scenario_id}")
    print(f"  Rounds: {n_passed}/{n} passed  (outcome_accuracy = {outcome_acc:.1%})")
    print(f"  Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
