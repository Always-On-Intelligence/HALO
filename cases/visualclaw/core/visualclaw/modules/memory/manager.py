from __future__ import annotations

import logging
import re
import threading
import uuid
from pathlib import Path

from .consolidator import MemoryConsolidator
from .embeddings import BaseEmbedder, HashingEmbedder, create_embedder
from .metrics import summarize_memory_store
from .models import MemoryQuery, MemorySearchHit, MemoryStatus, MemoryType, MemoryUnit, utc_now_iso
from .policy import MemoryPolicy
from .policy_optimizer import MemoryPolicyOptimizer
from .policy_store import MemoryPolicyState, MemoryPolicyStore
from .retriever import MemoryRetriever
from .store import MemoryStore
from .telemetry import MemoryTelemetryStore

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    return len(text.split())


class _MultiTurnContext:
    """Tracks entities across turns for co-reference (minimal implementation)."""
    def __init__(self):
        self.entities: list[str] = []
        self.topics: list[str] = []

    def update(self, entities, topics):
        self.entities.extend(e for e in entities if e not in self.entities)
        self.topics.extend(t for t in topics if t not in self.topics)


class MemoryManager:
    """Facade for retrieval, rendering, and write-side session extraction."""

    def __init__(
        self,
        store: MemoryStore,
        policy: MemoryPolicy | None = None,
        scope_id: str = "default",
        auto_consolidate: bool = True,
        retrieval_mode: str = "keyword",
        use_embeddings: bool = False,
        policy_store: MemoryPolicyStore | None = None,
        telemetry_store: MemoryTelemetryStore | None = None,
        embedding_mode: str = "hashing",
        embedding_model: str = "all-MiniLM-L6-v2",
        embedder: BaseEmbedder | None = None,
        flush_every: int = 5,
        mmr_lambda: float = 1.0,
    ):
        self.store = store
        self.policy = policy or MemoryPolicy()
        self.scope_id = scope_id
        self.auto_consolidate = auto_consolidate
        self.retrieval_mode = retrieval_mode
        self.use_embeddings = use_embeddings or retrieval_mode in {"embedding", "hybrid"}
        self.policy_store = policy_store
        self.telemetry_store = telemetry_store
        self.embedding_mode = embedding_mode
        self.embedding_model = embedding_model
        if embedder is not None:
            self.embedder = embedder
        elif self.use_embeddings:
            self.embedder = create_embedder(
                mode=embedding_mode,
                model_name=embedding_model,
                fallback=True,
            )
        else:
            self.embedder = None
        self.policy_optimizer = MemoryPolicyOptimizer(
            store=self.store,
            telemetry_store=self.telemetry_store,
        )
        self.mmr_lambda = max(0.0, min(1.0, float(mmr_lambda)))
        self.retriever = MemoryRetriever(
            store=self.store,
            policy=self.policy,
            retrieval_mode=retrieval_mode,
            embedder=self.embedder,
            mmr_lambda=self.mmr_lambda,
        )
        self.consolidator = MemoryConsolidator(store=self.store)
        self._retrieval_cache: dict[str, list[MemoryUnit]] = {}
        self._cache_max_size = 16
        self._event_callbacks: list = []
        self.flush_every = max(1, flush_every)
        self._session_buffers: dict[str, list[dict]] = {}
        self._session_contexts: dict[str, _MultiTurnContext] = {}
        self._session_turn_counts: dict[str, int] = {}
        self._session_all_turns: dict[str, list[dict]] = {}
        # Sessions that have already emitted at least one [Memory] INFO line.
        # Used to keep the ingestion log visible (one entry per session) while
        # suppressing subsequent "ingested 0" flushes that otherwise flood the
        # gateway log during long multi-turn conversations.
        #
        # Long-running gateways accumulate sessions that never hit the
        # session_done cleanup path (OpenClaw auto-generates a fresh session
        # id per POST), so the set is capped — when it overflows we drop the
        # whole thing, which at worst produces one duplicate heartbeat per
        # in-flight session. Cheaper than LRU bookkeeping for a log gate.
        self._logged_sessions: set[str] = set()
        self._logged_sessions_lock = threading.Lock()
        self._logged_sessions_cap = 10000
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    @classmethod
    def from_gateway_config(cls, cfg: "VisualClawConfig", data_dir: str | None = None, scope_id: str | None = None) -> "MemoryManager":
        """Create from a VisualClawConfig object."""
        from visualclaw.config import VisualClawConfig as _Cfg
        mem_cfg = cfg.memory
        # Resolve paths via the config resolve_path method
        resolve = getattr(cfg, "resolve_path", lambda p: Path(str(p)).expanduser())
        _data_dir = Path(str(resolve(data_dir or mem_cfg.data_dir)))
        _data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(_data_dir / "memories.db")
        policy_path = str(_data_dir / "policy.json")
        telemetry_path = str(_data_dir / "telemetry.jsonl")
        _scope_id = scope_id or getattr(mem_cfg, "scope", "default")
        store = MemoryStore(db_path)
        policy_store = MemoryPolicyStore(policy_path)
        telemetry_store = MemoryTelemetryStore(telemetry_path)
        policy_state = policy_store.load()
        # Bootstrap policy from config values if no saved policy
        if not Path(policy_path).exists():
            policy_state.max_injected_units = getattr(mem_cfg, "max_injected_units", 6)
            policy_state.max_injected_tokens = getattr(mem_cfg, "max_injected_tokens", 800)
            policy_state.retrieval_mode = getattr(getattr(mem_cfg, "retrieval", None), "mode", "keyword")
            policy_store.save(policy_state, reason="bootstrap")
        policy = MemoryPolicy.from_state(policy_state)
        retrieval_mode = getattr(getattr(mem_cfg, "retrieval", None), "mode", "keyword") or "keyword"
        use_embeddings = getattr(mem_cfg, "use_embeddings", False)
        embedding_mode = getattr(mem_cfg, "embedding_mode", "hashing")
        embedding_model = getattr(mem_cfg, "embedding_model", "all-MiniLM-L6-v2")
        flush_every = getattr(mem_cfg, "flush_every", 5)
        auto_consolidate = getattr(mem_cfg, "auto_consolidate", True)
        return cls(
            store=store,
            policy=policy,
            scope_id=_scope_id,
            auto_consolidate=auto_consolidate,
            retrieval_mode=retrieval_mode,
            use_embeddings=use_embeddings,
            policy_store=policy_store,
            telemetry_store=telemetry_store,
            embedding_mode=embedding_mode,
            embedding_model=embedding_model,
            flush_every=flush_every,
        )

    def register_event_callback(self, callback) -> None:
        """Register a callback for memory events.

        Callbacks receive a dict with at least 'event' (str) and 'scope_id' (str).
        Additional keys depend on the event type.
        """
        self._event_callbacks.append(callback)

    def _notify(self, event: str, **kwargs) -> None:
        """Fire all registered event callbacks. Best-effort; errors are logged."""
        if not self._event_callbacks:
            return
        payload = {"event": event, **kwargs}
        for cb in self._event_callbacks:
            try:
                cb(payload)
            except Exception as exc:
                logger.debug("Event callback error for %s: %s", event, exc)

    def ingest_session_turns(
        self,
        session_id: str,
        turns: list[dict],
        scope_id: str | None = None,
    ) -> int:
        """Create phase-1 memory units from a completed session (one-shot)."""
        scope = scope_id or self.scope_id
        context = _MultiTurnContext()
        units = self._extract_turns_to_units(scope, session_id, turns, context, turn_offset=0)
        if turns:
            summary_unit = self._build_working_summary_unit(
                scope, session_id, turns, turn_start=1, turn_end=len(turns),
            )
            if summary_unit is not None:
                units.append(summary_unit)
        return self._persist_units(scope, session_id, units)

    def buffer_turn(
        self,
        session_id: str,
        turn: dict,
        scope_id: str | None = None,
    ) -> int | None:
        """Append a single turn to the session's buffer.

        Auto-flushes (incremental, no working_summary) once the buffer reaches
        `flush_every` turns. Returns the number of memories added if a flush
        happened, else None.
        """
        scope = scope_id or self.scope_id
        buf = self._session_buffers.setdefault(session_id, [])
        buf.append(turn)
        self._session_all_turns.setdefault(session_id, []).append(turn)
        if len(buf) >= self.flush_every:
            return self.flush_session(session_id, scope_id=scope, final=False)
        return None

    def flush_session(
        self,
        session_id: str,
        scope_id: str | None = None,
        final: bool = True,
    ) -> int:
        """Flush buffered turns for a session.

        When `final=True`, also emits a working_summary covering all turns seen
        so far and clears the session's buffered state. When `final=False`,
        extraction runs against the current buffer only and working_summary is
        skipped (incremental mid-session flush).
        """
        scope = scope_id or self.scope_id
        buf = self._session_buffers.get(session_id, [])
        context = self._session_contexts.setdefault(session_id, _MultiTurnContext())
        prior = self._session_turn_counts.get(session_id, 0)
        units = self._extract_turns_to_units(
            scope, session_id, buf, context, turn_offset=prior,
        )
        total_turns = self._session_all_turns.get(session_id, [])
        if final and total_turns:
            summary_unit = self._build_working_summary_unit(
                scope, session_id, total_turns,
                turn_start=1, turn_end=len(total_turns),
            )
            if summary_unit is not None:
                units.append(summary_unit)
        added = self._persist_units(scope, session_id, units)
        self._session_turn_counts[session_id] = prior + len(buf)
        self._session_buffers[session_id] = []
        if final:
            self._session_buffers.pop(session_id, None)
            self._session_contexts.pop(session_id, None)
            self._session_turn_counts.pop(session_id, None)
            self._session_all_turns.pop(session_id, None)
            with self._logged_sessions_lock:
                self._logged_sessions.discard(session_id)
        return added

    def _extract_turns_to_units(
        self,
        scope_id: str,
        session_id: str,
        turns: list[dict],
        context: "_MultiTurnContext",
        turn_offset: int = 0,
    ) -> list[MemoryUnit]:
        """Extract MemoryUnit objects from conversation turns using pattern extraction."""
        from visualclaw.modules.memory.extractor import extract_from_turns
        extracted = extract_from_turns(turns=turns)
        units: list[MemoryUnit] = []
        for idx, em in enumerate(extracted):
            try:
                mtype = MemoryType(em.memory_type)
            except ValueError:
                mtype = MemoryType.EPISODIC
            units.append(MemoryUnit(
                memory_id=str(uuid.uuid4()),
                scope_id=scope_id,
                memory_type=mtype,
                content=em.content,
                summary=em.content[:200],
                source_session_id=session_id,
                source_turn_start=turn_offset + 1,
                source_turn_end=turn_offset + len(turns),
                importance=em.importance,
                confidence=em.confidence,
            ))
        if units:
            logger.info(
                "[Memory] extract turns=%d → %d units [%s]",
                len(turns), len(units),
                ", ".join(u.memory_type.value for u in units),
            )
        return units

    def _build_working_summary_unit(
        self,
        scope_id: str,
        session_id: str,
        turns: list[dict],
        turn_start: int,
        turn_end: int,
    ) -> MemoryUnit | None:
        text = " ".join(
            str(t.get("content", ""))[:500]
            for t in turns
            if isinstance(t, dict) and t.get("role") in ("user", "assistant") and t.get("content")
        )[:2000]
        if not text.strip():
            return None
        return MemoryUnit(
            memory_id=str(uuid.uuid4()),
            scope_id=scope_id,
            memory_type=MemoryType.WORKING_SUMMARY,
            content=text,
            summary=text[:200],
            source_session_id=session_id,
            source_turn_start=turn_start,
            source_turn_end=turn_end,
            importance=0.9,
            confidence=0.8,
        )

    def _persist_units(
        self,
        scope: str,
        session_id: str,
        units: list[MemoryUnit],
    ) -> int:
        # Pre-ingestion validation: skip units with empty or overly short content.
        pre_validate_count = len(units)
        units = [u for u in units if len(u.content.strip()) >= 3]

        # Pre-ingestion dedup: skip units whose content already exists in the store.
        pre_dedup_count = len(units)
        units = _dedup_against_store(units, self.store, scope)
        dedup_skipped = pre_dedup_count - len(units)
        if dedup_skipped or (pre_validate_count - pre_dedup_count):
            logger.info(
                "[Memory] pre-filter: validated=%d dedup_skipped=%d remaining=%d",
                pre_validate_count - pre_dedup_count, dedup_skipped, len(units),
            )

        if self.embedder is not None:
            for unit in units:
                unit.embedding = self.embedder.encode(
                    " ".join([unit.summary, unit.content, " ".join(unit.topics), " ".join(unit.entities)])
                )

        added = self.store.add_memories(units)
        self.clear_cache()
        if self.auto_consolidate:
            consolidation_result = self.consolidator.consolidate(scope)
            if self.telemetry_store is not None and consolidation_result:
                self.telemetry_store.record(
                    "memory_consolidation",
                    {
                        "scope_id": scope,
                        "session_id": session_id,
                        "superseded": consolidation_result.get("superseded", 0),
                        "decayed": consolidation_result.get("decayed", 0),
                        "reinforced": consolidation_result.get("reinforced", 0),
                    },
                )
        stats = summarize_memory_store(self.store, scope)
        self._refresh_policy(scope)
        if self.telemetry_store is not None:
            self.telemetry_store.record(
                "memory_ingest",
                {
                    "scope_id": scope,
                    "session_id": session_id,
                    "added": added,
                    "active": stats.get("active", 0),
                    "dominant_type": stats.get("dominant_type", ""),
                    "active_by_type": stats.get("active_by_type", {}),
                },
            )
        # Keep [Memory] visible but not spammy. Log at INFO when:
        #   * something was actually ingested (added > 0), or
        #   * this is the first flush we see for the session (heartbeat
        #     proving the memory pipeline is wired, even if nothing met
        #     the importance threshold yet).
        # Later empty flushes in the same session go to DEBUG.
        with self._logged_sessions_lock:
            first_time = session_id not in self._logged_sessions
            if first_time:
                if len(self._logged_sessions) >= self._logged_sessions_cap:
                    self._logged_sessions.clear()
                self._logged_sessions.add(session_id)
        if added > 0:
            logger.info(
                "[Memory] ingested %d memory units from session=%s scope=%s active=%d dominant_type=%s",
                added,
                session_id,
                scope,
                stats.get("active", 0),
                stats.get("dominant_type", ""),
            )
        elif first_time:
            # Reword the zero-ingest case so it can't be misread as a failure.
            logger.info(
                "[Memory] pipeline active for session=%s scope=%s (no new units this flush; store active=%d)",
                session_id,
                scope,
                stats.get("active", 0),
            )
        else:
            logger.debug(
                "[Memory] ingested %d memory units from session=%s scope=%s active=%d dominant_type=%s",
                added,
                session_id,
                scope,
                stats.get("active", 0),
                stats.get("dominant_type", ""),
            )
        try:
            self.store.save_stats_snapshot(scope)
        except Exception:
            pass
        self._notify("ingest", scope_id=scope, session_id=session_id, added=added)
        return added

    def _refresh_policy(self, scope: str) -> None:
        """Propose and apply policy updates based on current store state."""
        if self.policy_store is None:
            return
        try:
            current_state = self.policy_store.load()
            proposed = self.policy_optimizer.propose(scope, current_state)
            if proposed.__dict__ != current_state.__dict__:
                self.policy_store.save(proposed, reason="auto_optimize")
                self.policy = MemoryPolicy.from_state(proposed)
                self.retriever.policy = self.policy
        except Exception as exc:
            logger.debug("Policy refresh failed: %s", exc)

    def retrieve_for_prompt(
        self,
        query_text: str,
        scope_id: str | None = None,
        max_tokens: int | None = None,
        top_k: int | None = None,
        context_tags: list[str] | None = None,
    ) -> list[MemorySearchHit]:
        """Retrieve relevant memories for prompt injection.

        Returns list[MemorySearchHit] for downstream formatting.
        """
        scope = scope_id or self.scope_id
        policy = self.policy
        _top_k = top_k or policy.max_injected_units
        _max_tokens = max_tokens or policy.max_injected_tokens
        query = MemoryQuery(
            scope_id=scope,
            query_text=query_text,
            top_k=_top_k,
            max_tokens=_max_tokens,
            context_tags=context_tags or [],
        )
        hits = self.retriever.retrieve(query)
        now = utc_now_iso()
        self.store.mark_accessed([h.unit.memory_id for h in hits], now)
        if self.telemetry_store:
            self.telemetry_store.record("memory_retrieval", {
                "scope_id": scope,
                "query_length": len(query_text),
                "retrieved_count": len(hits),
                "types_retrieved": list({h.unit.memory_type.value for h in hits}),
            })
        return hits

    @staticmethod
    def render_for_prompt(
        hits,
        max_chars: int = 0,
        failure_handling: str = "neutral",
    ) -> str:
        """Format MemorySearchHit list or MemoryUnit list as markdown for prompt injection.

        Parameters
        ----------
        hits : iterable
            MemorySearchHit or MemoryUnit objects, in retriever-provided order.
        max_chars : int
            v4 Fix 1 (length cap). If > 0, truncate the rendered output to
            this many characters total. Hits are sorted by retrieval score
            descending first, so the highest-relevance hits survive
            truncation. 0 = no cap (backward-compat default).
        failure_handling : str
            v4 Fix 0 (failure-aware retrieval). One of:
              - "neutral"  (default)  : original v3 behavior, no outcome
                                        awareness. **This is the safe
                                        default** — the empirical s11
                                        retry (2026-05-23) showed that
                                        "warn" does NOT lift accuracy:
                                        warnings appear correctly but the
                                        agent's underlying failure mode on
                                        cascade scenarios is categorical
                                        confusion, not memory replication.
                                        See docs/visualclawarena/J6_FINDINGS_2026_05_22.md §9.
              - "warn"               : keep failed-round memories, prefix
                                        with explicit warning so the agent
                                        knows not to replicate the
                                        reasoning. Currently NOT recommended
                                        based on empirical tests.
              - "exclude"            : drop failed-round memories entirely.
                                        Untested at scale.

        Failure-aware mode uses unit.outcome ("passed" | "failed" | "") which
        the VisualClawArena runner populates per round; other ingestion paths leave
        it empty, in which case behavior is identical to "neutral".

        See docs/visualclawarena/V4_MEMORY_FIXES_DESIGN.md §2 + §8 (empirical results).
        """
        if not hits:
            return ""
        _TYPE_LABEL = {
            "preference": "Preference",
            "project_state": "Project Context",
            "procedural_observation": "Procedure",
            "semantic": "Context",
            "episodic": "Past Interaction",
            "working_summary": "Session Summary",
        }
        # v4 Fix 1: sort by retrieval score descending so truncation preserves
        # the highest-relevance hits. MemorySearchHit has .score; raw
        # MemoryUnits fall back to score=0 (preserves input order).
        try:
            sorted_hits = sorted(
                hits, key=lambda h: getattr(h, "score", 0.0), reverse=True,
            )
        except TypeError:
            sorted_hits = list(hits)

        header = "## Relevant Memory\n"
        lines = [header]
        acc = len(header)
        for h in sorted_hits:
            # Support both MemorySearchHit and MemoryUnit
            unit = getattr(h, "unit", h)
            outcome = getattr(unit, "outcome", "")
            # v4 Fix 0: skip or warn on failed-round memories
            if failure_handling == "exclude" and outcome == "failed":
                continue
            label = _TYPE_LABEL.get(unit.memory_type.value, "Memory")
            if failure_handling == "warn" and outcome == "failed":
                line = (
                    f"- [{label}] ⚠️ **PRIOR ATTEMPT FAILED — DO NOT REPEAT "
                    f"THIS REASONING**: {unit.content}"
                )
            else:
                line = f"- [{label}] {unit.content}"
            # v4 Fix 1: enforce total length cap. Stop accumulating once we'd
            # exceed it (the +1 accounts for the newline join separator).
            if max_chars and acc + len(line) + 1 > max_chars:
                break
            lines.append(line)
            acc += len(line) + 1
        return "\n".join(lines)

    def get_scope_stats(self, scope_id: str | None = None) -> dict:
        return summarize_memory_store(self.store, scope_id or self.scope_id)

    def get_policy_state(self) -> dict:
        if self.policy_store is None:
            return {}
        return self.policy_store.load().__dict__

    def get_access_patterns(self, scope_id: str | None = None, limit: int = 5) -> dict:
        """Return access pattern insights for the given scope."""
        scope = scope_id or self.scope_id
        units = self.store.list_active(scope, limit=500)
        if not units:
            return {"total": 0, "most_accessed": [], "never_accessed": 0}
        sorted_by_access = sorted(units, key=lambda u: u.access_count, reverse=True)
        most_accessed = [
            {"id": u.memory_id, "type": u.memory_type.value, "access_count": u.access_count, "content": u.content[:100]}
            for u in sorted_by_access[:limit]
        ]
        never_accessed = sum(1 for u in units if u.access_count == 0)
        avg_access = sum(u.access_count for u in units) / float(len(units))
        return {
            "total": len(units),
            "most_accessed": most_accessed,
            "never_accessed": never_accessed,
            "avg_access_count": round(avg_access, 2),
        }

    def diagnose(self, scope_id: str | None = None) -> dict:
        """Return a diagnostic summary for operator debugging."""
        scope = scope_id or self.scope_id
        stats = self.get_scope_stats(scope)
        access = self.get_access_patterns(scope)
        policy = self.get_policy_state()

        telemetry = self.get_recent_telemetry(limit=50)
        retrieval_events = [
            e for e in telemetry if e.get("event_type") == "memory_retrieval"
        ]
        zero_retrievals = sum(
            1 for e in retrieval_events
            if e.get("payload", {}).get("retrieved_count", 0) == 0
        )
        avg_retrieved = 0.0
        if retrieval_events:
            avg_retrieved = sum(
                e.get("payload", {}).get("retrieved_count", 0)
                for e in retrieval_events
            ) / float(len(retrieval_events))

        from datetime import datetime, timezone

        age_buckets = {"<1h": 0, "<24h": 0, "<7d": 0, "older": 0}
        units = self.store.list_active(scope, limit=500)
        now = datetime.now(timezone.utc)
        for u in units:
            try:
                created = datetime.fromisoformat(u.created_at.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_hours = max((now - created).total_seconds() / 3600.0, 0.0)
            except (ValueError, TypeError):
                age_hours = float("inf")
            if age_hours < 1:
                age_buckets["<1h"] += 1
            elif age_hours < 24:
                age_buckets["<24h"] += 1
            elif age_hours < 168:
                age_buckets["<7d"] += 1
            else:
                age_buckets["older"] += 1

        total_cache = self._cache_hits + self._cache_misses
        cache_hit_rate = round(self._cache_hits / max(total_cache, 1), 4)

        ttl_set = sum(1 for u in units if u.expires_at)
        ttl_expiring_soon = 0
        for u in units:
            if u.expires_at:
                try:
                    exp = datetime.fromisoformat(u.expires_at.replace("Z", "+00:00"))
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    hours_left = (exp - now).total_seconds() / 3600.0
                    if 0 < hours_left < 24:
                        ttl_expiring_soon += 1
                except (ValueError, TypeError):
                    pass

        issues: list[str] = []
        if stats.get("active", 0) == 0:
            issues.append("no active memories in store")
        if access.get("never_accessed", 0) > stats.get("active", 1) * 0.8:
            issues.append("over 80% of memories have never been accessed")
        if retrieval_events and zero_retrievals > len(retrieval_events) * 0.5:
            issues.append("over 50% of retrievals returned zero results")
        if ttl_expiring_soon > 0:
            issues.append(f"{ttl_expiring_soon} memories expiring within 24 hours")

        return {
            "scope_id": scope,
            "store": {
                "active": stats.get("active", 0),
                "dominant_type": stats.get("dominant_type", ""),
                "type_count": stats.get("type_count", 0),
                "age_distribution": age_buckets,
            },
            "access": {
                "avg_access_count": access.get("avg_access_count", 0.0),
                "never_accessed": access.get("never_accessed", 0),
            },
            "retrieval": {
                "recent_events": len(retrieval_events),
                "avg_retrieved": round(avg_retrieved, 2),
                "zero_retrieval_count": zero_retrievals,
            },
            "cache": {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate": cache_hit_rate,
            },
            "ttl": {
                "memories_with_ttl": ttl_set,
                "expiring_within_24h": ttl_expiring_soon,
            },
            "policy": {
                "retrieval_mode": policy.get("retrieval_mode", ""),
                "max_injected_units": policy.get("max_injected_units", 0),
                "max_injected_tokens": policy.get("max_injected_tokens", 0),
            },
            "issues": issues,
        }

    def detect_conflicts(self, scope_id: str | None = None) -> list[dict]:
        """Detect potential contradictions within the active memory pool."""
        scope = scope_id or self.scope_id
        units = self.store.list_active(scope, limit=500)
        if len(units) < 2:
            return []

        conflicts: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for i, a in enumerate(units):
            a_terms = set(t.lower() for t in a.topics + a.entities)
            if not a_terms:
                continue
            for b in units[i + 1:]:
                if a.memory_type != b.memory_type:
                    continue
                b_terms = set(t.lower() for t in b.topics + b.entities)
                if not b_terms:
                    continue
                overlap = len(a_terms & b_terms) / float(len(a_terms | b_terms))
                if overlap < 0.65:
                    continue
                if a.content.strip().lower() == b.content.strip().lower():
                    continue
                pair_key = tuple(sorted([a.memory_id, b.memory_id]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                conflicts.append({
                    "id_a": a.memory_id,
                    "id_b": b.memory_id,
                    "type": a.memory_type.value,
                    "overlap": round(overlap, 4),
                    "content_a": a.content[:120],
                    "content_b": b.content[:120],
                })
        return conflicts

    def explain_retrieval(
        self,
        task_description: str,
        scope_id: str | None = None,
    ) -> list[dict]:
        """Return detailed retrieval results with scoring explanations."""
        effective_scope = scope_id or self.scope_id
        query = MemoryQuery(
            scope_id=effective_scope,
            query_text=task_description,
            top_k=self.policy.max_injected_units,
            max_tokens=self.policy.max_injected_tokens,
        )
        hits = self.retriever.retrieve(query)
        return [
            {
                "memory_id": h.unit.memory_id,
                "type": h.unit.memory_type.value,
                "score": round(h.score, 4),
                "matched_terms": h.matched_terms,
                "reason": h.reason,
                "content_preview": h.unit.content[:120],
                "importance": h.unit.importance,
                "access_count": h.unit.access_count,
            }
            for h in hits
        ]

    def list_scopes(self) -> list[dict]:
        """List all scopes in the store with memory counts."""
        return self.store.list_scopes()

    def update_memory(self, memory_id: str, content: str, summary: str = "") -> bool:
        """Update the content of an existing memory."""
        result = self.store.update_content(memory_id, content, summary)
        if result:
            self.clear_cache()
        return result

    def get_memory(self, memory_id: str) -> MemoryUnit | None:
        """Get a specific memory by ID."""
        return self.store._get_by_id(memory_id)

    def set_ttl(self, memory_id: str, expires_at: str) -> bool:
        """Set or clear a TTL on a memory."""
        result = self.store.set_ttl(memory_id, expires_at)
        if result:
            self.clear_cache()
        return result

    def expire_stale(self, scope_id: str | None = None) -> int:
        """Archive all memories that have passed their TTL."""
        scope = scope_id or self.scope_id
        count = self.store.expire_stale(scope)
        if count:
            self.clear_cache()
            self._notify("expire", scope_id=scope, expired_count=count)
        return count

    def share_memory(self, memory_id: str, target_scope_id: str) -> str | None:
        """Copy a memory to another scope for cross-scope knowledge sharing."""
        new_id = self.store.share_to_scope(memory_id, target_scope_id)
        if new_id:
            self.clear_cache()
            self._notify("share", memory_id=memory_id, target_scope_id=target_scope_id, new_id=new_id)
        return new_id

    def export_scope(self, scope_id: str | None = None) -> list[dict]:
        """Export all active memories for a scope as JSON-serializable dicts."""
        scope = scope_id or self.scope_id
        return self.store.export_scope_json(scope)

    def import_memories(self, data: list[dict], target_scope_id: str | None = None) -> int:
        """Import memories from JSON dicts into the store."""
        scope = target_scope_id or self.scope_id
        count = self.store.import_memories_json(data, scope)
        if count:
            self.clear_cache()
        return count

    def set_type_ttl(
        self,
        memory_type: MemoryType,
        expires_at: str,
        scope_id: str | None = None,
    ) -> int:
        """Set TTL on all active memories of a given type."""
        scope = scope_id or self.scope_id
        count = self.store.set_type_ttl(scope, memory_type, expires_at)
        if count:
            self.clear_cache()
        return count

    def merge_memories(self, id_a: str, id_b: str, merged_content: str, merged_summary: str = "") -> str | None:
        """Merge two memories into a new one, superseding both."""
        new_id = self.store.merge_memories(id_a, id_b, merged_content, merged_summary)
        if new_id:
            self.clear_cache()
            self._notify("merge", id_a=id_a, id_b=id_b, new_id=new_id)
        return new_id

    def get_memory_history(self, memory_id: str) -> list[dict]:
        """Get version history for a memory through its supersedes chain."""
        return self.store.get_memory_history(memory_id)

    def get_scope_analytics(self, scope_id: str | None = None) -> dict:
        """Get comprehensive analytics for a scope."""
        scope = scope_id or self.scope_id
        return self.store.get_scope_analytics(scope)

    def add_tags(self, memory_id: str, tags: list[str]) -> bool:
        """Add user-defined tags to a memory."""
        result = self.store.add_tags(memory_id, tags)
        if result:
            self.clear_cache()
        return result

    def remove_tags(self, memory_id: str, tags: list[str]) -> bool:
        """Remove tags from a memory."""
        result = self.store.remove_tags(memory_id, tags)
        if result:
            self.clear_cache()
        return result

    def search_by_tag(self, tag: str, scope_id: str | None = None, limit: int = 50) -> list[MemoryUnit]:
        """Find all active memories with a given tag."""
        scope = scope_id or self.scope_id
        return self.store.search_by_tag(scope, tag, limit)

    def bulk_archive(self, memory_ids: list[str]) -> int:
        """Archive multiple memories at once."""
        count = self.store.bulk_archive(memory_ids)
        if count:
            self.clear_cache()
        return count

    def snapshot_scope(self, scope_id: str | None = None) -> dict:
        """Create a point-in-time snapshot for potential rollback."""
        scope = scope_id or self.scope_id
        return self.store.snapshot_scope(scope)

    def restore_snapshot(self, snapshot: dict) -> int:
        """Restore a scope from a previous snapshot."""
        count = self.store.restore_snapshot(snapshot)
        if count:
            self.clear_cache()
        return count

    def get_event_log(self, scope_id: str | None = None, limit: int = 50) -> list[dict]:
        """Get recent memory mutation events."""
        scope = scope_id or ""
        return self.store.get_event_log(scope_id=scope, limit=limit)

    def find_similar(self, memory_id: str, limit: int = 5) -> list[dict]:
        """Find memories similar to a given memory by topic/entity overlap."""
        results = self.store.find_similar(memory_id, limit)
        return [
            {
                "memory_id": u.memory_id,
                "type": u.memory_type.value,
                "similarity": score,
                "content": u.content[:120],
            }
            for u, score in results
        ]

    def get_health_score(self, scope_id: str | None = None) -> dict:
        """Get a composite health score (0-100) for the memory pool."""
        scope = scope_id or self.scope_id
        return self.store.compute_health_score(scope)

    def find_duplicates(self, scope_id: str | None = None, threshold: float = 0.80) -> list[dict]:
        """Find near-duplicate memory pairs by content similarity."""
        scope = scope_id or self.scope_id
        return self.store.find_duplicates(scope, threshold)

    def consolidation_dry_run(self, scope_id: str | None = None) -> dict:
        """Preview what consolidation would do without applying changes."""
        scope = scope_id or self.scope_id
        return self.consolidator.dry_run(scope)

    def save_stats_snapshot(self, scope_id: str | None = None) -> dict:
        """Save a timestamped stats snapshot for trend tracking."""
        scope = scope_id or self.scope_id
        return self.store.save_stats_snapshot(scope)

    def get_stats_trend(self, scope_id: str | None = None, limit: int = 20) -> list[dict]:
        """Get stats trend over time."""
        scope = scope_id or self.scope_id
        return self.store.get_stats_trend(scope, limit)

    def search_advanced(
        self,
        keyword: str = "",
        memory_type: str = "",
        tag: str = "",
        min_importance: float = 0.0,
        scope_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryUnit]:
        """Search memories with combined criteria."""
        scope = scope_id or self.scope_id
        return self.store.search_advanced(scope, keyword, memory_type, tag, min_importance, limit)

    def compare_scopes(self, scope_a: str, scope_b: str) -> dict:
        """Compare two scopes to find shared and unique memories."""
        return self.store.compare_scopes(scope_a, scope_b)

    def auto_resolve_conflicts(self, scope_id: str | None = None) -> dict:
        """Automatically resolve conflicts by superseding older memories."""
        scope = scope_id or self.scope_id
        conflicts = self.detect_conflicts(scope)
        if not conflicts:
            return {"resolved": 0}

        now = utc_now_iso()
        resolved = 0
        for c in conflicts:
            a = self.store._get_by_id(c["id_a"])
            b = self.store._get_by_id(c["id_b"])
            if a is None or b is None:
                continue
            if a.status != MemoryStatus.ACTIVE or b.status != MemoryStatus.ACTIVE:
                continue
            if a.importance >= 0.99 or b.importance >= 0.99:
                continue
            if a.created_at <= b.created_at:
                self.store.supersede(a.memory_id, b.memory_id, now)
            else:
                self.store.supersede(b.memory_id, a.memory_id, now)
            resolved += 1

        if resolved:
            self.clear_cache()
        result = {"resolved": resolved, "total_conflicts": len(conflicts)}
        self._notify("conflict_resolution", scope_id=scope, **result)
        return result

    def pin_memory(self, memory_id: str) -> bool:
        """Pin a memory so it always ranks highest in retrieval."""
        result = self.store.pin_memory(memory_id)
        if result:
            self.clear_cache()
        return result

    def unpin_memory(self, memory_id: str) -> bool:
        """Unpin a previously pinned memory."""
        result = self.store.unpin_memory(memory_id)
        if result:
            self.clear_cache()
        return result

    def provide_feedback(self, memory_id: str, helpful) -> None:
        """Record retrieval feedback for a specific memory."""
        if isinstance(helpful, str):
            helpful = helpful.lower() in ("positive", "true", "yes", "1", "helpful")
        self.store.record_feedback(memory_id, helpful)
        self.clear_cache()
        self._notify("feedback", memory_id=memory_id, helpful=helpful)
        if self.telemetry_store is not None:
            self.telemetry_store.record(
                "memory_feedback",
                {"memory_id": memory_id, "helpful": helpful},
            )

    def get_pool_summary(self, scope_id: str | None = None, max_per_type: int = 3) -> str:
        """Generate a concise summary of the entire memory pool."""
        scope = scope_id or self.scope_id
        units = self.store.list_active(scope, limit=500)
        if not units:
            return "No active memories."

        by_type: dict[str, list[MemoryUnit]] = {}
        for u in units:
            by_type.setdefault(u.memory_type.value, []).append(u)

        lines = [f"Memory pool: {len(units)} active memories across {len(by_type)} types"]
        for type_name, group in sorted(by_type.items()):
            lines.append(f"\n{type_name} ({len(group)}):")
            top = sorted(group, key=lambda u: u.importance, reverse=True)[:max_per_type]
            for u in top:
                preview = u.content[:100].replace("\n", " ")
                lines.append(f"  - [{u.importance:.2f}] {preview}")
            if len(group) > max_per_type:
                lines.append(f"  ... and {len(group) - max_per_type} more")

        conflicts = self.detect_conflicts(scope)
        if conflicts:
            lines.append(f"\nPotential conflicts: {len(conflicts)}")
            for c in conflicts[:3]:
                lines.append(f"  - {c['content_a'][:60]} vs {c['content_b'][:60]}")

        return "\n".join(lines)

    def search_memories(
        self,
        query_text: str,
        scope_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search memories by keyword with scoring information."""
        scope = scope_id or self.scope_id
        hits = self.store.search_keyword(scope, query_text, limit=limit)
        return [
            {
                "memory_id": h.unit.memory_id,
                "type": h.unit.memory_type.value,
                "score": round(h.score, 4),
                "content": h.unit.content[:200],
                "importance": h.unit.importance,
                "access_count": h.unit.access_count,
                "matched_terms": h.matched_terms,
                "created_at": h.unit.created_at,
            }
            for h in hits
        ]

    def get_recent_telemetry(self, limit: int = 20) -> list[dict]:
        if self.telemetry_store is None:
            return []
        return self.telemetry_store.read_recent(limit=limit)

    def clear_cache(self) -> None:
        """Clear the retrieval cache (e.g., after ingestion)."""
        self._retrieval_cache.clear()

    def get_memories_by_ids(self, memory_ids: list[str]) -> list:
        """Retrieve multiple memories by their IDs in a single operation."""
        return self.store.get_by_ids(memory_ids)

    # --- Scope access control ---

    def grant_scope_access(self, scope_id: str, principal: str, permission: str = "read") -> bool:
        """Grant a principal access to a scope."""
        return self.store.grant_access(scope_id, principal, permission)

    def revoke_scope_access(self, scope_id: str, principal: str, permission: str | None = None) -> int:
        """Revoke a principal's access to a scope."""
        return self.store.revoke_access(scope_id, principal, permission)

    def check_scope_access(self, scope_id: str, principal: str, permission: str = "read") -> bool:
        """Check if a principal can access a scope."""
        return self.store.check_access(scope_id, principal, permission)

    def list_scope_grants(self, scope_id: str) -> list[dict]:
        """List all access grants for a scope."""
        return self.store.list_scope_grants(scope_id)

    # --- Memory watches ---

    def watch_memory(self, memory_id: str, watcher: str) -> bool:
        """Watch a memory for changes."""
        return self.store.add_watch(memory_id, watcher)

    def unwatch_memory(self, memory_id: str, watcher: str) -> bool:
        """Stop watching a memory."""
        return self.store.remove_watch(memory_id, watcher)

    def get_watchers(self, memory_id: str) -> list[str]:
        """Get all watchers for a memory."""
        return self.store.get_watchers(memory_id)

    def get_watched_memories(self, watcher: str) -> list[str]:
        """Get all memory IDs watched by a watcher."""
        return self.store.get_watched_memories(watcher)

    # --- Memory annotations ---

    def add_annotation(self, memory_id: str, content: str, author: str = "") -> int:
        """Add an annotation to a memory."""
        return self.store.add_annotation(memory_id, content, author)

    def get_annotations(self, memory_id: str) -> list[dict]:
        """Get all annotations for a memory."""
        return self.store.get_annotations(memory_id)

    def delete_annotation(self, annotation_id: int) -> bool:
        """Delete an annotation by ID."""
        return self.store.delete_annotation(annotation_id)

    # --- Memory links ---

    def add_link(self, source_id: str, target_id: str, link_type: str = "related") -> bool:
        """Create a directed link between two memories."""
        return self.store.add_link(source_id, target_id, link_type)

    def remove_link(self, source_id: str, target_id: str, link_type: str | None = None) -> int:
        """Remove a link between two memories."""
        return self.store.remove_link(source_id, target_id, link_type)

    def get_links(self, memory_id: str, direction: str = "both") -> list[dict]:
        """Get all links for a memory."""
        return self.store.get_links(memory_id, direction)

    def get_linked_memories(self, memory_id: str, link_type: str | None = None) -> list[MemoryUnit]:
        """Get all memory units linked to a given memory."""
        return self.store.get_linked_memories(memory_id, link_type)


def _dedup_against_store(
    units: list[MemoryUnit],
    store: MemoryStore,
    scope: str,
) -> list[MemoryUnit]:
    """Filter out units whose content already exists verbatim in the active pool."""
    existing = store.list_active(scope, limit=2000)
    existing_content = {u.content.strip().lower() for u in existing}
    return [u for u in units if u.content.strip().lower() not in existing_content]
