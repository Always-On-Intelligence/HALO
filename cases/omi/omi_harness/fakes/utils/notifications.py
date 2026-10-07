"""Fake of backend/utils/notifications.py (the FCM transport): deliveries are recorded in STORE.delivered."""
from omi_harness.loader import CLOCK
from omi_harness.store import STORE


def _deliver(user_id, title, body, data=None, kind='push'):
    STORE.delivered.append({'at': CLOCK.now().isoformat(), 'title': title, 'body': body, 'kind': kind,
                            'app_id': (data or {}).get('plugin_id') if isinstance(data, dict) else None})
    return 1


def send_notification_result(user_id, title, body, data=None):
    return _deliver(user_id, title, body, data)


async def send_notification_async(user_id, title, body, data=None):
    return _deliver(user_id, title, body, data)


def send_notification(user_id, title, body, data=None, *args, **kwargs):
    return _deliver(user_id, title, body, data)


def send_action_item_data_message(user_id, action_item_id, description, due_at):
    return None


def sync_action_item_reminder(*args, **kwargs):
    return None


def send_important_conversation_message(*args, **kwargs):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
