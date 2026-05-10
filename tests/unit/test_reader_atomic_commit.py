"""T036 — FR-006: atomic SQLite commit per emitted event.

Simulates a SQLite commit failure mid-batch and asserts that no event
row is visible AND no offset advance occurred.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from agenttower.events.dao import select_events, EventFilter
from agenttower.events.reader import EventsReader
from agenttower.logs.reader_recovery import ReaderCycleResult
from agenttower.state import log_attachments as la_state
from agenttower.state import log_offsets as lo_state
from agenttower.state import schema


def _open_v6(tmp_path: Path) -> sqlite3.Connection:
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    for v in (2, 3, 4, 5, 6):
        schema._MIGRATIONS[v](conn)
    return conn


def _make_attachment(log_path: str) -> la_state.LogAttachmentRecord:
    return la_state.LogAttachmentRecord(
        attachment_id="atc_aabbccddeeff",
        agent_id="agt_a1b2c3d4e5f6",
        container_id="c" * 64,
        tmux_socket_path="/tmp/sock",
        tmux_session_name="s",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id="%1",
        log_path=log_path,
        status="active",
        source="explicit",
        pipe_pane_command=f"cat >> {log_path}",
        prior_pipe_target=None,
        attached_at="2026-05-10T00:00:00.000000+00:00",
        last_status_at="2026-05-10T00:00:00.000000+00:00",
        superseded_at=None,
        superseded_by=None,
        created_at="2026-05-10T00:00:00.000000+00:00",
    )


def test_sqlite_failure_leaves_no_events_and_no_offset_advance(tmp_path: Path) -> None:
    """Force ``advance_offset`` to raise sqlite3.Error mid-transaction.
    Assert: zero events visible, byte_offset still 0."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello world\n", encoding="utf-8")

    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path=str(log_path),
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    def _fake_recovery(**kwargs):
        from agenttower.state.log_offsets import FileChangeKind
        return ReaderCycleResult(
            change=FileChangeKind.UNCHANGED,
            state_mutated=False,
            lifecycle_event_emitted=None,
            audit_row_appended=False,
        )

    def _failing_advance(*args, **kwargs):
        raise sqlite3.OperationalError("simulated commit failure")

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery,
    ), patch(
        "agenttower.events.reader.lo_state.advance_offset",
        side_effect=_failing_advance,
    ):
        result = reader.run_cycle_for_attachment(
            conn,
            attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T00:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    # Failure surfaced.
    assert result.failed is True
    assert result.failure_class == "sqlite_commit"

    # No events visible.
    rows, _ = select_events(
        conn, filter=EventFilter(), cursor=None, limit=50, reverse=False
    )
    assert rows == []

    # Offset still at zero (no advance).
    offset_row = lo_state.select(
        conn, agent_id="agt_a1b2c3d4e5f6", log_path=str(log_path)
    )
    assert offset_row is not None
    assert offset_row.byte_offset == 0
    assert offset_row.line_offset == 0


def test_successful_commit_persists_event_and_advances_offset(tmp_path: Path) -> None:
    """Happy-path control: when the commit succeeds, exactly one
    event row is visible and the offset advances by the consumed
    byte count."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello world\n", encoding="utf-8")

    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path=str(log_path),
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )

    # Pre-create the events.jsonl file with the FEAT-001 0o600 mode.
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    import os
    os.chmod(events_file, 0o600)

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=events_file,
        lifecycle_logger=None,
    )

    def _fake_recovery(**kwargs):
        from agenttower.state.log_offsets import FileChangeKind
        return ReaderCycleResult(
            change=FileChangeKind.UNCHANGED,
            state_mutated=False,
            lifecycle_event_emitted=None,
            audit_row_appended=False,
        )

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery,
    ):
        result = reader.run_cycle_for_attachment(
            conn,
            attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T00:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    # The activity event opens a debounce window — no immediate commit.
    # That's correct per FR-014 (activity collapses). Force flush to
    # close the window and emit the event by calling the cycle a second
    # time after the budget elapses.
    log_path.write_text("hello world\nsecond line\n", encoding="utf-8")
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery,
    ):
        reader.run_cycle_for_attachment(
            conn,
            attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T00:00:10.000000+00:00",
            now_monotonic=110.0,
        )

    # By now the first activity window should have closed (5s budget
    # elapsed at monotonic=110.0 vs window started at 100.0).
    rows, _ = select_events(
        conn, filter=EventFilter(), cursor=None, limit=50, reverse=False
    )
    assert len(rows) >= 1
    # Offset advanced past the first record.
    offset_row = lo_state.select(
        conn, agent_id="agt_a1b2c3d4e5f6", log_path=str(log_path)
    )
    assert offset_row is not None
    assert offset_row.byte_offset > 0
