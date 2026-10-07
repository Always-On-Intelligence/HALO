"""Fake of backend/database/mem_db.py (per-process cache of rate-limit timestamps)."""
from omi_harness.loader import CLOCK
from omi_harness.store import STORE


def get_proactive_noti_sent_at(uid: str, app_id: str):
    v = STORE.redis.get(f'mem:proactive_noti_sent_at:{uid}:{app_id}')
    if not v:
        return None
    value, expires = v
    if expires is not None and CLOCK.time() >= expires:
        return None
    return value


def set_proactive_noti_sent_at(uid: str, app_id: str, ts: int, ttl: int = 30):
    STORE.redis[f'mem:proactive_noti_sent_at:{uid}:{app_id}'] = (ts, CLOCK.time() + ttl)


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
