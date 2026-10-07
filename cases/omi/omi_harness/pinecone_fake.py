"""In-memory stand-in for the Pinecone index used by backend/database/vector_db.py (vendored unchanged).

database/vector_db.py keeps all of its own logic (ids, metadata, filters, thresholds, ranking);
only its module-level ``index`` handle is replaced by FakeIndex. Scores are cosine similarity of
all-MiniLM-L6-v2 embeddings.

Cut sites at this boundary, by namespace (ns1 = conversation summaries, ns4 = tasks):
  S->M  ns1 upsert: a processed conversation is not indexed
  A->M  ns4 upsert: a created task is not indexed
  A->S  ns4 query during Sensing: open tasks do not reach transcript extraction
  M->A  ns1/ns4 query during Action: stored conversations and tasks are not retrieved
"""
from __future__ import annotations

import sys
import types

from omi_harness.store import STORE, cosine

CONVERSATIONS_NS, ACTION_ITEMS_NS = 'ns1', 'ns4'


def install_pinecone_module():
    """vector_db.py does `from pinecone import Pinecone`; it is only constructed with an API key."""
    if 'pinecone' not in sys.modules:
        mod = types.ModuleType('pinecone')

        class Pinecone:   # never constructed: PINECONE_API_KEY is unset in the run
            def __init__(self, *a, **k):
                raise RuntimeError('Pinecone client is replaced by omi_harness.pinecone_fake.FakeIndex')

        mod.Pinecone = Pinecone
        sys.modules['pinecone'] = mod


def _match_value(value, cond) -> bool:
    if isinstance(cond, dict):
        for op, arg in cond.items():
            vals = value if isinstance(value, list) else [value]
            if op == '$eq' and not any(v == arg for v in vals):
                return False
            if op == '$ne' and any(v == arg for v in vals):
                return False
            if op == '$in' and not any(v in arg for v in vals):
                return False
            if op == '$nin' and any(v in arg for v in vals):
                return False
            if op in ('$gt', '$gte', '$lt', '$lte'):
                if value is None or isinstance(value, list):
                    return False
                if op == '$gt' and not value > arg:
                    return False
                if op == '$gte' and not value >= arg:
                    return False
                if op == '$lt' and not value < arg:
                    return False
                if op == '$lte' and not value <= arg:
                    return False
            if op == '$exists' and (value is not None) != bool(arg):
                return False
        return True
    vals = value if isinstance(value, list) else [value]
    return cond in vals


def _matches(metadata: dict, flt) -> bool:
    if not flt:
        return True
    for key, cond in flt.items():
        if key == '$and':
            if not all(_matches(metadata, c) for c in cond):
                return False
        elif key == '$or':
            if not any(_matches(metadata, c) for c in cond):
                return False
        elif not _match_value(metadata.get(key), cond):
            return False
    return True


def _score(query, stored) -> float:
    """Cosine similarity; a long (windowed) query scores by its best sentence window (llm_bridge.WindowedQuery)."""
    if query is None:
        return 0.0
    windows = getattr(query, 'windows', None)
    if windows:
        return max(cosine(w, stored) for w in windows)
    return cosine(query, stored)


class FakeIndex:
    def upsert(self, vectors, namespace: str = ''):
        if namespace == CONVERSATIONS_NS and STORE.cut_active('S->M', 'pinecone.upsert[ns1]'):
            return {'upserted_count': 0}
        if namespace == ACTION_ITEMS_NS and STORE.cut_active('A->M', 'pinecone.upsert[ns4]'):
            return {'upserted_count': 0}
        ns = STORE.vectors[namespace]
        for v in vectors:
            ns[v['id']] = (list(v['values']), dict(v.get('metadata') or {}))
        return {'upserted_count': len(vectors)}

    def query(self, vector=None, top_k: int = 10, filter=None, namespace: str = '', include_metadata: bool = False,
              include_values: bool = False, **kwargs):
        withheld = False
        if STORE.phase == 'sensing' and namespace == ACTION_ITEMS_NS:
            withheld = STORE.cut_active('A->S', 'pinecone.query[ns4] during sensing')
        elif STORE.reading_for_action() and namespace in (CONVERSATIONS_NS, ACTION_ITEMS_NS):
            withheld = STORE.cut_active('M->A', f'pinecone.query[{namespace}] during action')
        if withheld:
            return {'matches': [], 'namespace': namespace}
        rows = [(vid, vals, md) for vid, (vals, md) in STORE.vectors[namespace].items() if _matches(md, filter)]
        scored = sorted(((_score(vector, vals), vid, vals, md) for vid, vals, md in rows), key=lambda x: (-x[0], x[1]))
        matches = []
        for score, vid, vals, md in scored[:top_k]:
            m = {'id': vid, 'score': score}
            if include_metadata:
                m['metadata'] = dict(md)
            if include_values:
                m['values'] = list(vals)
            matches.append(m)
        return {'matches': matches, 'namespace': namespace}

    def update(self, id, set_metadata=None, namespace: str = '', **kwargs):
        row = STORE.vectors[namespace].get(id)
        if row and set_metadata:
            row[1].update(set_metadata)
        return {}

    def delete(self, ids=None, filter=None, namespace: str = '', delete_all: bool = False, **kwargs):
        ns = STORE.vectors[namespace]
        if delete_all:
            ns.clear()
        for vid in ids or []:
            ns.pop(vid, None)
        if filter:
            for vid in [k for k, (_, md) in ns.items() if _matches(md, filter)]:
                ns.pop(vid, None)
        return {}

    def fetch(self, ids, namespace: str = '', **kwargs):
        ns = STORE.vectors[namespace]
        return {'vectors': {i: {'id': i, 'values': ns[i][0], 'metadata': ns[i][1]} for i in ids if i in ns}}


INDEX = FakeIndex()
