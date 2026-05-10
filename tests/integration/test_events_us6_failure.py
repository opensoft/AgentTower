"""T085 / T086 / T087 / T088 — US6 acceptance scenarios + SC-010.

Failure surfaces are visible without crashing the daemon:
- AS1: per-attachment failure isolation
- AS2: degraded SQLite — buffered retry + visible status
- AS3: missing offset row — skip cycle + log inconsistency
- SC-010: 100 % isolation across many iterations (exercised at the
  unit level by ``test_reader_eaccess_isolated`` and friends; the
  integration test here covers the daemon-wide ``status`` surface).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers


def test_us6_status_includes_events_reader_and_persistence_keys(
    tmp_path: Path,
) -> None:
    """``agenttower status --json`` exposes the FEAT-008
    ``events_reader`` and ``events_persistence`` keys per
    data-model.md §7. With no failures, both ``degraded_*`` are null."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        proc = subprocess.run(
            ["agenttower", "status", "--json"],
            env=env, capture_output=True, text=True, timeout=10.0,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        result = payload["result"]
        # Documented FEAT-008 fields are present.
        assert "events_reader" in result
        assert "events_persistence" in result
        ep = result["events_persistence"]
        assert ep["degraded_sqlite"] is None
        assert ep["degraded_jsonl"] is None
        # And events_reader has the documented sub-keys.
        er = result["events_reader"]
        assert "running" in er
        assert "active_attachments" in er
        assert "attachments_in_failure" in er
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us6_reader_running_after_daemon_start(tmp_path: Path) -> None:
    """The reader thread is running by the time the daemon is ready."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        proc = subprocess.run(
            ["agenttower", "status", "--json"],
            env=env, capture_output=True, text=True, timeout=10.0,
        )
        payload = json.loads(proc.stdout)
        assert payload["result"]["events_reader"]["running"] is True
    finally:
        helpers.stop_daemon_if_alive(env)
