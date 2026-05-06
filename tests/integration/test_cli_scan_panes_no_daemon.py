"""Integration tests for FEAT-004 US3 — daemon-unreachable variant of SC-004.

When the daemon is not running (or has been stopped), the user-facing CLI
commands `agenttower scan --panes` and `agenttower list-panes` MUST exit with
code 2 and print the FEAT-002 daemon-unavailable message on stderr. The CLI
does NOT emit a JSON envelope on exit-code 2 (FEAT-002 contract; see
`tests/integration/test_cli_status.py::test_status_unavailable_returns_exit_2`
for the reference shape).
"""

from __future__ import annotations

import subprocess

from ._daemon_helpers import ensure_daemon, stop_daemon

DAEMON_UNAVAILABLE_MESSAGE = (
    "error: daemon is not running or socket is unreachable: "
    "try `agenttower ensure-daemon`"
)


def _scan_panes(env, *, json_mode: bool = False, timeout: float = 10.0):
    cmd = ["agenttower", "scan", "--panes"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )


def _list_panes(env, *args: str, timeout: float = 10.0):
    return subprocess.run(
        ["agenttower", "list-panes", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_scan_panes_without_daemon_exits_2_with_message(env_with_fake) -> None:
    """SC-004 daemon-unreachable variant — scan --panes with no daemon."""
    env, _docker_fake, _home = env_with_fake
    # Intentionally do NOT call ensure_daemon — the socket is absent.
    proc = _scan_panes(env)
    assert proc.returncode == 2, proc.stderr
    assert DAEMON_UNAVAILABLE_MESSAGE in proc.stderr


def test_list_panes_without_daemon_exits_2_with_message(env_with_fake) -> None:
    """SC-004 daemon-unreachable variant — list-panes with no daemon."""
    env, _docker_fake, _home = env_with_fake
    proc = _list_panes(env)
    assert proc.returncode == 2, proc.stderr
    assert DAEMON_UNAVAILABLE_MESSAGE in proc.stderr


def test_scan_panes_after_stop_daemon_exits_2(env_with_fake) -> None:
    """SC-004 — scan --panes after the daemon is stopped also exits 2."""
    env, _docker_fake, _home = env_with_fake
    ensure_daemon(env)
    stop_proc = stop_daemon(env)
    assert stop_proc.returncode == 0, stop_proc.stderr
    proc = _scan_panes(env)
    assert proc.returncode == 2, proc.stderr
    assert DAEMON_UNAVAILABLE_MESSAGE in proc.stderr


def test_list_panes_json_when_daemon_down_uses_two_line_stderr_form(
    env_with_fake,
) -> None:
    """FEAT-002 contract — exit-code 2 path does NOT emit a JSON envelope.

    The connect-time failure happens before any `--json` parsing, so the
    CLI prints the actionable stderr message and exits 2 even when the user
    asked for JSON output.
    """
    env, _docker_fake, _home = env_with_fake
    proc = _list_panes(env, "--json")
    assert proc.returncode == 2, proc.stderr
    assert DAEMON_UNAVAILABLE_MESSAGE in proc.stderr
    # No JSON envelope on stdout when the daemon is unavailable.
    assert proc.stdout.strip() == "", proc.stdout
