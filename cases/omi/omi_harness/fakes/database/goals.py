"""Fake of backend/database/goals.py.

M->A cut site (goals): goals do not reach Action decisions (mentor prompts, chat system prompt).
"""
from omi_harness.store import STORE


def get_user_goals(uid: str, limit: int = 100, include_inactive: bool = False):
    if STORE.reading_for_action() and STORE.cut_active('M->A', 'database.goals.get_user_goals'):
        return []
    return [dict(g) for g in STORE.goals.get(uid, [])][:limit]


def get_user_goal(uid: str):
    goals = get_user_goals(uid, limit=1)
    return goals[0] if goals else None


def get_task_workflow_account_generation(uid: str):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
