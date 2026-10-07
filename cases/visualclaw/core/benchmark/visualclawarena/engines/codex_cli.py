"""Codex CLI engine for VisualClawArena agent-backend runs.

Codex ``exec`` can run noninteractively in hosted environments where file-write
approval is unavailable. To keep VisualClawArena's agent-backend contract intact, this
engine asks Codex to emit explicit file operations and applies those operations
locally after the Codex process exits. The runner still sees the same thing it
expects from Claude Code: files changed in the staged workspace before scoring.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .base import AgentEngine, AgentResult


FILE_OPS_BLOCK_RE = re.compile(
    r"```(?:visualclawarena_file_ops|file_ops)\s*(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
WRITE_FILE_BLOCK_RE = re.compile(
    r"<visualclawarena_write_file\s+path=(['\"])(.*?)\1\s*>\n?(.*?)\n?</visualclawarena_write_file>",
    re.DOTALL | re.IGNORECASE,
)
DELETE_FILE_BLOCK_RE = re.compile(
    r"<visualclawarena_delete_file\s+path=(['\"])(.*?)\1\s*/>",
    re.DOTALL | re.IGNORECASE,
)

TEXT_SNAPSHOT_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".py",
    ".text",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_SNAPSHOT_SKIP_DIRS = {
    "__pycache__",
    ".git",
    "_clip_frames",
    "agent_logs",
}
TEXT_SNAPSHOT_SKIP_NAMES = {
    # These scenario control files often describe the legacy `### WRITE_FILE`
    # protocol. The runner/backend prompt is the authority for Codex, so keep
    # them out of the injected snapshot to avoid conflicting output formats.
    "AGENTS.md",
    "IDENTITY.md",
}
DEFAULT_SNAPSHOT_MAX_CHARS = 160_000
DEFAULT_SNAPSHOT_MAX_FILE_CHARS = 24_000
CODEX_FATAL_STDERR_PATTERNS = (
    "image_generation_user_error",
    "The model 'gpt-image-2' does not exist",
)


CODEX_FILE_OPS_INSTRUCTIONS = """\
## Codex backend file-write protocol

You are running under `codex exec`. In this environment write/edit tool calls may
be rejected even when the workspace is writable, and shell reads may also be
rejected in noninteractive exec mode. Use the injected workspace snapshot below
as your primary source of file contents. Do not spend turns trying shell commands
if the needed file contents are already in the snapshot.

For every file that must be created or replaced, end your final answer with one
raw write block per file:

<visualclawarena_write_file path="relative/path/inside/workspace.ext">
complete final file contents
</visualclawarena_write_file>

For deletions, use:

<visualclawarena_delete_file path="relative/path/inside/workspace.ext"/>

Rules:
- Use a write block for create or full replacement.
- Use a delete block only if a file must be removed.
- Paths must be relative to the current workspace.
- Put complete final file content inside the write block; do not use diffs.
- Do not base64-encode file contents.
- Do not wrap the write block itself in Markdown fences.
- For exec_check rounds, write requested files only through these VisualClawArena blocks.
- For multi-choice rounds, still finish with the required `\\bbox{X}` answer.
"""

CODEX_EXEC_CONSTRAINTS = """\
## Codex exec constraints

