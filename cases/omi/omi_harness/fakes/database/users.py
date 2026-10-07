"""Fake of backend/database/users.py: profile settings and stored people (speaker profiles).

M->S cut site (people half): while Sensing processes an incoming transcript, the stored people
behind person_id labels are not available, so names cannot be attached to speakers.
"""
from omi_harness.store import STORE


def get_people_by_ids(uid: str, person_ids):
    if STORE.phase == 'sensing' and STORE.cut_active('M->S', 'database.users.get_people_by_ids'):
        return []
    people = STORE.people.get(uid, {})
    return [dict(people[p]) for p in person_ids if p in people]


def get_person(uid: str, person_id: str, include_speech_samples: bool = False):
    p = STORE.people.get(uid, {}).get(person_id)
    return dict(p) if p else None


def get_person_by_name(uid: str, name: str):
    for p in STORE.people.get(uid, {}).values():
        if p['name'].casefold() == (name or '').casefold():
            return dict(p)
    return None


def get_people(uid: str):
    return [dict(p) for p in STORE.people.get(uid, {}).values()]


def get_user_language_preference(uid: str):
    return STORE.users.get(uid, {}).get('language', 'en')


def get_user_location_context_consent(uid: str):
    return False


def get_user_valid_subscription(uid: str, *args, **kwargs):
    return {'plan': 'operator', 'status': 'active'}


def get_user_profile(uid: str):
    return dict(STORE.users.get(uid, {}))


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
