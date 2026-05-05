"""Integration tests for ``agenttower ensure-daemon`` (T015).

Covers FR-002, FR-003, FR-007, FR-028, SC-001, SC-002, SC-008.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _set_state_dir_mode(paths: dict[str, Path], mode: int) -> None:
    os.chmod(paths["state_dir"], mode)


def test_refuses_when_feat001_not_initialized(env: dict[str, str]) -> None:
    proc = ensure_daemon(env)
    assert proc.returncode == 1
    assert "agenttower is not initialized" in proc.stderr


def test_first_run_starts_daemon_and_prints_ready(env: dict[str, str]) -> None:
    run_config_init(env)
    paths = resolved_paths(Path(env["HOME"]))
    proc = ensure_daemon(env)
    assert proc.returncode == 0, proc.stderr
    assert "agenttowerd ready:" in proc.stdout
    assert paths["socket"].exists()
    assert stat.S_IMODE(paths["socket"].lstat().st_mode) == 0o600
    assert paths["pid_file"].exists()
    assert stat.S_IMODE(paths["pid_file"].lstat().st_mode) == 0o600
    assert paths["lock_file"].exists()
    assert paths["log_file"].exists()


def test_second_run_is_idempotent_and_reports_started_false(env: dict[str, str]) -> None:
    run_config_init(env)
    first = ensure_daemon(env, json_mode=True)
    assert first.returncode == 0, first.stderr
    second = ensure_daemon(env, json_mode=True)
    assert second.returncode == 0, second.stderr

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["ok"] is True
    assert first_payload["started"] is True
    assert second_payload["ok"] is True
    assert second_payload["started"] is False
    assert first_payload["pid"] == second_payload["pid"]
    assert first_payload["socket_path"] == second_payload["socket_path"]


def test_twenty_sequential_invocations_leave_one_daemon(env: dict[str, str]) -> None:
    """SC-002 — 20 reruns → exactly one live daemon."""
    run_config_init(env)
    pids: set[int] = set()
    for _ in range(20):
        proc = ensure_daemon(env, json_mode=True)
        assert proc.returncode == 0, proc.stderr
        pids.add(json.loads(proc.stdout)["pid"])
    # All invocations refer to the same daemon pid.
    assert len(pids) == 1


def test_first_ensure_daemon_within_two_seconds(env: dict[str, str]) -> None:
    """SC-001 — first ensure-daemon ready within 2 s on a normally-loaded host."""
    run_config_init(env)
    start = time.monotonic()
    proc = ensure_daemon(env)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 2.0


def test_refuses_when_state_dir_has_unsafe_mode(env: dict[str, str]) -> None:
    """SC-008 — state-dir mode 0755 → refusal."""
    run_config_init(env)
    paths = resolved_paths(Path(env["HOME"]))
    _set_state_dir_mode(paths, 0o755)
    try:
        proc = ensure_daemon(env)
    finally:
        _set_state_dir_mode(paths, 0o700)
    assert proc.returncode == 1
    assert "unsafe permissions" in proc.stderr


def test_json_output_shape(env: dict[str, str]) -> None:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.keys() == {"ok", "started", "pid", "socket_path", "state_path"}
    assert payload["ok"] is True
    assert payload["started"] is True
    assert isinstance(payload["pid"], int)
