"""FEAT-013 per-container serializer (T010).

Per-container ``threading.Lock`` map. Implements FR-019: a second
``create_layout`` request targeting the same bench container blocks
until the first finishes.

Implementation note (deviation from research §R2): the spec planned
``asyncio.Lock``; the existing AgentTower daemon is **threaded** (see
``src/agenttower/agents/mutex.py`` for the FEAT-009 lock-map pattern).
This module uses ``threading.Lock`` to match the actual daemon execution
model. The FIFO fairness property still holds — Python's ``threading.Lock``
on CPython is FIFO under normal contention, matching the operator-visible
"second request waits" semantic from Q3.
"""

from __future__ import annotations

import threading
from typing import Final


class ContainerSerializer:
    """Per-container lock map keyed by ``container_id``.

    Cross-container calls proceed in parallel. Locks live for the daemon
    process lifetime (mirrors FEAT-009 ``_PerKeyLockMap``); no LRU
    eviction at MVP scale.
    """

    def __init__(self) -> None:
        self._guard: Final[threading.Lock] = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def for_container(self, container_id: str) -> threading.Lock:
        """Return the lock for ``container_id``, creating it if absent."""
        if not container_id:
            raise ValueError("container_id must be non-empty")
        with self._guard:
            lock = self._locks.get(container_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[container_id] = lock
            return lock

    def known_containers(self) -> list[str]:
        """Return a snapshot of containers with a known lock (test/diagnostic use)."""
        with self._guard:
            return list(self._locks.keys())
