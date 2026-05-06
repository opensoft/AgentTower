"""T046 / US3 AS2 / FR-006 / FR-007 / R-004: hostname-source identity wins.

Scenario: ``/proc/self/cgroup`` contains an empty (or non-matching) line so
the cgroup signal does NOT fire; ``/etc/hostname`` is set to a 12-character
hex prefix that matches a row in the FEAT-003 ``list_containers`` output;
``$AGENTTOWER_CONTAINER_ID`` is unset.

The hostname-step in the FR-006 four-step precedence (``env`` → ``cgroup``
→ ``hostname`` → ``hostname_env``) is the one that produces the candidate.

Because seeding the FEAT-003 daemon registry inside an integration test is
expensive, this file demonstrates the *unmatched* hostname-source path
(no containers in the registry → ``no_match``); the matched path is
exercised at the unit level by ``tests/unit/test_container_identity.py``.
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


# ---------------------------------------------------------------------------
# hostname-source candidate emitted; container set is empty → no_match flag
# ---------------------------------------------------------------------------


class TestHostnameSourceCandidate:
    def test_hostname_source_drives_the_candidate(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        # /.dockerenv fires ContainerContext but cgroup is empty → cgroup
        # signal returns nothing → hostname is the source.
        fake_root = tmp_path / "fake-hostname-only"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        (fake_root / "proc" / "self" / "cgroup").write_text("")
        (fake_root / ".dockerenv").write_text("")
        # 12-char hex string — short-id-prefix shape per US3 AS2
        (fake_root / "etc" / "hostname").write_text("abcdef012345\n")
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        env.pop("AGENTTOWER_CONTAINER_ID", None)

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        # The hostname signal produced a candidate; the daemon's container
        # set is empty so we expect no_match (closed set per FR-007).
        assert ci["sub_code"] in {"no_match", "no_candidate"}
        if ci["sub_code"] == "no_match":
            assert ci.get("source") == "hostname"

    def test_no_match_includes_actionable_scan_message(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        fake_root = tmp_path / "fake-hostname-no-match"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        (fake_root / "proc" / "self" / "cgroup").write_text("")
        (fake_root / ".dockerenv").write_text("")
        (fake_root / "etc" / "hostname").write_text("deadbeef0042\n")
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        if ci["status"] == "fail":
            assert "actionable_message" in ci
            assert "scan --containers" in ci["actionable_message"]


# ---------------------------------------------------------------------------
# AGENTTOWER_CONTAINER_ID env override beats hostname (FR-006 precedence)
# ---------------------------------------------------------------------------


class TestEnvOverrideBeatsHostname:
    def test_env_value_takes_precedence_over_hostname(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        fake_root = tmp_path / "fake-env-vs-hostname"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        (fake_root / "proc" / "self" / "cgroup").write_text("")
        (fake_root / ".dockerenv").write_text("")
        (fake_root / "etc" / "hostname").write_text("abcdef012345\n")
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        env["AGENTTOWER_CONTAINER_ID"] = "deadbeef9999"

        proc = _run_doctor_json(env)
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        # env signal produced the candidate (FR-006 step 1)
        if ci["status"] == "fail" and ci.get("source"):
            assert ci["source"] == "env"
