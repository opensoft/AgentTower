"""FEAT-010 routing-worker heartbeat (spec §FR-039a + Clarifications Q3).

Separate daemon thread that emits one ``routing_worker_heartbeat``
JSONL entry every ``interval_seconds`` regardless of routing cycle
activity. Decoupled from the routing worker so:

1. A long routing cycle (e.g., draining a 100-event backlog) never
   delays the heartbeat.
2. A slow JSONL write (degraded filesystem) never delays the routing
   cycle.

Per FR-039a, the first heartbeat fires ONE FULL INTERVAL after the
thread enters its loop — no startup beacon. Counters reset to zero
immediately after the snapshot under the shared lock.

The ``degraded`` field on each emission is the canonical JSONL-side
mirror of ``_SharedRoutingState.routing_worker_degraded`` (per
data-model.md §4) — JSONL consumers can detect worker degradation
without polling ``agenttower status``.

All thread safety lives on the shared :class:`_SharedRoutingState`'s
lock (mutation happens in the worker; snapshot-and-reset happens
here). The lock is held only during the brief snapshot+reset window,
NOT during the JSONL write — a slow disk does not stall the worker.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Final, Protocol

from agenttower.routing.timestamps import Clock, SystemClock

_log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Bounds (data-model.md §7)
# ──────────────────────────────────────────────────────────────────────


DEFAULT_HEARTBEAT_INTERVAL_S: Final[int] = 60
_HEARTBEAT_INTERVAL_BOUNDS: Final[tuple[int, int]] = (10, 3600)


# ──────────────────────────────────────────────────────────────────────
# Protocol-typed dependencies
# ──────────────────────────────────────────────────────────────────────


class _SharedStateProtocol(Protocol):
    """The read-and-reset surface of ``worker._SharedRoutingState``
    that this module consumes. Defined as a Protocol so unit tests
    can pass a thin in-memory fake.
    """

    cycles_since_last_heartbeat: int
    events_consumed_since_last_heartbeat: int
    skips_since_last_heartbeat: int
    routing_worker_degraded: bool
    lock: threading.Lock


class _AuditEmitter(Protocol):
    """The single emit method consumed here."""

    def emit_routing_worker_heartbeat(
        self,
        events_file: Path,
        *,
        interval_seconds: int,
        cycles_since_last_heartbeat: int,
        events_consumed_since_last_heartbeat: int,
        skips_since_last_heartbeat: int,
        degraded: bool,
    ) -> None: ...


# ──────────────────────────────────────────────────────────────────────
# HeartbeatEmitter
# ──────────────────────────────────────────────────────────────────────


class HeartbeatEmitter:
    """Single-thread heartbeat loop.

    Construction wires every dependency; :meth:`run` is the loop body
    invoked on a daemon thread by ``daemon_adapters.RoutingWorkerThread``.

    Lifecycle:

    - ``run()`` enters a wait-emit cycle until ``shutdown_event`` is set.
    - First emission fires ONE FULL INTERVAL after thread start
      (FR-039a: no startup beacon).
    - On shutdown, NO final heartbeat is emitted (per plan §Implementation
      Invariants §2) — the next daemon start emits its first heartbeat
      one full interval into its lifetime.
    - The thread exits cleanly when ``shutdown_event`` is set; the
      ``run()`` method returns when the event fires during the wait.
    """

    def __init__(
        self,
        *,
        audit_emitter: _AuditEmitter,
        shared_state: _SharedStateProtocol,
        events_file: Path,
        shutdown_event: threading.Event,
        clock: Clock | None = None,
        interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_S,
    ) -> None:
        if not (
            _HEARTBEAT_INTERVAL_BOUNDS[0]
            <= interval_seconds
            <= _HEARTBEAT_INTERVAL_BOUNDS[1]
        ):
            raise ValueError(
                f"interval_seconds {interval_seconds} out of bounds "
                f"{_HEARTBEAT_INTERVAL_BOUNDS}"
            )
        self._audit = audit_emitter
        self._state = shared_state
        self._events_file = events_file
        self._shutdown_event = shutdown_event
        self._clock = clock if clock is not None else SystemClock()
        self._interval_seconds = int(interval_seconds)

    def run(self) -> None:
        """Loop until shutdown: wait one interval, snapshot+reset
        counters under lock, emit one JSONL entry.

        Uses ``threading.Event.wait(timeout)`` for the inter-emission
        sleep so a shutdown signal mid-interval breaks the loop
        without waiting out the full interval.
        """
        while True:
            # FR-039a: first heartbeat is ONE FULL INTERVAL after
            # thread start — no startup beacon. event.wait returns
            # True iff shutdown_event was set during the wait, which
            # short-circuits BEFORE the emission so the shutdown
            # interval doesn't produce a partial-counter heartbeat
            # (plan §Implementation Invariants §2).
            shutdown_during_wait = self._shutdown_event.wait(
                self._interval_seconds,
            )
            if shutdown_during_wait:
                return

            # Snapshot + reset under the shared lock. Held briefly so
            # the worker's per-event counter increments don't stall.
            with self._state.lock:
                cycles = self._state.cycles_since_last_heartbeat
                events_consumed = self._state.events_consumed_since_last_heartbeat
                skips = self._state.skips_since_last_heartbeat
                degraded = self._state.routing_worker_degraded
                # Reset counters AFTER the snapshot so we don't lose
                # increments that arrived between snapshot and reset.
                self._state.cycles_since_last_heartbeat = 0
                self._state.events_consumed_since_last_heartbeat = 0
                self._state.skips_since_last_heartbeat = 0

            # Emit OUTSIDE the lock — a slow JSONL write must not
            # stall the worker (plan §1 / research §R12).
            try:
                self._audit.emit_routing_worker_heartbeat(
                    self._events_file,
                    interval_seconds=self._interval_seconds,
                    cycles_since_last_heartbeat=cycles,
                    events_consumed_since_last_heartbeat=events_consumed,
                    skips_since_last_heartbeat=skips,
                    degraded=degraded,
                )
            except Exception:  # pragma: no cover — defensive
                _log.exception("heartbeat emission raised unexpectedly")
