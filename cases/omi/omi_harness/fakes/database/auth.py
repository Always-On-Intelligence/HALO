"""Fake of backend/database/auth.py (user profile name)."""
from omi_harness.store import STORE


def get_user_name(uid: str, use_default: bool = True):
    name = STORE.users.get(uid, {}).get('name')
    if name:
        return name
    return 'The User' if use_default else None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
