"""FEAT-011 in-memory scan registry (FR-030b, FR-030c, FR-030d, FR-030e).

A small store holding the **last 100** scan records issued by
``app.scan.containers`` / ``app.scan.panes``. Each record is keyed by a
fresh ``scan_id`` (uuid v4 hex) and goes through ``running →
{completed, failed}``. Records are evicted FIFO at the 100-record cap;
a subsequent ``app.scan.status`` for an evicted ``scan_id`` returns
``scan_not_found``.

Three contract rules are enforced here, not in the per-scan handlers:

* **FR-030c**: scan-state closed set is exactly ``{running, completed,
  failed}`` at v1.0. ``expired`` is intentionally absent.
* **FR-030d** (Round-4 Block D Q24): two concurrent scans of the same
  ``scan_kind`` MUST coalesce on the existing in-flight scan. The
  second caller MUST receive the in-flight ``scan_id`` (not a fresh
  one).
* **FR-030e** (Round-4 Block D Q25): at most **4** in-flight scans
  process-wide across all sessions. The 5th attempt MUST be rejected.

The handlers in this module (T036–T038) wrap the existing FEAT-003 /
FEAT-004 scan workers; the registry's job is purely lifecycle
bookkeeping plus the two normative gates above.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Final


MAX_RECORDS: Final[int] = 100
"""FR-030c: FIFO cap on retained scan records per daemon process."""

MAX_IN_FLIGHT: Final[int] = 4
"""FR-030e: hard cap on concurrent in-flight scans across all sessions."""

# Closed set per FR-030c — ``expired`` intentionally absent at v1.0.
STATE_RUNNING: Final[str] = "running"
STATE_COMPLETED: Final[str] = "completed"
STATE_FAILED: Final[str] = "failed"

# Closed set per FR-030c / app-methods.md.
KIND_CONTAINERS: Final[str] = "containers"
KIND_PANES: Final[str] = "panes"
_VALID_KINDS = frozenset({KIND_CONTAINERS, KIND_PANES})


class ScanCapExceeded(Exception):
    """Raised by ``ScanRegistry.start()`` when ``MAX_IN_FLIGHT`` scans are
    already running (FR-030e). The handler translates this to
    ``validation_failed.details = {field: "scan_kind", reason:
    "too_many_scans_in_flight"}``.
    """


@dataclass
class ScanRecord:
    """One row in the registry. Mirrors the ``app.scan.status`` response
    fields (FR-030c) plus an event for coalescing waiters.
    """

    scan_id: str
    scan_kind: str
    state: str
    started_at_ms: int
    issued_by_app_session_id: int
    completed_at_ms: int | None = None
    result: dict[str, Any] | None = None
    # threading.Event signalled when state transitions out of running.
    # Used by ``wait=true`` callers and same-kind coalescing waiters.
    done: threading.Event = field(default_factory=threading.Event)


class ScanRegistry:
    """Thread-safe scan lifecycle table.

    Bounded at ``MAX_RECORDS`` (FIFO eviction). Enforces
    ``MAX_IN_FLIGHT`` and same-kind coalescing on ``start()``.
    """

    def __init__(
        self,
        *,
        max_records: int = MAX_RECORDS,
        max_in_flight: int = MAX_IN_FLIGHT,
    ) -> None:
        self._max_records = max_records
        self._max_in_flight = max_in_flight
        self._lock = threading.Lock()
        self._records: OrderedDict[str, ScanRecord] = OrderedDict()

    # ── start / coalesce ──────────────────────────────────────────────

    def start(
        self,
        *,
        scan_kind: str,
        issued_by_app_session_id: int,
    ) -> tuple[ScanRecord, bool]:
        """Create or coalesce a scan record.

        Returns ``(record, was_coalesced)``. When ``was_coalesced`` is
        True, the caller MUST NOT trigger the underlying scan worker —
        another caller is already running it; the caller should just
        wait on ``record.done`` (for ``wait=true``) or return the
        running record (for ``wait=false``).

        Raises ``ScanCapExceeded`` when no in-flight slot is available
        and no same-kind coalesce target exists.

        Raises ``ValueError`` when ``scan_kind`` is not in the closed
        set ``{containers, panes}``.
        """
        if scan_kind not in _VALID_KINDS:
            raise ValueError(
                f"scan_kind must be in {sorted(_VALID_KINDS)}, got {scan_kind!r}"
            )
        with self._lock:
            # FR-030d: same-kind coalescing. If any record with this
            # kind is still running, return it.
            for existing in self._records.values():
                if existing.scan_kind == scan_kind and existing.state == STATE_RUNNING:
                    return existing, True

            # FR-030e: in-flight cap.
            in_flight = sum(
                1 for r in self._records.values() if r.state == STATE_RUNNING
            )
            if in_flight >= self._max_in_flight:
                raise ScanCapExceeded(
                    f"in-flight scan cap reached "
                    f"({self._max_in_flight} concurrent scans across all kinds)"
                )

            # FR-030c: new record in running state.
            record = ScanRecord(
                scan_id=uuid.uuid4().hex,
                scan_kind=scan_kind,
                state=STATE_RUNNING,
                started_at_ms=int(time.time() * 1000),
                issued_by_app_session_id=issued_by_app_session_id,
            )
            self._records[record.scan_id] = record
            self._evict_if_over_cap()
            return record, False

    # ── state transitions ─────────────────────────────────────────────

    def complete(self, scan_id: str, result: dict[str, Any]) -> ScanRecord | None:
        """Mark a record completed and store the result.

        Returns the updated record, or ``None`` if the id is unknown
        (e.g., already evicted — shouldn't happen for a record the
        caller just created, but tolerate it).
        """
        with self._lock:
            record = self._records.get(scan_id)
            if record is None:
                return None
            record.state = STATE_COMPLETED
            record.completed_at_ms = int(time.time() * 1000)
            record.result = result
        # Signal outside the registry lock so coalescing waiters don't
        # contend with future start() calls during their wake-up path.
        record.done.set()
        return record

    def fail(self, scan_id: str, error: dict[str, Any]) -> ScanRecord | None:
        """Mark a record failed and store the error payload as the result.

        ``error`` should be a dict; the wait=true response shape carries
        the error as the ``result`` field per FR-030c when state is
        ``failed`` (the underlying summary slot is reused).
        """
        with self._lock:
            record = self._records.get(scan_id)
            if record is None:
                return None
            record.state = STATE_FAILED
            record.completed_at_ms = int(time.time() * 1000)
            record.result = error
        record.done.set()
        return record

    # ── lookup ────────────────────────────────────────────────────────

    def lookup(self, scan_id: str) -> ScanRecord | None:
        """Return the record for ``scan_id`` or ``None`` if unknown / evicted."""
        with self._lock:
            return self._records.get(scan_id)

    def size(self) -> int:
        """Current number of records held (running + terminal)."""
        with self._lock:
            return len(self._records)

    def in_flight_count(self) -> int:
        """Number of records currently in the ``running`` state."""
        with self._lock:
            return sum(
                1 for r in self._records.values() if r.state == STATE_RUNNING
            )

    def clear(self) -> None:
        """Drop all records. Test seam — production never calls this."""
        with self._lock:
            for r in self._records.values():
                r.done.set()
            self._records.clear()

    # ── internals ─────────────────────────────────────────────────────

    def _evict_if_over_cap(self) -> None:
        """FR-030c: keep at most ``MAX_RECORDS`` records; FIFO eviction.

        Caller MUST hold ``self._lock``. Eviction policy:

        * Prefer evicting the **oldest terminal** record (state in
          ``{completed, failed}``). This is the common case at v1.0:
          terminal records vastly outnumber in-flight ones (cap 4
          in-flight + retain 100 terminals).
        * Fall back to evicting the **oldest** record (which may be
          running) only if every record is in-flight — vanishingly
          unlikely with the 4-in-flight cap but possible in
          pathological test fixtures.

        When a running record IS evicted, we signal ``record.done`` to
        wake any blocked waiters so they observe ``scan_not_found`` on
        the subsequent registry lookup rather than blocking forever.
        """
        while len(self._records) > self._max_records:
            # First pass: find the oldest terminal record.
            terminal_scan_id: str | None = None
            for sid, rec in self._records.items():
                if rec.state in (STATE_COMPLETED, STATE_FAILED):
                    terminal_scan_id = sid
                    break
            if terminal_scan_id is not None:
                self._records.pop(terminal_scan_id, None)
                continue
            # All records still running — fall back to oldest-first and
            # signal the evicted record's done event so waiters wake.
            oldest_id, oldest = self._records.popitem(last=False)
            oldest.done.set()


# ─── Module-level singleton ─────────────────────────────────────────────

_REGISTRY: ScanRegistry = ScanRegistry()


def get_registry() -> ScanRegistry:
    return _REGISTRY


def set_registry(registry: ScanRegistry) -> None:
    """Test seam — replace the module-level registry."""
    global _REGISTRY
    _REGISTRY = registry


__all__ = [
    "MAX_RECORDS",
    "MAX_IN_FLIGHT",
    "STATE_RUNNING",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "KIND_CONTAINERS",
    "KIND_PANES",
    "ScanCapExceeded",
    "ScanRecord",
    "ScanRegistry",
    "get_registry",
    "set_registry",
]
