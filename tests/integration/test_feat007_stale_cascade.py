"""US5 / FR-042 / SC-009 — pane reconcile flips active → stale in same transaction.

When FEAT-004 reconciliation observes a previously-active pane transitioning
to inactive, every bound ``log_attachments`` row MUST flip from active to
stale in the same SQLite transaction. ``log_offsets`` is unchanged.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agenttower.state import log_attachments as state_log_attachments


def _seed_active_attachment(state_db: Path) -> tuple[str, tuple]:
    """Create a fully-seeded attached agent with an active log_attachment.

    Returns (attachment_id, pane_composite_key).
    """
    container_id = "c" * 64
    agent_id = "agt_abc123def456"
    pane_socket = "/tmp/tmux-1000/default"
    pane_session = "main"
    pane_window = 0
    pane_index = 0
    pane_id = "%17"
    now = "2026-05-08T14:00:00.000000+00:00"
    pane_key = (container_id, pane_socket, pane_session, pane_window, pane_index, pane_id)

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (container_id, "bench-acme", "bench:latest", "running",
             "{}", "[]", "{}", "brett", "/home/brett", 1, now, now),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            pane_key + ("bench-acme", "brett", 12345, "/dev/pts/0",
                        "bash", "/home/brett", "main", 1, 1, now, now),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id,) + pane_key + ("slave", "codex", "codex-01", "", None, "{}", now, now, None, 1),
        )
        conn.execute(
            "INSERT INTO log_attachments (attachment_id, agent_id, "
            "container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "log_path, status, source, pipe_pane_command, prior_pipe_target, "
            "attached_at, last_status_at, superseded_at, superseded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("lat_a1b2c3d4e5f6", agent_id) + pane_key + (
                "/host/log/x.log", "active", "explicit",
                "docker exec ...", None, now, now, None, None, now,
            ),
        )
        conn.execute(
            "INSERT INTO log_offsets (agent_id, log_path, byte_offset, "
            "line_offset, last_event_offset, last_output_at, file_inode, "
            "file_size_seen, created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 0, NULL, NULL, 0, ?, ?)",
            (agent_id, "/host/log/x.log", now, now),
        )
    finally:
        conn.close()
    return "lat_a1b2c3d4e5f6", pane_key


def test_cascade_to_stale_for_panes_unit(tmp_path: Path) -> None:
    """Direct unit test of the cascade helper (FR-042)."""
    from agenttower.state import schema

    state_db = tmp_path / "state.sqlite3"
    state_dir = tmp_path
    conn, _ = schema.open_registry(state_db, namespace_root=state_dir)
    conn.close()

    attachment_id, pane_key = _seed_active_attachment(state_db)

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        affected = state_log_attachments.cascade_to_stale_for_panes(
            conn,
            pane_keys=[list(pane_key)],
            now_iso="2026-05-08T15:00:00.000000+00:00",
        )
    finally:
        conn.close()

    assert len(affected) == 1
    assert affected[0].attachment_id == attachment_id
    assert affected[0].status == "active", "captured pre-update status"

    # Verify the row is now stale.
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT status, last_status_at FROM log_attachments WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "stale"
    assert row[1] == "2026-05-08T15:00:00.000000+00:00"


def test_cascade_offsets_unchanged(tmp_path: Path) -> None:
    """FR-042: log_offsets row MUST be unchanged when status flips to stale."""
    from agenttower.state import schema

    state_db = tmp_path / "state.sqlite3"
    state_dir = tmp_path
    conn, _ = schema.open_registry(state_db, namespace_root=state_dir)
    conn.close()
    _, pane_key = _seed_active_attachment(state_db)

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        # Advance the offset before cascade (simulating a real reader cycle).
        from agenttower.state import log_offsets

        log_offsets.advance_offset_for_test(
            conn,
            agent_id="agt_abc123def456",
            log_path="/host/log/x.log",
            byte_offset=4096,
            line_offset=137,
            last_event_offset=3200,
            file_inode="234:1234567",
            file_size_seen=8192,
            last_output_at="2026-05-08T14:23:00.000000+00:00",
            timestamp="2026-05-08T14:23:00.000000+00:00",
        )
        state_log_attachments.cascade_to_stale_for_panes(
            conn,
            pane_keys=[list(pane_key)],
            now_iso="2026-05-08T15:00:00.000000+00:00",
        )
        row = conn.execute(
            "SELECT byte_offset, line_offset, last_event_offset, file_inode, file_size_seen "
            "FROM log_offsets WHERE agent_id = ? AND log_path = ?",
            ("agt_abc123def456", "/host/log/x.log"),
        ).fetchone()
    finally:
        conn.close()

    assert row == (4096, 137, 3200, "234:1234567", 8192)


def test_cascade_no_op_for_unbound_panes(tmp_path: Path) -> None:
    """If no log_attachments row is bound to the pane key, cascade returns []."""
    from agenttower.state import schema

    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()

    conn = sqlite3.connect(str(state_db))
    try:
        affected = state_log_attachments.cascade_to_stale_for_panes(
            conn,
            pane_keys=[("c" * 64, "/tmp/sock", "main", 0, 0, "%1")],
            now_iso="2026-05-08T15:00:00.000000+00:00",
        )
    finally:
        conn.close()
    assert affected == []


def test_cascade_skips_non_active_rows(tmp_path: Path) -> None:
    """A row already in stale/superseded/detached MUST NOT be re-affected."""
    from agenttower.state import schema

    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()
    _, pane_key = _seed_active_attachment(state_db)

    # Manually mark the row stale before cascade.
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "UPDATE log_attachments SET status = 'stale' WHERE attachment_id = ?",
            ("lat_a1b2c3d4e5f6",),
        )
        affected = state_log_attachments.cascade_to_stale_for_panes(
            conn,
            pane_keys=[list(pane_key)],
            now_iso="2026-05-08T15:00:00.000000+00:00",
        )
    finally:
        conn.close()
    assert affected == []  # already stale; cascade is a no-op
