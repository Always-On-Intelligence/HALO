"""Fake of backend/utils/managed_compute.py (plan and billing resolution).

The scripted user is on a paid plan that includes Omi-funded processing and the mentor, so every
managed-compute decision resolves to allowed.
"""
from types import SimpleNamespace


def authorize_managed_compute(uid, feature=None, provider=None, *args, subscription=None, **kwargs):
    return SimpleNamespace(plan_resolved=True, allowed=True, reason='paid_plan', funding_owner=uid)


def managed_compute_decision_for(uid):
    def decision_for(*args, **kwargs):
        return authorize_managed_compute(uid, *args, **kwargs)
    return decision_for


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
