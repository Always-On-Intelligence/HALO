"""Fake of backend/utils/conversations/lifecycle.py: the Firestore lifecycle transactions that persist
a processed conversation become writes to STORE.conversations.

S->M cut site: the processed conversation (notes + transcript) is not admitted to the store. The
processor is told the write succeeded, so the rest of finalization runs unchanged.
"""
from typing import Any

from omi_harness.store import STORE


def _persist(uid: str, data: dict) -> bool:
    if STORE.cut_active('S->M', 'utils.conversations.lifecycle.persist'):
        return True
    row = dict(data)
    STORE.conversations.setdefault(uid, {})[row['id']] = row
    STORE.note('conversation.persist', id=row['id'], title=(row.get('structured') or {}).get('title'))
    return True


def create_completed_conversation(uid: str, conversation_data: dict[str, Any], *, idempotent: bool = False) -> bool:
    return _persist(uid, conversation_data)


def persist_processed_conversation(uid: str, conversation_data: dict[str, Any], *, smart_merge_refresh=None) -> bool:
    return _persist(uid, conversation_data)


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
