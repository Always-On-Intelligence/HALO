"""Fake of backend/utils/memory/memory_service.py: the canonical memory store as a list of MemoryDB rows.

Upstream MemoryService is the Firestore-backed canonical memory authority (ledger, short-term
promotion, consolidation, vector projections). Here it keeps the rows the extraction writes and
returns them to readers immediately; promotion and consolidation are not run.

Cut sites at this storage boundary:
  S->M  memories extracted from a transcript are not written (replace_conversation_memories)
  A->M  a memory the chat agent saves is not written (create_external_memory)
  M->A  while Action decides (mentor, chat), read() and search() return nothing
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models.memories import MemoryDB
from omi_harness.llm_bridge import EMBEDDINGS
from omi_harness.loader import CLOCK
from omi_harness.store import STORE, cosine


@dataclass(frozen=True)
class MemorySearchMatch:
    memory: MemoryDB
    score: float


class MemoryBackingStoreUnavailable(Exception):
    pass


def _rows(uid: str) -> Dict[str, MemoryDB]:
    return STORE.memories.setdefault(uid, {})


def _to_memory(payload: Dict[str, Any]) -> MemoryDB:
    fields = set(MemoryDB.model_fields)
    return MemoryDB.model_validate({k: v for k, v in payload.items() if k in fields})


def _withheld(site: str) -> bool:
    return STORE.reading_for_action() and STORE.cut_active('M->A', site)


class MemoryService:
    def __init__(self, *, db_client: Any = None):
        self.db_client = db_client

    def _invalidate_prompt_cache(self, uid: str) -> None:
        try:
            from utils.llms.memory import clear_prompt_data_cache
        except ImportError:
            return
        clear_prompt_data_cache(uid)

    def ensure_canonical_mutation_ready(self, uid: str) -> None:
        return None

    # ---- writes ----------------------------------------------------------------------------
    def replace_conversation_memories(self, uid: str, conversation_id: str, items: List[Dict[str, Any]]):
        for p in items:
            STORE.note('memory.extracted', conversation_id=conversation_id, content=p.get('content'))
        if STORE.cut_active('S->M', 'utils.memory.memory_service.replace_conversation_memories'):
            return {'written_memory_ids': [], 'retracted_memory_ids': []}
        rows = _rows(uid)
        new = [_to_memory(p) for p in items]
        retracted = [] if not new else [mid for mid, m in rows.items() if m.conversation_id == conversation_id]
        for mid in retracted:
            rows.pop(mid, None)
        for m in new:
            rows[m.id] = m
            STORE.note('memory.write', id=m.id, content=m.content, source='conversation')
        self._invalidate_prompt_cache(uid)
        return {'written_memory_ids': [m.id for m in new], 'retracted_memory_ids': retracted}

    def create_external_memory(self, uid: str, memory_db: MemoryDB, *, memory_system=None, consumer: str = '',
                               operation: str = '', upsert_vector: bool = True, require_canonical_promotion: bool = True,
                               direct_user_authority=None) -> MemoryDB:
        if STORE.cut_active('A->M', 'utils.memory.memory_service.create_external_memory'):
            return memory_db
        _rows(uid)[memory_db.id] = memory_db
        STORE.note('memory.write', id=memory_db.id, content=memory_db.content, source=consumer)
        self._invalidate_prompt_cache(uid)
        return memory_db

    def write(self, uid: str, data: Dict[str, Any]) -> str:
        m = _to_memory(data)
        self.create_external_memory(uid, m, consumer='write')
        return m.id

    # ---- reads -----------------------------------------------------------------------------
    def read(self, uid: str, *, limit: int = 100, offset: int = 0, device_scope_request=None,
             include_pending_processing: bool = False, include_archive: bool = False, now=None, budget=None,
             view: str = 'released', as_of=None) -> List[MemoryDB]:
        if _withheld('utils.memory.memory_service.read'):
            return []
        rows = [m for m in _rows(uid).values() if m.invalid_at is None]
        rows.sort(key=lambda m: (m.created_at, m.id), reverse=True)
        return rows[offset:offset + limit]

    def search(self, uid: str, query: str, *, limit: int = 5, candidate_limit: Optional[int] = None,
               device_scope_request=None, canonical_item_filter=None, result_filter=None, ledger_kinds=None,
               view: str = 'released', as_of=None) -> List[MemorySearchMatch]:
        if _withheld('utils.memory.memory_service.search'):
            return []
        rows = [m for m in _rows(uid).values() if m.invalid_at is None and not m.is_locked]
        if result_filter is not None:
            rows = [m for m in rows if result_filter(m)]
        if not rows or not (query or '').strip():
            return []
        q = EMBEDDINGS.embed_query(query)
        vecs = EMBEDDINGS.embed_documents([m.content for m in rows])
        scored = sorted(((cosine(q, v), m) for v, m in zip(vecs, rows)), key=lambda x: -x[0])
        capped = max(1, min(int(limit or 5), 20))
        return [MemorySearchMatch(memory=m, score=s) for s, m in scored[:capped]]


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
