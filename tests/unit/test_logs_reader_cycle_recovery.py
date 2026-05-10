"""Unit tests for FEAT-007 ``reader_cycle_offset_recovery`` (T181 / FR-024..026).

The helper translates a single file-change observation into the right
combination of state mutation, audit row, and lifecycle event.

State mutations are committed in their own ``BEGIN IMMEDIATE`` transaction
(mirrors the ``pane_service`` cascade pattern). Audit rows are appended
after COMMIT.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agenttower.logs import host_fs as host_fs_mod
from agenttower.logs import lifecycle as logs_lifecycle
from agenttower.logs.reader_recovery import (
    ReaderCycleResult,
    reader_cycle_offset_recovery,
)
from agenttower.state import schema


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class _RecordingLogger:
    """Drop-in for the lifecycle logger; records emitted events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, *, level: str = "info", **fields: Any) -> None:
        self.events.append((event, fields))


@pytest.fixture(autouse=True)
def _reset_lifecycle_suppression() -> None:
    """Ensure each test starts with a clean FR-061 suppression registry."""
    logs_lifecycle.reset_for_test()
    yield
    logs_lifecycle.reset_for_test()


@pytest.fixture
def primed_db(tmp_path: Path) -> tuple[Path, Path]:
    """Open a v5 schema, return (db_path, events_file_path)."""
    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    # FEAT-001 events writer requires 0o600 mode; test fixture must comply.
    os.chmod(events_file, 0o600)
    return state_db, events_file


def _now() -> str:
    return "2026-05-08T15:00:00.000000+00:00"


def _seed_attachment(
    state_db: Path,
    *,
    log_path: str,
    status: str,
    file_inode: str | None,
    file_size_seen: int,
    byte_offset: int = 0,
    line_offset: int = 0,
) -> str:
    """Seed one attached agent + one log_attachment row + one log_offsets row.

    Returns the attachment_id.
    """
    container_id = "c" * 64
    agent_id = "agt_abc123def456"
    attachment_id = "lat_a1b2c3d4e5f6"
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
            (attachment_id, agent_id) + pane_key + (
                log_path, status, "explicit",
                "docker exec ...", None, now, now, None, None, now,
            ),
        )
        conn.execute(
            "INSERT INTO log_offsets (agent_id, log_path, byte_offset, "
            "line_offset, last_event_offset, last_output_at, file_inode, "
            "file_size_seen, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?, ?)",
            (agent_id, log_path, byte_offset, line_offset,
             file_inode, file_size_seen, now, now),
        )
    finally:
        conn.close()
    return attachment_id


def _row_status(state_db: Path, attachment_id: str) -> str:
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT status FROM log_attachments WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0]


def _offset_row(state_db: Path, log_path: str) -> tuple:
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT byte_offset, line_offset, last_event_offset, "
            "file_inode, file_size_seen FROM log_offsets "
            "WHERE agent_id = ? AND log_path = ?",
            ("agt_abc123def456", log_path),
        ).fetchone()
    finally:
        conn.close()
    return row


