"""Fake of backend/utils/jit_rollout.py (PostHog-backed rollout authority for desktop JIT features).

The configuration excludes the rollout-gated JIT features, so every decision is "not admitted".
"""
from enum import Enum
from types import SimpleNamespace


class JITDecisionStage(str, Enum):
    READ_ONLY = 'read_only'
    PROCESSING = 'processing'
    FIRST_OPEN = 'first_open'


_DENY = SimpleNamespace(permits_work=False, admitted=False, reason='not_enrolled', enabled=False)


async def resolve_jit_rollout(uid, *, stage=None, force_refresh: bool = False):
    return _DENY


def resolve_jit_rollout_sync(uid, *, stage=None, force_refresh: bool = False, **kwargs):
    return _DENY


def is_jit_admission_allowlisted(uid) -> bool:
    return False


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
