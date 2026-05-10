"""H4 fix — clock-driven tests for ``pane_exited`` / ``long_running``
synthesis (FR-013 / FR-016 / FR-017 / FR-018, Plan §R11).

The reader synthesizes these two event types at cycle entry, BEFORE
the FEAT-007 recovery call, when:

- ``pane_exited``: the bound FEAT-004 pane row reports
  ``active = 0`` AND ``now - last_output_at >= pane_exited_grace``.
  Exactly once per attachment lifecycle (FR-018).
- ``long_running``: the most-recent prior emitted event for the
  attachment is in the eligibility set
  (``activity``/``error``/``test_failed``/``manual_review_needed``/
  ``swarm_member_reported``) AND ``now - last_output_at >=
  long_running_grace``. Exactly once per running task (FR-013);
  marker resets when a fresh eligible event lands afterwards.
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


def _seed_pane(conn: sqlite3.Connection, *, active: int) -> None:
    """Insert a panes row matching the test attachment's composite key."""
    conn.execute(
        "INSERT OR REPLACE INTO panes ("
        "container_id, tmux_socket_path, tmux_session_name, "
        "tmux_window_index, tmux_pane_index, tmux_pane_id, "
        "container_name, container_user, pane_pid, pane_tty, "
        "pane_current_command, pane_current_path, pane_title, "
        "pane_active, active, first_seen_at, last_scanned_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "c" * 64, "/tmp/sock", "s", 0, 0, "%1",
            "bench", "user", 1, "/dev/pts/0",
            "bash", "/", "title", 1, active,
            "2026-05-10T00:00:00.000000+00:00",
            "2026-05-10T00:00:00.000000+00:00",
        ),
    )


def _seed_offsets(
    conn: sqlite3.Connection, log_path: str, *, last_output_at: str | None
) -> None:
    lo_state.insert_initial(
        conn,
        agent_id="agt_a1b2c3d4e5f6",
        log_path=log_path,
        timestamp="2026-05-10T12:00:00.000000+00:00",
    )
    if last_output_at is not None:
        lo_state.update_file_observation(
            conn,
            agent_id="agt_a1b2c3d4e5f6",
            log_path=log_path,
            file_inode=None,
            file_size_seen=0,
            last_output_at=last_output_at,
            timestamp=last_output_at,
        )


def _seed_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    excerpt: str = "x",
    observed_at: str = "2026-05-10T12:00:00.000000+00:00",
) -> int:
    cur = conn.execute(
        "INSERT INTO events ("
        "event_type, agent_id, attachment_id, log_path, "
        "byte_range_start, byte_range_end, "
        "line_offset_start, line_offset_end, "
        "observed_at, excerpt, classifier_rule_id, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_type, "agt_a1b2c3d4e5f6", "atc_aabbccddeeff",
            "/tmp/agent.log", 0, 10, 0, 1,
            observed_at, excerpt, f"{event_type}.test.v1", 1,
        ),
    )
    return int(cur.lastrowid or 0)


def _make_reader(tmp_path: Path, **kwargs) -> EventsReader:
    import os
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)
    return EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=events_file,
        lifecycle_logger=None,
        **kwargs,
    )


def _fake_recovery_unchanged(**kwargs):
    return ReaderCycleResult(
        change=lo_state.FileChangeKind.UNCHANGED,
        state_mutated=False,
        lifecycle_event_emitted=None,
        audit_row_appended=False,
    )


# --------------------------------------------------------------------------
# pane_exited synthesis (FR-016 / FR-017 / FR-018)
# --------------------------------------------------------------------------


def test_pane_exited_emits_when_pane_inactive_and_grace_elapsed(tmp_path: Path) -> None:
    """FR-016 / FR-017: pane reports inactive AND grace elapsed → exactly
    one synthesized ``pane_exited`` event."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_pane(conn, active=0)
    # last_output_at 60 s before "now" (well past the 30 s grace).
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:59:00.000000+00:00")

    reader = _make_reader(tmp_path, pane_exited_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:00:00.000000+00:00",
            now_monotonic=100.0,
        )

    rows = conn.execute(
        "SELECT event_type, classifier_rule_id, excerpt FROM events "
        "WHERE event_type = 'pane_exited'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("pane_exited", "pane_exited.synth.v1", "")


def test_pane_exited_does_not_emit_when_grace_not_yet_elapsed(tmp_path: Path) -> None:
    """FR-017: grace not elapsed → no emission this cycle."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_pane(conn, active=0)
    # last_output_at only 5 s before "now" (well under the 30 s grace).
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:59:55.000000+00:00")

    reader = _make_reader(tmp_path, pane_exited_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:00:00.000000+00:00",
            now_monotonic=100.0,
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'pane_exited'"
    ).fetchone()[0] == 0


