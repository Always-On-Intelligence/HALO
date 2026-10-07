from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_MILLISECOND_TOKEN_RE = re.compile(r"(?:^|_)(?:cur_)?kf_(\d{7,})(?:\D|$)")


def frame_timestamp_seconds(
    value: Any,
    path: str | None = None,
    *,
    token: str | None = None,
) -> float | None:
    """Normalize explicit seconds or millisecond-encoded frame names to seconds."""

    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None

    path_text = str(path or "")
    token_text = str(token or "")
    if not token_text and path_text:
        match = _MILLISECOND_TOKEN_RE.search(Path(path_text).stem)
        token_text = match.group(1) if match else ""

    token_value: float | None = None
    if token_text.isdigit() and len(token_text) >= 7:
        token_value = float(token_text)

    # Explicit metadata is already in seconds when it matches the filename's
    # millisecond token after scaling (for example 1010.002 vs 001010002).
    if token_value is not None and abs(timestamp * 1000.0 - token_value) <= 1.0:
        return round(timestamp, 3)

    value_matches_ms_token = token_value is not None and abs(timestamp - token_value) <= 1e-6
    is_stream_ms_keyframe = "stream/keyframes" in path_text.replace("\\", "/")
    if timestamp >= 1000.0 and (value_matches_ms_token or (is_stream_ms_keyframe and timestamp.is_integer())):
        timestamp /= 1000.0
    return round(timestamp, 3)


def frame_timestamp_from_path(path: str) -> float | None:
    stem = Path(path).stem
    for part in reversed(stem.split("_")):
        if not part.isdigit():
            continue
        return frame_timestamp_seconds(int(part), path, token=part)
    return None
