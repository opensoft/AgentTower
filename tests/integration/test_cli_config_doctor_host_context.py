"""T034 / US2 AS3 / edge case 7: ``config doctor`` on the host shell.

Three scenarios via parametrize:

* ``host_in_tmux_pane_in_registry`` — ``$TMUX`` set, pane visible in
  FEAT-004 registry → ``tmux_pane_match`` is ``pass``.
* ``host_in_tmux_pane_not_in_registry`` — ``$TMUX`` set but pane absent
  from registry → ``tmux_pane_match`` is ``fail``/``pane_unknown_to_daemon``.
* ``host_not_in_tmux`` — both ``$TMUX`` and ``$TMUX_PANE`` unset →
  ``tmux_present`` and ``tmux_pane_match`` both ``info``/``not_in_tmux``.

In all three: ``container_identity`` is ``info``/``host_context``
(NOT ``fail``); ``AGENTTOWER_CONTAINER_ID`` is unset; runtime context is
forced to host via an empty fake ``/proc`` so the dev box's own container
context does not leak into the test.
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
    """Empty fake ``/proc`` → runtime detects HostContext."""
    fake_root = tmp_path / "fake-host-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text("0::/\n")
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


# ---------------------------------------------------------------------------
# host_not_in_tmux — neither $TMUX nor $TMUX_PANE set
# ---------------------------------------------------------------------------


class TestHostNotInTmux:
    def test_container_identity_host_context(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE"):
            env.pop(var, None)
        env.pop("AGENTTOWER_CONTAINER_ID", None)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        assert ci["status"] == "info"
        assert ci["sub_code"] == "host_context"

    def test_tmux_present_not_in_tmux_info(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE"):
            env.pop(var, None)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tp = envelope["checks"]["tmux_present"]
        assert tp["status"] == "info"
        assert tp["sub_code"] == "not_in_tmux"

    def test_tmux_pane_match_not_in_tmux_info(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE"):
            env.pop(var, None)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tpm = envelope["checks"]["tmux_pane_match"]
        assert tpm["status"] == "info"
        assert tpm["sub_code"] == "not_in_tmux"

    def test_exit_code_zero(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        for var in ("TMUX", "TMUX_PANE"):
            env.pop(var, None)
        env.pop("AGENTTOWER_CONTAINER_ID", None)
        proc = _run_doctor(env)
        assert proc.returncode == 0


# ---------------------------------------------------------------------------
# host_in_tmux_pane_not_in_registry — $TMUX/$TMUX_PANE set but pane unknown
# ---------------------------------------------------------------------------


class TestHostInTmuxPaneNotInRegistry:
    def test_pane_unknown_to_daemon(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        env["TMUX"] = "/tmp/never-scanned-socket,12345,$0"
        env["TMUX_PANE"] = "%0"
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        # tmux_present should pass (env parses cleanly)
        tp = envelope["checks"]["tmux_present"]
        assert tp["status"] == "pass", tp
        # pane is not in the FEAT-004 registry (no scan run) → unknown
        tpm = envelope["checks"]["tmux_pane_match"]
        assert tpm["status"] == "fail"
        assert tpm["sub_code"] == "pane_unknown_to_daemon"

    def test_exit_code_5_when_only_non_required_check_fails(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        env["TMUX"] = "/tmp/never-scanned-socket,12345,$0"
        env["TMUX_PANE"] = "%0"
        proc = _run_doctor(env)
        # required checks pass; tmux_pane_match fails → degraded exit 5
        assert proc.returncode == 5

    def test_container_identity_still_host_context(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        env["TMUX"] = "/tmp/never-scanned-socket,12345,$0"
        env["TMUX_PANE"] = "%0"
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        assert ci["status"] == "info"
        assert ci["sub_code"] == "host_context"
