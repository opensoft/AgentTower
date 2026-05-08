"""Unit tests for FEAT-007 orphan recovery (T211 / FR-043 / FR-061)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agenttower.logs import lifecycle as logs_lifecycle
from agenttower.logs.docker_exec import DockerExecResult
from agenttower.logs.orphan_recovery import detect_orphans
from agenttower.state import schema


class _RecordingLogger:
    """Drop-in for the lifecycle logger; records emitted events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, *, level: str = "info", **fields: Any) -> None:
        self.events.append((event, fields))


class _StubRunner:
    """Returns a programmable result for any docker-exec call."""

    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, timeout_seconds: float = 5.0) -> DockerExecResult:
        self.calls.append(list(argv))
        return DockerExecResult(returncode=self.returncode, stdout=self.stdout, stderr="")


@pytest.fixture
def state_db(tmp_path: Path) -> Path:
    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()
    return state_db


def _seed_active_container(state_db: Path, *, container_id: str, bench_user: str = "brett") -> None:
    now = "2026-05-08T14:00:00.000000+00:00"
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (container_id, "bench-acme", "bench:latest", "running",
             "{}", "[]", "{}", bench_user, "/home/" + bench_user, 1, now, now),
        )
    finally:
        conn.close()


def test_no_active_containers_emits_nothing(state_db: Path, tmp_path: Path) -> None:
    runner = _StubRunner(stdout="")
    logger = _RecordingLogger()
    count = detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    assert count == 0
    assert logger.events == []
    assert runner.calls == []


def test_pane_with_no_active_pipe_is_not_orphan(state_db: Path, tmp_path: Path) -> None:
    container_id = "c" * 64
    _seed_active_container(state_db, container_id=container_id)
    # Pane exists but pane_pipe=0.
    runner = _StubRunner(stdout="main:0.0 0 \n")
    logger = _RecordingLogger()
    count = detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    assert count == 0
    assert logger.events == []


def test_pane_pipe_to_foreign_path_is_not_orphan(state_db: Path, tmp_path: Path) -> None:
    container_id = "c" * 64
    _seed_active_container(state_db, container_id=container_id)
    # Pipe targets /tmp/random.log — not under canonical-prefix.
    runner = _StubRunner(stdout="main:0.0 1 cat >> /tmp/random.log\n")
    logger = _RecordingLogger()
    count = detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    assert count == 0


def test_canonical_pipe_with_log_attachments_row_is_not_orphan(
    state_db: Path, tmp_path: Path
) -> None:
    """A canonical-pipe whose log_attachments row exists is the normal case."""
    container_id = "c" * 64
    agent_id = "agt_abc123def456"
    _seed_active_container(state_db, container_id=container_id)

    canonical = (
        f"{tmp_path}/.local/state/opensoft/agenttower/logs/"
        f"{container_id}/{agent_id}.log"
    )
    # Insert a matching log_attachments row.
    now = "2026-05-08T14:00:00.000000+00:00"
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (container_id, "/tmp/tmux-1000/default", "main", 0, 0, "%17",
             "bench-acme", "brett", 12345, "/dev/pts/0", "bash",
             "/home/brett", "main", 1, 1, now, now),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, container_id, "/tmp/tmux-1000/default", "main", 0, 0, "%17",
             "slave", "codex", "codex-01", "", None, "{}", now, now, None, 1),
        )
        conn.execute(
            "INSERT INTO log_attachments (attachment_id, agent_id, container_id, "
            "tmux_socket_path, tmux_session_name, tmux_window_index, "
            "tmux_pane_index, tmux_pane_id, log_path, status, source, "
            "pipe_pane_command, prior_pipe_target, attached_at, last_status_at, "
            "superseded_at, superseded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("lat_a1b2c3d4e5f6", agent_id, container_id, "/tmp/tmux-1000/default",
             "main", 0, 0, "%17", canonical, "active", "explicit",
             "docker exec ...", None, now, now, None, None, now),
        )
    finally:
        conn.close()

    # Pipe targets the canonical path — but the row exists, so not an orphan.
    # tmux's pane_pipe_command field returns the literal command that was
    # issued via shlex.quote(); for a path with no shell-meta chars this is
    # the bare path without quotes, matching what the daemon would have
    # written.
    import shlex as _shlex
    runner = _StubRunner(stdout=f"main:0.0 1 cat >> {_shlex.quote(canonical)}\n")
    logger = _RecordingLogger()
    count = detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    assert count == 0
    assert logger.events == []


