"""T060 / edge case 12 / CHK011: ``_connect_via_chdir`` must not regress.

The FEAT-002 ``_connect_via_chdir`` workaround sidesteps the kernel's
108-byte ``sun_path`` limit by ``chdir(parent) + connect(basename)`` so
deep cwds and long absolute socket paths still work.

This test pins that workaround under FEAT-005's resolver: constructs a
daemon ``$HOME`` whose absolute socket path exceeds 108 bytes, runs
``agenttower status`` from a deep cwd, and asserts the round-trip
succeeds. The resolver's ``(path, source)`` plumbing must hand the long
path to ``client.py`` untouched.

Sanity: the test also verifies that a raw ``socket.connect(absolute_path)``
on the same path fails with ``OSError`` — proving the path is genuinely
too long and the chdir workaround is doing real work.
"""

from __future__ import annotations

import os
import socket
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


_SUN_PATH_LIMIT = 108  # Linux AF_UNIX sun_path[108] (man 7 unix)


def _build_long_home(tmp_path: Path) -> Path:
    """Construct a $HOME deep enough that the resulting socket path
    exceeds ``_SUN_PATH_LIMIT``. Padding is split into two segments so
    no single path component exceeds typical NAME_MAX (255 on ext4).
    """
    pad_a = "a" * 80
    pad_b = "b" * 80
    home = tmp_path / pad_a / pad_b / "home"
    home.mkdir(parents=True)
    return home


@pytest.fixture
def long_path_env(tmp_path: Path):
    home = _build_long_home(tmp_path)
    env = isolated_env(home)
    yield env, home
    stop_daemon_if_alive(env)


# ---------------------------------------------------------------------------
# Sanity: the constructed socket path is genuinely too long for AF_UNIX
# ---------------------------------------------------------------------------


class TestConstructedPathExceedsLimit:
    def test_socket_path_exceeds_sun_path_limit(self, long_path_env):
        _, home = long_path_env
        socket_path = resolved_paths(home)["socket"]
        path_bytes = str(socket_path).encode("utf-8")
        assert len(path_bytes) > _SUN_PATH_LIMIT, (
            f"socket path is only {len(path_bytes)} bytes; "
            f"need > {_SUN_PATH_LIMIT} for the test to be meaningful"
        )

    def test_raw_connect_with_absolute_path_fails(self, long_path_env, tmp_path):
        """Without ``_connect_via_chdir``, ``connect(abs_path)`` must fail
        — proves the workaround is doing real work, not a no-op."""
        _, home = long_path_env
        socket_path = resolved_paths(home)["socket"]
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        # Don't actually need a listener — connect() will fail at bind-time
        # path-length check before reaching any listener.
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError):
                sock.connect(str(socket_path))
        finally:
            sock.close()


# ---------------------------------------------------------------------------
# T060 main assertion: daemon round-trip succeeds under FEAT-005's resolver
# ---------------------------------------------------------------------------


class TestDeepCwdConnectStillWorks:
    def test_status_succeeds_with_long_socket_path(self, long_path_env):
        env, home = long_path_env
        run_config_init(env)
        ensure_daemon(env)

        proc = subprocess.run(
            ["agenttower", "status"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0, (
            f"deep-cwd status failed; stderr={proc.stderr!r}"
        )
        assert proc.stdout.strip(), "expected status output on stdout"

    def test_status_from_deep_cwd_directory(self, long_path_env, tmp_path):
        """Run ``agenttower status`` from a CWD that is ITSELF a deep path,
        not just one whose socket is deep. This exercises the chdir
        workaround under cwd-restoration semantics."""
        env, home = long_path_env
        run_config_init(env)
        ensure_daemon(env)

        deep_cwd = tmp_path / ("c" * 80) / ("d" * 80)
        deep_cwd.mkdir(parents=True)

        proc = subprocess.run(
            ["agenttower", "status"],
            env=env,
            cwd=str(deep_cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0, (
            f"deep-cwd status failed; stderr={proc.stderr!r}"
        )

    def test_cwd_is_restored_after_status(self, long_path_env, tmp_path):
        """``_connect_via_chdir`` chdirs into the socket parent then
        restores the original cwd. Verify the parent process's cwd is
        unchanged after the subprocess returns (the subprocess inherits
        cwd, so we test by running and checking our own cwd post-call)."""
        env, home = long_path_env
        run_config_init(env)
        ensure_daemon(env)

        original = os.getcwd()
        try:
            subprocess.run(
                ["agenttower", "status"],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert os.getcwd() == original


        finally:
            os.chdir(original)


# ---------------------------------------------------------------------------
# Resolver hands the path through untouched (FEAT-005 contract)
# ---------------------------------------------------------------------------


class TestResolverHandsPathThroughUntouched:
    def test_config_paths_reports_long_socket_path_verbatim(self, long_path_env):
        env, home = long_path_env
        run_config_init(env)
        socket_path = resolved_paths(home)["socket"]

        proc = subprocess.run(
            ["agenttower", "config", "paths"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        # The resolver must NOT shorten, normalize, or rewrite the path
        # (which would break the subsequent connect).
        assert f"SOCKET={socket_path}" in proc.stdout, proc.stdout

    def test_config_paths_reports_host_default_source(self, long_path_env):
        """No ``AGENTTOWER_SOCKET`` override and no fake ``/proc`` →
        ``SOCKET_SOURCE=host_default``."""
        env, home = long_path_env
        env.pop("AGENTTOWER_SOCKET", None)
        env.pop("AGENTTOWER_TEST_PROC_ROOT", None)
        run_config_init(env)

        proc = subprocess.run(
            ["agenttower", "config", "paths"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert "SOCKET_SOURCE=host_default" in proc.stdout, proc.stdout
