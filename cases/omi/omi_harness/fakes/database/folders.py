"""Fake of backend/database/folders.py: the scripted user has no conversation folders, so the
AI folder assignment in process_conversation (utils/conversations/process_conversation.py:3205-3230) does
not run (it would be one more model call per conversation)."""


def get_folders(uid: str):
    return []


def initialize_system_folders(uid: str):
    return []


def resolve_category_folder_id(category, user_folders):
    return None


def update_folder_conversation_count(uid, folder_id):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
