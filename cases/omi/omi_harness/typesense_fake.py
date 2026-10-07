"""In-memory stand-in for the Typesense client used by backend/utils/conversations/search.py (vendored).

Upstream keeps a Typesense `conversations` collection synced from Firestore and queries it by
keyword over structured.title and structured.overview. Here the collection is STORE.conversations;
a document matches when a query word (two or more letters) starts a word of the title or overview.

M->A cut site: while Action decides (chat tools), the keyword search returns no hits.
"""
from __future__ import annotations

import re
import sys
import types
from datetime import datetime, timezone

from omi_harness.store import STORE

_WORD = re.compile(r'[a-z0-9]+')


def _ts(v):
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace('Z', '+00:00'))
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return int(v.timestamp())
    return int(v or 0)


def _parse_filter(filter_by: str):
    clauses = [c.strip() for c in (filter_by or '').split('&&') if c.strip()]
    out = []
    for c in clauses:
        m = re.match(r'(\w+):(>=|<=|=|>|<)(.+)', c)
        if m:
            out.append((m.group(1), m.group(2), m.group(3).strip()))
    return out


class _Documents:
    def __init__(self, name):
        self.name = name

    def search(self, params):
        if STORE.reading_for_action() and STORE.cut_active('M->A', 'typesense.search during action'):
            return {'hits': [], 'found': 0}
        q = (params.get('q') or '*').strip().lower()
        terms = [t for t in _WORD.findall(q) if len(t) >= 2] if q != '*' else []
        filters = _parse_filter(params.get('filter_by', ''))
        docs = []
        for uid, rows in STORE.conversations.items():
            for row in rows.values():
                structured = row.get('structured') or {}
                doc = {
                    'id': row['id'], 'userId': uid, 'discarded': bool(row.get('discarded')),
                    'created_at': _ts(row.get('created_at')), 'started_at': _ts(row.get('started_at')),
                    'finished_at': _ts(row.get('finished_at')), 'is_locked': bool(row.get('is_locked')),
                    'structured': {k: structured.get(k) for k in ('title', 'overview', 'emoji', 'category')},
                }
                ok = True
                for field, op, value in filters:
                    have = doc.get(field)
                    if field == 'discarded':
                        ok &= have == (value == 'true')
                    elif field == 'userId':
                        ok &= have == value
                    else:
                        v = int(value)
                        ok &= {'=': have == v, '>=': have >= v, '<=': have <= v, '>': have > v, '<': have < v}[op]
                if not ok:
                    continue
                if terms:
                    words = set(_WORD.findall(f"{structured.get('title') or ''} {structured.get('overview') or ''}".lower()))
                    if not any(any(w.startswith(t) for w in words) for t in terms):
                        continue
                docs.append(doc)
        docs.sort(key=lambda d: -d['created_at'])
        per_page, page = int(params.get('per_page', 10)), int(params.get('page', 1))
        page_docs = docs[(page - 1) * per_page: page * per_page]
        return {'hits': [{'document': d} for d in page_docs], 'found': len(docs)}


class _Collection:
    def __init__(self, name):
        self.documents = _Documents(name)


class _Collections(dict):
    def __missing__(self, name):
        return _Collection(name)


class Client:
    def __init__(self, config=None):
        self.collections = _Collections()


def install_typesense_module():
    if 'typesense' not in sys.modules:
        mod = types.ModuleType('typesense')
        mod.Client = Client
        exceptions = types.ModuleType('typesense.exceptions')
        for name in ('TypesenseClientError', 'ServiceUnavailable', 'Timeout', 'RequestMalformed', 'ObjectNotFound',
                     'ServerError', 'HTTPStatus0Error'):
            setattr(exceptions, name, type(name, (Exception,), {}))
        mod.exceptions = exceptions
        sys.modules['typesense'] = mod
        sys.modules['typesense.exceptions'] = exceptions
