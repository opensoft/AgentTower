"""Unit tests for the FEAT-002 lifecycle primitives (T006).

Covers lock acquisition / release, ``assert_paths_safe``, pid-file
read/write/remove helpers, and ``LifecycleLogger`` line shape.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from agenttower.socket_api import lifecycle


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def test_acquire_exclusive_lock_succeeds_on_empty_state(tmp_path: Path) -> None:
    lock_path = tmp_path / "agenttowerd.lock"
    fd = lifecycle.acquire_exclusive_lock(lock_path)
    try:
        assert lock_path.exists()
        assert (lock_path.stat().st_mode & 0o777) == 0o600
    finally:
        lifecycle.release_lock(fd)


def test_acquire_exclusive_lock_fails_non_blocking_when_held(tmp_path: Path) -> None:
    lock_path = tmp_path / "agenttowerd.lock"
    first = lifecycle.acquire_exclusive_lock(lock_path)
    try:
        with pytest.raises(lifecycle.LockHeldError):
            lifecycle.acquire_exclusive_lock(lock_path)
    finally:
        lifecycle.release_lock(first)


def test_acquire_exclusive_lock_releases_on_fd_close(tmp_path: Path) -> None:
    lock_path = tmp_path / "agenttowerd.lock"
    first = lifecycle.acquire_exclusive_lock(lock_path)
    lifecycle.release_lock(first)
    # Should now be re-acquirable.
    second = lifecycle.acquire_exclusive_lock(lock_path)
    lifecycle.release_lock(second)


def test_acquire_exclusive_lock_refuses_broader_mode(tmp_path: Path) -> None:
    lock_path = tmp_path / "agenttowerd.lock"
    lock_path.write_text("")
    os.chmod(lock_path, 0o644)
    with pytest.raises(PermissionError):
        lifecycle.acquire_exclusive_lock(lock_path)


# ---------------------------------------------------------------------------
# assert_paths_safe
# ---------------------------------------------------------------------------


def _make_dir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    return path


def _make_file(path: Path, mode: int = 0o600) -> Path:
    path.write_text("")
    os.chmod(path, mode)
    return path


def test_assert_paths_safe_accepts_0700_directories(tmp_path: Path) -> None:
    state = _make_dir(tmp_path / "state")
    logs = _make_dir(tmp_path / "logs")
    lifecycle.assert_paths_safe(state_dir=state, logs_dir=logs)


def test_assert_paths_safe_rejects_0755_state_dir(tmp_path: Path) -> None:
    state = _make_dir(tmp_path / "state", mode=0o755)
    logs = _make_dir(tmp_path / "logs")
    with pytest.raises(lifecycle.UnsafePathError) as info:
        lifecycle.assert_paths_safe(state_dir=state, logs_dir=logs)
    assert info.value.path == state
    assert "0o755" in info.value.reason


def test_assert_paths_safe_rejects_missing_dir(tmp_path: Path) -> None:
    state = tmp_path / "state-missing"
    logs = _make_dir(tmp_path / "logs")
    with pytest.raises(lifecycle.UnsafePathError):
        lifecycle.assert_paths_safe(state_dir=state, logs_dir=logs)


def test_assert_paths_safe_rejects_broader_pid_file(tmp_path: Path) -> None:
    state = _make_dir(tmp_path / "state")
    logs = _make_dir(tmp_path / "logs")
    pid = _make_file(state / "agenttowerd.pid", mode=0o644)
    with pytest.raises(lifecycle.UnsafePathError):
        lifecycle.assert_paths_safe(state_dir=state, logs_dir=logs, pid_file=pid)


def test_assert_paths_safe_passes_when_optional_files_missing(tmp_path: Path) -> None:
    state = _make_dir(tmp_path / "state")
    logs = _make_dir(tmp_path / "logs")
    # Optional files don't exist yet → should pass.
    lifecycle.assert_paths_safe(
        state_dir=state,
        logs_dir=logs,
        lock_file=state / "agenttowerd.lock",
        pid_file=state / "agenttowerd.pid",
        log_file=logs / "agenttowerd.log",
    )


# ---------------------------------------------------------------------------
# Pid file
# ---------------------------------------------------------------------------


def test_write_then_read_pid_file_roundtrips(tmp_path: Path) -> None:
    pid_path = tmp_path / "agenttowerd.pid"
    lifecycle.write_pid_file(pid_path, 4242)
    assert pid_path.exists()
    assert (pid_path.stat().st_mode & 0o777) == 0o600
    assert lifecycle.read_pid_file(pid_path) == 4242


def test_read_pid_file_returns_none_when_missing(tmp_path: Path) -> None:
    assert lifecycle.read_pid_file(tmp_path / "missing") is None


def test_read_pid_file_returns_none_when_malformed(tmp_path: Path) -> None:
    pid_path = tmp_path / "bad.pid"
    pid_path.write_text("not-a-number\n")
    assert lifecycle.read_pid_file(pid_path) is None


def test_remove_pid_file_idempotent(tmp_path: Path) -> None:
    pid_path = tmp_path / "agenttowerd.pid"
    lifecycle.write_pid_file(pid_path, 1)
    lifecycle.remove_pid_file(pid_path)
    lifecycle.remove_pid_file(pid_path)  # second call must not raise
    assert not pid_path.exists()


# ---------------------------------------------------------------------------
# Lifecycle log
# ---------------------------------------------------------------------------


_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$"
)


def test_lifecycle_logger_emits_one_tsv_line_per_event(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "agenttowerd.log"
    logger = lifecycle.LifecycleLogger(log_path)
    try:
        logger.emit(lifecycle.EVENT_DAEMON_STARTING, pid=4321, state_dir=str(tmp_path))
        logger.emit(lifecycle.EVENT_DAEMON_READY, socket=str(tmp_path / "x.sock"))
    finally:
        logger.close()

    assert log_path.exists()
    assert (log_path.stat().st_mode & 0o777) == 0o600
    lines = log_path.read_text(encoding="utf-8").rstrip("\n").splitlines()
    assert len(lines) == 2
    for line in lines:
        ts, level_kv, event_kv, *_ = line.split("\t")
        assert _TS_RE.match(ts), f"bad ts: {ts!r}"
        assert level_kv.startswith("level=")
        assert event_kv.startswith("event=")


def test_lifecycle_logger_rejects_unknown_event(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "agenttowerd.log"
    logger = lifecycle.LifecycleLogger(log_path)
    try:
        with pytest.raises(ValueError):
            logger.emit("bogus_event")
    finally:
        logger.close()


def test_lifecycle_logger_creates_log_dir(tmp_path: Path) -> None:
    log_path = tmp_path / "deep" / "logs" / "agenttowerd.log"
    logger = lifecycle.LifecycleLogger(log_path)
    try:
        logger.emit(lifecycle.EVENT_DAEMON_STARTING)
    finally:
        logger.close()
    assert log_path.parent.is_dir()
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600


# ---------------------------------------------------------------------------
# T026: stale-artifact classification & recovery.
# ---------------------------------------------------------------------------


import socket as _socket


def _make_real_socket_at(path: Path) -> _socket.socket:
    """Bind a closed AF_UNIX socket inode at *path* (used to fake stale state)."""
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    saved = os.getcwd()
    try:
        os.chdir(path.parent)
        sock.bind(path.name)
    finally:
        os.chdir(saved)
    sock.close()  # leaves the inode on disk
    return sock


def test_classify_socket_path_missing(tmp_path: Path) -> None:
    assert lifecycle.classify_socket_path(tmp_path / "absent.sock") == "missing"


def test_classify_socket_path_stale_socket(tmp_path: Path) -> None:
    sock_path = tmp_path / "agenttowerd.sock"
    _make_real_socket_at(sock_path)
    assert lifecycle.classify_socket_path(sock_path) == "stale_socket"


def test_classify_socket_path_regular_file_is_refuse(tmp_path: Path) -> None:
    p = tmp_path / "agenttowerd.sock"
    p.write_text("not a socket")
    assert lifecycle.classify_socket_path(p) == "refuse"


def test_classify_socket_path_directory_is_refuse(tmp_path: Path) -> None:
    p = tmp_path / "agenttowerd.sock"
    p.mkdir()
    assert lifecycle.classify_socket_path(p) == "refuse"


def test_classify_socket_path_symlink_is_refuse(tmp_path: Path) -> None:
    p = tmp_path / "agenttowerd.sock"
    p.symlink_to(tmp_path / "nowhere")
    assert lifecycle.classify_socket_path(p) == "refuse"


def test_recover_stale_artifacts_unlinks_stale_socket_and_pid(tmp_path: Path) -> None:
    sock_path = tmp_path / "agenttowerd.sock"
    pid_path = tmp_path / "agenttowerd.pid"
    log_path = tmp_path / "logs" / "agenttowerd.log"
    _make_real_socket_at(sock_path)
    pid_path.write_text("12345\n")
    logger = lifecycle.LifecycleLogger(log_path)
    try:
        lifecycle.recover_stale_artifacts(
            socket_path=sock_path, pid_path=pid_path, logger=logger
        )
    finally:
        logger.close()
    assert not sock_path.exists()
    assert not pid_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "event=daemon_recovering" in log_text
    assert "reason=stale_socket" in log_text
    assert "reason=stale_pid" in log_text


def test_recover_stale_artifacts_refuses_regular_file_at_socket_path(tmp_path: Path) -> None:
    sock_path = tmp_path / "agenttowerd.sock"
    pid_path = tmp_path / "agenttowerd.pid"
    sock_path.write_text("not a socket")
    with pytest.raises(lifecycle.StaleArtifactRefused) as info:
        lifecycle.recover_stale_artifacts(socket_path=sock_path, pid_path=pid_path)
    assert info.value.kind == "regular file"
    # Refused — file untouched.
    assert sock_path.read_text() == "not a socket"


def test_recover_stale_artifacts_refuses_directory_at_socket_path(tmp_path: Path) -> None:
    sock_path = tmp_path / "agenttowerd.sock"
    sock_path.mkdir()
    with pytest.raises(lifecycle.StaleArtifactRefused) as info:
        lifecycle.recover_stale_artifacts(
            socket_path=sock_path, pid_path=tmp_path / "x.pid"
        )
    assert info.value.kind == "directory"
    assert sock_path.is_dir()


def test_recover_stale_artifacts_refuses_dangling_symlink(tmp_path: Path) -> None:
    sock_path = tmp_path / "agenttowerd.sock"
    sock_path.symlink_to(tmp_path / "nowhere")
    with pytest.raises(lifecycle.StaleArtifactRefused) as info:
        lifecycle.recover_stale_artifacts(
            socket_path=sock_path, pid_path=tmp_path / "x.pid"
        )
    assert info.value.kind == "symlink"
    assert sock_path.is_symlink()


def test_recover_stale_artifacts_no_op_on_clean_state(tmp_path: Path) -> None:
    # No socket, no pid file → just returns without raising or emitting.
    log_path = tmp_path / "logs" / "agenttowerd.log"
    logger = lifecycle.LifecycleLogger(log_path)
    try:
        lifecycle.recover_stale_artifacts(
            socket_path=tmp_path / "agenttowerd.sock",
            pid_path=tmp_path / "agenttowerd.pid",
            logger=logger,
        )
    finally:
        logger.close()
    log_text = log_path.read_text(encoding="utf-8")
    assert "event=daemon_recovering" not in log_text
