"""End-to-end integration test for `agenttower list-containers` (US1)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ._daemon_helpers import (
    ensure_daemon,
)


def _list(env, *, json_mode: bool = False, active_only: bool = False, timeout: float = 5.0):
    cmd = ["agenttower", "list-containers"]
    if active_only:
        cmd.append("--active-only")
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _scan(env, timeout: float = 15.0):
    return subprocess.run(
        ["agenttower", "scan", "--containers"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _write_fixture(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_list_containers_default_emits_header_only_when_empty(env_with_fake) -> None:
    env, _fake_path, _home = env_with_fake
    ensure_daemon(env)
    result = _list(env)
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0] == "ACTIVE\tID\tNAME\tIMAGE\tSTATUS\tLAST_SCANNED"


def test_list_containers_after_scan_shows_persisted_row(env_with_fake) -> None:
    env, fake_path, _home = env_with_fake
    _write_fixture(
        fake_path,
        {
            "list_running": {"action": "ok", "containers": [{"container_id": "abc", "name": "py-bench"}]},
            "inspect": {"action": "ok", "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}]},
        },
    )
    ensure_daemon(env)
    _scan(env)
    result = _list(env)
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines[0].startswith("ACTIVE\tID")
    body = lines[1].split("\t")
    assert body[0] == "1"
    assert body[1] == "abc"
    assert body[2] == "py-bench"


def test_list_containers_json_envelope(env_with_fake) -> None:
    env, fake_path, _home = env_with_fake
    _write_fixture(
        fake_path,
        {
            "list_running": {"action": "ok", "containers": [{"container_id": "abc", "name": "py-bench"}]},
            "inspect": {"action": "ok", "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}]},
        },
    )
    ensure_daemon(env)
    _scan(env)
    result = _list(env, json_mode=True)
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["filter"] == "all"
    containers = payload["result"]["containers"]
    assert len(containers) == 1
    assert {"id", "name", "image", "status", "labels", "mounts", "active", "last_scanned_at"}.issubset(containers[0].keys())


def test_list_containers_active_only_filters_inactive_rows(env_with_fake) -> None:
    env, fake_path, _home = env_with_fake
    # First scan: persist 1 active row.
    _write_fixture(
        fake_path,
        {
            "list_running": {"action": "ok", "containers": [{"container_id": "abc", "name": "py-bench"}]},
            "inspect": {"action": "ok", "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}]},
        },
    )
    ensure_daemon(env)
    _scan(env)

    # Second scan: empty Docker → row reconciled inactive.
    _write_fixture(
        fake_path,
        {"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok", "results": []}},
    )
    _scan(env)

    all_rows = _list(env)
    assert all_rows.returncode == 0
    lines = all_rows.stdout.splitlines()
    assert len(lines) == 2  # header + 1 inactive row
    assert lines[1].startswith("0\t")

    active_rows = _list(env, active_only=True)
    assert active_rows.returncode == 0
    lines = active_rows.stdout.splitlines()
    assert len(lines) == 1  # header only — no active rows
