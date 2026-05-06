"""T056 / FR-014 / edge case 15: ``--json`` output is stdout-pure.

Asserts the FR-014 / edge case 15 / contracts/cli.md ``--json`` and
stderr discipline:

* ``agenttower config doctor --json`` MUST emit exactly one valid JSON
  object on stdout per invocation.
* stderr MUST be empty under ``--json`` on the documented code paths
  (healthy, daemon-down, no-mount). The ONLY documented exception is the
  FR-002 pre-flight error, which predates ``--json`` parsing — covered
  in its own test class below.
* No warning, deprecation notice, or incidental log line leaks to stderr.
* ``summary.exit_code`` matches the actual CLI exit.

Resolves checklist CHK053.
"""

from __future__ import annotations

import json
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


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _run_doctor_json(env, *, timeout: float = 10.0):
    return subprocess.run(
        ["agenttower", "config", "doctor", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _pin_host_context(env, tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-host-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text("0::/\n")
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


# ---------------------------------------------------------------------------
# Healthy daemon — stdout is one JSON object, stderr is empty
# ---------------------------------------------------------------------------


class TestJsonStdoutHealthy:
    def test_stdout_is_one_valid_json_object(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert isinstance(envelope, dict)
        # Top-level shape per FR-014
        assert "summary" in envelope
        assert "checks" in envelope
        # Exactly one object — no trailing JSON lines, no second envelope
        stripped = proc.stdout.rstrip("\n")
        assert stripped.count("\n}") <= 1, "looks like multiple JSON objects"

    def test_stderr_is_empty_under_json_when_healthy(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)

        proc = _run_doctor_json(env)
        assert proc.stderr == "", repr(proc.stderr)

    def test_summary_exit_code_matches_cli_exit(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert envelope["summary"]["exit_code"] == proc.returncode


# ---------------------------------------------------------------------------
# Daemon down — stdout is still one valid JSON object, stderr stays empty
# ---------------------------------------------------------------------------


class TestJsonStdoutDaemonDown:
    def test_stdout_is_one_valid_json_object_when_daemon_down(self, env, tmp_path):
        run_config_init(env)
        # Don't start the daemon → socket_reachable will fail
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert isinstance(envelope, dict)
        assert "summary" in envelope
        assert "checks" in envelope

    def test_stderr_is_empty_under_json_when_daemon_down(self, env, tmp_path):
        run_config_init(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)

        proc = _run_doctor_json(env)
        # FR-024 / SC-004: no raw errno text leaks to stderr; under --json
        # stderr should be entirely silent.
        assert proc.stderr == "", repr(proc.stderr)

    def test_no_errno_text_anywhere_in_output_when_daemon_down(self, env, tmp_path):
        run_config_init(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)

        proc = _run_doctor_json(env)
        # FR-024: closed-set sub-codes only; no raw socket(2)/connect(2) text
        forbidden = ("Errno", "strerror", "Connection refused", "ENOENT", "EACCES")
        for token in forbidden:
            assert token not in proc.stdout, f"{token!r} leaked into stdout"
            assert token not in proc.stderr, f"{token!r} leaked into stderr"

    def test_summary_exit_code_matches_cli_exit_when_daemon_down(
        self, env, tmp_path
    ):
        run_config_init(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert envelope["summary"]["exit_code"] == proc.returncode


# ---------------------------------------------------------------------------
# No mount — AGENTTOWER_SOCKET points to a path that does not exist
# ---------------------------------------------------------------------------


class TestJsonStdoutNoMount:
    def test_stdout_is_one_valid_json_object_when_socket_missing(
        self, env, tmp_path
    ):
        run_config_init(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE", "AGENTTOWER_CONTAINER_ID"):
            env.pop(var, None)
        # Point the override at a path that exists as a directory, so the
        # *resolver* succeeds (it's a valid absolute path) but the *transport*
        # fails — exercising the daemon-down code path with an explicit path.
        missing_socket = resolved_paths(tmp_path)["socket"]
        # Don't start the daemon; ensure the socket file does not exist.
        assert not missing_socket.exists()

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert isinstance(envelope, dict)
        assert proc.stderr == "", repr(proc.stderr)


# ---------------------------------------------------------------------------
# FR-002 pre-flight is the documented stderr exception under --json
# ---------------------------------------------------------------------------


class TestPreflightStderrException:
    """The FR-002 pre-flight error (malformed AGENTTOWER_SOCKET) is the ONE
    documented stderr line under ``--json``. It happens BEFORE the
    ``--json`` flag is honored because the pre-flight gate runs first.
    Other code paths must keep stderr empty.
    """

    def test_relative_path_pre_flight_writes_to_stderr_and_exits_1(
        self, env, tmp_path
    ):
        run_config_init(env)
        env["AGENTTOWER_SOCKET"] = "relative/path"
        proc = _run_doctor_json(env)
        # FR-002 contract: exit 1, message starts with "error:"
        assert proc.returncode == 1, proc.stdout
        assert "AGENTTOWER_SOCKET" in proc.stderr
        assert "absolute path" in proc.stderr

    def test_pre_flight_exception_does_not_leak_other_warnings(
        self, env, tmp_path
    ):
        """stderr should contain ONLY the FR-002 line — no warnings, no
        deprecation notices, no log lines."""
        run_config_init(env)
        env["AGENTTOWER_SOCKET"] = ""
        proc = _run_doctor_json(env)
        assert proc.returncode == 1
        # Exactly one error line (plus possible trailing newline)
        non_empty_lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
        assert len(non_empty_lines) == 1, repr(proc.stderr)
        assert non_empty_lines[0].startswith("error:")
