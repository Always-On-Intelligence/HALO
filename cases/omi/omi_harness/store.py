"""In-memory state that stands in for Firestore, Pinecone and Redis during one run.

Every fake database module reads and writes STORE. The adapter resets it at the start of each
run, seeds the user, and sets ``cut`` and ``phase`` so the fakes can apply the cut sites that live
at a storage boundary (see the adapter docstring for the list).
"""
from __future__ import annotations

import collections
import threading

import numpy as np


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.cut = set()
        # who is reading: 'sensing' (conversation processing), 'action' (mentor, chat) or None
        self.phase = None
        self.users = {}            # uid -> profile dict (name, language, time_zone, mentor_frequency, ...)
        self.people = {}           # uid -> {person_id: person dict}
        self.goals = {}            # uid -> [goal dict]
        self.conversations = {}    # uid -> {conversation_id: dict}
        self.memories = {}         # uid -> {memory_id: MemoryDB}
        self.messages = {}         # uid -> [message dict] (chat and app messages, oldest first)
        self.action_items = {}     # uid -> {action_item_id: dict}
        self.vectors = collections.defaultdict(dict)   # namespace -> {vector_id: (np.ndarray, metadata)}
        self.redis = {}            # key -> value
        self.delivered = []        # notifications delivered to the phone, in order
        self.log = []              # storage events, for the run record
        self.withheld = collections.Counter()   # reads/writes suppressed by a cut, per site

    # ---- helpers used by the fakes -------------------------------------------------------
    def cut_active(self, channel: str, site: str) -> bool:
        if channel in self.cut:
            self.withheld[f'{channel}:{site}'] += 1
            return True
        return False

    def reading_for_action(self) -> bool:
        return self.phase == 'action'

    def note(self, event: str, **data):
        self.log.append({'event': event, **data})


STORE = Store()


def cosine(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(a @ b / (na * nb))
