from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROJECT_STATE = "project_state"
    WORKING_SUMMARY = "working_summary"
    PROCEDURAL_OBSERVATION = "procedural_observation"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


@dataclass
class MemoryUnit:
    memory_id: str
    scope_id: str
    memory_type: MemoryType
    content: str
    summary: str = ""
    source_session_id: str = ""
    source_turn_start: int = 0
    source_turn_end: int = 0
    entities: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 0.7
    access_count: int = 0
    reinforcement_score: float = 0.0
    status: MemoryStatus = MemoryStatus.ACTIVE
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str = ""
    embedding: list[float] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_accessed_at: str = ""
    expires_at: str = ""
    tags: list[str] = field(default_factory=list)
    # v4 Fix 0 — failure-aware retrieval. "passed" | "failed" | "" (unknown /
    # not a benchmark Q&A unit). When set to "failed", render_for_prompt
    # prefixes the memory with an explicit warning so downstream rounds don't
    # replicate the erroneous reasoning (cascade pattern from v3 full31 sweep —
    # 41% of regressions; see docs/visualclawarena/V4_MEMORY_FIXES_DESIGN.md §2).
    outcome: str = ""


@dataclass
class MemoryQuery:
    scope_id: str
    query_text: str
    top_k: int = 6
    max_tokens: int = 800
    include_types: list[MemoryType] = field(default_factory=list)
    context_tags: list[str] = field(default_factory=list)


@dataclass
class MemorySearchHit:
    unit: MemoryUnit
    score: float
    matched_terms: list[str] = field(default_factory=list)
    reason: str = ""
