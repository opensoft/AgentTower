"""FR-025 / analyze finding A2 — production binary refuses to honor a leaked
``AGENTTOWER_TEST_PROC_ROOT`` (T055).

Per Clarifications 2026-05-06 (analyze A2), when ``AGENTTOWER_TEST_PROC_ROOT``
is set in a non-test invocation (no companion ``AGENTTOWER_TEST_*`` var
present), the CLI MUST exit ``1`` with an explicit stderr message rather
than silently substituting the fake ``/proc`` for the real one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ._daemon_helpers import isolated_env


def _spawn_cli(env, *args):
    return subprocess.run(
        ["agenttower", *args], env=env, capture_output=True, text=True, timeout=10
    )


def _stripped_env(home: Path) -> dict[str, str]:
    """Build an isolated subprocess env with NO AGENTTOWER_TEST_* companions.

    Uses the canonical ``isolated_env`` helper for $PATH / $HOME setup, then
    strips any AGENTTOWER_TEST_* var that may have leaked from the host
    pytest invocation so the production guard's "no companion" rule can be
    exercised cleanly.
    """
    env = isolated_env(home)
    for key in list(env.keys()):
        if key.startswith("AGENTTOWER_TEST_"):
            env.pop(key, None)
    return env


class TestProductionRejection:
    def test_proc_root_alone_is_refused(self, tmp_path):
        env = _stripped_env(tmp_path)
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(tmp_path / "fake-proc")
        proc = _spawn_cli(env, "config", "paths")
        assert proc.returncode == 1
        assert "AGENTTOWER_TEST_PROC_ROOT" in proc.stderr
        assert "outside the test harness" in proc.stderr

    def test_proc_root_with_companion_var_allowed(self, tmp_path):
        """When at least one other AGENTTOWER_TEST_* var is also set (the
        normal pytest pattern), the guard does not fire."""
        env = _stripped_env(tmp_path)
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(tmp_path / "fake-proc")
        env["AGENTTOWER_TEST_DOCKER_FAKE"] = "1"  # companion marker
        proc = _spawn_cli(env, "--version")
        assert proc.returncode == 0
        assert "AGENTTOWER_TEST_PROC_ROOT" not in proc.stderr

    def test_no_proc_root_no_guard(self, tmp_path):
        """When PROC_ROOT is unset, the guard never fires."""
        env = _stripped_env(tmp_path)
        proc = _spawn_cli(env, "--version")
        assert proc.returncode == 0


class TestErrorMessageShape:
    def test_stderr_includes_actionable_remediation(self, tmp_path):
        env = _stripped_env(tmp_path)
        env["AGENTTOWER_TEST_PROC_ROOT"] = "/nonexistent"
        proc = _spawn_cli(env, "--version")
        assert "unset it" in proc.stderr
