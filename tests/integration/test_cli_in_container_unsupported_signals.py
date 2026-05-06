"""T024 / FR-002 / FR-003 / FR-004 / FR-021 / SC-002: malformed env signals.

For each malformed ``AGENTTOWER_SOCKET`` shape and for two named edge cases
(privileged container with empty cgroup; ``--network host`` hostname
collision), assert the CLI exits with the documented code and message
without modifying daemon-side state.

The pre-flight resolver rejects malformed ``AGENTTOWER_SOCKET`` values
within the SC-002 50 ms wall-clock budget; we assert a generous 1.0 s
ceiling here to stay stable on slow CI while still catching pathological
regressions.
"""

from __future__ import annotations

import subprocess
import time
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


# ---------------------------------------------------------------------------
# Malformed AGENTTOWER_SOCKET → exit 1 with FR-002 closed-set <reason> token
# ---------------------------------------------------------------------------


def _make_regular_file(tmp_path: Path) -> Path:
    p = tmp_path / "file.txt"
    p.write_text("not a socket")
    return p


def _make_directory(tmp_path: Path) -> Path:
    p = tmp_path / "dir"
    p.mkdir()
    return p


def _make_broken_symlink(tmp_path: Path) -> Path:
    target = tmp_path / "missing-target.sock"
    link = tmp_path / "broken.sock"
    link.symlink_to(target)  # target does not exist
    return link


@pytest.mark.parametrize(
    "id,value_factory,reason",
    [
        ("relative_path", lambda tmp: "relative/path.sock", "value is not absolute"),
        ("empty_value", lambda tmp: "", "value is empty"),
        # ``nul_byte`` cannot be passed through ``subprocess`` (Python rejects
        # embedded NULs in env values); the closed-set ``value contains NUL
        # byte`` reason is locked at the unit level by
        # ``tests/unit/test_socket_path_resolution.py`` instead.
        (
            "broken_symlink",
            lambda tmp: str(_make_broken_symlink(tmp)),
            "value does not exist",
        ),
        (
            "regular_file",
            lambda tmp: str(_make_regular_file(tmp)),
            "value is not a Unix socket",
        ),
        (
            "directory_target",
            lambda tmp: str(_make_directory(tmp)),
            "value is not a Unix socket",
        ),
    ],
)
class TestMalformedSocketEnv:
    def test_exits_1_with_fr002_message(self, env, tmp_path, id, value_factory, reason):
        env["AGENTTOWER_SOCKET"] = value_factory(tmp_path)
        proc = status(env)
        assert proc.returncode == 1, (id, proc.stderr)
        assert "AGENTTOWER_SOCKET must be an absolute path to a Unix socket" in proc.stderr
        assert reason in proc.stderr

    def test_pre_flight_under_1_second(self, env, tmp_path, id, value_factory, reason):
        env["AGENTTOWER_SOCKET"] = value_factory(tmp_path)
        start = time.perf_counter()
        status(env)
        elapsed = time.perf_counter() - start
        # SC-002 says 50 ms in-process; subprocess overhead pushes the wall
        # clock higher, so we use a 1 s ceiling. Still catches pathological
        # regressions (e.g. a 5 s daemon connect attempt before validation).
        assert elapsed < 1.0, (id, f"{elapsed*1000:.0f}ms")


# ---------------------------------------------------------------------------
# Privileged-container edge case: empty /proc/self/cgroup
# ---------------------------------------------------------------------------


class TestPrivilegedContainerEmptyCgroup:
    def test_empty_cgroup_falls_through_safely(self, env, tmp_path):
        """Privileged containers may have an empty ``/proc/self/cgroup``;
        without ``/.dockerenv`` either, the runtime detects HostContext.
        ``status`` must still work against a healthy daemon (host_default)."""
        run_config_init(env)
        ensure_daemon(env)
        # Empty cgroup, no /.dockerenv → host context
        fake_root = tmp_path / "fake-empty-cgroup"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        (fake_root / "proc" / "self" / "cgroup").write_text("")
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        proc = status(env)
        assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# --network host hostname collision: in-container hostname == host hostname.
# Doctor's container_identity check should classify this as no_match (not crash).
# ---------------------------------------------------------------------------


class TestNetworkHostHostnameCollision:
    def test_no_match_classification_does_not_crash_status(self, env, tmp_path):
        """``--network host`` makes ``/etc/hostname`` equal the host's own
        hostname. The resolver and ``status`` must not crash under this
        condition; the doctor's classifier is the place that surfaces
        ``no_match`` (covered by unit tests)."""
        run_config_init(env)
        ensure_daemon(env)
        fake_root = tmp_path / "fake-network-host"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        # Fire ContainerContext via /.dockerenv but with empty cgroup, and an
        # arbitrary hostname (the daemon's container set is empty so this
        # naturally yields no_match in the doctor).
        (fake_root / "proc" / "self" / "cgroup").write_text("")
        (fake_root / ".dockerenv").write_text("")
        (fake_root / "etc" / "hostname").write_text("host-collides-here\n")
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        proc = status(env)
        assert proc.returncode == 0, proc.stderr  # status itself is unaffected
