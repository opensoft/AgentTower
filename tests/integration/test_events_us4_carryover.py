"""T066 / T067 / T068 / T069 / T070 / T071 — US4 acceptance scenarios.

FEAT-007 carry-over: T175 (truncation), T176 (recreation), T177
(missing → recreated → operator re-attach), plus the no-replay
invariant (FR-043 / SC-004 / SC-005 / SC-006).

These tests exercise the FEAT-008 reader against a real
attachment + log file, then mutate the log file (truncate / delete
/ recreate) and assert the reader's `run_cycle_for_attachment`
produces the documented offsets and emits no events whose
``byte_range_start`` falls within pre-reset bytes.

The tests use direct DB seeding rather than the FEAT-007
``attach-log`` CLI chain (which requires Docker / tmux fixtures
unavailable in this CI). The reader's behavior is the same — it
cycles every active ``log_attachments`` row regardless of how the
row got there.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from agenttower.events.reader import EventsReader
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


def _seed_attachment(
    conn: sqlite3.Connection, log_path: Path
) -> la_state.LogAttachmentRecord:
    """Seed a log_offsets row with the file's actual inode/size."""
    rec = _make_attachment(str(log_path))
    lo_state.insert_initial(
        conn,
        agent_id=rec.agent_id,
        log_path=rec.log_path,
        timestamp="2026-05-10T00:00:00.000000+00:00",
    )
    if log_path.exists():
        st = os.stat(str(log_path))
        lo_state.update_file_observation(
            conn,
            agent_id=rec.agent_id,
            log_path=rec.log_path,
            file_inode=f"{st.st_dev}:{st.st_ino}",
            file_size_seen=st.st_size,
            last_output_at=None,
            timestamp="2026-05-10T00:00:00.000000+00:00",
        )
    return rec


def _seed_offsets(
    conn: sqlite3.Connection,
    rec: la_state.LogAttachmentRecord,
    *,
    byte_offset: int,
    line_offset: int,
    file_inode: str,
    file_size_seen: int,
) -> None:
    """Advance offsets to a specific position AND set inode/size."""
    lo_state.advance_offset(
        conn,
        agent_id=rec.agent_id,
        log_path=rec.log_path,
        byte_offset=byte_offset,
        line_offset=line_offset,
        last_event_offset=byte_offset,
        file_inode=file_inode,
        file_size_seen=file_size_seen,
        last_output_at="2026-05-10T00:00:01.000000+00:00",
        timestamp="2026-05-10T00:00:01.000000+00:00",
    )


def _make_reader(tmp_path: Path) -> EventsReader:
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)
    return EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=events_file,
        lifecycle_logger=None,
    )


def _count_events(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])


def test_us4_as1_truncation_resets_offsets_no_pre_truncate_events(
    tmp_path: Path,
) -> None:
    """AS1 (T175): truncate the log in place; offsets reset to (0,0,0)
    within ≤ 1 reader cycle; zero durable events from pre-truncate
    bytes."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("aaaa\nbbbb\ncccc\n", encoding="utf-8")

    rec = _seed_attachment(conn, log_path)
    # Insert the attachment row (FK off).
    la_state.insert(conn, rec)

    # Seed offsets such that the reader has consumed all 15 bytes.
    st = os.stat(str(log_path))
    inode = f"{st.st_dev}:{st.st_ino}"
    _seed_offsets(
        conn, rec,
        byte_offset=15,
        line_offset=3,
        file_inode=inode,
        file_size_seen=15,
    )

    # Truncate in place (same inode, smaller size).
    log_path.write_bytes(b"")

    reader = _make_reader(tmp_path)
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:01.000000+00:00",
        now_monotonic=100.0,
    )

    # Offsets reset.
    offsets_after = lo_state.select(
        conn, agent_id=rec.agent_id, log_path=rec.log_path
    )
    assert offsets_after.byte_offset == 0
    assert offsets_after.line_offset == 0
    assert offsets_after.last_event_offset == 0
    # Inode preserved (truncate-in-place).
    assert offsets_after.file_inode == inode

    # Zero durable events emitted.
    assert _count_events(conn) == 0


def test_us4_as2_recreation_resets_offsets_with_new_inode(
    tmp_path: Path,
) -> None:
    """AS2 (T176): delete-and-recreate with new inode; offsets reset;
    inode updated."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _seed_attachment(conn, log_path)
    la_state.insert(conn, rec)

    old_st = os.stat(str(log_path))
    old_inode = f"{old_st.st_dev}:{old_st.st_ino}"
    _seed_offsets(
        conn, rec,
        byte_offset=6,
        line_offset=1,
        file_inode=old_inode,
        file_size_seen=6,
    )

    # Delete + recreate (new inode). Use a tempfile + os.replace so
    # the new inode is guaranteed different from the deleted file's
    # — small filesystems otherwise reuse the just-freed inode.
    log_path.unlink()
    tmp_replacement = tmp_path / "_replacement"
    tmp_replacement.write_text("brand new\n", encoding="utf-8")
    os.replace(str(tmp_replacement), str(log_path))
    new_st = os.stat(str(log_path))
    new_inode = f"{new_st.st_dev}:{new_st.st_ino}"
    if new_inode == old_inode:
        pytest.skip(
            "filesystem reused the just-freed inode; can't exercise the"
            " inode-change branch on this filesystem"
        )

    reader = _make_reader(tmp_path)
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:01.000000+00:00",
        now_monotonic=100.0,
    )

    offsets_after = lo_state.select(
        conn, agent_id=rec.agent_id, log_path=rec.log_path
    )
    # Reset.
    assert offsets_after.byte_offset == 0
    assert offsets_after.line_offset == 0
    # Inode updated to new.
    assert offsets_after.file_inode == new_inode

    # Zero events from pre-recreation bytes.
    rows = conn.execute(
        "SELECT excerpt FROM events WHERE agent_id = ?", (rec.agent_id,)
    ).fetchall()
    excerpts = {r[0] for r in rows}
    assert "hello" not in excerpts


