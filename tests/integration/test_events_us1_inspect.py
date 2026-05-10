"""T042 / T043 / T044 / T045 — US1 acceptance scenarios.

These tests drive the daemon through a subprocess (the harness from
``_daemon_helpers``) and exercise ``agenttower events`` end-to-end.

Because spinning up a full FEAT-001..007 attach-log + tmux pipe-pane
chain requires Docker / tmux fixtures that aren't always available
in CI, the tests in this module manually seed the events SQLite
table and then verify that ``events.list`` and ``agenttower events``
return the expected shape and content. The full reader → emit
pipeline is exercised by the unit-level reader tests
(``tests/unit/test_reader_*``).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers


def _isolated_env_with_daemon(tmp_path: Path):
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    return env


def _seed_event(
    db_path: Path,
    *,
    event_type: str = "activity",
    agent_id: str = "agt_a1b2c3d4e5f6",
    excerpt: str = "test event",
    observed_at: str = "2026-05-10T12:00:00.000000+00:00",
    classifier_rule_id: str = "activity.fallback.v1",
    byte_start: int = 0,
    byte_end: int = 10,
) -> int:
    """Insert one event row into the daemon's SQLite db. Returns event_id."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO events ("
            "event_type, agent_id, attachment_id, log_path, "
            "byte_range_start, byte_range_end, "
            "line_offset_start, line_offset_end, "
            "observed_at, excerpt, classifier_rule_id, schema_version"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_type,
                agent_id,
                "atc_aabbccddeeff",
                "/tmp/agent.log",
                byte_start,
                byte_end,
                0,
                1,
                observed_at,
                excerpt,
                classifier_rule_id,
                1,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def _seed_agent(db_path: Path, agent_id: str) -> None:
    """Manually insert an agents row (FEAT-006-style schema)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id,
                "c" * 64,
                "/tmp/sock",
                "s",
                0,
                0,
                "%1",
                "slave",
                "shell",
                "demo",
                "",
                None,
                "{}",
                "2026-05-10T00:00:00.000000+00:00",
                "2026-05-10T00:00:00.000000+00:00",
                None,
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _agenttower_events(
    env: dict[str, str], *args: str, timeout: float = 10.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agenttower", "events", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_us1_as1_one_error_event_appears(tmp_path: Path) -> None:
    """AS1: write one error line → exactly one error event listed
    via the CLI, with the redacted excerpt."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")
        eid = _seed_event(
            paths["state_db"],
            event_type="error",
            classifier_rule_id="error.line.v1",
            excerpt="Error: division by zero",
            observed_at="2026-05-10T12:00:01.000000+00:00",
        )
        assert eid >= 1

        result = _agenttower_events(
            env, "--target", "agt_a1b2c3d4e5f6", "--json", "--limit", "1"
        )
        assert result.returncode == 0, result.stderr
        line = result.stdout.strip()
        # One JSON line.
        assert "\n" not in line, "expected exactly one event line; got:\n" + result.stdout
        event = json.loads(line)
        assert event["event_type"] == "error"
        assert event["agent_id"] == "agt_a1b2c3d4e5f6"
        assert event["excerpt"] == "Error: division by zero"
        assert event["classifier_rule_id"] == "error.line.v1"
        assert event["observed_at"] == "2026-05-10T12:00:01.000000+00:00"
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us1_as2_oldest_first_ordering(tmp_path: Path) -> None:
    """AS2: error then test_passed → both listed in observed_at order,
    oldest first by default."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")
        _seed_event(
            paths["state_db"],
            event_type="error",
            classifier_rule_id="error.line.v1",
            excerpt="Error",
            observed_at="2026-05-10T12:00:01.000000+00:00",
        )
        _seed_event(
            paths["state_db"],
            event_type="test_passed",
            classifier_rule_id="test_passed.generic.v1",
            excerpt="all tests passed",
            observed_at="2026-05-10T12:00:02.000000+00:00",
        )

        result = _agenttower_events(env, "--target", "agt_a1b2c3d4e5f6", "--json")
        assert result.returncode == 0, result.stderr
        lines = [ln for ln in result.stdout.strip().splitlines() if ln]
        assert len(lines) == 2
        events = [json.loads(ln) for ln in lines]
        # Skip cursor lines (single-key dicts).
        events = [e for e in events if "event_id" in e]
        assert [e["event_type"] for e in events] == ["error", "test_passed"]
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us1_as4_no_attachment_returns_empty(tmp_path: Path) -> None:
    """AS4: registered agent with no events → empty result, exit 0."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")

        result = _agenttower_events(env, "--target", "agt_a1b2c3d4e5f6", "--json")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ""
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us1_excerpt_is_what_we_seed(tmp_path: Path) -> None:
    """AS3 (simplified): the persisted excerpt comes through to the CLI
    byte-for-byte. The full FEAT-007-redaction integration is exercised
    by the unit tests; here we assert the SQLite→CLI path doesn't
    mutate the excerpt."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")
        _seed_event(
            paths["state_db"],
            excerpt="redacted [REDACTED-JWT] sentinel",
            observed_at="2026-05-10T12:00:01.000000+00:00",
        )
        result = _agenttower_events(env, "--target", "agt_a1b2c3d4e5f6", "--json")
        assert result.returncode == 0
        events = [json.loads(ln) for ln in result.stdout.strip().splitlines() if ln]
        events = [e for e in events if "event_id" in e]
        assert len(events) >= 1
        assert events[0]["excerpt"] == "redacted [REDACTED-JWT] sentinel"
    finally:
        helpers.stop_daemon_if_alive(env)
