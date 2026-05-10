"""T018 / FR-019 / FR-026: ``config paths`` SOCKET_SOURCE= line is the LAST line.

The first six ``KEY=value`` lines (``CONFIG_FILE``, ``STATE_DB``,
``EVENTS_FILE``, ``LOGS_DIR``, ``SOCKET``, ``CACHE_DIR``) are the FEAT-001
contract; FEAT-005 appends exactly one trailing line
``SOCKET_SOURCE=<env_override|mounted_default|host_default>`` after them.

Covers the three resolution branches; the integration counterpart in
``test_cli_in_container_socket_override.py`` covers env_override and
host_default end-to-end. This file adds the mounted_default branch via the
``AGENTTOWER_TEST_PROC_ROOT`` fixture and locks the ordering invariant.
"""

from __future__ import annotations

import socket as socket_mod
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import isolated_env, stop_daemon_if_alive
from ._proc_fixtures import fake_proc_root  # noqa: F401  (registers fixture)


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _run_paths(env):
    return subprocess.run(
        ["agenttower", "config", "paths"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Ordering invariant — the trailing line is LAST and the first six are FIXED
# ---------------------------------------------------------------------------


class TestSocketSourceOrdering:
    """``SOCKET_SOURCE=`` is appended AFTER the FEAT-001 six-line block."""

    def test_six_existing_lines_in_declared_paths_order_unchanged(self, env):
        """First seven lines mirror the FEAT-001..005 ``Paths`` field
        order. FEAT-008 appends ten ``EVENTS_*`` lines after; this test
        only checks the first seven for stability."""
        proc = _run_paths(env)
        assert proc.returncode == 0
        lines = proc.stdout.rstrip("\n").splitlines()
        # FEAT-001 + FEAT-005 SOCKET_SOURCE + FEAT-008 EVENTS_* = 17 total.
        assert len(lines) == 17
        assert lines[0].startswith("CONFIG_FILE=")
        assert lines[1].startswith("STATE_DB=")
        assert lines[2].startswith("EVENTS_FILE=")
        assert lines[3].startswith("LOGS_DIR=")
        assert lines[4].startswith("SOCKET=")
        assert lines[5].startswith("CACHE_DIR=")
        assert lines[6].startswith("SOCKET_SOURCE=")
        # After SOCKET_SOURCE come the FEAT-008 EVENTS_* lines.
        assert lines[7].startswith("EVENTS_")

    def test_socket_source_is_the_last_pre_events_line(self, env):
        """SOCKET_SOURCE is the FINAL of the FEAT-001..005 lines.
        FEAT-008 appends EVENTS_* keys after it (FR-019 ordering of the
        original block is preserved)."""
        proc = _run_paths(env)
        lines = proc.stdout.rstrip("\n").splitlines()
        assert lines[6].startswith("SOCKET_SOURCE=")

    def test_no_json_mode_introduced(self, env):
        """``config paths`` does not add ``--json`` in FEAT-005."""
        proc = subprocess.run(
            ["agenttower", "config", "paths", "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        # argparse rejects unknown flag → exit code != 0; specifically 2
        assert proc.returncode != 0


# ---------------------------------------------------------------------------
# host_default — dev-box runs in a container, so we must pin runtime context
# to host via an empty fake `/proc` to avoid mounted_default firing
# ---------------------------------------------------------------------------


class TestHostDefault:
    def test_host_default_token_emitted(self, env, tmp_path):
        fake_root = tmp_path / "fake-host-proc"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        (fake_root / "proc" / "self" / "cgroup").write_text("0::/\n")
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        proc = _run_paths(env)
        assert proc.returncode == 0
        # SOCKET_SOURCE is line 7 (FEAT-001..005 block); FEAT-008
        # appends 10 EVENTS_* lines after, so it's no longer last.
        lines = proc.stdout.rstrip("\n").splitlines()
        assert lines[6] == "SOCKET_SOURCE=host_default"


# ---------------------------------------------------------------------------
# env_override — AGENTTOWER_SOCKET wins regardless of context
# ---------------------------------------------------------------------------


class TestEnvOverride:
    def test_env_override_token_emitted(self, env, tmp_path):
        sock_path = tmp_path / "x.sock"
        s = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        s.bind(str(sock_path))
        try:
            env["AGENTTOWER_SOCKET"] = str(sock_path)
            proc = _run_paths(env)
            assert proc.returncode == 0
            # SOCKET_SOURCE is line 7 (FEAT-001..005 block); FEAT-008
            # appends EVENTS_* lines after.
            lines = proc.stdout.rstrip("\n").splitlines()
            assert lines[6] == "SOCKET_SOURCE=env_override"
        finally:
            s.close()
            if sock_path.exists():
                sock_path.unlink()

    def test_env_override_socket_line_reflects_override(self, env, tmp_path):
        """The ``SOCKET=`` line and ``SOCKET_SOURCE=`` line cannot drift —
        both are sourced from a single ``resolve_socket_path`` call."""
        sock_path = tmp_path / "x.sock"
        s = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        s.bind(str(sock_path))
        try:
            env["AGENTTOWER_SOCKET"] = str(sock_path)
            proc = _run_paths(env)
            assert proc.returncode == 0
            lines = proc.stdout.rstrip("\n").splitlines()
            socket_line = next(line for line in lines if line.startswith("SOCKET="))
            source_line = next(line for line in lines if line.startswith("SOCKET_SOURCE="))
            assert socket_line == f"SOCKET={sock_path}"
            assert source_line == "SOCKET_SOURCE=env_override"
        finally:
            s.close()
            if sock_path.exists():
                sock_path.unlink()


# ---------------------------------------------------------------------------
# mounted_default — fixture-fired ContainerContext + a real socket at
# /run/agenttower/agenttowerd.sock
# ---------------------------------------------------------------------------


class TestMountedDefault:
    """The mounted-default candidate at ``/run/agenttower/agenttowerd.sock``
    fires only when:

    1. ``RuntimeContext`` is ``ContainerContext`` (fired via fake-/proc cgroup)
    2. ``AGENTTOWER_SOCKET`` is unset
    3. The mounted-default path resolves to a real ``S_ISSOCK``

    On a dev box where ``/run/agenttower/`` cannot be created (no root), this
    branch cannot be exercised end-to-end; the unit tests in
    ``test_socket_path_resolution.py`` already lock the resolver's behavior
    for this case. We skip rather than failing the suite.
    """

    def test_mounted_default_token_when_path_resolves(self, env, tmp_path):
        mount_dir = Path("/run/agenttower")
        try:
            mount_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            pytest.skip("cannot create /run/agenttower (need root); resolver unit test covers this")

        sock_path = mount_dir / "agenttowerd.sock"
        if sock_path.exists():
            pytest.skip("/run/agenttower/agenttowerd.sock already exists; refusing to clobber")

        s = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        try:
            s.bind(str(sock_path))
        except (PermissionError, OSError):
            s.close()
            pytest.skip("cannot bind socket under /run/agenttower")

        # Fixture-fire ContainerContext via fake /proc with a cgroup match.
        fake_root = tmp_path / "fake-container-proc"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        (fake_root / "proc" / "self" / "cgroup").write_text(
            "0::/docker/abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567\n"
        )
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")

        try:
            proc = _run_paths(env)
            assert proc.returncode == 0
            last = proc.stdout.rstrip("\n").splitlines()[-1]
            assert last == "SOCKET_SOURCE=mounted_default"
        finally:
            s.close()
            try:
                sock_path.unlink()
            except OSError:
                pass
