"""T033 — FR-002: ``reader_cycle_offset_recovery`` is called exactly
once per cycle BEFORE any byte read.

Uses mocked recovery / read paths to record call ordering; no DB
seeding needed for the ordering invariant.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from agenttower.events.reader import EventsReader
from agenttower.logs.reader_recovery import ReaderCycleResult
from agenttower.state import log_attachments as la_state
from agenttower.state import log_offsets as lo_state
from agenttower.state import schema


def _open_v6(tmp_path: Path) -> sqlite3.Connection:
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = OFF")  # bypass FK for unit isolation
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    for v in (2, 3, 4, 5, 6):
        schema._MIGRATIONS[v](conn)
    return conn


def _make_attachment() -> la_state.LogAttachmentRecord:
    """Synthesize a LogAttachmentRecord without DB insertion."""
    return la_state.LogAttachmentRecord(
        attachment_id="atc_aabbccddeeff",
        agent_id="agt_a1b2c3d4e5f6",
        container_id="c" * 64,
        tmux_socket_path="/tmp/sock",
        tmux_session_name="s",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id="%1",
        log_path="/tmp/agent.log",
        status="active",
        source="explicit",
        pipe_pane_command="cat >> /tmp/agent.log",
        prior_pipe_target=None,
        attached_at="2026-05-10T00:00:00.000000+00:00",
        last_status_at="2026-05-10T00:00:00.000000+00:00",
        superseded_at=None,
        superseded_by=None,
        created_at="2026-05-10T00:00:00.000000+00:00",
    )


def _seed_offset_row(conn: sqlite3.Connection) -> None:
    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path="/tmp/agent.log",
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )


def test_recovery_called_exactly_once_before_byte_read(tmp_path: Path) -> None:
    """FR-002: helper invoked exactly once per cycle, BEFORE byte read."""
    conn = _open_v6(tmp_path)
    _seed_offset_row(conn)

    call_order: list[str] = []

    def _fake_recovery(**kwargs):
        call_order.append("recovery")
        from agenttower.state.log_offsets import FileChangeKind
        return ReaderCycleResult(
            change=FileChangeKind.UNCHANGED,
            state_mutated=False,
            lifecycle_event_emitted=None,
            audit_row_appended=False,
        )

    def _fake_read(self, *args, **kwargs):
        call_order.append("read")
        return b""

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery,
    ), patch(
        "agenttower.events.reader.EventsReader._read_bytes", _fake_read
    ):
        reader.run_cycle_for_attachment(
            conn,
            attachment=_make_attachment(),
            now_iso="2026-05-10T00:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    assert call_order == ["recovery", "read"]


def test_recovery_called_exactly_once_per_cycle(tmp_path: Path) -> None:
    """One ``run_cycle_for_attachment`` call → exactly one
    ``reader_cycle_offset_recovery`` invocation."""
    conn = _open_v6(tmp_path)
    _seed_offset_row(conn)

    call_count = {"n": 0}

    def _fake_recovery(**kwargs):
        call_count["n"] += 1
        from agenttower.state.log_offsets import FileChangeKind
        return ReaderCycleResult(
            change=FileChangeKind.UNCHANGED,
            state_mutated=False,
            lifecycle_event_emitted=None,
            audit_row_appended=False,
        )

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery,
    ), patch(
        "agenttower.events.reader.EventsReader._read_bytes", lambda self, *a, **k: b""
    ):
        reader.run_cycle_for_attachment(
            conn,
            attachment=_make_attachment(),
            now_iso="2026-05-10T00:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    assert call_count["n"] == 1


def test_byte_read_skipped_when_recovery_returns_truncated(tmp_path: Path) -> None:
    """FR-021 / FR-023: when recovery returns TRUNCATED, the reader
    skips byte reads. No event from pre-reset bytes."""
    conn = _open_v6(tmp_path)
    _seed_offset_row(conn)

    read_called = {"n": 0}

    def _fake_recovery(**kwargs):
        from agenttower.state.log_offsets import FileChangeKind
        return ReaderCycleResult(
            change=FileChangeKind.TRUNCATED,
            state_mutated=True,
            lifecycle_event_emitted="log_rotation_detected",
            audit_row_appended=False,
        )

    def _fake_read(self, *args, **kwargs):
        read_called["n"] += 1
        return b""

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery,
    ), patch(
        "agenttower.events.reader.EventsReader._read_bytes", _fake_read
    ):
        reader.run_cycle_for_attachment(
            conn,
            attachment=_make_attachment(),
            now_iso="2026-05-10T00:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    assert read_called["n"] == 0
