"""Per-key advisory mutex registries (FR-038 / FR-039; research R-005).

Two thread-safe per-key registries:

* :class:`RegisterLockMap` — keyed by the FEAT-004 pane composite key
  tuple. Serializes ``register_agent`` requests addressing the same
  pane. FEAT-004 reconciliation MUST NOT acquire it (Clarifications
  session 2026-05-07-continued Q4); cross-subsystem ordering with
  ``register_agent`` is provided exclusively by SQLite ``BEGIN
  IMMEDIATE`` semantics.

* :class:`AgentLockMap` — keyed by ``agent_id``. Serializes
  ``set_role`` / ``set_label`` / ``set_capability`` calls addressing
  the same agent.

Concurrent calls addressing distinct keys / agent_ids proceed in
parallel. No LRU eviction at MVP scale; entries live for the daemon
process lifetime (memory overhead bounded by MVP agent count).
"""

from __future__ import annotations

import threading
from typing import Generic, Hashable, TypeVar


_KeyT = TypeVar("_KeyT", bound=Hashable)


class _PerKeyLockMap(Generic[_KeyT]):
    """Internal helper: thread-safe ``key → threading.Lock`` map."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[_KeyT, threading.Lock] = {}

    def for_key(self, key: _KeyT) -> threading.Lock:
        """Return the per-key lock, creating it under :attr:`_guard` if absent."""
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def known_keys(self) -> list[_KeyT]:
        """Return a snapshot of the current key set (test/diagnostic use)."""
        with self._guard:
            return list(self._locks.keys())


# FEAT-004 pane composite key tuple shape: (container_id, tmux_socket_path,
# tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id).
PaneCompositeKey = tuple[str, str, str, int, int, str]


class RegisterLockMap(_PerKeyLockMap[PaneCompositeKey]):
    """Per-(container_id, pane composite key) mutex registry (FR-038)."""


class AgentLockMap(_PerKeyLockMap[str]):
    """Per-``agent_id`` mutex registry (FR-039)."""
