"""Integration tests for ``agenttower stop-daemon`` (T032).

Covers FR-018, FR-022, US4 acceptance scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon,
    stop_daemon_if_alive,
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def test_stop_daemon_clean_default_output(env: dict[str, str]) -> None:
    run_config_init(env)
    ensure_daemon(env)
    proc = stop_daemon(env)
    assert proc.returncode == 0, proc.stderr
    assert "agenttowerd stopped:" in proc.stdout
    paths = resolved_paths(Path(env["HOME"]))
    assert not paths["socket"].exists()
    assert not paths["pid_file"].exists()


def test_stop_daemon_json_output(env: dict[str, str]) -> None:
    run_config_init(env)
    ensure_daemon(env)
    proc = stop_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["stopped"] is True
    assert payload["socket_path"].endswith("agenttowerd.sock")


def test_stop_daemon_when_no_daemon_running(env: dict[str, str]) -> None:
    """US4 acceptance #3 — exit 2 when no daemon to stop."""
    run_config_init(env)
    proc = stop_daemon(env)
    assert proc.returncode == 2
    assert "no reachable daemon to stop" in proc.stderr


def test_stop_daemon_no_daemon_does_not_invoke_docker_or_tmux(
    env: dict[str, str], tmp_path: Path
) -> None:
    """FR-020 + analyze finding E1 — no fallback when daemon unavailable."""
    run_config_init(env)
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
    proc = stop_daemon(env_with_shims)
    assert proc.returncode == 2
    assert not marker.exists()
