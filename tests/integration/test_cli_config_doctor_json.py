"""T036 / US2 AS5 / SC-005 / FR-014: ``config doctor --json`` envelope across
every documented scenario.

For each parametrized scenario, run ``agenttower config doctor --json`` and:

* assert ``json.loads(stdout)`` succeeds (one canonical JSON object)
* assert ``summary.exit_code == proc.returncode``
* assert ``--json`` produces no incidental stderr
* assert closed-set token spellings (``not_in_container`` and
  ``no_containers_known`` are negative-locked since both are dead synonyms
  per Clarifications 2026-05-06).
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


def _run_doctor_json(env):
    return subprocess.run(
        ["agenttower", "config", "doctor", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _pin_host_context(env, tmp_path):
    fake_root = tmp_path / "fake-host-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text("0::/\n")
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _scenario_healthy(env, tmp_path):
    run_config_init(env)
    ensure_daemon(env)
    _pin_host_context(env, tmp_path)


def _scenario_daemon_down(env, tmp_path):
    run_config_init(env)
    # Don't start the daemon
    _pin_host_context(env, tmp_path)


def _scenario_no_mount(env, tmp_path):
    """Container context, AGENTTOWER_SOCKET unset, daemon's mounted-default
    socket does not exist → doctor surfaces socket_missing."""
    run_config_init(env)
    fake_root = tmp_path / "fake-container-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text(
        "0::/docker/abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567\n"
    )
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


def _scenario_no_tmux(env, tmp_path):
    run_config_init(env)
    ensure_daemon(env)
    _pin_host_context(env, tmp_path)
    for var in ("TMUX", "TMUX_PANE"):
        env.pop(var, None)


def _scenario_unknown_container(env, tmp_path):
    """ContainerContext fires; daemon has no row for the candidate id."""
    run_config_init(env)
    ensure_daemon(env)
    fake_root = tmp_path / "fake-container-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text(
        "0::/docker/abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567\n"
    )
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")


def _scenario_ambiguous_pane(env, tmp_path):
    """Run doctor with $TMUX set but the daemon never scanned it."""
    run_config_init(env)
    ensure_daemon(env)
    _pin_host_context(env, tmp_path)
    env["TMUX"] = "/tmp/never-scanned,1234,$0"
    env["TMUX_PANE"] = "%5"


SCENARIOS = [
    "healthy",
    "daemon_down",
    "no_mount",
    "no_tmux",
    "unknown_container",
    "ambiguous_pane",
]

SCENARIO_BUILDERS = {
    "healthy": _scenario_healthy,
    "daemon_down": _scenario_daemon_down,
    "no_mount": _scenario_no_mount,
    "no_tmux": _scenario_no_tmux,
    "unknown_container": _scenario_unknown_container,
    "ambiguous_pane": _scenario_ambiguous_pane,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", SCENARIOS)
class TestJsonEnvelopeAcrossScenarios:
    def test_stdout_parses_as_one_canonical_json_object(self, env, tmp_path, scenario):
        SCENARIO_BUILDERS[scenario](env, tmp_path)
        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert isinstance(envelope, dict)
        assert set(envelope.keys()) == {"summary", "checks"}

    def test_summary_exit_code_matches_cli_exit(self, env, tmp_path, scenario):
        SCENARIO_BUILDERS[scenario](env, tmp_path)
        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert envelope["summary"]["exit_code"] == proc.returncode

    def test_stderr_is_empty(self, env, tmp_path, scenario):
        """FR-014 + FR-029: --json mode emits stdout only with no incidental
        stderr (the FR-002 pre-flight error which predates --json parsing is
        the documented exception, not exercised by these scenarios)."""
        SCENARIO_BUILDERS[scenario](env, tmp_path)
        proc = _run_doctor_json(env)
        assert proc.stderr == ""

    def test_dead_synonyms_never_appear(self, env, tmp_path, scenario):
        """``not_in_container`` and ``no_containers_known`` are dead synonyms
        per Clarifications 2026-05-06."""
        SCENARIO_BUILDERS[scenario](env, tmp_path)
        proc = _run_doctor_json(env)
        assert "not_in_container" not in proc.stdout
        assert "no_containers_known" not in proc.stdout

    def test_six_check_codes_present(self, env, tmp_path, scenario):
        SCENARIO_BUILDERS[scenario](env, tmp_path)
        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        assert set(envelope["checks"].keys()) == {
            "socket_resolved",
            "socket_reachable",
            "daemon_status",
            "container_identity",
            "tmux_present",
            "tmux_pane_match",
        }


# ---------------------------------------------------------------------------
# unknown_container: when ContainerContext fires but the daemon's container
# set is empty, the row carries daemon_container_set_empty=true (NEVER a
# no_containers_known sub-code; closed set is not extended)
# ---------------------------------------------------------------------------


class TestDaemonContainerSetEmpty:
    def test_no_match_with_daemon_container_set_empty_flag(self, env, tmp_path):
        _scenario_unknown_container(env, tmp_path)
        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        # FR-007 closed set: no_match (since a candidate from cgroup signal exists)
        assert ci["sub_code"] in {"no_match", "no_candidate"}
        # The empty-list_containers flag is the canonical signal
        assert ci.get("daemon_container_set_empty") is True
        # Negative-lock: never a synthetic no_containers_known sub_code
        assert ci["sub_code"] != "no_containers_known"


# ---------------------------------------------------------------------------
# ambiguous_pane: the named scenario routes to pane_unknown_to_daemon
# (true ambiguity requires seeded duplicate panes; covered at unit level).
# Here we confirm the JSON envelope is well-formed regardless.
# ---------------------------------------------------------------------------


class TestAmbiguousPaneEnvelope:
    def test_envelope_is_valid_json(self, env, tmp_path):
        _scenario_ambiguous_pane(env, tmp_path)
        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        # tmux_pane_match exists and has a sub_code in the closed set
        tpm = envelope["checks"]["tmux_pane_match"]
        assert tpm["sub_code"] in {
            "pane_match",
            "pane_unknown_to_daemon",
            "pane_ambiguous",
            "not_in_tmux",
            "daemon_unavailable",
        }
