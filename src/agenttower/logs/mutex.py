"""FEAT-007 per-``log_path`` mutex registry (FR-041 / FR-059 / Research R-007).

Mirrors the FEAT-006 ``_PerKeyLockMap`` pattern but keys on the canonical
host-side log path. Acquired AFTER the per-``agent_id`` lock from FEAT-006
``agent_locks`` (FR-040 / FR-059); reverse-order acquisition is forbidden
and raises ``internal_error``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from ..agents.mutex import _PerKeyLockMap


class LogPathLockMap(_PerKeyLockMap[str]):
    """Per-``log_path`` mutex registry (FR-041)."""


class MutexOrderViolation(Exception):
    """Raised when callers attempt to acquire ``log_path_locks`` before ``agent_locks`` (FR-059)."""


@contextmanager
def acquire_in_order(
    agent_lock: threading.Lock,
    log_path_lock: threading.Lock | None,
) -> Iterator[None]:
    """Acquire per-agent lock FIRST, then per-log_path lock SECOND (FR-059).

    ``log_path_lock`` may be None when no explicit ``--log`` was supplied
    (FR-005 canonical-path attach uses only the per-agent lock).

    Releases in LIFO order on exit. Reverse-order use is structurally
    impossible because this helper is the only construction site.
    """
    if not agent_lock.acquire(timeout=30.0):
        raise MutexOrderViolation(
            "agent_lock acquire timed out after 30s; refusing to escalate"
        )
    try:
        if log_path_lock is not None:
            if not log_path_lock.acquire(timeout=30.0):
                raise MutexOrderViolation(
                    "log_path_lock acquire timed out after 30s; refusing to escalate"
                )
            try:
                yield
            finally:
                log_path_lock.release()
        else:
            yield
    finally:
        agent_lock.release()
