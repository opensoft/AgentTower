"""US3 preview/status edge-case unit tests (T105/T106/T108/T109).

Drives ``LogService.attach_log_status`` and ``LogService.attach_log_preview``
in-process to verify the FR-032 / FR-033 / FR-064 / Clarifications Q3
contracts at unit granularity. Integration coverage of these methods
through the CLI lives in ``test_feat007_lifecycle.py``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agenttower.agents.mutex import AgentLockMap
from agenttower.logs import host_fs as host_fs_mod
from agenttower.logs.docker_exec import FakeDockerExecRunner
from agenttower.logs.mutex import LogPathLockMap
from agenttower.logs.service import LogService
from agenttower.agents.errors import RegistrationError
from agenttower.state import schema


AGENT_ID = "agt_abc123def456"
CONTAINER_ID = "c" * 64
PANE_KEY = (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 0, "%17")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def log_service(tmp_path: Path) -> tuple[LogService, Path, Path]:
    """A LogService bound to an empty state.sqlite3 + events.jsonl in tmp_path."""
    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)

    runner = FakeDockerExecRunner({"calls": []})
    service = LogService(
        connection_factory=lambda: sqlite3.connect(str(state_db), isolation_level=None),
        agent_locks=AgentLockMap(),
        log_path_locks=LogPathLockMap(),
        events_file=events_file,
        schema_version=5,
        daemon_home=tmp_path,
        docker_exec_runner=runner,
        lifecycle_logger=None,
    )
    return service, state_db, events_file


def _seed_agent(state_db: Path, *, agent_id: str = AGENT_ID, active: int = 1) -> None:
    now = "2026-05-08T14:00:00.000000+00:00"
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (CONTAINER_ID, "bench", "bench:latest", "running",
             "{}", "[]", "{}", "brett", "/home/brett", 1, now, now),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            PANE_KEY + ("bench", "brett", 1, "/dev/pts/0", "bash",
                        "/home/brett", "main", 1, 1, now, now),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id,) + PANE_KEY + ("slave", "codex", "codex", "", None, "{}", now, now, None, active),
        )
    finally:
        conn.close()


def _seed_attachment(
    state_db: Path,
    *,
    log_path: str,
    status: str,
    attachment_id: str = "lat_a1b2c3d4e5f6",
    agent_id: str = AGENT_ID,
) -> None:
    now = "2026-05-08T14:00:00.000000+00:00"
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO log_attachments (attachment_id, agent_id, "
            "container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "log_path, status, source, pipe_pane_command, prior_pipe_target, "
            "attached_at, last_status_at, superseded_at, superseded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (attachment_id, agent_id) + PANE_KEY + (
                log_path, status, "explicit", "docker exec ...", None,
                now, now, None, None, now,
            ),
        )
        conn.execute(
            "INSERT INTO log_offsets (agent_id, log_path, byte_offset, "
            "line_offset, last_event_offset, last_output_at, file_inode, "
            "file_size_seen, created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 0, NULL, NULL, 0, ?, ?)",
            (agent_id, log_path, now, now),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T105 — preview allowed statuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("allowed_status", ["active", "stale", "detached"])
def test_t105_preview_allowed_against_active_stale_detached(
    log_service, tmp_path: Path, allowed_status: str
) -> None:
    """FR-033 / Clarifications Q3 — preview succeeds when most-recent row
    is in {active, stale, detached}."""
    service, state_db, _ = log_service
    log_path = tmp_path / "preview.log"
    log_path.write_bytes(b"hello world\n")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status=allowed_status)

    result = service.attach_log_preview(
        {"schema_version": 5, "agent_id": AGENT_ID, "lines": 5},
        socket_peer_uid=1000,
    )
    assert result["agent_id"] == AGENT_ID
    assert result["log_path"] == str(log_path)
    assert result["lines"] == ["hello world"]


def test_t105_preview_against_superseded_refused_attachment_not_found(
    log_service, tmp_path: Path
) -> None:
    """FR-033 / Q3 — preview against a most-recent ``superseded`` row
    refuses with ``attachment_not_found``."""
    service, state_db, _ = log_service
    log_path = tmp_path / "old.log"
    log_path.write_bytes(b"")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="superseded")

    with pytest.raises(RegistrationError) as exc_info:
        service.attach_log_preview(
            {"schema_version": 5, "agent_id": AGENT_ID, "lines": 1},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "attachment_not_found"


def test_t105_preview_against_no_row_refused_attachment_not_found(
    log_service,
) -> None:
    """FR-033 / Q3 — preview against an agent with no log_attachments row
    refuses with ``attachment_not_found``."""
    service, state_db, _ = log_service
    _seed_agent(state_db)  # agent exists but no attachment row

    with pytest.raises(RegistrationError) as exc_info:
        service.attach_log_preview(
            {"schema_version": 5, "agent_id": AGENT_ID, "lines": 1},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "attachment_not_found"


# ---------------------------------------------------------------------------
# T106 — preview against allowed status but file missing
# ---------------------------------------------------------------------------


def test_t106_preview_file_missing_refused_log_file_missing(
    log_service, tmp_path: Path
) -> None:
    """FR-033 / Q3 — row in allowed status but host file gone → refuse
    with closed-set ``log_file_missing``."""
    service, state_db, _ = log_service
    log_path = tmp_path / "vanished.log"  # never created
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    with pytest.raises(RegistrationError) as exc_info:
        service.attach_log_preview(
            {"schema_version": 5, "agent_id": AGENT_ID, "lines": 1},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "log_file_missing"


def test_t106_preview_file_missing_does_not_mutate_attachment(
    log_service, tmp_path: Path
) -> None:
    """The preview path MUST NOT change the attachment row when refusing
    ``log_file_missing`` — status changes happen via the FEAT-008 reader
    cycle (FR-026), not via --preview."""
    service, state_db, _ = log_service
    log_path = tmp_path / "vanished.log"
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    with pytest.raises(RegistrationError):
        service.attach_log_preview(
            {"schema_version": 5, "agent_id": AGENT_ID, "lines": 1},
            socket_peer_uid=1000,
        )
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT status FROM log_attachments WHERE agent_id = ?", (AGENT_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "active", "preview must NOT mutate row status (FR-033 + FR-026)"


# ---------------------------------------------------------------------------
# T108 — preview line cap
# ---------------------------------------------------------------------------


def test_t108_preview_n_equals_one(log_service, tmp_path: Path) -> None:
    """N=1 returns exactly the last line (FR-033)."""
    service, state_db, _ = log_service
    log_path = tmp_path / "many.log"
    log_path.write_bytes(b"line1\nline2\nline3\n")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    result = service.attach_log_preview(
        {"schema_version": 5, "agent_id": AGENT_ID, "lines": 1},
        socket_peer_uid=1000,
    )
    assert result["lines"] == ["line3"]


def test_t108_preview_n_at_upper_bound_200(log_service, tmp_path: Path) -> None:
    """N=200 (the FR-033 hard cap) accepted."""
    service, state_db, _ = log_service
    log_path = tmp_path / "exact.log"
    log_path.write_bytes(b"only-one\n")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    result = service.attach_log_preview(
        {"schema_version": 5, "agent_id": AGENT_ID, "lines": 200},
        socket_peer_uid=1000,
    )
    assert result["lines"] == ["only-one"]


@pytest.mark.parametrize("bad_n", [0, 201, -1])
def test_t108_preview_n_out_of_range_value_out_of_set(
    log_service, tmp_path: Path, bad_n: int
) -> None:
    """N=0 / N=201 / N=-1 refused with ``value_out_of_set`` (FR-033 + FR-064)."""
    service, state_db, _ = log_service
    _seed_agent(state_db)
    _seed_attachment(
        state_db, log_path=str(tmp_path / "x.log"), status="active",
    )

    with pytest.raises(RegistrationError) as exc_info:
        service.attach_log_preview(
            {"schema_version": 5, "agent_id": AGENT_ID, "lines": bad_n},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "value_out_of_set"


def test_t108_preview_empty_file_returns_empty_lines(log_service, tmp_path: Path) -> None:
    """Empty file (zero bytes) returns an empty lines array."""
    service, state_db, _ = log_service
    log_path = tmp_path / "empty.log"
    log_path.write_bytes(b"")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    result = service.attach_log_preview(
        {"schema_version": 5, "agent_id": AGENT_ID, "lines": 5},
        socket_peer_uid=1000,
    )
    assert result["lines"] == []


def test_t108_preview_fewer_than_n_lines_returns_all(log_service, tmp_path: Path) -> None:
    """File with M < N lines returns all M lines."""
    service, state_db, _ = log_service
    log_path = tmp_path / "short.log"
    log_path.write_bytes(b"a\nb\n")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    result = service.attach_log_preview(
        {"schema_version": 5, "agent_id": AGENT_ID, "lines": 50},
        socket_peer_uid=1000,
    )
    assert result["lines"] == ["a", "b"]


# ---------------------------------------------------------------------------
# T109 — status universal read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("any_status", ["active", "stale", "detached", "superseded"])
def test_t109_status_succeeds_for_every_attachment_status(
    log_service, tmp_path: Path, any_status: str
) -> None:
    """FR-032 / Q3 — --status returns the most recent row regardless of status,
    including ``superseded`` (which preview refuses)."""
    service, state_db, _ = log_service
    _seed_agent(state_db)
    _seed_attachment(
        state_db, log_path=str(tmp_path / f"{any_status}.log"), status=any_status,
    )

    result = service.attach_log_status(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    assert result["agent_id"] == AGENT_ID
    assert result["attachment"] is not None
    assert result["attachment"]["status"] == any_status
    assert result["offset"] is not None


def test_t109_status_for_agent_with_no_attachment_returns_nulls(log_service) -> None:
    """FR-032 / Q3 — agent registered but no attachment → null payload."""
    service, state_db, _ = log_service
    _seed_agent(state_db)

    result = service.attach_log_status(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    assert result == {
        "agent_id": AGENT_ID,
        "attachment": None,
        "offset": None,
    }


def test_t109_status_never_invokes_docker_exec(log_service, tmp_path: Path) -> None:
    """FR-032 — --status is read-only. The docker-exec runner MUST NOT be
    invoked even when an active row exists.

    Verified by giving the service a fake runner that records every call
    and asserting ``recorded_argv`` stays empty across status reads.
    """
    service, state_db, _ = log_service
    log_path = tmp_path / "x.log"
    log_path.write_bytes(b"")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    # The service's docker_exec_runner is the FakeDockerExecRunner from the
    # fixture — its recorded_argv list is empty before any call.
    runner: FakeDockerExecRunner = service.docker_exec_runner  # type: ignore[assignment]
    assert runner.recorded_argv == []

    # Run --status against every status (including missing-row case).
    for _ in range(5):
        service.attach_log_status(
            {"schema_version": 5, "agent_id": AGENT_ID},
            socket_peer_uid=1000,
        )

    assert runner.recorded_argv == [], (
        f"FR-032 --status MUST NOT issue docker exec; got {runner.recorded_argv}"
    )


def test_t109_status_never_reads_host_file(
    log_service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-032 — --status MUST NOT read the host log file.

    Verified by stubbing host_fs.read_tail_lines to raise; the test passes
    iff status doesn't reach that code path.
    """
    service, state_db, _ = log_service
    log_path = tmp_path / "x.log"
    log_path.write_bytes(b"some content\n")
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path=str(log_path), status="active")

    sentinel_calls: list[str] = []

    def _exploding_read(*args, **kwargs):
        sentinel_calls.append(str(args))
        raise AssertionError("host_fs.read_tail_lines must not be called by status")

    monkeypatch.setattr(host_fs_mod, "read_tail_lines", _exploding_read)

    # Status should succeed without touching the file.
    result = service.attach_log_status(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    assert result["attachment"]["status"] == "active"
    assert sentinel_calls == []


def test_t109_status_with_unknown_agent_id_returns_agent_not_found(log_service) -> None:
    """FR-032 — when the agent doesn't exist, status raises agent_not_found.
    (The Q3 universal-read rule applies AFTER agent resolution.)"""
    service, _, _ = log_service
    with pytest.raises(RegistrationError) as exc_info:
        service.attach_log_status(
            {"schema_version": 5, "agent_id": "agt_deadbeef0000"},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "agent_not_found"