def test_pane_exited_does_not_emit_when_pane_still_active(tmp_path: Path) -> None:
    """FR-016: pane still active → no emission."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_pane(conn, active=1)
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:00:00.000000+00:00")

    reader = _make_reader(tmp_path, pane_exited_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:00:00.000000+00:00",
            now_monotonic=100.0,
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'pane_exited'"
    ).fetchone()[0] == 0


def test_pane_exited_emits_exactly_once_per_lifecycle(tmp_path: Path) -> None:
    """FR-018: even with multiple cycles satisfying the conditions, only
    one ``pane_exited`` event is emitted per attachment lifecycle."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_pane(conn, active=0)
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:00:00.000000+00:00")

    reader = _make_reader(tmp_path, pane_exited_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        for ts in (
            "2026-05-10T12:00:00.000000+00:00",
            "2026-05-10T12:00:01.000000+00:00",
            "2026-05-10T12:00:02.000000+00:00",
        ):
            reader.run_cycle_for_attachment(
                conn, attachment=rec, now_iso=ts, now_monotonic=100.0,
            )

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'pane_exited'"
    ).fetchone()[0] == 1


# --------------------------------------------------------------------------
# long_running synthesis (FR-013)
# --------------------------------------------------------------------------


def test_long_running_emits_when_eligible_event_then_grace_elapsed(
    tmp_path: Path,
) -> None:
    """FR-013: prior eligible event (``activity``) + grace elapsed →
    exactly one ``long_running``."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:00:00.000000+00:00")
    _seed_event(conn, event_type="activity", excerpt="working")

    reader = _make_reader(tmp_path, long_running_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:00:00.000000+00:00",
            now_monotonic=100.0,
        )

    rows = conn.execute(
        "SELECT event_type, classifier_rule_id FROM events "
        "WHERE event_type = 'long_running'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("long_running", "long_running.synth.v1")


def test_long_running_does_not_emit_when_last_was_completed(tmp_path: Path) -> None:
    """FR-013: ``completed`` is INELIGIBLE — task is done, no
    ``long_running``."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:00:00.000000+00:00")
    _seed_event(conn, event_type="completed", excerpt="DONE")

    reader = _make_reader(tmp_path, long_running_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:00:00.000000+00:00",
            now_monotonic=100.0,
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'long_running'"
    ).fetchone()[0] == 0


def test_long_running_does_not_emit_when_last_was_waiting_for_input(
    tmp_path: Path,
) -> None:
    """FR-013 explicit: ``waiting_for_input`` is INELIGIBLE."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:00:00.000000+00:00")
    _seed_event(conn, event_type="waiting_for_input", excerpt=">>>")

    reader = _make_reader(tmp_path, long_running_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:00:00.000000+00:00",
            now_monotonic=100.0,
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'long_running'"
    ).fetchone()[0] == 0


def test_long_running_does_not_emit_twice_in_a_row(tmp_path: Path) -> None:
    """FR-013: exactly once per running task. A second cycle with the
    same conditions does NOT emit a second ``long_running``."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:00:00.000000+00:00")
    _seed_event(conn, event_type="activity", excerpt="working")

    reader = _make_reader(tmp_path, long_running_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        for ts in (
            "2026-05-10T12:00:00.000000+00:00",
            "2026-05-10T12:00:30.000000+00:00",
            "2026-05-10T12:01:00.000000+00:00",
        ):
            reader.run_cycle_for_attachment(
                conn, attachment=rec, now_iso=ts, now_monotonic=100.0,
            )

    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'long_running'"
    ).fetchone()[0] == 1


def test_long_running_resets_after_fresh_eligible_event(tmp_path: Path) -> None:
    """FR-013: once a fresh eligible event lands AFTER ``long_running``,
    the marker resets and a later quiet period emits again."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _make_attachment(str(log_path))
    la_state.insert(conn, rec)
    _seed_offsets(conn, str(log_path), last_output_at="2026-05-10T11:00:00.000000+00:00")
    _seed_event(
        conn, event_type="activity", excerpt="working",
        observed_at="2026-05-10T11:00:00.000000+00:00",
    )

    reader = _make_reader(tmp_path, long_running_grace_seconds=30.0)
    with patch(
        "agenttower.events.reader.reader_recovery.reader_cycle_offset_recovery",
        side_effect=_fake_recovery_unchanged,
    ):
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:00:00.000000+00:00",
            now_monotonic=100.0,
        )
        # First long_running emitted. Now a fresh eligible event lands.
        _seed_event(
            conn, event_type="error", excerpt="oh no",
            observed_at="2026-05-10T12:01:00.000000+00:00",
        )
        # Marker reset on the next cycle's first eligible-event
        # observation; second long_running is eligible if grace elapses.
        # Bump last_output_at to 12:01 so the elapsed check at 12:02
        # is still > 30 s.
        lo_state.update_file_observation(
            conn, agent_id=rec.agent_id, log_path=rec.log_path,
            file_inode=None, file_size_seen=0,
            last_output_at="2026-05-10T12:01:00.000000+00:00",
            timestamp="2026-05-10T12:01:00.000000+00:00",
        )
        reader.run_cycle_for_attachment(
            conn, attachment=rec,
            now_iso="2026-05-10T12:02:00.000000+00:00",
            now_monotonic=100.0,
        )

    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'long_running'"
    ).fetchone()[0]
    # At least 2 — one before the error, one after-with-fresh-grace.
    assert count == 2
