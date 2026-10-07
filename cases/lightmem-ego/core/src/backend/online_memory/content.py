"""Canonical text extraction for episodic memory records.

Memory producers have historically used several names for the same user-visible
caption.  Keeping the precedence in one small module prevents derived indexes
from accidentally reading a stale alias after an edit.
"""

from __future__ import annotations

from typing import Any

EPISODIC_CONTENT_FIELDS = (
    "text",
    "fine_caption",
    "caption",
    "scene_summary",
    "visual_summary",
)


def effective_episodic_content(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    for field in EPISODIC_CONTENT_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def effective_episodic_content_field(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    for field in EPISODIC_CONTENT_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return field
    return None
