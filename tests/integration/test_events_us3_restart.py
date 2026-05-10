"""T060 / T061 / T062 / T063 — US3: daemon restart does not duplicate events.

Per spec §US3 / FR-020 / FR-021 / FR-022 / FR-029 / SC-003: across
N consecutive daemon restarts with no intervening log writes, the
SQLite event count and JSONL appended-line count for every attached
agent remain unchanged. The persisted offsets + jsonl_appended_at
watermark are authoritative; restart resume MUST NOT depend on JSONL
state.

These tests exercise the daemon stop/start cycle while inspecting the
events SQLite table directly.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

from . import _daemon_helpers as helpers


def _isolated_env_with_daemon(tmp_path: Path) -> dict[str, str]:
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    return env


def _seed_event(
    db_path: Path,
    *,
    event_type: str = "activity",
    excerpt: str = "x",
    observed_at: str | None = None,
    agent_id: str = "agt_a1b2c3d4e5f6",
    classifier_rule_id: str = "activity.fallback.v1",
    jsonl_appended_at: str | None = "2026-05-10T12:00:00.000000+00:00",
) -> int:
    if observed_at is None:
        observed_at = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000000+00:00", time.gmtime()
        )
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO events ("
            "event_type, agent_id, attachment_id, log_path, "
            "byte_range_start, byte_range_end, "
            "line_offset_start, line_offset_end, "
            "observed_at, excerpt, classifier_rule_id, schema_version, "
            "jsonl_appended_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_type,
                agent_id,
                "atc_aabbccddeeff",
                "/tmp/agent.log",
                0,
                10,
                0,
                1,
                observed_at,
                excerpt,
                classifier_rule_id,
                1,
                jsonl_appended_at,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def _count_events(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(
            conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        )
    finally:
        conn.close()


def test_us3_as1_count_unchanged_after_restart(tmp_path: Path) -> None:
    """AS1: persist N events, stop daemon, count rows, restart, wait
    two cycles, assert SQLite event count unchanged."""
    env = _isolated_env_with_daemon(tmp_path)
    paths = helpers.resolved_paths(tmp_path)
    db = paths["state_db"]
    try:
        # Seed 5 events.
        for i in range(5):
            _seed_event(
                db,
                excerpt=f"x{i}",
                observed_at=f"2026-05-10T12:00:0{i}.000000+00:00",
            )
        assert _count_events(db) == 5

        helpers.stop_daemon_if_alive(env)
        helpers.ensure_daemon(env, timeout=10.0)

        # Wait two reader-cycle worth of wall-clock for the reader to
        # observe the empty active-attachments set and idle.
        time.sleep(2.5)

        assert _count_events(db) == 5, (
            "events count changed across restart"
        )
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us3_as3_no_pre_restart_replay(tmp_path: Path) -> None:
    """AS3 (simplified): events that have ``jsonl_appended_at`` set
    do NOT get re-appended to JSONL on restart. The FR-029 watermark
    is authoritative.

    We seed two rows: one with ``jsonl_appended_at`` set (should NOT
    be retried) and one with NULL (should be retried). After restart,
    only the second should still be NULL.
    """
    env = _isolated_env_with_daemon(tmp_path)
    paths = helpers.resolved_paths(tmp_path)
    db = paths["state_db"]
    try:
        appended_id = _seed_event(
            db,
            excerpt="already-appended",
            jsonl_appended_at="2026-05-10T11:00:00.000000+00:00",
        )
        pending_id = _seed_event(
            db,
            excerpt="pending-jsonl",
            jsonl_appended_at=None,
        )

        helpers.stop_daemon_if_alive(env)
        helpers.ensure_daemon(env, timeout=10.0)
        # Reader's first cycle runs the JSONL retry pass.
        time.sleep(2.5)

        conn = sqlite3.connect(db)
        try:
            row_appended = conn.execute(
                "SELECT jsonl_appended_at FROM events WHERE event_id = ?",
                (appended_id,),
            ).fetchone()
            row_pending = conn.execute(
                "SELECT jsonl_appended_at FROM events WHERE event_id = ?",
                (pending_id,),
            ).fetchone()
        finally:
            conn.close()

        # The pre-existing appended row's watermark is unchanged.
        assert row_appended[0] == "2026-05-10T11:00:00.000000+00:00"
        # The pending row was retried successfully (now non-NULL).
        assert row_pending[0] is not None
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us3_sc_003_ten_consecutive_restarts(tmp_path: Path) -> None:
    """SC-003: 10 consecutive daemon restarts with no log writes;
    SQLite event count remains exactly the seeded N."""
    env = _isolated_env_with_daemon(tmp_path)
    paths = helpers.resolved_paths(tmp_path)
    db = paths["state_db"]
    try:
        for i in range(3):
            _seed_event(
                db,
                excerpt=f"x{i}",
                observed_at=f"2026-05-10T12:00:0{i}.000000+00:00",
            )
        baseline = _count_events(db)
        assert baseline == 3

        for restart in range(10):
            helpers.stop_daemon_if_alive(env)
            helpers.ensure_daemon(env, timeout=10.0)
            time.sleep(0.3)  # one reader cycle is ≤ 1 s
            assert _count_events(db) == baseline, (
                f"event count drifted on restart {restart + 1}: "
                f"expected {baseline}, got {_count_events(db)}"
            )
    finally:
        helpers.stop_daemon_if_alive(env)
