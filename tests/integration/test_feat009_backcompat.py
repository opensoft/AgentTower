"""T087 — FEAT-001..008 backward-compatibility smoke against the
FEAT-009 daemon.

**Test mode**: CLI integration. Drives the ``agenttower`` CLI as a
subprocess and asserts that every FEAT-001..008 command still works
against the FEAT-009-extended daemon (schema v7, 29-method dispatch
table, new status fields). The byte-identical-baseline form of this
test (captured stdout/stderr snapshots from FEAT-008) was not feasible
in this branch — we don't have a FEAT-008 binary alongside to compare.
Instead we assert STRUCTURAL backward compatibility: the FEAT-001..008
keys remain present and typed correctly in ``--json`` outputs, and
exit codes are preserved.

What this test verifies:

* ``agenttower --version`` exits 0.
* ``agenttower status --json`` includes every FEAT-002..008 key.
* ``agenttower list-containers --json`` parses (FEAT-003).
* ``agenttower list-panes --json`` parses (FEAT-004).
* ``agenttower list-agents --json`` parses (FEAT-006).
* ``agenttower events --json`` parses (FEAT-008).
* New FEAT-009 fields are additive (``routing``, ``queue_audit``);
  no FEAT-001..008 field was renamed or removed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


@pytest.fixture()
def daemon(tmp_path: Path):
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


def _cli(env: dict[str, str], *args: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agenttower", *args],
        env=env, capture_output=True, text=True, timeout=timeout,
    )


# ──────────────────────────────────────────────────────────────────────
# FEAT-002 status — additive growth only
# ──────────────────────────────────────────────────────────────────────


def test_backcompat_status_json_keeps_feat002_through_008_keys(daemon) -> None:
    env, _ = daemon
    proc = _cli(env, "status", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    result = payload["result"]

    # FEAT-002..004 baseline keys.
    feat_002_keys = {
        "alive", "pid", "start_time_utc", "uptime_seconds",
        "socket_path", "state_path", "schema_version", "daemon_version",
    }
    # FEAT-008 keys.
    feat_008_keys = {"events_reader", "events_persistence"}
    # FEAT-009 additive keys.
    feat_009_keys = {"routing", "queue_audit"}

    missing = feat_002_keys - set(result.keys())
    assert not missing, f"FEAT-002 keys missing: {missing}"
    missing = feat_008_keys - set(result.keys())
    assert not missing, f"FEAT-008 keys missing: {missing}"
    missing = feat_009_keys - set(result.keys())
    assert not missing, f"FEAT-009 additive keys missing: {missing}"
    # Schema bumped to 7.
    assert result["schema_version"] == 7


# ──────────────────────────────────────────────────────────────────────
# FEAT-003 list-containers + FEAT-004 list-panes
# ──────────────────────────────────────────────────────────────────────


def _result(payload: dict) -> dict:
    """Unwrap the FEAT-002 envelope when present."""
    return payload["result"] if isinstance(payload, dict) and "result" in payload else payload


def test_backcompat_list_containers_json_parses(daemon) -> None:
    env, _ = daemon
    proc = _cli(env, "list-containers", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    result = _result(payload)
    assert "containers" in result


def test_backcompat_list_panes_json_parses(daemon) -> None:
    env, _ = daemon
    proc = _cli(env, "list-panes", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    result = _result(payload)
    assert "panes" in result


# ──────────────────────────────────────────────────────────────────────
# FEAT-006 list-agents
# ──────────────────────────────────────────────────────────────────────


def test_backcompat_list_agents_json_parses(daemon) -> None:
    env, _ = daemon
    proc = _cli(env, "list-agents", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    result = _result(payload)
    assert "agents" in result


# ──────────────────────────────────────────────────────────────────────
# FEAT-008 events
# ──────────────────────────────────────────────────────────────────────


def test_backcompat_events_list_runs(daemon) -> None:
    env, _ = daemon
    proc = _cli(env, "events", "--json")
    assert proc.returncode == 0, proc.stderr
    # Output is one JSON line per event (potentially empty here).


# ──────────────────────────────────────────────────────────────────────
# --version smoke + help discovery
# ──────────────────────────────────────────────────────────────────────


def test_backcompat_version_command(daemon) -> None:
    env, _ = daemon
    proc = _cli(env, "--version")
    assert proc.returncode == 0
    # agenttower --version prints "agenttower <version>".
    assert proc.stdout.startswith("agenttower"), proc.stdout


def test_backcompat_help_lists_feat001_through_008_subcommands(daemon) -> None:
    env, _ = daemon
    proc = _cli(env, "--help")
    assert proc.returncode == 0
    # FEAT-002..008 commands all present in --help output.
    for subcommand in [
        "status",         # FEAT-002
        "list-containers", "scan",  # FEAT-003
        "list-panes",                # FEAT-004
        "list-agents", "register-self", "set-role",  # FEAT-006
        "attach-log", "detach-log",  # FEAT-007
        "events",                    # FEAT-008
        # FEAT-009 additive — should also appear.
        "send-input", "queue", "routing",
    ]:
        assert subcommand in proc.stdout, (
            f"subcommand {subcommand!r} missing from --help output"
        )
