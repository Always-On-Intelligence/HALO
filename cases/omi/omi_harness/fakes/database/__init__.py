"""Fake `database` package: Firestore, Pinecone and Redis access replaced by omi_harness.store.STORE.

Submodules with a file here are fakes. database/document_ids.py is vendored unchanged (pure hashing).
Any other database submodule a vendored module imports is an inert stub (see omi_harness/loader.py).
"""
