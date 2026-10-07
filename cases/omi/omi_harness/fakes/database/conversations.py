"""Fake of backend/database/conversations.py: conversation documents in STORE.conversations.

M->A cut site: while Action decides (mentor, chat tools), stored conversations are not read back.
(The write side, and the S->M cut on it, is utils/conversations/lifecycle.py's fake.)
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from omi_harness.store import STORE


def _rows(uid: str) -> List[Dict[str, Any]]:
    return list(STORE.conversations.get(uid, {}).values())


def _withheld(site: str) -> bool:
    return STORE.reading_for_action() and STORE.cut_active('M->A', site)


def _ts(row, field='created_at'):
    v = row.get(field) or row.get('started_at')
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace('Z', '+00:00'))
    if isinstance(v, datetime) and v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v or datetime.min.replace(tzinfo=timezone.utc)


def get_conversation(uid, conversation_id, *, read_site=None, include_transcript_decode_status=False):
    if _withheld('database.conversations.get_conversation'):
        return None
    row = STORE.conversations.get(uid, {}).get(conversation_id)
    return dict(row) if row else None


def get_conversations(uid: str, limit: int = 100, offset: int = 0, include_discarded: bool = False,
                      statuses: List[str] = [], start_date: Optional[datetime] = None,
                      end_date: Optional[datetime] = None, categories: Optional[List[str]] = None,
                      folder_id: Optional[str] = None, starred: Optional[bool] = None, date_field: str = 'created_at',
                      *, metadata_only: bool = False):
    if _withheld('database.conversations.get_conversations'):
        return []
    rows = []
    for row in _rows(uid):
        if not include_discarded and row.get('discarded'):
            continue
        if statuses and str(getattr(row.get('status'), 'value', row.get('status'))) not in statuses:
            continue
        ts = _ts(row, date_field)
        if start_date and ts < start_date:
            continue
        if end_date and ts > end_date:
            continue
        if categories and (row.get('structured') or {}).get('category') not in categories:
            continue
        rows.append(row)
    rows.sort(key=lambda r: _ts(r, date_field), reverse=True)
    return [dict(r) for r in rows[offset:offset + limit]]


def get_conversations_without_photos(uid: str, limit: int = 100, offset: int = 0, include_discarded: bool = False,
                                     statuses: List[str] = [], sources=None, start_date=None, end_date=None,
                                     categories=None, folder_id=None, starred=None, budget=None):
    return get_conversations(uid, limit=limit, offset=offset, include_discarded=include_discarded, statuses=statuses,
                             start_date=start_date, end_date=end_date, categories=categories)


def get_conversations_by_id(uid, conversation_ids, include_discarded: bool = False, *, read_site=None):
    if _withheld('database.conversations.get_conversations_by_id'):
        return []
    store = STORE.conversations.get(uid, {})
    out = []
    for cid in conversation_ids:
        row = store.get(cid)
        if row and (include_discarded or not row.get('discarded')):
            out.append(dict(row))
    return out


get_conversations_by_id_without_photos = get_conversations_by_id


def update_conversation(uid: str, conversation_id: str, update_data: dict) -> bool:
    row = STORE.conversations.get(uid, {}).get(conversation_id)
    if row is None:
        return False
    row.update(update_data)
    return True


def initialize_first_open_work(uid: str, conversation_id: str) -> bool:
    return False


def get_in_progress_conversation(uid: str):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
