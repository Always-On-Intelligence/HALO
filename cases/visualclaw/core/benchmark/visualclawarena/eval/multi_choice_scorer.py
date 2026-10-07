"""
multi_choice_scorer.py — MC round scoring.

Extracts the agent's answer from its response and compares to the expected
single-letter answer(s) declared in ``round.eval.answer``.

Parsing precedence (most-canonical first):
    1. ``\bbox{X}``           — ClawArena canonical extraction
    2. ``Answer: X``          — fallback phrasing
    3. ``The answer is X``    — fallback phrasing
    4. Last solitary capital letter in the response — last-resort
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class MCScore:
    passed: bool
    score: float
    extracted: str | None
    expected: list[str]
    parse_method: str   # which regex matched, for debugging
    raw_response_tail: str  # last 200 chars of agent response, for audit


BBOX_RE = re.compile(r"\\bbox\{\s*([A-Z])\s*\}")
ANSWER_LINE_RE = re.compile(r"(?:^|\n)\s*Answer\s*[:=]\s*([A-Z])\b", re.IGNORECASE)
THE_ANSWER_RE = re.compile(r"\bthe\s+answer\s+is\s+\(?\s*([A-Z])\b", re.IGNORECASE)
SOLITARY_LETTER_RE = re.compile(r"(?:^|[\s\(\[])([A-Z])(?:[\s\.\)\]\.,]|$)")


def extract_answer(response: str) -> tuple[str | None, str]:
    """Return (letter, parse_method) — letter may be None if unparseable."""
    if not response:
        return None, "empty_response"

    m = BBOX_RE.search(response)
    if m:
        return m.group(1).upper(), "bbox"

    m = ANSWER_LINE_RE.search(response)
    if m:
        return m.group(1).upper(), "answer_line"

    m = THE_ANSWER_RE.search(response)
    if m:
        return m.group(1).upper(), "the_answer_is"

    # Last-resort: scan from the END for a solitary capital letter
    tail = response[-300:]  # only look at end of response
    matches = SOLITARY_LETTER_RE.findall(tail)
    if matches:
        return matches[-1].upper(), "solitary_letter_tail"

    return None, "unparseable"


def score_mc_round(rnd: dict[str, Any], response: str) -> MCScore:
    """Score one multi_choice round."""
    eval_block = rnd.get("eval", {})
    expected = eval_block.get("answer", [])
    if isinstance(expected, str):
        expected = [expected]
    expected = [e.upper() for e in expected if isinstance(e, str)]

    extracted, method = extract_answer(response or "")
    passed = extracted is not None and extracted in expected

    return MCScore(
        passed=passed,
        score=1.0 if passed else 0.0,
        extracted=extracted,
        expected=expected,
        parse_method=method,
        raw_response_tail=(response or "")[-200:],
    )
