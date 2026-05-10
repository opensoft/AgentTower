"""T084 — FR-036 / FR-038: per-attachment failures isolate cleanly.

An EACCES (or any I/O error) on one attachment's log file MUST NOT
prevent other attachments' cycles from running. The failed attachment
surfaces in ``status.events_reader.attachments_in_failure`` without
crashing the daemon.
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


def _fake_recovery_unchanged(**kwargs):
    return ReaderCycleResult(
        change=lo_state.FileChangeKind.UNCHANGED,
        state_mutated=False,
        lifecycle_event_emitted=None,
        audit_row_appended=False,
    )


def test_eaccess_on_log_file_surfaces_diagnostic_no_crash(
    tmp_path: Path,
) -> None:
    """When ``_read_bytes`` raises an OSError, the cycle returns
    failed=True with the OSError's class name and does NOT crash the
    daemon thread."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
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

    def _eacces_read(self, log_path, byte_offset, cap):
        raise PermissionError(13, "Permission denied", str(log_path))

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ), patch(
        "agenttower.events.reader.EventsReader._read_bytes", _eacces_read
    ):
        result = reader.run_cycle_for_attachment(
            conn, attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T12:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    assert result.failed is True
    assert result.failure_class == "PermissionError"

    # The attachment row is NOT lost.
    offset_row = lo_state.select(
        conn, agent_id="agt_a1b2c3d4e5f6", log_path=str(log_path)
    )
    assert offset_row is not None


def test_one_attachment_failure_does_not_crash_thread(tmp_path: Path) -> None:
    """A failure on one attachment doesn't propagate up
    ``run_cycle_for_attachment``; the call returns a failure marker
    so ``_run_one_cycle`` can iterate to the next attachment."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
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

    def _eacces_read(self, log_path, byte_offset, cap):
        raise OSError(13, "Permission denied")

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ), patch(
        "agenttower.events.reader.EventsReader._read_bytes", _eacces_read
    ):
        # The call returns a result rather than raising.
        result = reader.run_cycle_for_attachment(
            conn, attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T12:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    assert result.failed is True
    # Reader still functional — call again with a working read.
    log_path.write_text("hello\nworld\n", encoding="utf-8")
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        result2 = reader.run_cycle_for_attachment(
            conn, attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T12:00:02.000000+00:00",
            now_monotonic=110.0,
        )
    # Second call succeeds because no I/O error.
    assert result2.failed is False
