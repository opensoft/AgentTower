"""T037 / FR-027 / FR-029: ``config doctor`` writes nothing to disk.

Asserts:

* When daemon is down, every check still emits a ``CheckResult`` row
  (``daemon_status``, ``container_identity``, ``tmux_pane_match`` carry
  ``info`` + ``daemon_unavailable``); none are silently omitted.
* The doctor performs no writes against
  ``$XDG_STATE_HOME/opensoft/agenttower/`` — diff before/after.

Note: SC-003 (500 ms) wall-clock budget is asserted in
``test_cli_config_doctor_healthy.py`` (T032). This file is FR-027/FR-029
only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
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


def _run_doctor(env, *, json_mode=False):
    cmd = ["agenttower", "config", "doctor"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)


def _state_dir_snapshot(home: Path) -> dict[Path, tuple[int, str]]:
    """Snapshot every file under the state dir as (size, sha256)."""
    state_dir = resolved_paths(home)["state_dir"]
    snapshot: dict[Path, tuple[int, str]] = {}
    if not state_dir.exists():
        return snapshot
    for child in state_dir.rglob("*"):
        if child.is_file():
            data = child.read_bytes()
            snapshot[child] = (len(data), hashlib.sha256(data).hexdigest())
    return snapshot


# ---------------------------------------------------------------------------
# Every check emits a row even when the daemon is unreachable
# ---------------------------------------------------------------------------


class TestEveryCheckEmitsRow:
    def test_no_silent_omission_when_socket_reachable_fails(self, env, tmp_path):
        run_config_init(env)
        # Don't start the daemon → socket_reachable will fail
        proc = _run_doctor(env, json_mode=True)
        envelope = json.loads(proc.stdout)
        # Every closed-set check produces a row
        assert set(envelope["checks"].keys()) == {
            "socket_resolved",
            "socket_reachable",
            "daemon_status",
            "container_identity",
            "tmux_present",
            "tmux_pane_match",
        }
        # Dependent checks carry status=info + daemon_unavailable per data-model §6
        for code in ("daemon_status", "container_identity", "tmux_pane_match"):
            check = envelope["checks"][code]
            assert check["status"] == "info", code
            assert check["sub_code"] == "daemon_unavailable", code


# ---------------------------------------------------------------------------
# Doctor writes nothing to disk
# ---------------------------------------------------------------------------


class TestDoctorWritesNothing:
    def test_state_dir_unchanged_after_doctor_run(self, env, tmp_path):
        run_config_init(env)
        before = _state_dir_snapshot(tmp_path)
        _run_doctor(env)
        after = _state_dir_snapshot(tmp_path)
        # Same set of files, same contents
        assert set(before.keys()) == set(after.keys()), (
            f"new files: {set(after) - set(before)}; "
            f"removed: {set(before) - set(after)}"
        )
        for path, signature in before.items():
            assert after[path] == signature, f"{path} changed"

    def test_state_dir_unchanged_after_json_mode(self, env, tmp_path):
        run_config_init(env)
        before = _state_dir_snapshot(tmp_path)
        _run_doctor(env, json_mode=True)
        after = _state_dir_snapshot(tmp_path)
        assert set(before.keys()) == set(after.keys())
        for path, signature in before.items():
            assert after[path] == signature, f"{path} changed under --json"

    def test_no_log_file_appended(self, env, tmp_path):
        run_config_init(env)
        log_path = resolved_paths(tmp_path)["log_file"]
        size_before = log_path.stat().st_size if log_path.exists() else None
        _run_doctor(env)
        size_after = log_path.stat().st_size if log_path.exists() else None
        assert size_before == size_after, "doctor must not append to daemon log"
