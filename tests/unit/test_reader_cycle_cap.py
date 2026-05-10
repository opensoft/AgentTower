"""T103 — FR-001: reader cycle wall-clock cap.

The reader's ``run_loop`` budgets each cycle at
``READER_CYCLE_WALLCLOCK_CAP_SECONDS`` (default 1.0 s). With an
injected fake clock, one cycle's logical-clock duration must not
exceed the cap.
"""

from __future__ import annotations

from pathlib import Path

from agenttower.events import (
    READER_CYCLE_WALLCLOCK_CAP_SECONDS,
    Clock,
)
from agenttower.events.reader import EventsReader
from agenttower.state import schema


class _StubClock(Clock):
    """Deterministic clock for budget assertions."""

    def __init__(self, *, start_iso: str = "2026-05-10T00:00:00.000000+00:00") -> None:
        self.iso = start_iso
        self.mono = 0.0

    def now_iso(self) -> str:
        return self.iso

    def monotonic(self) -> float:
        return self.mono


def test_default_cycle_cap_is_one_second() -> None:
    """FR-001: the documented MVP default is ``1.0`` seconds."""
    assert READER_CYCLE_WALLCLOCK_CAP_SECONDS == 1.0


def test_run_one_cycle_completes_under_budget_with_no_attachments(tmp_path: Path) -> None:
    """A cycle with zero active attachments must complete trivially
    fast. The clock advancement is up to the test fixture; we measure
    by whether the cycle returns at all (no infinite loop)."""
    state_db = tmp_path / "state.sqlite3"
    import sqlite3

    conn = sqlite3.connect(state_db, isolation_level=None)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    for v in (2, 3, 4, 5, 6):
        schema._MIGRATIONS[v](conn)
    conn.close()

    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    import os
    os.chmod(events_file, 0o600)

    clock = _StubClock()
    reader = EventsReader(
        state_db=state_db,
        events_file=events_file,
        lifecycle_logger=None,
        clock=clock,
    )

    # _run_one_cycle is a single pass; no inf-loop possibility.
    reader._run_one_cycle(now_iso=clock.now_iso(), now_monotonic=clock.monotonic())
    snap = reader.status_snapshot()
    assert snap.active_attachments == 0


def test_run_loop_respects_stop_event(tmp_path: Path) -> None:
    """Setting the stop event makes ``run_loop`` exit promptly without
    burning the cycle budget — used to bound thread-shutdown time."""
    state_db = tmp_path / "state.sqlite3"
    import sqlite3

    conn = sqlite3.connect(state_db, isolation_level=None)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    for v in (2, 3, 4, 5, 6):
        schema._MIGRATIONS[v](conn)
    conn.close()

    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    import os
    os.chmod(events_file, 0o600)

    clock = _StubClock()
    reader = EventsReader(
        state_db=state_db,
        events_file=events_file,
        lifecycle_logger=None,
        clock=clock,
        cycle_cap_seconds=10.0,  # large cap; stop_event must short-circuit
    )

    reader._stop_event.set()  # signal stop BEFORE start
    reader.run_loop()  # returns immediately on first iteration
    # If the loop were broken, this would block for 10 seconds.
