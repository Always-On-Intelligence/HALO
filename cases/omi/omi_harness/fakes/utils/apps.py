"""Fake of backend/utils/apps.py (app marketplace): the scripted user has installed no third-party app.
The built-in mentor is not a marketplace app; it runs from utils/app_integrations.py directly."""


def get_available_apps(uid, *args, **kwargs):
    return []


def get_available_app_by_id(app_id, uid=None, *args, **kwargs):
    return None


def get_available_app_model_by_id(app_id, uid=None, *args, **kwargs):
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
