"""Fake of backend/utils/memory/rejected_memory_feedback.py: the scripted user has rejected no memory."""


def get_recent_rejected_memory_examples(uid: str, *, db_client=None):
    return ()


def bound_rejected_memory_examples(examples):
    return tuple(examples or ())


def clear_rejected_memory_feedback_cache(uid=None):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