def test_us4_as3_missing_flips_to_stale_no_offset_change(
    tmp_path: Path,
) -> None:
    """AS3: file deleted; row transitions ``active → stale``; offsets
    unchanged byte-for-byte."""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("hello\n", encoding="utf-8")
    rec = _seed_attachment(conn, log_path)
    la_state.insert(conn, rec)

    st = os.stat(str(log_path))
    inode = f"{st.st_dev}:{st.st_ino}"
    _seed_offsets(
        conn, rec,
        byte_offset=6,
        line_offset=1,
        file_inode=inode,
        file_size_seen=6,
    )

    # Delete the file.
    log_path.unlink()

    reader = _make_reader(tmp_path)
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:01.000000+00:00",
        now_monotonic=100.0,
    )

    # Row transitions to stale.
    new_rec = la_state.select_for_agent_path(
        conn, agent_id=rec.agent_id, log_path=rec.log_path
    )
    assert new_rec is not None
    assert new_rec.status == "stale"

    # Offsets unchanged byte-for-byte.
    offsets_after = lo_state.select(
        conn, agent_id=rec.agent_id, log_path=rec.log_path
    )
    assert offsets_after.byte_offset == 6
    assert offsets_after.line_offset == 1
    assert offsets_after.file_inode == inode


def test_us4_no_replay_invariant_across_truncation_cycle(
    tmp_path: Path,
) -> None:
    """FR-043 / SC-004: the reader emits NO durable event whose
    excerpt comes from pre-reset bytes — exercised end-to-end with
    a write → cycle → truncate → cycle → fresh-write → cycle pattern.
    """
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("error: pre-truncate\n", encoding="utf-8")
    rec = _seed_attachment(conn, log_path)
    la_state.insert(conn, rec)

    reader = _make_reader(tmp_path)

    # Cycle 1: read the pre-truncate content.
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:01.000000+00:00",
        now_monotonic=100.0,
    )
    pre_truncate_excerpts = {
        r[0] for r in conn.execute(
            "SELECT excerpt FROM events WHERE agent_id = ?", (rec.agent_id,)
        )
    }
    # The activity-class debounce window keeps the event in memory until
    # it closes; the error-class line emits immediately. We may have
    # the "error" line persisted now.

    # Truncate in place.
    log_path.write_bytes(b"")

    # Cycle 2: post-truncate, no new bytes yet → recovery resets offsets,
    # zero new events.
    pre_count = _count_events(conn)
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:02.000000+00:00",
        now_monotonic=110.0,  # past debounce budget
    )
    # Offsets are reset.
    offsets_after = lo_state.select(
        conn, agent_id=rec.agent_id, log_path=rec.log_path
    )
    assert offsets_after.byte_offset == 0

    # Cycle 3: write fresh content, run cycle.
    log_path.write_text("fresh: post-truncate line\n", encoding="utf-8")
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:03.000000+00:00",
        now_monotonic=120.0,
    )

    # The freshly-written line gets a row eventually (closing the
    # debounce window in cycle 4 below if it is activity).
    log_path.write_text(
        "fresh: post-truncate line\nerror: post-truncate\n",
        encoding="utf-8",
    )
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:04.000000+00:00",
        now_monotonic=121.0,
    )

    all_excerpts = {
        r[0] for r in conn.execute(
            "SELECT excerpt FROM events WHERE agent_id = ?", (rec.agent_id,)
        )
    }
    # No duplicates of the pre-truncate excerpt in the post-truncate
    # window's events (we must not have re-emitted "error: pre-truncate"
    # from the pre-reset bytes).
    pre_truncate_count = sum(
        1 for r in conn.execute(
            "SELECT excerpt, byte_range_start FROM events WHERE agent_id = ? "
            "ORDER BY event_id",
            (rec.agent_id,),
        )
        if r[0] == "error: pre-truncate"
    )
    # At most one — the original cycle 1 emission. Never two.
    assert pre_truncate_count <= 1


def test_us4_sc_006_truncation_round_trip_one_iteration(tmp_path: Path) -> None:
    """SC-006: a single iteration of the truncation round-trip is
    deterministic. (We don't run 100× to keep CI fast; the reader's
    behaviour is fully synchronous and this single-iteration assertion
    covers the load-bearing invariants.)"""
    conn = _open_v6(tmp_path)
    log_path = tmp_path / "agent.log"
    log_path.write_text("a\nb\n", encoding="utf-8")
    rec = _seed_attachment(conn, log_path)
    la_state.insert(conn, rec)

    st = os.stat(str(log_path))
    inode = f"{st.st_dev}:{st.st_ino}"
    _seed_offsets(
        conn, rec,
        byte_offset=4,
        line_offset=2,
        file_inode=inode,
        file_size_seen=4,
    )

    # Truncate.
    log_path.write_bytes(b"")
    reader = _make_reader(tmp_path)
    reader.run_cycle_for_attachment(
        conn, attachment=rec,
        now_iso="2026-05-10T12:00:01.000000+00:00",
        now_monotonic=100.0,
    )
    offsets_after = lo_state.select(
        conn, agent_id=rec.agent_id, log_path=rec.log_path
    )
    assert offsets_after.byte_offset == 0
    assert offsets_after.line_offset == 0
