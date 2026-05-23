"""FEAT-011 per-session idempotency dedupe store (FR-031a).

The ``app.send_input`` handler is the only FEAT-011 mutation that
accepts an ``idempotency_key`` (FR-031a) — clients retry safely after
a network blip without creating duplicate queue rows. The store is:

* **Per-session** — keyed by ``(app_session_id, idempotency_key)`` in
  effect, but practically stored as one ``IdempotencyStore`` instance
  per ``AppSession`` so the lookup is just ``store.lookup(key)``.
* **In-memory only** — no SQLite, no JSONL. Lost on daemon restart or
  on registry eviction of the owning session (FR-008b + FR-031a).
* **Bounded** — 256 entries per session with LRU eviction. A long-lived
  session cannot leak memory.
* **Wall-clock-free** — no TTL; eviction is purely cap-driven.

When ``app.send_input`` is called with an ``idempotency_key``:

1. Look up the key in the store.
2. If present → return the **cached response envelope** with
   ``deduplicated: true`` (the field is added at lookup time, not
   stored, so the original record stays clean).
3. If absent → run the mutation, then ``record(key, message_id, env)``
   where ``env`` is the full success envelope returned to the caller.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Final


MAX_ENTRIES: Final[int] = 256
"""FR-031a: per-session cap on idempotency entries. LRU eviction."""

MAX_KEY_LENGTH: Final[int] = 256
"""FR-031a / data-model.md: idempotency_key max length."""


@dataclass(frozen=True)
class IdempotencyEntry:
    """A recorded ``app.send_input`` outcome ready to replay.

    ``deduplicated_response`` is the success envelope produced by the
    first call. Callers append ``deduplicated: true`` to the result
    payload at replay time; the stored envelope itself stays clean so
    the same record can be replayed any number of times.
    """

    idempotency_key: str
    message_id: str
    deduplicated_response: dict[str, Any]
    created_at_ms: int


class IdempotencyStore:
    """Thread-safe per-session LRU dedupe map.

    Use one instance per ``AppSession``. Lookups O(1); inserts O(1)
    amortized; eviction is LRU at ``MAX_ENTRIES``.
    """

    def __init__(self, *, max_entries: int = MAX_ENTRIES) -> None:
        self._max = max_entries
        self._lock = threading.Lock()
        # OrderedDict gives us LRU semantics: move_to_end on access,
        # popitem(last=False) for eviction.
        self._entries: OrderedDict[str, IdempotencyEntry] = OrderedDict()

    def lookup(self, key: str) -> IdempotencyEntry | None:
        """Return the recorded entry for ``key`` or ``None`` if absent.

        On hit, the entry is marked most-recently-used.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key, last=True)
            return entry

    def record(
        self,
        key: str,
        message_id: str,
        response_envelope: dict[str, Any],
        created_at_ms: int,
    ) -> IdempotencyEntry:
        """Insert a new dedupe record. Evicts the LRU entry if at cap.

        If ``key`` is already present, the existing entry is replaced
        rather than raising.

        Concurrency caveat (review finding): ``app.send_input`` performs
        ``lookup`` → mutate → ``record`` WITHOUT holding a lock across
        the whole sequence — the store's lock guards only the individual
        ``lookup`` / ``record`` calls. Two concurrent calls with the same
        ``(session, key)`` can therefore both miss the lookup and both
        enqueue a real queue row (a check-and-act TOCTOU). The store's
        per-op locking keeps the structure itself consistent; it does NOT
        make the end-to-end dedupe atomic. A per-(session,key) lock held
        across the mutation is the proper fix and is tracked as follow-up.
        """
        entry = IdempotencyEntry(
            idempotency_key=key,
            message_id=message_id,
            deduplicated_response=response_envelope,
            created_at_ms=created_at_ms,
        )
        with self._lock:
            if key in self._entries:
                # Refresh the recency on re-record.
                self._entries.move_to_end(key, last=True)
                self._entries[key] = entry
                return entry
            self._entries[key] = entry
            if len(self._entries) > self._max:
                # LRU eviction.
                self._entries.popitem(last=False)
            return entry

    def size(self) -> int:
        """Current number of stored entries. For tests / diagnostics."""
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        """Drop all entries (e.g., on session invalidation)."""
        with self._lock:
            self._entries.clear()


__all__ = [
    "MAX_ENTRIES",
    "MAX_KEY_LENGTH",
    "IdempotencyEntry",
    "IdempotencyStore",
]
