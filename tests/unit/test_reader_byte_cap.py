"""T035 — FR-019: per-cycle byte cap.

The reader caps bytes read per attachment per cycle at
``PER_CYCLE_BYTE_CAP_BYTES``; any excess remains on disk and is
processed on the next cycle.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

from agenttower.events.dao import EventFilter, select_events
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


def _fake_recovery(**kwargs):
    return ReaderCycleResult(
        change=lo_state.FileChangeKind.UNCHANGED,
        state_mutated=False,
        lifecycle_event_emitted=None,
        audit_row_appended=False,
    )


def test_read_bytes_honors_cap(tmp_path: Path) -> None:
    """Direct test of the reader's byte-read primitive."""
    log = tmp_path / "log.txt"
    payload = b"x" * 10_000
    log.write_bytes(payload)

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=0, cap=4096)
    assert len(out) == 4096
    assert out == payload[:4096]


def test_read_bytes_advances_to_offset(tmp_path: Path) -> None:
    """Reading from a non-zero offset returns bytes starting from that
    position."""
    log = tmp_path / "log.txt"
    log.write_bytes(b"abcdefghij")

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=3, cap=4)
    assert out == b"defg"


def test_read_bytes_returns_empty_at_eof(tmp_path: Path) -> None:
    log = tmp_path / "log.txt"
    log.write_bytes(b"hello")

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=5, cap=4096)
    assert out == b""


def test_read_bytes_returns_only_available(tmp_path: Path) -> None:
    """If only N bytes are available and cap > N, return N bytes
    (remainder will appear next cycle once written)."""
    log = tmp_path / "log.txt"
    log.write_bytes(b"hello")  # 5 bytes

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=0, cap=4096)
    assert out == b"hello"


def test_long_line_without_newline_forces_event_and_advances(tmp_path: Path) -> None:
    """A cap-sized read with no newline must make forward progress."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_bytes(b"abcdefghijk")
    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path=str(log_path),
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=events_file,
        lifecycle_logger=None,
        per_cycle_byte_cap_bytes=8,
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

    assert result.events_emitted == 1
    assert result.bytes_read == 8
    rows, _ = select_events(
        conn, filter=EventFilter(), cursor=None, limit=50, reverse=False
    )
    assert len(rows) == 1
    assert rows[0].excerpt == "abcdefgh"
    offset_row = lo_state.select(
        conn, agent_id="agt_a1b2c3d4e5f6", log_path=str(log_path)
    )
    assert offset_row is not None
    assert offset_row.byte_offset == 8
