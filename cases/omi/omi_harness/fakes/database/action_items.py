"""Fake of backend/database/action_items.py: tasks in STORE.action_items.

A->M cut site: tasks the service creates (extracted at conversation end, or created by the chat
agent) are not written. M->A cut site: while Action decides, stored tasks are not read back.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from omi_harness.loader import CLOCK, SIM_UUID
from omi_harness.store import STORE


def _items(uid):
    return STORE.action_items.setdefault(uid, {})


def _withheld(site: str) -> bool:
    return STORE.reading_for_action() and STORE.cut_active('M->A', site)


def _create(uid: str, data: Dict[str, Any], document_id: Optional[str] = None) -> str:
    aid = document_id or str(SIM_UUID.uuid4())
    if STORE.cut_active('A->M', 'database.action_items.create'):
        return aid
    row = dict(data)
    row['id'] = aid
    row.setdefault('created_at', CLOCK.now())
    row.setdefault('updated_at', row['created_at'])
    row.setdefault('completed', False)
    _items(uid)[aid] = row
    STORE.note('action_item.create', id=aid, description=row.get('description'))
    return aid


def create_action_item(uid: str, action_item_data: Dict[str, Any], idempotency_key: Optional[str] = None, *,
                       document_id: Optional[str] = None) -> str:
    return _create(uid, action_item_data, document_id)


def create_action_items_batch(uid: str, action_items_data: List[Dict[str, Any]], *, document_ids=None) -> List[str]:
    ids = document_ids or [None] * len(action_items_data)
    return [_create(uid, d, i) for d, i in zip(action_items_data, ids)]


def get_action_item(uid: str, action_item_id: str):
    if _withheld('database.action_items.get_action_item'):
        return None
    row = _items(uid).get(action_item_id)
    return dict(row) if row and not row.get('deleted') else None


def get_action_items(uid: str, conversation_id: Optional[str] = None, completed: Optional[bool] = None,
                     start_date=None, end_date=None, due_start_date=None, due_end_date=None,
                     limit: Optional[int] = None, offset: int = 0, budget=None, extra_fields=()):
    if _withheld('database.action_items.get_action_items'):
        return []
    rows = [r for r in _items(uid).values() if not r.get('deleted')]
    if conversation_id is not None:
        rows = [r for r in rows if r.get('conversation_id') == conversation_id]
    if completed is not None:
        rows = [r for r in rows if bool(r.get('completed')) == completed]
    rows.sort(key=lambda r: (bool(r.get('completed')), -(r['created_at'].timestamp())))
    rows = rows[offset:]
    return [dict(r) for r in (rows[:limit] if limit else rows)]


def get_action_items_by_conversation(uid: str, conversation_id: str, *, extra_fields=()):
    rows = [r for r in _items(uid).values() if r.get('conversation_id') == conversation_id and not r.get('deleted')]
    return [dict(r) for r in rows]


def get_action_items_by_ids(uid: str, action_item_ids: List[str]):
    store = _items(uid)
    return [dict(store[i]) for i in action_item_ids if i in store and not store[i].get('deleted')]


def update_action_item(uid: str, action_item_id: str, update_data: Dict[str, Any]) -> bool:
    row = _items(uid).get(action_item_id)
    if row is None:
        return False
    if STORE.cut_active('A->M', 'database.action_items.update'):
        return True
    row.update(update_data)
    row['updated_at'] = CLOCK.now()
    STORE.note('action_item.update', id=action_item_id, data={k: str(v) for k, v in update_data.items()})
    return True


def delete_action_items_for_conversation(uid: str, conversation_id: str) -> int:
    store = _items(uid)
    ids = [i for i, r in store.items() if r.get('conversation_id') == conversation_id]
    for i in ids:
        del store[i]
    return len(ids)


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