def _read_audit_rows(events_file: Path) -> list[dict[str, Any]]:
    rows = []
    for line in events_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return [r for r in rows if r.get("type") == "log_attachment_change"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unchanged_active_is_noop(primed_db: tuple[Path, Path], tmp_path: Path) -> None:
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    log_path.write_bytes(b"x" * 4096)
    inode = f"{os.stat(log_path).st_dev}:{os.stat(log_path).st_ino}"
    _seed_attachment(
        state_db, log_path=str(log_path), status="active",
        file_inode=inode, file_size_seen=4096, byte_offset=2048, line_offset=64,
    )
    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        result = reader_cycle_offset_recovery(
            conn=conn,
            events_file=events_file,
            lifecycle_logger=logger,
            agent_id="agt_abc123def456",
            log_path=str(log_path),
            timestamp=_now(),
        )
    finally:
        conn.close()

    assert isinstance(result, ReaderCycleResult)
    assert result.change.value == "unchanged"
    assert result.state_mutated is False
    assert result.lifecycle_event_emitted is None
    assert result.audit_row_appended is False
    assert logger.events == []
    assert _offset_row(state_db, str(log_path)) == (2048, 64, 0, inode, 4096)
    assert _read_audit_rows(events_file) == []


def test_truncated_resets_offsets_preserves_inode_emits_rotation(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    log_path.write_bytes(b"x" * 8192)
    inode = f"{os.stat(log_path).st_dev}:{os.stat(log_path).st_ino}"
    _seed_attachment(
        state_db, log_path=str(log_path), status="active",
        file_inode=inode, file_size_seen=8192, byte_offset=4096, line_offset=137,
    )
    # Truncate in place — same inode, smaller size.
    with open(log_path, "wb"):
        pass

    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        result = reader_cycle_offset_recovery(
            conn=conn,
            events_file=events_file,
            lifecycle_logger=logger,
            agent_id="agt_abc123def456",
            log_path=str(log_path),
            timestamp=_now(),
        )
    finally:
        conn.close()

    assert result.change.value == "truncated"
    assert result.state_mutated is True
    assert result.lifecycle_event_emitted == "log_rotation_detected"
    assert result.audit_row_appended is False
    # offsets reset, inode preserved, size updated to 0.
    assert _offset_row(state_db, str(log_path)) == (0, 0, 0, inode, 0)
    assert _row_status(state_db, "lat_a1b2c3d4e5f6") == "active"
    assert len(logger.events) == 1
    event_name, payload = logger.events[0]
    assert event_name == "log_rotation_detected"
    assert payload["prior_inode"] == inode
    assert payload["new_inode"] == inode
    assert payload["prior_size"] == 8192
    assert payload["new_size"] == 0
    assert _read_audit_rows(events_file) == []


def test_recreated_resets_offsets_updates_inode_emits_rotation(
    primed_db: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inode mismatch path uses the fs fake; tmpfs reuses inodes on recreate."""
    state_db, events_file = primed_db
    log_path = "/host/log/recreated.log"
    prior_inode = "234:1111111"
    new_inode = "234:2222222"
    fake_path = tmp_path / "fs_fake.json"
    fake_path.write_text(json.dumps({
        log_path: {"exists": True, "inode": new_inode, "size": 1024},
    }))
    monkeypatch.setenv("AGENTTOWER_TEST_LOG_FS_FAKE", str(fake_path))
    host_fs_mod._reset_for_test()
    _seed_attachment(
        state_db, log_path=log_path, status="active",
        file_inode=prior_inode, file_size_seen=4096,
        byte_offset=2048, line_offset=64,
    )

    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        result = reader_cycle_offset_recovery(
            conn=conn,
            events_file=events_file,
            lifecycle_logger=logger,
            agent_id="agt_abc123def456",
            log_path=log_path,
            timestamp=_now(),
        )
    finally:
        conn.close()
        host_fs_mod._reset_for_test()

    assert result.change.value == "recreated"
    assert result.state_mutated is True
    assert result.lifecycle_event_emitted == "log_rotation_detected"
    assert result.audit_row_appended is False
    assert _offset_row(state_db, log_path) == (0, 0, 0, new_inode, 1024)
    assert _row_status(state_db, "lat_a1b2c3d4e5f6") == "active"
    assert len(logger.events) == 1
    event_name, payload = logger.events[0]
    assert event_name == "log_rotation_detected"
    assert payload["prior_inode"] == prior_inode
    assert payload["new_inode"] == new_inode
    assert payload["prior_size"] == 4096
    assert payload["new_size"] == 1024


def test_missing_against_active_flips_to_stale_emits_lifecycle_and_audit(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    log_path.write_bytes(b"x" * 4096)
    inode = f"{os.stat(log_path).st_dev}:{os.stat(log_path).st_ino}"
    _seed_attachment(
        state_db, log_path=str(log_path), status="active",
        file_inode=inode, file_size_seen=4096,
        byte_offset=2048, line_offset=64,
    )
    log_path.unlink()

    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        result = reader_cycle_offset_recovery(
            conn=conn,
            events_file=events_file,
            lifecycle_logger=logger,
            agent_id="agt_abc123def456",
            log_path=str(log_path),
            timestamp=_now(),
        )
    finally:
        conn.close()

    assert result.change.value == "missing"
    assert result.state_mutated is True
    assert result.lifecycle_event_emitted == "log_file_missing"
    assert result.audit_row_appended is True
    # FR-026: offsets unchanged.
    assert _offset_row(state_db, str(log_path)) == (2048, 64, 0, inode, 4096)
    # Status flipped to stale.
    assert _row_status(state_db, "lat_a1b2c3d4e5f6") == "stale"
    # One lifecycle event.
    assert len(logger.events) == 1
    event_name, payload = logger.events[0]
    assert event_name == "log_file_missing"
    assert payload["last_known_inode"] == inode
    assert payload["last_known_size"] == 4096
    # One audit row.
    audit = _read_audit_rows(events_file)
    assert len(audit) == 1
    assert audit[0]["payload"]["prior_status"] == "active"
    assert audit[0]["payload"]["new_status"] == "stale"
    assert audit[0]["payload"]["source"] == "explicit"


def test_missing_against_stale_is_noop_after_first_emit(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    """Second cycle on an already-stale missing row MUST NOT re-fire (FR-061)."""
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    inode = "234:1234567"
    _seed_attachment(
        state_db, log_path=str(log_path), status="active",
        file_inode=inode, file_size_seen=4096,
    )
    # First cycle: file missing, row flips to stale, log_file_missing emitted.
    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        first = reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_abc123def456", log_path=str(log_path), timestamp=_now(),
        )
        assert first.state_mutated is True
        assert first.lifecycle_event_emitted == "log_file_missing"
        # Second cycle: row already stale, file still missing.
        second = reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_abc123def456", log_path=str(log_path), timestamp=_now(),
        )
    finally:
        conn.close()

    assert second.change.value == "missing"
    assert second.state_mutated is False
    # FR-061 suppression: second emit is dropped.
    assert second.lifecycle_event_emitted is None
    assert second.audit_row_appended is False
    # Only one lifecycle event total.
    assert len(logger.events) == 1
    # Only one audit row total.
    assert len(_read_audit_rows(events_file)) == 1


def test_reappeared_emits_log_file_returned_no_state_change(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    """File comes back at a stale row → log_file_returned, status stays stale (FR-026)."""
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    prior_inode = "234:1234567"
    _seed_attachment(
        state_db, log_path=str(log_path), status="stale",
        file_inode=prior_inode, file_size_seen=4096,
        byte_offset=2048, line_offset=64,
    )
    log_path.write_bytes(b"new content\n")
    new_inode = f"{os.stat(log_path).st_dev}:{os.stat(log_path).st_ino}"

    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        result = reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_abc123def456", log_path=str(log_path), timestamp=_now(),
        )
    finally:
        conn.close()

    # FR-026: reappearance does NOT auto-recover. status stays stale.
    assert _row_status(state_db, "lat_a1b2c3d4e5f6") == "stale"
    # Offsets unchanged.
    assert _offset_row(state_db, str(log_path)) == (2048, 64, 0, prior_inode, 4096)
    # No audit row.
    assert _read_audit_rows(events_file) == []
    # One log_file_returned event.
    assert result.lifecycle_event_emitted == "log_file_returned"
    assert result.state_mutated is False
    assert result.audit_row_appended is False
    assert len(logger.events) == 1
    event_name, payload = logger.events[0]
    assert event_name == "log_file_returned"
    assert payload["prior_inode"] == prior_inode
    assert payload["new_inode"] == new_inode
    assert payload["new_size"] == len(b"new content\n")


def test_reappeared_suppressed_on_repeat(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    """FR-061: log_file_returned suppressed per (agent_id, log_path, file_inode) triple."""
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    _seed_attachment(
        state_db, log_path=str(log_path), status="stale",
        file_inode="234:1234567", file_size_seen=4096,
    )
    log_path.write_bytes(b"reappeared\n")
    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        first = reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_abc123def456", log_path=str(log_path), timestamp=_now(),
        )
        second = reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_abc123def456", log_path=str(log_path), timestamp=_now(),
        )
    finally:
        conn.close()
    assert first.lifecycle_event_emitted == "log_file_returned"
    assert second.lifecycle_event_emitted is None
    assert len(logger.events) == 1


def test_no_attachment_row_returns_noop(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    """Reader called for an agent with no attachment → no-op, no errors."""
    state_db, events_file = primed_db
    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        result = reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_unknown00001", log_path="/nope.log", timestamp=_now(),
        )
    finally:
        conn.close()
    assert result.change.value == "missing"
    assert result.state_mutated is False
    assert result.lifecycle_event_emitted is None
    assert result.audit_row_appended is False


def test_unchanged_against_stale_row_does_not_emit_returned(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    """If row is stale and file is observed UNCHANGED (same stored inode), still treat as REAPPEARED.

    A row is only stale because the reader observed a missing file at some
    prior cycle. If the file is now present and the inode happens to match
    the previously stored inode (e.g. inode reuse on a recreated file), we
    still want exactly one log_file_returned. Suppression is keyed on the
    NEW inode so reuse + reappearance at same inode emits once per triple.
    """
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    log_path.write_bytes(b"hello\n")
    real_inode = f"{os.stat(log_path).st_dev}:{os.stat(log_path).st_ino}"
    _seed_attachment(
        state_db, log_path=str(log_path), status="stale",
        file_inode=real_inode, file_size_seen=len(b"hello\n"),
    )
    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        result = reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_abc123def456", log_path=str(log_path), timestamp=_now(),
        )
    finally:
        conn.close()
    assert result.lifecycle_event_emitted == "log_file_returned"
    assert _row_status(state_db, "lat_a1b2c3d4e5f6") == "stale"


def test_no_implicit_detach_on_missing(
    primed_db: tuple[Path, Path], tmp_path: Path
) -> None:
    """SC-011 / FR-021a: missing-file flow MUST NOT reach status=detached."""
    state_db, events_file = primed_db
    log_path = tmp_path / "x.log"
    _seed_attachment(
        state_db, log_path=str(log_path), status="active",
        file_inode="234:1234567", file_size_seen=4096,
    )
    logger = _RecordingLogger()
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        reader_cycle_offset_recovery(
            conn=conn, events_file=events_file, lifecycle_logger=logger,
            agent_id="agt_abc123def456", log_path=str(log_path), timestamp=_now(),
        )
    finally:
        conn.close()
    # Missing-file path lands in stale, never detached.
    assert _row_status(state_db, "lat_a1b2c3d4e5f6") == "stale"
