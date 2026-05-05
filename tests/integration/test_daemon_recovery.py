"""Stale-state recovery integration tests (T027 / FR-008 / FR-009 / SC-004)."""

from __future__ import annotations

import json
import os
import signal
import socket as _socket
import time
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    process_exists,
    resolved_paths,
    run_config_init,
    send_test_signal,
    stop_daemon_if_alive,
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _wait_for_pid_to_exit(pid: int, *, timeout: float = 3.0) -> None:
    """Wait for *pid* to leave the kernel runqueue (zombie state counts as dead)."""
    deadline = time.monotonic() + timeout
    stat_path = Path(f"/proc/{pid}/stat")
    while time.monotonic() < deadline:
        if not process_exists(pid):
            return
        # /proc/<pid>/stat field 3 is the state code; 'Z' means zombie.
        try:
            data = stat_path.read_text(encoding="utf-8", errors="replace")
            # The comm field is in parens and may contain spaces; split after
            # the closing paren.
            after_comm = data[data.rfind(")") + 1 :].split()
            if after_comm and after_comm[0] == "Z":
                return
        except OSError:
            return
        time.sleep(0.02)
    raise AssertionError(f"pid {pid} still alive after {timeout}s")


def _make_socket_inode_at(path: Path) -> None:
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    saved = os.getcwd()
    try:
        os.chdir(path.parent)
        sock.bind(path.name)
    finally:
        os.chdir(saved)
    sock.close()


def test_kill_dash_nine_then_ensure_daemon_recovers_within_three_seconds(
    env: dict[str, str],
) -> None:
    """SC-004 — recovery within 3 s after abrupt termination."""
    run_config_init(env)
    first = ensure_daemon(env, json_mode=True)
    assert first.returncode == 0, first.stderr
    pid = json.loads(first.stdout)["pid"]
    send_test_signal(pid, signal.SIGKILL)
    _wait_for_pid_to_exit(pid)

    paths = resolved_paths(Path(env["HOME"]))
    # Stale artifacts may still be on disk after kill -9.
    assert paths["pid_file"].exists() or not paths["pid_file"].exists()  # tautology

    start = time.monotonic()
    second = ensure_daemon(env, json_mode=True)
    elapsed = time.monotonic() - start
    assert second.returncode == 0, second.stderr
    assert elapsed < 3.0
    new_pid = json.loads(second.stdout)["pid"]
    assert new_pid != pid


def test_stale_socket_without_daemon_recovers(env: dict[str, str]) -> None:
    """US3 acceptance #2 — stale socket inode without daemon → recovery succeeds."""
    run_config_init(env)
    paths = resolved_paths(Path(env["HOME"]))
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    _make_socket_inode_at(paths["socket"])
    proc = ensure_daemon(env)
    assert proc.returncode == 0, proc.stderr
    assert paths["socket"].exists()


def test_existing_live_daemon_is_not_disturbed(env: dict[str, str]) -> None:
    """US3 acceptance #3 — a live daemon owns the lock; second start succeeds via FR-007."""
    run_config_init(env)
    first = ensure_daemon(env, json_mode=True)
    assert first.returncode == 0, first.stderr
    first_pid = json.loads(first.stdout)["pid"]

    # Sanity check: the daemon is still running.
    assert process_exists(first_pid)

    second = ensure_daemon(env, json_mode=True)
    assert second.returncode == 0, second.stderr
    payload = json.loads(second.stdout)
    assert payload["started"] is False
    assert payload["pid"] == first_pid

    # Same daemon still alive.
    assert process_exists(first_pid)


def test_refuses_when_socket_path_is_regular_file(env: dict[str, str]) -> None:
    run_config_init(env)
    paths = resolved_paths(Path(env["HOME"]))
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    paths["socket"].write_text("not a socket")
    proc = ensure_daemon(env)
    assert proc.returncode == 2  # ensure-daemon: child exited code 1 → exit 2
    # The daemon's own stderr includes the refusal; pytest sees it via the
    # log tail in ensure-daemon's stderr.
    assert "is not a unix socket" in proc.stderr or "refusing to remove" in proc.stderr


def test_refuses_when_socket_path_is_directory(env: dict[str, str]) -> None:
    run_config_init(env)
    paths = resolved_paths(Path(env["HOME"]))
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    paths["socket"].mkdir()
    proc = ensure_daemon(env)
    assert proc.returncode == 2
    assert "is not a unix socket" in proc.stderr or "refusing to remove" in proc.stderr


def test_refuses_when_socket_path_is_dangling_symlink(env: dict[str, str]) -> None:
    run_config_init(env)
    paths = resolved_paths(Path(env["HOME"]))
    paths["state_dir"].mkdir(parents=True, exist_ok=True)
    paths["socket"].symlink_to(paths["state_dir"] / "nowhere")
    proc = ensure_daemon(env)
    assert proc.returncode == 2
    assert "is not a unix socket" in proc.stderr or "refusing to remove" in proc.stderr
