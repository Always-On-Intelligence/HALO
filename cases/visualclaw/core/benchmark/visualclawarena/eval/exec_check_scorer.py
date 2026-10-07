"""
exec_check_scorer.py — exec_check round scoring.

Runs ``round.eval.command`` as a subprocess against the agent's writable
workspace. Expands two placeholders in the command:

    ${eval_dir}        → scenario-spec parent (typically benchmark/data-spec/)
    ${agent_id}        → scenario name (per V0_SPEC ClawArena alignment)
    ${workspace}       → the writable workspace where the agent's outputs land

Pass condition:
    - exit code matches ``round.eval.expect_exit`` (default 0), AND
    - if ``round.eval.expect_stdout`` is set, stdout contains that substring, AND
    - if ``round.eval.expect_stdout_regex`` is set, stdout matches the pattern.

Timeout defaults to 30s (raise via ``round.eval.timeout``).
"""

from __future__ import annotations

import re
import subprocess
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ECScore:
    passed: bool
    score: float
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    command_executed: str
    expect_exit: int
    parse_notes: list[str] = field(default_factory=list)


def _expand_placeholders(
    cmd: str,
    eval_dir: Path,
    agent_id: str,
    workspace: Path,
) -> str:
    return (
        cmd
        .replace("${eval_dir}", str(eval_dir.resolve()))
        .replace("${agent_id}", agent_id)
        .replace("${workspace}", str(workspace.resolve()))
    )


def _argv_for_subprocess(cmd: str) -> list[str]:
    """Use the runner's interpreter for bare python eval commands.

    Scenario specs commonly use ``python ${eval_dir}/...``. Running that through
    ambient PATH can pick a different environment than the runner, which makes
    eval dependencies such as ``jsonschema`` disappear. Explicit interpreter
    paths are left untouched.
    """
    argv = shlex.split(cmd)
    if not argv:
        return argv
    exe = Path(argv[0])
    if len(exe.parts) == 1 and exe.name in {"python", "python3"}:
        argv[0] = sys.executable
    return argv


def score_ec_round(
    rnd: dict[str, Any],
    eval_dir: Path,
    agent_id: str,
    workspace: Path,
) -> ECScore:
    """Score one exec_check round by running its eval.command."""
    eval_block = rnd.get("eval", {})
    raw_cmd = eval_block.get("command", "")
    expect_exit = eval_block.get("expect_exit", 0)
    expect_stdout = eval_block.get("expect_stdout")
    expect_stdout_regex = eval_block.get("expect_stdout_regex")
    timeout = float(eval_block.get("timeout", 30))

    notes: list[str] = []

    if not raw_cmd:
        return ECScore(False, 0.0, None, "", "", "", expect_exit,
                       ["eval.command is empty"])

    cmd = _expand_placeholders(raw_cmd, eval_dir, agent_id, workspace)
    argv = _argv_for_subprocess(cmd)
    cmd_executed = shlex.join(argv) if argv else cmd

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace),
        )
    except subprocess.TimeoutExpired as e:
        return ECScore(
            False, 0.0, None,
            (e.stdout.decode() if e.stdout else "")[-500:],
            (e.stderr.decode() if e.stderr else "")[-500:],
            cmd_executed, expect_exit,
            [f"timeout after {timeout}s"],
        )
    except FileNotFoundError as e:
        return ECScore(False, 0.0, None, "", str(e), cmd_executed, expect_exit,
                       [f"command not found: {e}"])

    passed_exit = proc.returncode == expect_exit
    passed_stdout = True
    if expect_stdout is not None:
        passed_stdout = expect_stdout in proc.stdout
        if not passed_stdout:
            notes.append(f"expect_stdout substring missing")
    if expect_stdout_regex is not None:
        if not re.search(expect_stdout_regex, proc.stdout):
            passed_stdout = False
            notes.append(f"expect_stdout_regex did not match")

    passed = passed_exit and passed_stdout

    return ECScore(
        passed=passed,
        score=1.0 if passed else 0.0,
        exit_code=proc.returncode,
        stdout_tail=proc.stdout[-500:],
        stderr_tail=proc.stderr[-500:],
        command_executed=cmd_executed,
        expect_exit=expect_exit,
        parse_notes=notes,
    )
