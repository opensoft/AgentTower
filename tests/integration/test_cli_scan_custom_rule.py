"""End-to-end integration test for FEAT-003 US2 — config-driven matching."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    run_config_init,
    stop_daemon_if_alive,
)


def _scan(env, *, json_mode: bool = False, timeout: float = 15.0):
    cmd = ["agenttower", "scan", "--containers"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _list(env, *, json_mode: bool = False):
    cmd = ["agenttower", "list-containers"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=5.0)


def _write_fake(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def env_with_fake(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    fake_path = tmp_path / "docker-fake.json"
    fake_path.write_text(
        json.dumps({"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok", "results": []}}),
        encoding="utf-8",
    )
    env = isolated_env(home)
    env["AGENTTOWER_TEST_DOCKER_FAKE"] = str(fake_path)
    run_config_init(env)
    try:
        yield env, fake_path, home
    finally:
        stop_daemon_if_alive(env)


def _set_name_contains(home: Path, values: list[str] | str) -> None:
    config = home / ".config/opensoft/agenttower/config.toml"
    if isinstance(values, list):
        body = '[containers]\nname_contains = [' + ", ".join(f'"{v}"' for v in values) + "]\n"
    else:
        body = f'[containers]\nname_contains = "{values}"\n'
    config.write_text(body, encoding="utf-8")


def test_custom_name_contains_matches_multiple_substrings(env_with_fake) -> None:
    env, fake_path, home = env_with_fake
    _set_name_contains(home, ["bench", "dev"])
    _write_fake(
        fake_path,
        {
            "list_running": {
                "action": "ok",
                "containers": [
                    {"container_id": "abc", "name": "py-bench", "image": "i1", "status": "running"},
                    {"container_id": "def", "name": "api-dev", "image": "i2", "status": "running"},
                    {"container_id": "ghi", "name": "postgres", "image": "i3", "status": "running"},
                ],
            },
            "inspect": {
                "action": "ok",
                "results": [
                    {"container_id": "abc", "name": "py-bench", "image": "i1", "status": "running"},
                    {"container_id": "def", "name": "api-dev", "image": "i2", "status": "running"},
                ],
            },
        },
    )
    ensure_daemon(env)
    result = _scan(env, json_mode=True)
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    assert payload["result"]["matched_count"] == 2
    assert payload["result"]["ignored_count"] == 1


def test_rule_change_marks_previously_active_inactive(env_with_fake) -> None:
    """FR-049: previously-matching row becomes inactive after rule narrows."""
    env, fake_path, home = env_with_fake
    _set_name_contains(home, ["bench", "dev"])
    _write_fake(
        fake_path,
        {
            "list_running": {
                "action": "ok",
                "containers": [
                    {"container_id": "abc", "name": "py-bench"},
                    {"container_id": "def", "name": "api-dev"},
                ],
            },
            "inspect": {
                "action": "ok",
                "results": [
                    {"container_id": "abc", "name": "py-bench", "image": "i", "status": "running"},
                    {"container_id": "def", "name": "api-dev", "image": "i", "status": "running"},
                ],
            },
        },
    )
    ensure_daemon(env)
    _scan(env)

    # Narrow the rule: only "dev" remains. py-bench is still running but
    # no longer in scope; reconciliation MUST flip it to inactive (FR-049).
    _set_name_contains(home, ["dev"])
    second = _scan(env, json_mode=True)
    assert second.returncode == 0
    payload = json.loads(second.stdout.strip())
    assert payload["result"]["matched_count"] == 1  # api-dev only
    assert payload["result"]["inactive_reconciled_count"] == 1  # py-bench

    # list-containers shows py-bench as active=0.
    list_result = _list(env, json_mode=True)
    rows = json.loads(list_result.stdout.strip())["result"]["containers"]
    by_id = {r["id"]: r for r in rows}
    assert by_id["abc"]["active"] is False
    assert by_id["def"]["active"] is True
