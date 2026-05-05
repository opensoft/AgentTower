"""End-to-end FEAT-003 concurrent-scan serialization (US3 / FR-023 / FR-035)."""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    run_config_init,
    stop_daemon_if_alive,
)


def _scan(env, timeout: float = 15.0):
    return subprocess.run(
        ["agenttower", "scan", "--containers", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture()
def env_with_slow_fake(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    fake_path = tmp_path / "docker-fake.json"
    fake_path.write_text(
        json.dumps(
            {
                "list_running": {
                    "action": "ok",
                    "delay_ms": 200,  # adapter sleep so scans actually overlap
                    "containers": [{"container_id": "abc", "name": "py-bench"}],
                },
                "inspect": {
                    "action": "ok",
                    "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}],
                },
            }
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


def test_two_parallel_scans_serialize_via_mutex(env_with_slow_fake) -> None:
    env, _fake_path, _home = env_with_slow_fake
    ensure_daemon(env)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        future_a = ex.submit(_scan, env)
        future_b = ex.submit(_scan, env)
        result_a = future_a.result()
        result_b = future_b.result()

    assert result_a.returncode == 0
    assert result_b.returncode == 0
    payload_a = json.loads(result_a.stdout.strip())["result"]
    payload_b = json.loads(result_b.stdout.strip())["result"]
    assert payload_a["scan_id"] != payload_b["scan_id"]

    # Order by started_at and assert later scan started AFTER the earlier scan
    # completed — i.e., the mutex serialized them.
    by_started = sorted([payload_a, payload_b], key=lambda p: p["started_at"])
    earlier, later = by_started
    earlier_completed = datetime.fromisoformat(earlier["completed_at"])
    later_started = datetime.fromisoformat(later["started_at"])
    assert later_started >= earlier_completed


def test_five_callers_no_crash(env_with_slow_fake) -> None:
    """FR-035: more than two concurrent callers may all run safely."""
    env, _fake_path, _home = env_with_slow_fake
    ensure_daemon(env)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(_scan, env) for _ in range(5)]
        results = [f.result() for f in futures]
    for result in results:
        assert result.returncode == 0
    scan_ids = {json.loads(r.stdout.strip())["result"]["scan_id"] for r in results}
    assert len(scan_ids) == 5
