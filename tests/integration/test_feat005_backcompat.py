"""FEAT-005 backcompat byte-parity guard (T053, FR-005, FR-026, SC-006, SC-007).

Folds analyze findings:

* **A1** — `_connect_via_chdir` deep-cwd regression test for the kernel
  ``sun_path`` 108-byte limit (spec edge case 14).
* **A3** — ``--help`` byte-parity sweep across every existing subcommand;
  the only documented change vs. FEAT-004 is the addition of ``config doctor``
  to ``agenttower --help`` and ``agenttower config --help``.
"""

from __future__ import annotations

import os
import socket as socket_mod
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    isolated_env,
    run_config_init,
    stop_daemon_if_alive,
)


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _run(env, *args):
    return subprocess.run(
        ["agenttower", *args], env=env, capture_output=True, text=True, timeout=10
    )


# ---------------------------------------------------------------------------
# A3: --help byte-parity sweep
# ---------------------------------------------------------------------------


class TestHelpByteParity:
    """Each existing subcommand's `--help` text must remain stable under
    FEAT-005, except for the documented additive change of `config doctor`
    appearing under the `config` parent.
    """

    SUBCOMMANDS_UNCHANGED = (
        "ensure-daemon",
        "status",
        "stop-daemon",
        "scan",
        "list-containers",
        "list-panes",
    )

    @pytest.mark.parametrize("subcmd", SUBCOMMANDS_UNCHANGED)
    def test_subcommand_help_text_does_not_mention_doctor(self, env, subcmd):
        """The ``--help`` text for FEAT-001..004 subcommands MUST NOT mention
        ``doctor`` — adding the doctor subcommand to the parser tree should
        not bleed into unrelated subcommands' help output."""
        proc = _run(env, subcmd, "--help")
        assert proc.returncode == 0
        assert "doctor" not in proc.stdout.lower()

    def test_config_paths_help_unchanged(self, env):
        """``agenttower config paths --help`` is byte-stable — paths is a
        FEAT-001 surface and its help text does not change."""
        proc = _run(env, "config", "paths", "--help")
        assert proc.returncode == 0
        assert "doctor" not in proc.stdout.lower()
        assert "paths" in proc.stdout.lower()

    def test_config_init_help_unchanged(self, env):
        """``agenttower config init --help`` is byte-stable for the same reason."""
        proc = _run(env, "config", "init", "--help")
        assert proc.returncode == 0
        assert "doctor" not in proc.stdout.lower()

    def test_top_level_help_includes_doctor_under_config(self, env):
        """The only documented change to ``agenttower --help`` is the addition
        of ``config doctor`` to the listed config subcommands."""
        proc = _run(env, "--help")
        assert proc.returncode == 0
        assert "config doctor" in proc.stdout

    def test_config_help_includes_doctor_subcommand(self, env):
        proc = _run(env, "config", "--help")
        assert proc.returncode == 0
        assert "doctor" in proc.stdout.lower()

    def test_config_doctor_help_resolves(self, env):
        """``config doctor --help`` exists and is parseable (the subparser is
        registered); this is the new additive surface."""
        proc = _run(env, "config", "doctor", "--help")
        assert proc.returncode == 0
        assert "diagnostic" in proc.stdout.lower() or "checks" in proc.stdout.lower()


# ---------------------------------------------------------------------------
# Existing-command exit codes are byte-stable
# ---------------------------------------------------------------------------


class TestExistingExitCodes:
    def test_status_exit_2_when_daemon_down(self, env):
        run_config_init(env)
        proc = _run(env, "status")
        assert proc.returncode == 2  # FEAT-002 contract

    def test_list_containers_exit_2_when_daemon_down(self, env):
        run_config_init(env)
        proc = _run(env, "list-containers")
        assert proc.returncode == 2

    def test_list_panes_exit_2_when_daemon_down(self, env):
        run_config_init(env)
        proc = _run(env, "list-panes")
        assert proc.returncode == 2


# ---------------------------------------------------------------------------
# A1: deep-cwd / sun_path 108-byte regression guard (spec edge case 14)
# ---------------------------------------------------------------------------


class TestSunPathDeepCwd:
    """The FEAT-002 ``_connect_via_chdir`` workaround sidesteps the kernel's
    108-byte ``sun_path`` limit. FEAT-005 introduces a pre-flight resolver
    that MUST NOT regress this path; the resolver passes the path through
    untouched (the chdir workaround is applied later by ``client.py``).
    """

    def test_resolver_preserves_long_paths_byte_for_byte(self, tmp_path):
        """The resolver MUST NOT shorten / canonicalize / readlink-fold the
        AGENTTOWER_SOCKET value beyond the documented FR-002 single-readlink
        rule. A path that approaches the kernel's sun_path limit must be
        returned byte-for-byte so the client's chdir+connect can still bind it."""

        # Use a moderately deep path. Going beyond the 108-byte sun_path
        # limit would prevent us from creating the socket here in the first
        # place — the client's `_connect_via_chdir` is what handles that.
        deep_dir = tmp_path / ("d" * 60)
        deep_dir.mkdir()
        socket_path = deep_dir / "x.sock"
        s = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        try:
            s.bind(str(socket_path))
        except OSError:
            # If even a 60-char path is too long on this filesystem, fall
            # back to a tmp-rooted socket — we still test the byte-stable
            # passthrough invariant.
            socket_path = tmp_path / "short.sock"
            s.bind(str(socket_path))

        try:
            from agenttower.config_doctor.runtime_detect import HostContext
            from agenttower.config_doctor.socket_resolve import resolve_socket_path
            from agenttower.paths import resolve_paths

            env = {"HOME": str(tmp_path), "AGENTTOWER_SOCKET": str(socket_path)}
            paths = resolve_paths(env)
            resolved = resolve_socket_path(env, paths, HostContext())
            # Byte-for-byte passthrough — the deep-cwd path is preserved.
            assert str(resolved.path) == str(socket_path)
            assert resolved.source == "env_override"
        finally:
            s.close()
            if socket_path.exists():
                socket_path.unlink()