def test_canonical_pipe_without_log_attachments_row_is_orphan(
    state_db: Path, tmp_path: Path
) -> None:
    """The canonical FR-043 case: pipe is live, no row → emit orphan event."""
    logs_lifecycle.reset_for_test()
    container_id = "c" * 64
    agent_id = "agt_abc123def456"
    _seed_active_container(state_db, container_id=container_id)

    canonical = (
        f"{tmp_path}/.local/state/opensoft/agenttower/logs/"
        f"{container_id}/{agent_id}.log"
    )
    # tmux's pane_pipe_command field returns the literal command that was
    # issued via shlex.quote(); for a path with no shell-meta chars this is
    # the bare path without quotes, matching what the daemon would have
    # written.
    import shlex as _shlex
    runner = _StubRunner(stdout=f"main:0.0 1 cat >> {_shlex.quote(canonical)}\n")
    logger = _RecordingLogger()

    count = detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    assert count == 1
    assert len(logger.events) == 1
    name, fields = logger.events[0]
    assert name == "log_attachment_orphan_detected"
    assert fields["container_id"] == container_id
    assert fields["pane_short_form"] == "main:0.0"


def test_orphan_event_suppressed_on_repeat(state_db: Path, tmp_path: Path) -> None:
    """FR-061: at most one orphan event per (container, pane, target) per daemon lifetime."""
    logs_lifecycle.reset_for_test()
    container_id = "c" * 64
    agent_id = "agt_abc123def456"
    _seed_active_container(state_db, container_id=container_id)

    canonical = (
        f"{tmp_path}/.local/state/opensoft/agenttower/logs/"
        f"{container_id}/{agent_id}.log"
    )
    # tmux's pane_pipe_command field returns the literal command that was
    # issued via shlex.quote(); for a path with no shell-meta chars this is
    # the bare path without quotes, matching what the daemon would have
    # written.
    import shlex as _shlex
    runner = _StubRunner(stdout=f"main:0.0 1 cat >> {_shlex.quote(canonical)}\n")
    logger = _RecordingLogger()

    detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    # Even though we ran twice, FR-061 suppression collapses to one event.
    assert len(logger.events) == 1


def test_docker_exec_failure_does_not_block_startup(state_db: Path, tmp_path: Path) -> None:
    """If tmux is missing or docker exec fails, orphan-pass is best-effort."""
    container_id = "c" * 64
    _seed_active_container(state_db, container_id=container_id)

    runner = _StubRunner(stdout="", returncode=1)
    logger = _RecordingLogger()

    count = detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    assert count == 0
    assert logger.events == []


def test_substring_canonical_path_classified_foreign_fr054(
    state_db: Path, tmp_path: Path
) -> None:
    """FR-054 + FR-043: chained-redirect trickery is foreign, not orphan."""
    logs_lifecycle.reset_for_test()
    container_id = "c" * 64
    agent_id = "agt_abc123def456"
    _seed_active_container(state_db, container_id=container_id)

    canonical = (
        f"{tmp_path}/.local/state/opensoft/agenttower/logs/"
        f"{container_id}/{agent_id}.log"
    )
    # Pipe contains the canonical path AS A SUBSTRING but isn't strict equality.
    evil = f"cat >> /tmp/innocent.log; cat >> '{canonical}'"
    runner = _StubRunner(stdout=f"main:0.0 1 {evil}\n")
    logger = _RecordingLogger()

    count = detect_orphans(
        connection_factory=lambda: sqlite3.connect(str(state_db)),
        docker_exec_runner=runner,
        daemon_home=tmp_path,
        lifecycle_logger=logger,
    )
    assert count == 0
    assert logger.events == []
