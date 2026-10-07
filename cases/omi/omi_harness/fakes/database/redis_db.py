"""Fake of backend/database/redis_db.py: a dict with scenario-clock expiry.

Rate-limit timestamps are stored as scenario time (the vendored callers compare them with
time.time(), which reads the same scenario clock).
"""
from omi_harness.loader import CLOCK
from omi_harness.store import STORE


def _get(key):
    v = STORE.redis.get(key)
    if v is None:
        return None
    value, expires = v
    if expires is not None and CLOCK.time() >= expires:
        STORE.redis.pop(key, None)
        return None
    return value


def _set(key, value, ttl=None):
    STORE.redis[key] = (value, CLOCK.time() + ttl if ttl else None)


def get_proactive_noti_sent_at(uid: str, app_id: str):
    return _get(f'proactive_noti_sent_at:{uid}:{app_id}')


def set_proactive_noti_sent_at(uid: str, app_id: str, ts: int, ttl: int = 30):
    _set(f'proactive_noti_sent_at:{uid}:{app_id}', ts, ttl)


def get_proactive_noti_sent_at_ttl(uid: str, app_id: str) -> int:
    v = STORE.redis.get(f'proactive_noti_sent_at:{uid}:{app_id}')
    if not v or v[1] is None:
        return -1
    return max(0, int(v[1] - CLOCK.time()))


def _day_key(uid, day_zone):
    from datetime import datetime
    day = CLOCK.now().astimezone(day_zone).strftime('%Y-%m-%d') if day_zone else CLOCK.now().strftime('%Y-%m-%d')
    return f'daily_notification_count:{uid}:{day}'


def get_daily_notification_count(uid: str, day_zone=None) -> int:
    return int(_get(_day_key(uid, day_zone)) or 0)


def incr_daily_notification_count(uid: str, day_zone=None) -> int:
    key = _day_key(uid, day_zone)
    n = int(_get(key) or 0) + 1
    _set(key, n, 2 * 86400)
    return n


def publish_proactive_message(uid, app_id, title, message, conversation_id=None):
    return None


def try_acquire_conversation_goal_lock(uid: str, conversation_id: str) -> bool:
    key = f'goal_lock:{uid}:{conversation_id}'
    if _get(key):
        return False
    _set(key, True, 3600)
    return True


def release_conversation_goal_lock(uid: str, conversation_id: str):
    STORE.redis.pop(f'goal_lock:{uid}:{conversation_id}', None)


def try_acquire_goal_extraction_lock(uid: str) -> bool:
    return True


def add_filter_category_item(uid: str, category: str, item: str):
    STORE.redis.setdefault(f'filter:{uid}:{category}', (set(), None))[0].add(item)


def get_filter_category_items(uid: str, category: str, limit: int = 1000):
    return sorted(STORE.redis.get(f'filter:{uid}:{category}', (set(), None))[0])[:limit]


def get_generic_cache(key):
    return _get(f'generic:{key}')


def set_generic_cache(key, value, ttl=None):
    _set(f'generic:{key}', value, ttl)


def get_cached_user_geolocation(uid: str):
    return None


def reserve_rate_limit(key: str, policy: str, limit: int, window: int):
    k = f'rl:{policy}:{key}'
    n = int(_get(k) or 0) + 1
    _set(k, n, window)
    return n <= limit, max(0, limit - n), window


def has_important_conversation_notification_been_sent(uid, conversation_id):
    return bool(_get(f'important:{uid}:{conversation_id}'))


def set_important_conversation_notification_sent(uid, conversation_id):
    _set(f'important:{uid}:{conversation_id}', True, 86400)


def get_in_progress_conversation_id(uid):
    return None


def get_user_preferred_app(uid):
    return None


def get_conversation_summary_app_ids(uid):
    return []


def get_enabled_apps(uid):
    return []          # no marketplace app is installed


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
