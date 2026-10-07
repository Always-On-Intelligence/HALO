"""
access_logger.py — per-round JSONL access log for VisualClawArena runs.

Records every source touch (file read, image describe, clip frame access,
memory retrieval, skill retrieval) that the agent makes during a round.
The log is benchmark-side; agent code is not modified. The result of one
round is one JSONL file: ``runs/<run_id>/access_logs/Q01.jsonl``.

Per V0_SPEC §5, each line carries:
    qid       — round id
    t         — seconds elapsed since round start
    modality  — text | image | video | audio | memory | skill | exif | ocr
    source    — the resource that was accessed (file path, frame index, etc.)
    via       — call-site label (e.g. "read_file", "cascade_gate")
    + optional extras: tokens_returned, cache_hit, keyframes_forwarded, ...
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AccessLogger:
    run_id: str
    access_logs_dir: Path
    _current_qid: str | None = None
    _round_t0: float | None = None
    _records: list[dict[str, Any]] = None

    def __post_init__(self) -> None:
        self.access_logs_dir.mkdir(parents=True, exist_ok=True)
        self._records = []

    def begin_round(self, qid: str) -> None:
        """Open a new round. Flushes any open round first."""
        if self._current_qid is not None:
            self.end_round()
        self._current_qid = qid
        self._round_t0 = time.monotonic()
        self._records = []

    def end_round(self) -> Path | None:
        """Flush the current round's log to ``access_logs/<qid>.jsonl``."""
        if self._current_qid is None:
            return None
        out = self.access_logs_dir / f"{self._current_qid}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for rec in self._records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        prev_qid = self._current_qid
        self._current_qid = None
        self._round_t0 = None
        self._records = []
        return out

    def _t(self) -> float:
        if self._round_t0 is None:
            return 0.0
        return round(time.monotonic() - self._round_t0, 3)

    def log(self, modality: str, source: str, via: str, **extras: Any) -> None:
        """Record one access event. Silently no-ops if no round is open."""
        if self._current_qid is None:
            return
        rec = {
            "qid": self._current_qid,
            "t": self._t(),
            "modality": modality,
            "source": source,
            "via": via,
        }
        rec.update(extras)
        self._records.append(rec)

    # Convenience wrappers ---------------------------------------------------

    def log_text_read(self, path: str, tokens_returned: int | None = None) -> None:
        self.log("text", path, "read_file",
                 tokens_returned=tokens_returned)

    def log_image_read(self, path: str, *, cache_hit: bool = False,
                       description_tokens: int | None = None) -> None:
        self.log("image", path, "image_describer",
                 cache_hit=cache_hit, description_tokens=description_tokens)

    def log_clip_access(
        self,
        path: str,
        *,
        keyframes_forwarded: list[str] | None = None,
        frames_dropped: int | None = None,
        via: str = "cascade_gate",
    ) -> None:
        self.log("video", path, via,
                 keyframes_forwarded=keyframes_forwarded,
                 frames_dropped=frames_dropped)

    def log_memory(
        self,
        retrieved_uids: list[str],
        cosine_scores: list[float] | None = None,
    ) -> None:
        self.log("memory", "memory_store", "memory_retrieval",
                 retrieved_uids=retrieved_uids, cosine_scores=cosine_scores)

    def log_skill(self, retrieved_skills: list[str]) -> None:
        self.log("skill", "skill_bank", "skill_retrieval",
                 retrieved_skills=retrieved_skills)
