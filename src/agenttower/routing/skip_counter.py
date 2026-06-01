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
  ~400 KB worst case (~320 KB for 10_000 distinct large-int millisecond
  timestamps at ~32 B each, plus the ~83 KB deque block array) and
  prevents resource exhaustion from a misbehaving routing worker
  (Research §RB; security.md CHK006).

Lifecycle:

* Insert: drop-oldest on overflow (free property of
  ``deque(maxlen=MAXLEN)``).
* Read: filter ``entry_ms > now_ms - WINDOW_MS`` (strict ``>``; an entry
  at exactly the edge is **excluded** per Research §CW).
* Reset: implicit on daemon process exit. No *production* reset path —
  FR-008 daemon-restart-resets-to-zero is achieved by process restart, not
  by an in-process API (see T010's ``test_construction_returns_zero_count``).
  A test-only ``reset_default()`` (and ``SkipCounter.reset()``) hook exists
  for in-process test isolation (an autouse fixture in ``tests/conftest.py``
  calls it between tests); it is NOT a production mechanism.

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
from threading import Lock
from typing import Final

WINDOW_MS: Final[int] = 300_000
MAXLEN: Final[int] = 10_000


class SkipCounter:
    """Process-local sliding-window counter of FEAT-010 route-skip events.

    Each instance owns a private ``collections.deque(maxlen=MAXLEN)`` of
    monotonic-millisecond integers guarded by a ``threading.Lock``.

    Thread-safety: production callers cross threads — the FEAT-010
    ``RoutingWorkerThread`` calls ``record_skip`` while
    ``ThreadingUnixStreamServer`` request-handler threads call
    ``count_in_window`` for ``app.dashboard``. Both paths take the lock,
    so concurrent ``append`` + snapshot cannot raise
    ``RuntimeError: deque mutated during iteration`` and counts are
    consistent across reads. Critical sections are bounded:
    ``record_skip`` is O(1); the count_in_window snapshot is
    O(min(len, MAXLEN)) and at MAXLEN=10_000 ints is ~400 KB / sub-ms.
    """

    __slots__ = ("_entries", "_lock")

    def __init__(self) -> None:
        self._entries: deque[int] = deque(maxlen=MAXLEN)
        self._lock = Lock()

    def record_skip(self, now_ms: int) -> None:
        """Record a skip event at the given monotonic-millisecond timestamp.

        Drop-oldest semantics when the buffer is at ``MAXLEN`` capacity
        (Research §RB).
        """
        with self._lock:
            self._entries.append(now_ms)

    def count_in_window(self, now_ms: int) -> int:
        """Count entries whose age is strictly less than ``WINDOW_MS``.

        Strict ``>`` filter (Research §CW): an entry recorded at exactly
        ``now_ms - WINDOW_MS`` is **excluded** — the window is a half-open
        interval ``(now_ms - WINDOW_MS, now_ms]``.

        Concurrency: snapshots the deque under ``_lock`` and releases the
        lock before the threshold filter walk, so the writer's
        ``record_skip`` is not blocked on the (length-bounded but
        non-trivial) filter pass.
        """
        threshold = now_ms - WINDOW_MS
        with self._lock:
            entries = list(self._entries)
        # Half-open ``(now_ms - WINDOW_MS, now_ms]``: clamp the upper edge to
        # ``now_ms`` too, so an entry recorded "in the future" relative to
        # this read (a concurrent ``record_skip`` appended just after the
        # caller sampled ``now_ms``) is not counted as in-window.
        return sum(1 for entry_ms in entries if threshold < entry_ms <= now_ms)

    def reset(self) -> None:
        """Drop all recorded entries.

        Test-isolation hook (codex P2): the module-level singleton persists
        across tests in one interpreter, so a routing-worker test that
        records skips would otherwise leak a nonzero
        ``recently_skipped_count`` into a later empty-daemon dashboard test.
        NOT a production API — FR-008 daemon-restart-resets-to-zero is
        achieved by process restart, never an in-process reset call.
        """
        with self._lock:
            self._entries.clear()


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


def reset_default() -> None:
    """Clear the module-level default counter (test-isolation hook).

    The singleton lives for the life of the interpreter, so tests that
    drive the production ``record_skip`` path must reset it between tests
    to avoid cross-test leakage; an autouse fixture in ``tests/conftest.py``
    calls this before every test. NOT a production API (see
    ``SkipCounter.reset``).
    """
    _default_counter.reset()


__all__ = [
    "WINDOW_MS",
    "MAXLEN",
    "SkipCounter",
    "record_skip",
    "count_in_window",
    "reset_default",
]
