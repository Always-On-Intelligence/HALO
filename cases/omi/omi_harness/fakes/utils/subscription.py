"""Fake of backend/utils/subscription.py: paid plan, no trial paywall, no deferral of processing."""


def is_trial_paywalled(uid, platform=None, *args, **kwargs) -> bool:
    return False


def should_defer_desktop_processing(uid) -> bool:
    return False


def should_skip_omi_paid_postprocessing(uid, *args, **kwargs) -> bool:
    return False


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
