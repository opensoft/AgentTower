"""T021 / US1 AS1 / SC-001: ``agenttower status`` works the same from a
simulated bench container as from the host.

Scope:

* Eight-key ``status`` payload shape on a healthy daemon.
* Stable subset (``alive``, ``state_path``, ``schema_version``,
  ``daemon_version``) is byte-for-byte equivalent between host and
  in-container invocations.
* Volatile fields (``pid``, ``start_time_utc``, ``uptime_seconds``) are
  observed but not byte-compared.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    run_config_init,
    status,
    stop_daemon_if_alive,
)
from ._proc_fixtures import fake_proc_root  # noqa: F401  (registers fixture)


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


# Eight-key status payload per FEAT-002 contract (FR-005, SC-001)
EXPECTED_STATUS_KEYS = {
    "alive",
    "pid",
    "start_time_utc",
    "uptime_seconds",
    "socket_path",
    "state_path",
    "schema_version",
    "daemon_version",
}


# Subset that is byte-stable across host vs in-container invocations
STABLE_KEYS = ("alive", "state_path", "schema_version", "daemon_version")


def _fake_container_root(tmp_path: Path) -> Path:
    """Build a fake `/proc` that fires ContainerContext via a cgroup signal."""
    fake_root = tmp_path / "fake-container-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text(
        "0::/docker/abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567\n"
    )
    return fake_root


class TestStatusInContainerShape:
    def test_status_returns_eight_keys_under_simulated_container(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(_fake_container_root(tmp_path))
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        # AGENTTOWER_SOCKET overrides to the host daemon's socket — this
        # simulates the in-container CLI's mounted /run/agenttower/agenttowerd.sock
        from ._daemon_helpers import resolved_paths


        socket_path = resolved_paths(tmp_path)["socket"]
        env["AGENTTOWER_SOCKET"] = str(socket_path)

        proc = status(env, json_mode=True)
        assert proc.returncode == 0, proc.stderr
        envelope = json.loads(proc.stdout)
        assert envelope.get("ok") is True
        result = envelope["result"]
        assert set(result.keys()) >= EXPECTED_STATUS_KEYS, (
            f"missing keys: {EXPECTED_STATUS_KEYS - set(result.keys())}"
        )

    def test_stable_subset_matches_host_invocation(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)

        # Host invocation
        host_proc = status(env, json_mode=True)
        assert host_proc.returncode == 0
        host_result = json.loads(host_proc.stdout)["result"]

        # In-container invocation against the same daemon
        from ._daemon_helpers import resolved_paths


        socket_path = resolved_paths(tmp_path)["socket"]
        in_container_env = isolated_env(tmp_path)
        in_container_env["AGENTTOWER_TEST_PROC_ROOT"] = str(_fake_container_root(tmp_path))
        in_container_env["AGENTTOWER_TEST_DOCKER_FAKE"] = "1"
        in_container_env["AGENTTOWER_SOCKET"] = str(socket_path)

        in_container_proc = status(in_container_env, json_mode=True)
        assert in_container_proc.returncode == 0, in_container_proc.stderr
        in_container_result = json.loads(in_container_proc.stdout)["result"]

        for key in STABLE_KEYS:
            assert host_result[key] == in_container_result[key], (
                f"{key} drifted: host={host_result[key]!r} "
                f"in_container={in_container_result[key]!r}"
            )


class TestStatusInContainerExitCodes:
    def test_status_exits_0_on_healthy_daemon_from_simulated_container(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(_fake_container_root(tmp_path))
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        from ._daemon_helpers import resolved_paths

        env["AGENTTOWER_SOCKET"] = str(resolved_paths(tmp_path)["socket"])
        proc = status(env)
        assert proc.returncode == 0, proc.stderr
