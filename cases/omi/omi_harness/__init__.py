"""Harness that runs Omi's vendored backend modules (core/backend) outside their deployment.

loader.py        import hook: vendored modules from core/, fakes from fakes/, inert stubs otherwise;
                 simulated clock and deterministic uuid4 inside vendored modules
llm_bridge.py    LangChain chat model and embeddings that route to the HALO backbone / MiniLM
store.py         in-memory state behind the fakes (Firestore, Pinecone, Typesense, Redis stand-ins)
pinecone_fake.py the Pinecone index handle used by the vendored database/vector_db.py
typesense_fake.py the Typesense client used by the vendored utils/conversations/search.py
fakes/           same-named replacements of upstream modules (storage, model clients, delivery, executors)
"""
