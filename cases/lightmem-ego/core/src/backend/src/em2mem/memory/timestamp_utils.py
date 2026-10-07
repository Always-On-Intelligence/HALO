from __future__ import annotations

import re
from typing import Any


_DAY_LABEL_RE = re.compile(r"\bDAY\s*0*(\d+)\b", flags=re.IGNORECASE)
_LEADING_DAY_RE = re.compile(r"^\s*0*(\d+)(?:\D|$)")
_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?:[.:](\d{1,2}))?$")


def normalize_memory_day(value: Any) -> str:
    """Return the numeric day from labels such as ``DAY1 周一`` or ``1 周一``."""

    text = str(value or "").strip()
    match = _DAY_LABEL_RE.search(text) or _LEADING_DAY_RE.search(text)
    if match is None:
        raise ValueError(f"Invalid memory day label: {value!r}")
    return str(int(match.group(1)))


def normalize_memory_clock(value: Any) -> str:
    """Normalize a memory clock to the project's HHMMSSFF eight-digit form."""

    text = str(value or "").strip()
    if text.isdigit():
        if len(text) > 8:
            raise ValueError(f"Invalid memory clock: {value!r}")
        return text.zfill(8)

    match = _CLOCK_RE.fullmatch(text)
    if match is None:
        raise ValueError(f"Invalid memory clock: {value!r}")
    hour, minute, second = (int(match.group(index)) for index in (1, 2, 3))
    fraction = int((match.group(4) or "0").ljust(2, "0"))
    if hour > 23 or minute > 59 or second > 59 or fraction > 99:
        raise ValueError(f"Invalid memory clock: {value!r}")
    return f"{hour:02d}{minute:02d}{second:02d}{fraction:02d}"


def memory_timestamp_range(date: Any, start_time: Any, end_time: Any) -> tuple[int, int]:
    day = normalize_memory_day(date)
    start = normalize_memory_clock(start_time)
    end = normalize_memory_clock(end_time)
    return int(day + start), int(day + end)