Do not invoke shell, exec, or filesystem-read commands in this backend. The
noninteractive Codex exec environment may reject those commands, and the
workspace text you need has already been injected above. Use the injected
workspace snapshot and attached images only. For exec_check rounds, create or
replace files only through final `visualclawarena_write_file` blocks.
"""


class CodexCliEngine(AgentEngine):
    name = "codex"

    def __init__(
        self,
        *,
        model: str | None = None,
        codex_bin: str | None = None,
        sandbox_mode: str | None = None,
        approval_policy: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.codex_bin = codex_bin or os.environ.get("CODEX_BIN", "codex")
        self.sandbox_mode = sandbox_mode or os.environ.get(
            "VISUALCLAW_ARENA_CODEX_SANDBOX",
            os.environ.get("MM_ARENA_CODEX_SANDBOX", "read-only"),
        )
        self.approval_policy = approval_policy or os.environ.get(
            "VISUALCLAW_ARENA_CODEX_APPROVAL",
            os.environ.get("MM_ARENA_CODEX_APPROVAL", "on-request"),
        )
        self.reasoning_effort = reasoning_effort or os.environ.get(
            "VISUALCLAW_ARENA_CODEX_REASONING_EFFORT",
            os.environ.get("MM_ARENA_CODEX_REASONING_EFFORT"),
        )

    async def run_agent(
        self,
        *,
        message: str,
        workspace: Path,
        session_id: str | None = None,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> AgentResult:
        ws = workspace.resolve()
        if not ws.exists():
            return AgentResult(
                status="failed",
                answer="",
                error=f"workspace does not exist: {ws}",
            )

        image_paths = _collect_keyframe_images(ws) if "_clip_frames/" in message else []
        with tempfile.NamedTemporaryFile(
            prefix="visualclawarena_codex_last_",
            suffix=".txt",
            delete=False,
        ) as tmp:
            last_message_path = Path(tmp.name)

        cmd = [self.codex_bin]
        if self.approval_policy:
            cmd.extend(["--ask-for-approval", self.approval_policy])
        if self.reasoning_effort:
            cmd.extend([
                "--config",
                f'model_reasoning_effort="{self.reasoning_effort}"',
            ])
        cmd.extend([
            "exec",
            "--cd",
            str(ws),
            "--skip-git-repo-check",
            "--sandbox",
            self.sandbox_mode,
            "--ephemeral",
            "--output-last-message",
            str(last_message_path),
        ])
        if self.model:
            cmd.extend(["--model", self.model])
        for image_path in image_paths:
            cmd.extend(["--image", str(image_path)])
        cmd.append("-")

        workspace_snapshot = _workspace_snapshot_for_prompt(ws)
        prompt_parts = [CODEX_FILE_OPS_INSTRUCTIONS]
        if workspace_snapshot:
            prompt_parts.extend([
                "## Injected Workspace Snapshot\n\n"
                "The following text files were read by the VisualClawArena runner before "
                "Codex was invoked. Treat these as the workspace contents for this "
                "round. Binary/media files are omitted; visual keyframes are attached "
                "separately when present.\n\n"
                f"{workspace_snapshot}",
            ])
        prompt_parts.extend([message, CODEX_EXEC_CONSTRAINTS])
        prompt = "\n\n---\n\n".join(prompt_parts)
        env = os.environ.copy()
        env.update(extra_env or {})

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws),
                env=env,
            )
        except FileNotFoundError:
            _unlink_quietly(last_message_path)
            return AgentResult(
                status="failed",
                answer="",
                error=f"codex CLI not found: {self.codex_bin}",
            )

        try:
            if timeout is not None:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(prompt.encode("utf-8")),
                    timeout=timeout,
                )
            else:
                stdout_b, stderr_b = await proc.communicate(prompt.encode("utf-8"))
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            _unlink_quietly(last_message_path)
            return AgentResult(
                status="timeout",
                answer="",
                error=f"timeout after {timeout}s",
                returncode=-1,
            )

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        raw_answer = _read_text_quietly(last_message_path).strip()
        _unlink_quietly(last_message_path)
        if not raw_answer:
            raw_answer = stdout.strip()

        apply_result = _apply_file_ops_from_answer(raw_answer, ws)
        answer = _strip_file_op_blocks(raw_answer).strip()

        raw: dict[str, Any] = {
            "cmd": _redact_cmd(cmd),
            "stdout": stdout,
            "stderr": stderr,
            "images_attached": [str(p.relative_to(ws)) for p in image_paths],
            "file_ops": apply_result,
        }
        transcript = [{"role": "assistant", "text": answer}] if answer else []
        fatal_stderr = _codex_fatal_stderr(stderr)

        if proc.returncode != 0:
            return AgentResult(
                status="failed",
                answer=answer,
                error=_tail(stderr or stdout),
                returncode=proc.returncode,
                raw=raw,
                transcript=transcript,
            )
        if fatal_stderr:
            return AgentResult(
                status="failed",
                answer=answer,
                error=fatal_stderr,
                returncode=proc.returncode,
                raw=raw,
                transcript=transcript,
            )
        if apply_result["errors"]:
            return AgentResult(
                status="failed",
                answer=answer,
                error="Codex file operation errors: " + "; ".join(apply_result["errors"]),
                returncode=proc.returncode,
                raw=raw,
                transcript=transcript,
            )

        return AgentResult(
            status="success",
            answer=answer,
            returncode=proc.returncode,
            raw=raw,
            transcript=transcript,
        )


def _apply_file_ops_from_answer(answer: str, workspace: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"applied": [], "errors": [], "found_block": False}
    _apply_raw_file_blocks(answer or "", workspace, result)

    matches = list(FILE_OPS_BLOCK_RE.finditer(answer or ""))
    if not matches:
        return result
    result["found_block"] = True

    # Apply the last block. Earlier blocks are often examples repeated by the
    # model; the instruction says exactly one block, but this is more robust.
    payload = matches[-1].group(1).strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        if not result["applied"]:
            result["errors"].append(f"invalid file-ops JSON: {e}")
        return result

    ops = data.get("ops")
    if not isinstance(ops, list):
        result["errors"].append("file-ops JSON must contain an ops list")
        return result

    for idx, op in enumerate(ops):
        if not isinstance(op, dict):
            result["errors"].append(f"op {idx} is not an object")
            continue
        kind = op.get("op")
        rel = op.get("path")
        if not isinstance(rel, str) or not rel.strip():
            result["errors"].append(f"op {idx} has invalid path")
            continue
        try:
            target = _resolve_workspace_path(workspace, rel)
        except ValueError as e:
            result["errors"].append(f"op {idx}: {e}")
            continue

        if kind == "write_file":
            content, content_error = _decode_write_content(op)
            if content_error:
                result["errors"].append(f"op {idx} {content_error}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            result["applied"].append({"op": kind, "path": str(target.relative_to(workspace))})
        elif kind == "delete_file":
            if target.exists():
                if target.is_dir():
                    result["errors"].append(f"op {idx} refuses to delete directory: {rel}")
                    continue
                target.unlink()
            result["applied"].append({"op": kind, "path": str(target.relative_to(workspace))})
        else:
            result["errors"].append(f"op {idx} has unsupported op: {kind!r}")

    return result


def _apply_raw_file_blocks(answer: str, workspace: Path, result: dict[str, Any]) -> None:
    for idx, match in enumerate(WRITE_FILE_BLOCK_RE.finditer(answer)):
        result["found_block"] = True
        rel = match.group(2)
        content = match.group(3)
        try:
            target = _resolve_workspace_path(workspace, rel)
        except ValueError as e:
            result["errors"].append(f"write block {idx}: {e}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        result["applied"].append({"op": "write_file", "path": str(target.relative_to(workspace))})

    for idx, match in enumerate(DELETE_FILE_BLOCK_RE.finditer(answer)):
        result["found_block"] = True
        rel = match.group(2)
        try:
            target = _resolve_workspace_path(workspace, rel)
        except ValueError as e:
            result["errors"].append(f"delete block {idx}: {e}")
            continue
        if target.exists():
            if target.is_dir():
                result["errors"].append(f"delete block {idx} refuses to delete directory: {rel}")
                continue
            target.unlink()
        result["applied"].append({"op": "delete_file", "path": str(target.relative_to(workspace))})


def _strip_file_op_blocks(answer: str) -> str:
    text = FILE_OPS_BLOCK_RE.sub("", answer or "")
    text = WRITE_FILE_BLOCK_RE.sub("", text)
    text = DELETE_FILE_BLOCK_RE.sub("", text)
    return text


def _codex_fatal_stderr(stderr: str) -> str | None:
    if not stderr:
        return None
    if any(pattern in stderr for pattern in CODEX_FATAL_STDERR_PATTERNS):
        return "Codex fatal stderr: " + _tail(stderr)
    return None


def _workspace_snapshot_for_prompt(workspace: Path) -> str:
    max_chars = _env_int(
        "VISUALCLAW_ARENA_CODEX_WORKSPACE_SNAPSHOT_CHARS",
        DEFAULT_SNAPSHOT_MAX_CHARS,
        legacy_name="MM_ARENA_CODEX_WORKSPACE_SNAPSHOT_CHARS",
    )
    if max_chars <= 0:
        return ""
    max_file_chars = _env_int(
        "VISUALCLAW_ARENA_CODEX_WORKSPACE_SNAPSHOT_FILE_CHARS",
        DEFAULT_SNAPSHOT_MAX_FILE_CHARS,
        legacy_name="MM_ARENA_CODEX_WORKSPACE_SNAPSHOT_FILE_CHARS",
    )
    if max_file_chars <= 0:
        return ""

    chunks: list[str] = []
    used = 0
    omitted = 0
    truncated_files = 0

    for path in _iter_snapshot_files(workspace):
        rel = path.relative_to(workspace).as_posix()
        text = _read_snapshot_text(path, max_file_chars)
        if text is None:
            omitted += 1
            continue
        truncated = len(text) >= max_file_chars
        if truncated:
            truncated_files += 1
            text = text[:max_file_chars] + "\n[... file truncated for Codex prompt ...]\n"
        block = f'<workspace_file path="{rel}">\n{text}\n</workspace_file>\n'
        if used + len(block) > max_chars:
            omitted += 1
            continue
        chunks.append(block)
        used += len(block)

    if omitted or truncated_files:
        chunks.append(
            "<workspace_snapshot_note>"
            f"omitted_or_over_budget_files={omitted}; "
            f"truncated_files={truncated_files}; "
            f"max_chars={max_chars}"
            "</workspace_snapshot_note>\n"
        )
    return "\n".join(chunks).strip()


def _iter_snapshot_files(workspace: Path) -> list[Path]:
    files: list[Path] = []
    for path in workspace.rglob("*"):
        rel_parts = path.relative_to(workspace).parts
        if any(part in TEXT_SNAPSHOT_SKIP_DIRS for part in rel_parts):
            continue
        if not path.is_file():
            continue
        if path.name in TEXT_SNAPSHOT_SKIP_NAMES:
            continue
        if path.suffix.lower() not in TEXT_SNAPSHOT_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(workspace).as_posix())


def _read_snapshot_text(path: Path, max_chars: int) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    text = raw.decode("utf-8", errors="replace")
    return text[:max_chars]


def _env_int(name: str, default: int, *, legacy_name: str | None = None) -> int:
    raw = os.environ.get(name)
    if (raw is None or not raw.strip()) and legacy_name:
        raw = os.environ.get(legacy_name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _decode_write_content(op: dict[str, Any]) -> tuple[str | None, str | None]:
    encoded = op.get("content_base64")
    if isinstance(encoded, str):
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as e:
            return None, f"write_file content_base64 is invalid base64: {e}"
        try:
            return raw.decode("utf-8"), None
        except UnicodeDecodeError as e:
            return None, f"write_file content_base64 is not UTF-8: {e}"

    # Backward compatibility for old valid JSON payloads. The prompt no longer
    # asks for this because raw JSON strings are too easy to break with source
    # code, Markdown fences, quotes, or newlines.
    content = op.get("content")
    if isinstance(content, str):
        return content, None
    if "content" in op:
        return None, "write_file content must be a string"
    return None, "write_file requires content_base64"


def _resolve_workspace_path(workspace: Path, rel: str) -> Path:
    raw = Path(rel)
    if raw.is_absolute():
        raise ValueError(f"absolute paths are not allowed: {rel}")
    target = (workspace / raw).resolve()
    try:
        target.relative_to(workspace)
    except ValueError as e:
        raise ValueError(f"path escapes workspace: {rel}") from e
    return target


def _collect_keyframe_images(workspace: Path) -> list[Path]:
    frame_dir = workspace / "_clip_frames"
    if not frame_dir.exists():
        return []
    suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted(p for p in frame_dir.iterdir() if p.suffix.lower() in suffixes)


def _read_text_quietly(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as e:
        return f"[visualclawarena] failed to read Codex last-message file {path}: {e}"


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _tail(text: str, *, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _redact_cmd(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for i, part in enumerate(cmd):
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(part)
        if part in {"--output-last-message"} and i + 1 < len(cmd):
            skip_next = True
    return redacted
