"""Fake of backend/utils/memory/canonical_memory_adapter.py (Firestore canonical memory adapter).

extraction_memory_id is copied from upstream (lines 277-295); the read helpers used by the chat's
preference tool go through the fake MemoryService.
"""
from typing import Any, Dict, List, Optional

from models.memory_contracts import deterministic_contract_id


def extraction_memory_id(*, uid: str, source_id: str, content: str, subject_entity_id: Optional[str] = None) -> str:
    identity = {"uid": uid, "source_id": source_id, "content": (content or "").strip()}
    normalized_subject = (subject_entity_id or "").strip()
    if normalized_subject and normalized_subject != "user":
        identity["subject_entity_id"] = normalized_subject
    return "mem_" + deterministic_contract_id("canonical-extraction-memory", identity)[:32]


def search_canonical_memories(uid: str, query: str, *, limit: int = 5, db_client: Any = None, **kwargs) -> List[Dict[str, Any]]:
    from utils.memory.memory_service import MemoryService
    return [{'id': m.memory.id, 'content': m.memory.content, 'score': m.score}
            for m in MemoryService(db_client=db_client).search(uid, query, limit=limit)]


def read_canonical_memory_item(uid: str, memory_id: str, *, db_client: Any = None):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
