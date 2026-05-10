"""T083 — FR-039: missing offset row for active attachment.

When an active log_attachments row has no corresponding log_offsets
row, the reader skips that attachment for the cycle and surfaces the
inconsistency. The reader MUST NOT invent offset values.
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


def test_missing_offset_row_skips_cycle_and_surfaces_inconsistency(
    tmp_path: Path,
) -> None:
    """No log_offsets row → reader returns failed=True with
    ``failure_class='missing_offset_row'``; no offsets invented."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")

    # NOTE: we deliberately do NOT call lo_state.insert_initial here.

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    def _fake_recovery_returns_no_offset(**kwargs):
        # Recovery helper sees no offset row and returns MISSING-shape.
        # The reader's run_cycle then re-fetches and sees None.
        return ReaderCycleResult(
            change=lo_state.FileChangeKind.UNCHANGED,
            state_mutated=False,
            lifecycle_event_emitted=None,
            audit_row_appended=False,
        )

    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_returns_no_offset,
    ):
        result = reader.run_cycle_for_attachment(
            conn,
            attachment=_make_attachment(str(log_path)),
            now_iso="2026-05-10T12:00:01.000000+00:00",
            now_monotonic=100.0,
        )

    assert result.failed is True
    assert result.failure_class == "missing_offset_row"
    # No offset row was created.
    assert (
        lo_state.select(
            conn, agent_id="agt_a1b2c3d4e5f6", log_path=str(log_path)
        )
        is None
    )
