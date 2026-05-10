"""T082 — FR-029: JSONL retry watermark.

When append_event raises mid-cycle, the reader:
- leaves jsonl_appended_at NULL on the new event row (so the retry
  pass on subsequent cycles will pick it up);
- surfaces ``degraded_jsonl`` on ``agenttower status``;
- on the retry pass, marks the row appended once the OS error clears.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from agenttower.events.dao import select_pending_jsonl
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


def _make_reader(tmp_path: Path) -> EventsReader:
    import os
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)
    return EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=events_file,
        lifecycle_logger=None,
    )


def test_jsonl_failure_leaves_watermark_null(tmp_path: Path) -> None:
    """A JSONL append failure leaves ``jsonl_appended_at`` NULL so the
    next cycle retries. ``select_pending_jsonl`` returns the row."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    # Use an error line so the event is one-to-one (not debounced).
    log_path.write_text("Error: boom\n", encoding="utf-8")
    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path=str(log_path),
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )

    reader = _make_reader(tmp_path)

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ), patch(
        "agenttower.events.reader.append_event",
        side_effect=OSError("simulated JSONL write failure"),
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T12:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    pending = select_pending_jsonl(conn, limit=10)
    assert len(pending) == 1
    assert pending[0].excerpt == "Error: boom"
    assert pending[0].jsonl_appended_at is None

    snap = reader.status_snapshot()
    assert snap.degraded_jsonl is not None
    assert snap.degraded_jsonl["pending_event_count"] >= 1


def test_jsonl_retry_pass_clears_watermark_on_success(tmp_path: Path) -> None:
    """Once the OS error clears, the FR-029 retry pass marks the
    pending rows as appended and clears ``degraded_jsonl``."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("Error: boom\n", encoding="utf-8")
    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path=str(log_path),
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )

    reader = _make_reader(tmp_path)

    # Cycle 1: JSONL append fails.
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ), patch(
        "agenttower.events.reader.append_event",
        side_effect=OSError("simulated"),
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T12:00:01.000000+00:00",
            now_monotonic=100.0,
        )
    assert select_pending_jsonl(conn, limit=10)

    # Cycle 2: JSONL recovers; retry pass clears the watermark.
    reader._retry_pending_jsonl_appends(
        conn, now_iso="2026-05-10T12:00:02.000000+00:00"
    )
    assert select_pending_jsonl(conn, limit=10) == []
    snap = reader.status_snapshot()
    assert snap.degraded_jsonl is None
