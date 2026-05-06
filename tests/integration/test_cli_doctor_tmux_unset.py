"""T047 / US3 AS4 / FR-009 / FR-018 / R-005: ``$TMUX`` unset.

Asserts the spec's US3 AS4 wording verbatim:

* ``$TMUX`` and ``$TMUX_PANE`` unset → ``tmux_present`` is ``info`` /
  ``not_in_tmux`` (NOT ``fail``).
* ``tmux_pane_match`` is ``info`` / ``not_in_tmux``.
* ``container_identity`` is unaffected (produces its own classification
  regardless of tmux state).
* CLI exit stays ``0`` when every other required check passes.

The tmux behavior is tested under both runtime contexts (host and
simulated-in-container) to prove the tmux check is independent of
runtime context.
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


def _run_doctor(env, *, json_mode: bool = False):
    cmd = ["agenttower", "config", "doctor"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)


def _pin_host_context(env, tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-host-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text("0::/\n")
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


def _pin_container_context(env, tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-container-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text(
        "0::/docker/abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567\n"
    )
    (fake_root / ".dockerenv").write_text("")
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


def _strip_tmux(env) -> None:
    for var in ("TMUX", "TMUX_PANE"):
        env.pop(var, None)


# ---------------------------------------------------------------------------
# US3 AS4 — host context, tmux unset, exit 0
# ---------------------------------------------------------------------------


class TestTmuxUnsetHostContext:
    def test_tmux_present_info_not_in_tmux(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        _strip_tmux(env)
        env.pop("AGENTTOWER_CONTAINER_ID", None)

        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tp = envelope["checks"]["tmux_present"]
        assert tp["status"] == "info"
        assert tp["sub_code"] == "not_in_tmux"

    def test_tmux_pane_match_info_not_in_tmux(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        _strip_tmux(env)
        env.pop("AGENTTOWER_CONTAINER_ID", None)

        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tpm = envelope["checks"]["tmux_pane_match"]
        assert tpm["status"] == "info"
        assert tpm["sub_code"] == "not_in_tmux"

    def test_neither_tmux_check_reports_fail(self, env, tmp_path):
        """US3 AS4 wording: ``not_in_tmux`` and does NOT report ``fail``."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        _strip_tmux(env)
        env.pop("AGENTTOWER_CONTAINER_ID", None)

        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        for code in ("tmux_present", "tmux_pane_match"):
            assert envelope["checks"][code]["status"] != "fail", code

    def test_container_identity_unaffected(self, env, tmp_path):
        """Container check produces its own classification regardless of tmux."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        _strip_tmux(env)
        env.pop("AGENTTOWER_CONTAINER_ID", None)

        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        # Host context with no env override → host_context (info)
        assert ci["status"] == "info"
        assert ci["sub_code"] == "host_context"

    def test_exit_zero_when_only_tmux_unset(self, env, tmp_path):
        """Required checks pass; tmux/container are info → exit 0."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        _strip_tmux(env)
        env.pop("AGENTTOWER_CONTAINER_ID", None)

        proc = _run_doctor(env)
        assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Tmux check is independent of runtime context — same outcome in container
# ---------------------------------------------------------------------------


class TestTmuxUnsetContainerContext:
    def test_tmux_present_info_not_in_tmux_in_container(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)
        _strip_tmux(env)

        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tp = envelope["checks"]["tmux_present"]
        assert tp["status"] == "info"
        assert tp["sub_code"] == "not_in_tmux"

    def test_tmux_pane_match_info_not_in_tmux_in_container(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)
        _strip_tmux(env)

        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        tpm = envelope["checks"]["tmux_pane_match"]
        assert tpm["status"] == "info"
        assert tpm["sub_code"] == "not_in_tmux"

    def test_container_identity_independent_of_tmux(self, env, tmp_path):
        """Container check classification is not influenced by tmux env."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)
        _strip_tmux(env)

        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        # In container context with cgroup signal but empty FEAT-003 set,
        # the FR-007 closed set yields no_match (candidate exists, no row).
        # `host_context` MUST NOT appear in container context.
        assert ci["sub_code"] != "host_context"
        assert ci["sub_code"] in {"unique_match", "no_match", "no_candidate", "multi_match"}


# ---------------------------------------------------------------------------
# TSV human-readable output also reports not_in_tmux on the right rows
# ---------------------------------------------------------------------------


class TestTmuxUnsetTsvOutput:
    def test_tsv_rows_carry_not_in_tmux_token(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_host_context(env, tmp_path)
        _strip_tmux(env)
        env.pop("AGENTTOWER_CONTAINER_ID", None)

        proc = _run_doctor(env)
        # Parse the TSV: each row is "<check>\t<status>\t<detail>"
        rows = {
            line.split("\t", 2)[0]: line.split("\t", 2)
            for line in proc.stdout.splitlines()
            if line and not line.startswith(" ")
        }
        assert "tmux_present" in rows
        assert "tmux_pane_match" in rows
        assert rows["tmux_present"][1] == "info"
        assert rows["tmux_pane_match"][1] == "info"
        # The detail column (or actionable_message follow-up line) names the token
        assert "not_in_tmux" in proc.stdout
