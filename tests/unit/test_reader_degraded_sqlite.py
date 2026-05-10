"""T081 — FR-040: degraded SQLite buffered-retry path.

When the SQLite commit fails mid-cycle, the reader:
- does NOT advance offsets (so unread bytes stay on disk for retry);
- surfaces ``degraded_sqlite`` on ``agenttower status``;
- recovers on the next cycle when SQLite is writable again.
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


def _seed_offsets(conn: sqlite3.Connection, log_path: str) -> None:
    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path=log_path,
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )


def _fake_recovery_unchanged(**kwargs):
    return ReaderCycleResult(
        change=lo_state.FileChangeKind.UNCHANGED,
        state_mutated=False,
        lifecycle_event_emitted=None,
        audit_row_appended=False,
    )


def test_sqlite_failure_surfaces_degraded_state_and_no_offset_advance(
    tmp_path: Path,
) -> None:
    """When advance_offset raises, the cycle:
    (a) reports failed=True, (b) surfaces degraded_sqlite via status,
    (c) leaves byte_offset at 0."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    _seed_offsets(conn, str(log_path))

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    def _failing_advance(*args, **kwargs):
        raise sqlite3.OperationalError("simulated SQLite read-only")

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ), patch(
        "agenttower.events.reader.lo_state.advance_offset",
        side_effect=_failing_advance,
    ):
        result = reader.run_cycle_for_attachment(
            conn, attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T12:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    assert result.failed is True
    assert result.failure_class == "sqlite_commit"

    # status snapshot reports the degraded condition.
    snap = reader.status_snapshot()
    assert snap.degraded_sqlite is not None
    assert snap.degraded_sqlite["since"] == "2026-05-10T12:00:01.000000+00:00"
    bufs = snap.degraded_sqlite["buffered_attachments"]
    assert len(bufs) == 1
    assert bufs[0]["attachment_id"] == "atc_aabbccddeeff"
    assert bufs[0]["agent_id"] == "agt_a1b2c3d4e5f6"

    # No offset advance (unread bytes remain on disk for next cycle).
    offset_row = lo_state.select(
        conn, agent_id="agt_a1b2c3d4e5f6", log_path=str(log_path)
    )
    assert offset_row.byte_offset == 0
    assert offset_row.line_offset == 0
