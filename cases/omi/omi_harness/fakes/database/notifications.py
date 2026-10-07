"""Fake of backend/database/notifications.py (notification settings and time zone)."""
from omi_harness.store import STORE


def get_mentor_notification_frequency(uid: str) -> int:
    return int(STORE.users.get(uid, {}).get('mentor_frequency', 3))


def get_user_time_zone(uid: str):
    return STORE.users.get(uid, {}).get('time_zone')


def resolve_user_timezone(uid: str) -> str:
    return STORE.users.get(uid, {}).get('time_zone') or 'UTC'


def sync_user_time_zone_from_client(uid: str, time_zone: str):
    return STORE.users.get(uid, {}).get('time_zone') or time_zone


def get_token_only(uid: str):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
