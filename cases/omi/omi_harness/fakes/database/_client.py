"""Fake of backend/database/_client.py: no Firestore client exists in the run."""
from database.document_ids import document_id_from_seed  # vendored unchanged

db = None
data_plane_db = None


def get_firestore_client():
    return None


def get_customer_firestore_client():
    return None


def get_data_plane_firestore_client():
    return None


from omi_harness.fakes._base import missing
__getattr__ = missing(__name__)
