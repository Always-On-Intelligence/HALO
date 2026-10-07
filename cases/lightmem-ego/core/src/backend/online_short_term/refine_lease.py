from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TextIO

from online_preprocess.io_utils import utc_now_iso


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return default


@dataclass
class RefineEventLease:
    event_id: str
    owner: str
    path: Path
    handle: TextIO
    acquired_at: str


def _lease_path(session_dir: Path, event_id: str) -> Path:
    digest = hashlib.sha256(str(event_id).encode("utf-8")).hexdigest()
    return Path(session_dir) / "short_term" / "refine" / "event_leases" / f"{digest}.lock"


def _write_lease_diagnostics(handle: TextIO, payload: dict[str, object]) -> None:
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(payload, ensure_ascii=False, default=str))
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except OSError:
        pass


@contextmanager
def acquire_refine_event_lease(
    session_dir: Path,
    event_id: str,
    *,
    owner: str | None = None,
    wait_seconds: float | None = None,
    poll_seconds: float | None = None,
) -> Iterator[RefineEventLease | None]:
    """Acquire a cross-process exclusive lease for one M_st event.

    The kernel releases ``flock`` automatically if a worker exits or crashes, so
    stale lease files do not block future refinement. The file contents are only
    diagnostic metadata; lock ownership is determined exclusively by ``flock``.
    """

    event_id = str(event_id or "").strip()
    if not event_id:
        yield None
        return

    wait_seconds = (
        _env_float("EM2MEM_MST_REFINE_LEASE_WAIT_SECONDS", 2.0)
        if wait_seconds is None
        else max(0.0, float(wait_seconds))
    )
    poll_seconds = (
        _env_float("EM2MEM_MST_REFINE_LEASE_POLL_SECONDS", 0.1)
        if poll_seconds is None
        else max(0.01, float(poll_seconds))
    )
    owner = str(owner or f"pid-{os.getpid()}-thread-{threading.get_ident()}")
    path = _lease_path(Path(session_dir), event_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    deadline = time.monotonic() + wait_seconds
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))

        if not acquired:
            yield None
            return

        acquired_at = utc_now_iso()
        _write_lease_diagnostics(
            handle,
            {
                "status": "acquired",
                "event_id": event_id,
                "owner": owner,
                "pid": os.getpid(),
                "thread_id": threading.get_ident(),
                "acquired_at": acquired_at,
            },
        )
        yield RefineEventLease(
            event_id=event_id,
            owner=owner,
            path=path,
            handle=handle,
            acquired_at=acquired_at,
        )
    finally:
        if acquired:
            try:
                _write_lease_diagnostics(
                    handle,
                    {
                        "status": "released",
                        "event_id": event_id,
                        "owner": owner,
                        "pid": os.getpid(),
                        "thread_id": threading.get_ident(),
                        "released_at": utc_now_iso(),
                    },
                )
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
