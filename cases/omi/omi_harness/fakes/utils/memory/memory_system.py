"""Fake of backend/utils/memory/memory_system.py: the per-user writer control is the released
compatibility writer (the default before a ledger migration)."""
from enum import Enum
from types import SimpleNamespace


class MemorySystem(str, Enum):
    CANONICAL = 'canonical'
    LEGACY = 'legacy'


def ensure_canonical_apply_control_state(uid: str, *, db_client=None):
    return SimpleNamespace(writer_mode='compatibility')


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
