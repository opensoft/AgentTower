"""T035 / US2 AS4 / US3 AS5 / FR-010 / R-005: tmux_pane_match scenarios.

Parametrized scenarios:

* ``pane_unknown_to_daemon`` — ``$TMUX`` parses cleanly but no pane row
  matches → ``fail`` with sub-code ``pane_unknown_to_daemon`` and an
  actionable message advising ``agenttower scan --panes``. CLI exit is 5
  (degraded; round-trip ok, non-required check failed).
* ``tmux_socket_unreadable`` — ``$TMUX`` set with a path the in-container
  CLI cannot read → cross-check classifies as ``pane_unknown_to_daemon``
  rather than crashing.

The ``pane_match`` and ``pane_ambiguous`` cases are exercised at the unit
level by ``tests/unit/test_tmux_self_identity.py`` (cross-check classifier
fixtures); the integration counterpart is end-to-end coverage of the
``pane_unknown_to_daemon`` outcome since seeding the FEAT-004 registry from
inside an integration test is more involved than the unit cross-check.
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


def _pin_host_context(env, tmp_path):
    fake_root = tmp_path / "fake-host-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text("0::/\n")
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


# ---------------------------------------------------------------------------
# pane_unknown_to_daemon: $TMUX parses cleanly, but the daemon hasn't seen it
# ---------------------------------------------------------------------------


class TestPaneUnknownToDaemon:
    def test_unknown_pane_yields_fail_with_pane_unknown_to_daemon(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        env["TMUX"] = "/tmp/no-such-socket,98765,$1"
        env["TMUX_PANE"] = "%42"
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tpm = envelope["checks"]["tmux_pane_match"]
        assert tpm["status"] == "fail"
        assert tpm["sub_code"] == "pane_unknown_to_daemon"

    def test_actionable_message_advises_scan_panes(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        env["TMUX"] = "/tmp/no-such-socket,98765,$1"
        env["TMUX_PANE"] = "%42"
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tpm = envelope["checks"]["tmux_pane_match"]
        assert "actionable_message" in tpm
        assert "scan --panes" in tpm["actionable_message"]

    def test_cli_exit_5_degraded(self, env, tmp_path):
        """Round-trip ok, only the non-required check failed → exit 5."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        env["TMUX"] = "/tmp/no-such-socket,98765,$1"
        env["TMUX_PANE"] = "%42"
        proc = _run_doctor(env)
        assert proc.returncode == 5


# ---------------------------------------------------------------------------
# tmux_socket_unreadable_in_container (edge case 8): $TMUX path set but the
# in-container CLI can't read the socket. The doctor must NOT crash.
# ---------------------------------------------------------------------------


class TestTmuxSocketUnreadableInContainer:
    def test_unreadable_socket_path_does_not_crash_doctor(self, env, tmp_path):
        """The in-container tmux socket path may not be visible; the doctor
        falls back to ``pane_unknown_to_daemon`` rather than crashing."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        # Path exists nowhere on the dev box's filesystem
        env["TMUX"] = "/var/lib/never-mounted/tmux.sock,1,$0"
        env["TMUX_PANE"] = "%0"
        proc = _run_doctor(env, json_mode=True)
        # CLI exits cleanly (5 because only non-required check failed)
        assert proc.returncode == 5, proc.stderr
        envelope = json.loads(proc.stdout)
        tpm = envelope["checks"]["tmux_pane_match"]
        # Either pane_unknown_to_daemon OR (if it manages to classify
        # output_malformed) a non-crash sub_code from the closed set
        assert tpm["sub_code"] in {"pane_unknown_to_daemon", "not_in_tmux"}


# ---------------------------------------------------------------------------
# Malformed $TMUX → output_malformed bubbles via tmux_present
# ---------------------------------------------------------------------------


class TestMalformedTmux:
    def test_malformed_tmux_pane_id_yields_output_malformed(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        env["TMUX"] = "/tmp/sock,12345,$0"
        env["TMUX_PANE"] = "not-a-pane-id"  # fails ^%[0-9]+$ regex
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tp = envelope["checks"]["tmux_present"]
        assert tp["status"] == "fail"
        assert tp["sub_code"] == "output_malformed"
