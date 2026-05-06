"""Daemon-down doctor integration test (T033, FR-016, FR-024, FR-027, SC-004).

Validates the post-clarify Q1 short-circuit semantics: every check still
emits a CheckResult row; dependent checks carry status=info + sub_code
``daemon_unavailable``. No raw errno text leaks to stderr (FR-024).
"""

from __future__ import annotations

import json
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


def _run_doctor(env, *, json_mode=False):
    cmd = ["agenttower", "config", "doctor"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)


class TestDaemonDown:
    """Daemon never started; socket file does not exist (socket_missing)."""

    def test_exit_code_2_when_daemon_unavailable(self, env):
        run_config_init(env)  # config init runs; we never start the daemon
        proc = _run_doctor(env)
        assert proc.returncode == 2

    def test_socket_reachable_fails_with_socket_missing(self, env):
        run_config_init(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        assert envelope["checks"]["socket_reachable"]["status"] == "fail"
        assert envelope["checks"]["socket_reachable"]["sub_code"] == "socket_missing"

    def test_dependent_checks_emit_info_with_daemon_unavailable(self, env):
        """Q1 / FR-027: every check still emits a row; dependent ones skip the
        round-trip and carry status=info + sub_code=daemon_unavailable."""
        run_config_init(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        for code in ("daemon_status", "container_identity", "tmux_pane_match"):
            check = envelope["checks"][code]
            assert check["status"] == "info", code
            assert check["sub_code"] == "daemon_unavailable", code

    def test_tmux_present_runs_locally_independent_of_daemon(self, env):
        """tmux_present is a local-only check — should still produce a row
        not gated by daemon availability."""
        run_config_init(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        check = envelope["checks"]["tmux_present"]
        # Either pass (sub_code key omitted) or info=not_in_tmux; never daemon_unavailable.
        sub = check.get("sub_code")
        assert sub != "daemon_unavailable"

    def test_no_raw_errno_leak_to_stderr(self, env):
        """FR-024 / SC-004: raw socket(2) / connect(2) errno text MUST NOT leak."""
        run_config_init(env)
        proc = _run_doctor(env)
        assert "[Errno" not in proc.stderr
        assert "Errno" not in proc.stderr
        assert "ENOENT" not in proc.stderr
        assert "ECONNREFUSED" not in proc.stderr

    def test_no_raw_errno_leak_in_json(self, env):
        run_config_init(env)
        proc = _run_doctor(env, json_mode=True)
        assert "[Errno" not in proc.stdout
        # actionable_message text is sanitized; check for raw errno tokens
        assert "ENOENT" not in proc.stdout

    def test_every_check_emits_a_row_no_silent_omissions(self, env):
        """FR-027 (post-clarify): every closed-set check appears as a row."""
        run_config_init(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        assert set(envelope["checks"].keys()) == {
            "socket_resolved",
            "socket_reachable",
            "daemon_status",
            "container_identity",
            "tmux_present",
            "tmux_pane_match",
        }
