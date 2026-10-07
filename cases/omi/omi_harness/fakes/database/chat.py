"""Fake of backend/database/chat.py: chat and app messages in STORE.messages.

Mirrors the upstream read rules that matter here: newest first, filtered by plugin_id (app_id) or
chat session, reported rows hidden, and the cache-aligned history window (10..17 messages).

Cut sites at this storage boundary:
  S->M  a human chat turn (user-supplied evidence) is not written (add_message, sender=human)
  A->M  an assistant turn or app notification is not written (add_message sender=ai, add_app_message)
  M->A  while Action decides (mentor, chat), stored messages are not read back
"""
from datetime import timezone
from typing import Any, Dict, List, Optional

from models.chat import Message
from omi_harness.loader import CLOCK, SIM_UUID
from omi_harness.store import STORE

CHAT_HISTORY_BASE_VISIBLE_MESSAGES = 10   # database/chat.py:41
CHAT_HISTORY_APPEND_EPOCH_MESSAGES = 8    # database/chat.py:42


def _write(uid: str, data: Dict[str, Any]):
    data = dict(data)
    data.pop('memories', None)
    if data.get('app_id') is not None:
        data['plugin_id'] = data['app_id']
    STORE.messages.setdefault(uid, []).append(data)
    STORE.note('chat.add_message', sender=str(data.get('sender')), app_id=data.get('app_id'), text=data.get('text'))


def add_message(uid: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
    sender = getattr(message_data.get('sender'), 'value', message_data.get('sender'))
    channel = 'S->M' if sender == 'human' else 'A->M'
    if STORE.cut_active(channel, f'database.chat.add_message[{sender}]'):
        message_data.pop('memories', None)
        return message_data
    _write(uid, message_data)
    return message_data


def add_app_message(text: str, app_id: str, uid: str, conversation_id: Optional[str] = None, *,
                    proactivity_item_id: Optional[str] = None) -> Message:
    ai_message = Message(id=str(SIM_UUID.uuid4()), text=text, created_at=CLOCK.now(), sender='ai', app_id=app_id,
                         from_external_integration=False, type='text',
                         memories_id=[conversation_id] if conversation_id else [], chat_session_id=None)
    if STORE.cut_active('A->M', 'database.chat.add_app_message'):
        return ai_message
    _write(uid, ai_message.model_dump())
    return ai_message


def _visible(uid: str, app_id: Optional[str] = None, chat_session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = []
    for m in reversed(STORE.messages.get(uid, [])):
        if chat_session_id:
            if m.get('chat_session_id') != chat_session_id:
                continue
        elif m.get('plugin_id') != app_id:
            continue
        if m.get('reported') is True:
            continue
        rows.append(dict(m))
    return rows


def _withheld(site: str) -> bool:
    return STORE.reading_for_action() and STORE.cut_active('M->A', site)


def get_app_messages(uid: str, app_id: str, limit: int = 20, include_conversations: bool = False):
    if _withheld('database.chat.get_app_messages'):
        return []
    return _visible(uid, app_id)[:max(0, int(limit))]


def get_messages(uid: str, limit: int = 20, offset: int = 0, include_conversations: bool = False,
                 app_id: Optional[str] = None, chat_session_id: Optional[str] = None):
    if _withheld('database.chat.get_messages'):
        return []
    return _visible(uid, app_id, chat_session_id)[offset:offset + limit]


def cache_aligned_history_limit(total_visible_messages: int) -> int:
    if total_visible_messages <= CHAT_HISTORY_BASE_VISIBLE_MESSAGES:
        return total_visible_messages
    return CHAT_HISTORY_BASE_VISIBLE_MESSAGES + (
        (total_visible_messages - CHAT_HISTORY_BASE_VISIBLE_MESSAGES) % CHAT_HISTORY_APPEND_EPOCH_MESSAGES)


def get_cache_aligned_messages(uid: str, *, app_id: Optional[str] = None, chat_session_id: Optional[str] = None):
    if _withheld('database.chat.get_cache_aligned_messages'):
        return []
    rows = _visible(uid, app_id, chat_session_id)
    return rows[:cache_aligned_history_limit(len(rows))]


def get_chat_session(uid: str, app_id: Optional[str] = None):
    return None


def add_message_to_chat_session(uid: str, chat_session_id: str, message_id: str):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
