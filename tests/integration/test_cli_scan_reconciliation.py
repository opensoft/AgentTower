"""End-to-end FEAT-003 reconciliation flow (US3 / SC-002 / FR-040)."""

from __future__ import annotations

import json
import sqlite3
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


def _set_fixture(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_first_seen_for(home: Path, container_id: str) -> str:
    conn = sqlite3.connect(str(resolved_paths(home)["state_db"]))
    try:
        row = conn.execute(
            "SELECT first_seen_at FROM containers WHERE container_id = ?",
            (container_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else ""


def test_active_inactive_reactivate_preserves_first_seen(env_with_fake) -> None:
    env, fake_path, home = env_with_fake

    # Scan #1: persist py-bench as active.
    _set_fixture(
        fake_path,
        {
            "list_running": {"action": "ok", "containers": [{"container_id": "abc", "name": "py-bench"}]},
            "inspect": {"action": "ok", "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}]},
        },
    )
    ensure_daemon(env)
    _scan(env)
    first_seen_initial = _read_first_seen_for(home, "abc")
    assert first_seen_initial != ""

    # Scan #2: container disappeared → row reconciled inactive (SC-002).
    _set_fixture(
        fake_path,
        {"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok"}},
    )
    second = _scan(env)
    payload = json.loads(second.stdout.strip())
    assert payload["result"]["inactive_reconciled_count"] == 1

    conn = sqlite3.connect(str(resolved_paths(home)["state_db"]))
    try:
        row = conn.execute(
            "SELECT active, first_seen_at FROM containers WHERE container_id = 'abc'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 0
    assert row[1] == first_seen_initial  # unchanged

    # Scan #3: container reappears → row re-activated, first_seen_at preserved (FR-040).
    _set_fixture(
        fake_path,
        {
            "list_running": {"action": "ok", "containers": [{"container_id": "abc", "name": "py-bench"}]},
            "inspect": {"action": "ok", "results": [{"container_id": "abc", "name": "py-bench", "image": "img-v2", "status": "running"}]},
        },
    )
    _scan(env)
    conn = sqlite3.connect(str(resolved_paths(home)["state_db"]))
    try:
        row = conn.execute(
            "SELECT active, first_seen_at, image FROM containers WHERE container_id = 'abc'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 1  # re-active
    assert row[1] == first_seen_initial  # FR-040: preserved
    assert row[2] == "img-v2"  # mutable field updated
