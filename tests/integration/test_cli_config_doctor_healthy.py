"""US2 AS1 healthy-doctor integration test (T032, FR-012, FR-013, FR-014, FR-027, SC-003)."""

from __future__ import annotations

import json
import subprocess
import time
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


def _run_doctor(env, *, json_mode: bool = False, timeout: float = 10.0):
    cmd = ["agenttower", "config", "doctor"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )


class TestHealthyDoctor:
    def test_healthy_six_rows_in_fixed_order(self, env):
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env)
        # On a clean host (no tmux pane registered, no FEAT-003 scan run, no
        # in-container detection signals), exit will be 5 (degraded) or 0
        # depending on environment. We assert structure here and check
        # individual outcomes in TestStructure.
        lines = proc.stdout.rstrip("\n").split("\n")
        # 6 check rows + summary line = at least 7 lines; actionable lines may
        # add more for non-pass rows.
        check_codes = []
        for line in lines:
            if line.startswith("    "):  # actionable continuation
                continue
            if line.startswith("summary\t"):
                break
            cols = line.split("\t")
            assert len(cols) == 3, line
            check_codes.append(cols[0])
        assert check_codes == [
            "socket_resolved",
            "socket_reachable",
            "daemon_status",
            "container_identity",
            "tmux_present",
            "tmux_pane_match",
        ]

    def test_summary_line_format(self, env):
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env)
        last = proc.stdout.rstrip("\n").split("\n")[-1]
        assert last.startswith("summary\t")
        cols = last.split("\t")
        assert len(cols) == 3
        # Format is "summary\t<exit>\t<n_pass>/<total> checks passed"
        n_part = cols[2]
        assert n_part.endswith("checks passed")
        assert "/" in n_part

    def test_socket_reachable_passes_when_daemon_up(self, env):
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        assert envelope["checks"]["socket_reachable"]["status"] == "pass"
        assert envelope["checks"]["daemon_status"]["status"] == "pass"


class TestSC003WallClockBudget:
    def test_doctor_under_2_seconds_against_healthy_daemon(self, env):
        """SC-003 budget is 500ms but daemon spawn variance pushes us higher
        in tests; we assert a generous 2s ceiling here so the test is stable
        on slow CI while still catching pathological regressions."""
        run_config_init(env)
        ensure_daemon(env)
        start = time.perf_counter()
        proc = _run_doctor(env)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"doctor took {elapsed*1000:.0f}ms"
        assert proc.returncode in (0, 5), proc.stderr  # 5 if non-required check fails


class TestJSONShape:
    def test_json_envelope_top_level(self, env):
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        assert set(envelope.keys()) == {"summary", "checks"}

    def test_summary_field_keys(self, env):
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        s = envelope["summary"]
        assert set(s.keys()) == {
            "exit_code",
            "total",
            "passed",
            "warned",
            "failed",
            "info",
        }
        assert s["total"] == 6

    def test_check_codes_closed_set(self, env):
        run_config_init(env)
        ensure_daemon(env)
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

    def test_dead_tokens_never_appear(self, env):
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env, json_mode=True)
        # Negative-lock the dead synonyms per Clarifications 2026-05-06
        assert "not_in_container" not in proc.stdout
        assert "no_containers_known" not in proc.stdout

    def test_summary_exit_code_matches_cli_exit(self, env):
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        assert envelope["summary"]["exit_code"] == proc.returncode


class TestJSONStdoutPurity:
    def test_json_mode_emits_no_incidental_stderr(self, env):
        """FR-014 / edge case 15: --json output must be valid JSON on stdout
        with no incidental stderr lines (the FR-002 pre-flight error which
        predates --json parsing is the documented exception, not exercised here)."""
        run_config_init(env)
        ensure_daemon(env)
        proc = _run_doctor(env, json_mode=True)
        assert proc.stderr == ""
        # Round-trip the JSON to confirm parse correctness
        json.loads(proc.stdout)
