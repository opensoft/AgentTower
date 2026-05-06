"""T023 / US1 AS4 / edge case 3 / FR-005: missing socket mount → exit 2.

Scenario: a developer launched the bench container without mounting the host
daemon's socket. The CLI runs inside ContainerContext (cgroup signal fires)
but ``/run/agenttower/agenttowerd.sock`` does not exist; ``AGENTTOWER_SOCKET``
is unset. We expect the FEAT-002 ``DAEMON_UNAVAILABLE_MESSAGE`` and exit 2,
byte-for-byte preserved — and crucially, the host daemon (if any) is NOT
killed by this invocation.
"""

from __future__ import annotations

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


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _fake_container_root(tmp_path: Path) -> Path:
    fake_root = tmp_path / "fake-container-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text(
        "0::/docker/abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567\n"
    )
    return fake_root


# Byte-stable FEAT-002 message — must NOT change under FEAT-005
DAEMON_UNAVAILABLE_FRAGMENT = "daemon is not running or socket is unreachable"


class TestNoSocketMountInContainer:
    def test_status_exits_2_with_byte_stable_message(self, env, tmp_path):
        # Initialize config (so the FEAT-001 not-initialized path doesn't fire)
        run_config_init(env)
        # Fixture-fire ContainerContext but DON'T spawn a daemon and DON'T set
        # AGENTTOWER_SOCKET — the resolver will fall to mounted_default
        # (which doesn't exist) → host_default (which also doesn't exist).
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(_fake_container_root(tmp_path))
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")

        proc = status(env)
        assert proc.returncode == 2
        assert DAEMON_UNAVAILABLE_FRAGMENT in proc.stderr

    def test_no_raw_errno_leak(self, env, tmp_path):
        run_config_init(env)
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(_fake_container_root(tmp_path))
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        proc = status(env)
        assert "[Errno" not in proc.stderr
        assert "ECONNREFUSED" not in proc.stderr
        assert "ENOENT" not in proc.stderr

    def test_subsequent_real_daemon_status_succeeds(self, env, tmp_path):
        """The aborted in-container invocation does not poison the host daemon.

        We first run the no-mount status (exit 2), then start the daemon and
        run a normal host-side status — it must succeed."""
        run_config_init(env)
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(_fake_container_root(tmp_path))
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        proc = status(env)
        assert proc.returncode == 2

        # Drop the test seam, start a real daemon, status should work
        del env["AGENTTOWER_TEST_PROC_ROOT"]
        del env["AGENTTOWER_TEST_DOCKER_FAKE"]
        ensure_daemon(env)
        live = status(env)
        assert live.returncode == 0, live.stderr
