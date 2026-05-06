"""Integration tests for ``agenttower status`` (T022).

Covers FR-016, FR-018, FR-020, SC-003.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    status,
    stop_daemon_if_alive,
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def test_status_default_output_six_lines(env: dict[str, str]) -> None:
    run_config_init(env)
    ensure_daemon(env)
    proc = status(env)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert len(lines) == 6
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == [
        "alive",
        "pid",
        "start_time",
        "uptime_seconds",
        "socket_path",
        "state_path",
    ]
    alive_line = lines[0]
    assert alive_line == "alive=true"


def test_status_json_output_shape(env: dict[str, str]) -> None:
    run_config_init(env)
    ensure_daemon(env)
    proc = status(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    result = payload["result"]
    assert set(result.keys()) == {
        "alive",
        "pid",
        "start_time_utc",
        "uptime_seconds",
        "socket_path",
        "state_path",
        "schema_version",
        "daemon_version",
    }
    assert result["alive"] is True
    # FEAT-004 bumps the schema to v3 (data-model.md §7); we read the
    # current version symbolically so future bumps don't break this gate.
    from agenttower.state.schema import CURRENT_SCHEMA_VERSION

    assert result["schema_version"] == CURRENT_SCHEMA_VERSION


def test_status_unavailable_returns_exit_2(env: dict[str, str]) -> None:
    """US2 acceptance #2 — unavailable socket → exit 2 with actionable message."""
    run_config_init(env)
    # No ensure-daemon — socket should be missing.
    proc = status(env)
    assert proc.returncode == 2
    assert "daemon is not running or socket is unreachable" in proc.stderr


def test_status_unavailable_does_not_invoke_docker_or_tmux(
    env: dict[str, str], tmp_path: Path
) -> None:
    """FR-020 + analyze finding E1 — no fallback to Docker/tmux/shell."""
    run_config_init(env)
    # Stub PATH to a directory whose 'docker'/'tmux' shims write a marker on
    # invocation. If status falls back to either, the marker appears.
    shim_dir = tmp_path / "shims"
    shim_dir.mkdir()
    marker = tmp_path / "FALLBACK_INVOKED"
    for tool in ("docker", "tmux"):
        shim = shim_dir / tool
        shim.write_text(
            f"#!/bin/sh\necho INVOKED-{tool} >> '{marker}'\nexit 0\n", encoding="utf-8"
        )
        shim.chmod(0o755)
    env_with_shims = {**env, "PATH": str(shim_dir) + ":" + env["PATH"]}
    proc = status(env_with_shims)
    assert proc.returncode == 2
    assert not marker.exists(), (
        f"status invoked a fallback tool: {marker.read_text() if marker.exists() else ''}"
    )


def test_status_round_trip_within_one_second(env: dict[str, str]) -> None:
    """SC-003 — status round-trip ≤ 1 s on a normally-loaded host."""
    run_config_init(env)
    ensure_daemon(env)
    start = time.monotonic()
    proc = status(env)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 1.0
