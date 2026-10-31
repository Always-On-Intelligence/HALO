"""The ledger: an append-only SQLite file of the events agents log through the HALO plugin.

It stays on the machine that runs the server (by default ~/.halo/ledger.sqlite). Events are never
edited or deleted by the server, so a report can always be traced back to what the agent logged.
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from halo.mcp.analysis import KINDS

FIELDS = ['trigger', 'form', 'about', 'target', 'made_by', 'governance']
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    agent      TEXT NOT NULL,
    session    TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL,
    summary    TEXT NOT NULL,
    uses       TEXT NOT NULL DEFAULT '[]',
    trigger    TEXT, form TEXT, about TEXT, target TEXT, made_by TEXT, governance TEXT,
    client     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_agent ON events (agent, seq);
"""


class LedgerError(ValueError):
    """A logged event that cannot be stored as given; the message says how to fix it."""


class Ledger:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def add(self, agent, kind, summary, uses=(), session='', client='', **extra):
        if kind not in KINDS:
            raise LedgerError(f'unknown kind {kind!r}')
        summary = ' '.join((summary or '').split())
        if not summary:
            raise LedgerError('summary is empty: say in a few words what happened')
        uses = list(dict.fromkeys(uses or []))
        with self._lock:
            known = self._known(agent, uses + [extra.get('about')] if extra.get('about') else uses)
            missing = [u for u in uses if u not in known]
            if missing:
                raise LedgerError(f'unknown event id(s) {", ".join(missing)} for agent {agent!r}; '
                                  'call halo_trace to see the ids of your earlier events')
            if extra.get('about') and known.get(extra['about']) != 'act':
                raise LedgerError(f'about must be the id of one of your earlier act events, not {extra["about"]!r}')
            ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
            row = {k: extra.get(k) for k in FIELDS}
            cur = self._db.execute(
                'INSERT INTO events (ts, agent, session, kind, summary, uses, client, trigger, form, about, target, made_by, governance) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (ts, agent, session or '', kind, summary, json.dumps(uses), client or '', *[row[k] for k in FIELDS]))
            self._db.commit()
            return self._event(self._db.execute('SELECT * FROM events WHERE seq = ?', (cur.lastrowid,)).fetchone())

    def _known(self, agent, ids):
        seqs = [int(i[1:]) for i in ids if isinstance(i, str) and i[:1] == 'e' and i[1:].isdigit()]
        if not seqs:
            return {}
        marks = ','.join('?' * len(seqs))
        rows = self._db.execute(f'SELECT seq, kind FROM events WHERE agent = ? AND seq IN ({marks})', (agent, *seqs))
        return {f'e{r["seq"]}': r['kind'] for r in rows}

    def events(self, agent, session=None, limit=None):
        """The agent's events in order, optionally one session only, optionally only the last `limit`."""
        query, args = 'SELECT * FROM events WHERE agent = ?', [agent]
        if session:
            query, args = query + ' AND session = ?', args + [session]
        rows = [self._event(r) for r in self._db.execute(query + ' ORDER BY seq', args)]
        return rows[-limit:] if limit else rows

    def agents(self):
        return [r['agent'] for r in self._db.execute('SELECT agent, COUNT(*) FROM events GROUP BY agent ORDER BY MIN(seq)')]

    @staticmethod
    def _event(row):
        e = {'id': f'e{row["seq"]}', 'ts': row['ts'], 'agent': row['agent'], 'session': row['session'],
             'kind': row['kind'], 'summary': row['summary'], 'uses': json.loads(row['uses'])}
        e.update({k: row[k] for k in FIELDS if row[k] is not None})
        return e
