"""End-to-end integration test for `agenttower scan --containers` (US1)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


def _write_fake_fixture(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _scan_containers(env, *, json_mode: bool = False, timeout: float = 15.0):
    cmd = ["agenttower", "scan", "--containers"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


@pytest.fixture()
def env_with_fake(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    fake_path = tmp_path / "docker-fake.json"
    # Default to an empty-but-valid fake script so the daemon starts cleanly
    # even when a test does not write a custom fixture.
    fake_path.write_text(
        json.dumps(
            {"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok", "results": []}}
        ),
        encoding="utf-8",
    )
    env = isolated_env(home)
    env["AGENTTOWER_TEST_DOCKER_FAKE"] = str(fake_path)
    run_config_init(env)
    try:
        yield env, fake_path, home
    finally:
        stop_daemon_if_alive(env)


def test_scan_containers_default_summary(env_with_fake) -> None:
    env, fake_path, _home = env_with_fake
    _write_fake_fixture(
        fake_path,
        {
            "list_running": {
                "action": "ok",
                "containers": [
                    {"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"},
                    {"container_id": "def", "name": "redis", "image": "redis", "status": "running"},
                ],
            },
            "inspect": {
                "action": "ok",
                "results": [
                    {
                        "container_id": "abc",
                        "name": "py-bench",
                        "image": "img",
                        "status": "running",
                        "labels": {"opensoft.bench": "true"},
                        "mounts": [{"source": "/h", "target": "/workspace", "type": "bind", "mode": "rw", "rw": True}],
                    },
                ],
            },
        },
    )
    ensure_daemon(env)
    result = _scan_containers(env)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    pairs = (line.split("=", 1) for line in lines if "=" in line)
    by_key = {key: value for key, value in pairs}
    assert by_key["status"] == "ok"
    assert by_key["matched"] == "1"
    assert by_key["ignored"] == "1"
    assert by_key["inactive_reconciled"] == "0"


def test_scan_containers_json_envelope(env_with_fake) -> None:
    env, fake_path, _home = env_with_fake
    _write_fake_fixture(
        fake_path,
        {
            "list_running": {"action": "ok", "containers": [{"container_id": "abc", "name": "py-bench"}]},
            "inspect": {"action": "ok", "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}]},
        },
    )
    ensure_daemon(env)
    result = _scan_containers(env, json_mode=True)
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["status"] == "ok"
    assert payload["result"]["matched_count"] == 1
    assert payload["result"]["error_details"] == []


def test_scan_containers_empty_healthy_persists_zero_counter_row(env_with_fake) -> None:
    """FR-046: an empty healthy scan still persists a `container_scans` row."""
    env, fake_path, home = env_with_fake
    _write_fake_fixture(
        fake_path,
        {"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok", "results": []}},
    )
    ensure_daemon(env)
    result = _scan_containers(env)
    assert result.returncode == 0

    paths = resolved_paths(home)
    import sqlite3
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        rows = conn.execute(
            "SELECT matched_count, ignored_count, inactive_reconciled_count, status "
            "FROM container_scans"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(0, 0, 0, "ok")]


def test_bare_scan_without_target_flag_exits_one(env_with_fake) -> None:
    env, _fake_path, _home = env_with_fake
    result = subprocess.run(
        ["agenttower", "scan"], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 1
    assert "scan requires a target flag" in result.stderr
