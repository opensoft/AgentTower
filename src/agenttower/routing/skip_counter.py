"""FEAT-014 T013 — Process-local ring buffer for FEAT-010 route-skip telemetry.

Implements the ``RecentlySkippedRoutesWindow`` entity from
``data-model.md`` §RecentlySkippedRoutesWindow and the design decisions in
``research.md`` §RB (bounded deque, drop-oldest) and §CW (monotonic-ms
clock, strict ``>`` window-edge filter).

Surfaces a **dual-surface API** (per tasks.md T013 dual-surface contract):

* :class:`SkipCounter` — class for **test isolation** (each test constructs
  its own instance and exercises ``record_skip`` / ``count_in_window``
  against a private buffer; see ``tests/unit/test_skip_counter.py``).
* Module-level :func:`record_skip` / :func:`count_in_window` — convenience
  functions delegating to a single **process-local default instance**.
  Production callers use these:

  - FEAT-010 routing worker (``worker.py::_skip``) calls
    :func:`record_skip` synchronously on each skip decision (FR-008
    Lifecycle).
  - ``app_contract/dashboard.py`` calls :func:`count_in_window` once per
    ``app.dashboard`` request (FR-007).

Module constants:

* :data:`WINDOW_MS` (= ``300_000``) — fixed 5-min sliding window
  (Clarifications Q6; not client-tunable in v1.1 per FR-022).
* :data:`MAXLEN` (= ``10_000``) — deque hard cap; bounds memory at
  ~80 KB worst case and prevents resource exhaustion from a
  misbehaving routing worker (Research §RB; security.md CHK006).

Lifecycle:

* Insert: drop-oldest on overflow (free property of
  ``deque(maxlen=MAXLEN)``).
* Read: filter ``entry_ms > now_ms - WINDOW_MS`` (strict ``>``; an entry
  at exactly the edge is **excluded** per Research §CW).
* Reset: implicit on daemon process exit. No public reset path (FR-008
  daemon-restart-resets-to-zero is achieved by process restart, not by an
  in-process API; see T010's
  ``test_construction_returns_zero_count``).

FR-008 worker-stall decoupling (Clarifications R1 Q2): the counter is
structurally independent of FEAT-010 routing-worker liveness. If
``record_skip`` stops being called (worker stalled or crashed),
:func:`count_in_window` continues to return previously-recorded entries
until they age out via the window filter. The worker's degradation is
surfaced separately by the recommendation engine (US3) as
``subsystem_degraded`` for ``routing_worker``, **not** by the counter
going silently to zero.
"""

from __future__ import annotations

from collections import deque
from typing import Final

WINDOW_MS: Final[int] = 300_000
MAXLEN: Final[int] = 10_000


class SkipCounter:
    """Process-local sliding-window counter of FEAT-010 route-skip events.

    Each instance owns a private ``collections.deque(maxlen=MAXLEN)`` of
    monotonic-millisecond integers. Thread-safety: instance methods are
    NOT internally synchronized; production callers serialize through the
    routing worker's single-threaded cycle (FEAT-010 §R1) and the
    dashboard's per-request lock-free read (FR-018). Tests use private
    instances and run single-threaded.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: deque[int] = deque(maxlen=MAXLEN)

    def record_skip(self, now_ms: int) -> None:
        """Record a skip event at the given monotonic-millisecond timestamp.

        Drop-oldest semantics when the buffer is at ``MAXLEN`` capacity
        (Research §RB).
        """
        self._entries.append(now_ms)

    def count_in_window(self, now_ms: int) -> int:
        """Count entries whose age is strictly less than ``WINDOW_MS``.

        Strict ``>`` filter (Research §CW): an entry recorded at exactly
        ``now_ms - WINDOW_MS`` is **excluded** — the window is a half-open
        interval ``(now_ms - WINDOW_MS, now_ms]``.

        Concurrency note (post-swarm fix per Copilot + Codex P1): we
        snapshot the deque via ``list()`` before iterating. ``list(deque)``
        is a single atomic operation in CPython, immune to the
        ``RuntimeError: deque mutated during iteration`` race that would
        otherwise be possible when the FEAT-010 routing-worker thread
        appends concurrently with a dashboard read. The snapshot is also
        cheap — at MAXLEN=10_000 ints this is ~80 KB per read.
        """
        threshold = now_ms - WINDOW_MS
        entries = list(self._entries)
        return sum(1 for entry_ms in entries if entry_ms > threshold)


# ─── Module-level singleton + convenience functions ─────────────────────────
#
# Production callers (FEAT-010 worker.py, app_contract/dashboard.py) use
# the module-level functions; tests construct private SkipCounter() instances
# for isolation.

_default_counter: Final[SkipCounter] = SkipCounter()


def record_skip(now_ms: int) -> None:
    """Module-level: record a skip on the default singleton.

    Called synchronously by the FEAT-010 routing worker's ``_skip`` method
    on each route-skip decision (per data-model.md
    §RecentlySkippedRoutesWindow §Lifecycle).
    """
    _default_counter.record_skip(now_ms)


def count_in_window(now_ms: int) -> int:
    """Module-level: count entries in window on the default singleton.

    Called once per ``app.dashboard`` request to populate
    ``counts.routes.recently_skipped_count``.
    """
    return _default_counter.count_in_window(now_ms)


__all__ = [
    "WINDOW_MS",
    "MAXLEN",
    "SkipCounter",
    "record_skip",
    "count_in_window",
]
