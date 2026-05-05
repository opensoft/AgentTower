"""End-to-end integration tests for FEAT-003 US3 — degraded scan classes."""

from __future__ import annotations

import json
import sqlite3
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


def _scan(env, *, json_mode: bool = True, timeout: float = 15.0):
    cmd = ["agenttower", "scan", "--containers"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


@pytest.fixture()
def env_with_fake(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    fake_path = tmp_path / "docker-fake.json"
    env = isolated_env(home)
    env["AGENTTOWER_TEST_DOCKER_FAKE"] = str(fake_path)
    fake_path.write_text(
        json.dumps({"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok"}}),
        encoding="utf-8",
    )
    run_config_init(env)
    try:
        yield env, fake_path, home
    finally:
        stop_daemon_if_alive(env)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "action, expected_code",
    [
        ("command_not_found", "docker_unavailable"),
        ("permission_denied", "docker_permission_denied"),
        ("non_zero_exit", "docker_failed"),
        ("timeout", "docker_timeout"),
        ("malformed", "docker_malformed"),
    ],
)
def test_whole_scan_failure_classes(env_with_fake, action, expected_code) -> None:
    env, fake_path, home = env_with_fake
    _write(
        fake_path,
        {
            "list_running": {"action": action, "message": f"fake {action}"},
            "inspect": {"action": "ok", "results": []},
        },
    )
    ensure_daemon(env)
    start = time.monotonic()
    result = _scan(env)
    elapsed = time.monotonic() - start
    assert elapsed < 3.0, f"degraded {action} exceeded 3 s budget (took {elapsed:.2f}s)"
    assert result.returncode == 3
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == expected_code

    # Daemon stays alive: status still works.
    status_result = status(env)
    assert status_result.returncode == 0

    # A `container_scans` row exists with status='degraded'.
    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        rows = conn.execute(
            "SELECT status, error_code FROM container_scans"
        ).fetchall()
    finally:
        conn.close()
    assert any(r == ("degraded", expected_code) for r in rows)

    # JSONL gained exactly one container_scan_degraded record.
    events_text = paths["events_file"].read_text(encoding="utf-8")
    matched_lines = [
        line
        for line in events_text.splitlines()
        if '"type":"container_scan_degraded"' in line and expected_code in line
    ]
    assert len(matched_lines) == 1


def test_partial_inspect_failure_returns_exit_code_5(env_with_fake) -> None:
    """FR-044: top-level error_code is the FIRST per-container error in docker ps order."""
    env, fake_path, _home = env_with_fake
    _write(
        fake_path,
        {
            "list_running": {
                "action": "ok",
                "containers": [
                    {"container_id": "A", "name": "a-bench"},  # first in order
                    {"container_id": "B", "name": "b-bench"},  # second
                ],
            },
            "inspect": {
                "action": "ok",
                "results": [],
                "per_container_errors": {
                    "A": {"code": "docker_timeout", "message": "fake timeout for A"},
                    "B": {"code": "docker_failed", "message": "fake non-zero for B"},
                },
            },
        },
    )
    ensure_daemon(env)
    result = _scan(env)
    assert result.returncode == 5  # degraded, partial
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True  # envelope is ok
    assert payload["result"]["status"] == "degraded"
    # FR-044: first per-container error code in docker ps order.
    assert payload["result"]["error_code"] == "docker_timeout"
    assert len(payload["result"]["error_details"]) == 2


def test_lifecycle_log_remains_bounded_with_4kib_error(env_with_fake) -> None:
    """FR-033: lifecycle log row contains only closed-set tokens, no raw stderr."""
    env, fake_path, home = env_with_fake
    huge = "X" * 4096
    _write(
        fake_path,
        {
            "list_running": {"action": "non_zero_exit", "message": huge},
            "inspect": {"action": "ok"},
        },
    )
    ensure_daemon(env)
    _scan(env)

    paths = resolved_paths(home)
    log_text = paths["log_file"].read_text(encoding="utf-8")
    # Lifecycle rows must not contain the 4 KiB blob; the bounded message
    # caps at ≤2048 chars and our scan_completed line includes only counts +
    # error code, not the bounded message itself.
    assert huge not in log_text
    assert "scan_completed" in log_text
    assert "docker_failed" in log_text
