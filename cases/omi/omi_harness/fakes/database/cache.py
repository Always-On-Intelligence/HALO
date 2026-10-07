"""Fake of backend/database/cache.py: the in-process TTL cache, on the scenario clock."""
from omi_harness.loader import CLOCK
from omi_harness.store import STORE


class _MemoryCache:
    def get_or_fetch(self, key, fetch, ttl=None):
        hit = STORE.redis.get(f'cache:{key}')
        if hit and (hit[1] is None or CLOCK.time() < hit[1]):
            return hit[0]
        value = fetch()
        if value is not None:
            STORE.redis[f'cache:{key}'] = (value, CLOCK.time() + ttl if ttl else None)
        return value

    def get(self, key):
        hit = STORE.redis.get(f'cache:{key}')
        return hit[0] if hit and (hit[1] is None or CLOCK.time() < hit[1]) else None

    def set(self, key, value, ttl=None):
        STORE.redis[f'cache:{key}'] = (value, CLOCK.time() + ttl if ttl else None)

    def delete(self, key):
        STORE.redis.pop(f'cache:{key}', None)


_CACHE = _MemoryCache()


def get_memory_cache():
    return _CACHE


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
