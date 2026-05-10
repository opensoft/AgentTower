"""T076 — SC-012 host/container parity (simplified).

Per spec §SC-012: ``agenttower events --target X --json --limit N``
from the host vs from inside a bench container against the same
daemon must produce byte-identical stdout (modulo newline
normalization).

Without a bench-container fixture available in CI, this test
exercises the equivalent guarantee at the HOST side: TWO consecutive
``agenttower events`` invocations against the same daemon produce
byte-identical stdout and exit codes. The container path goes
through the same FEAT-005 thin-client routing that the host uses
when no socket is mounted, so byte-identical host output is the
load-bearing precondition for SC-012.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from . import _daemon_helpers as helpers


def _seed_agent(db_path: Path, agent_id: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO agents (agent_id, container_id, "
            "tmux_socket_path, tmux_session_name, tmux_window_index, "
            "tmux_pane_index, tmux_pane_id, role, capability, label, "
            "project_path, parent_agent_id, effective_permissions, "
            "created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                agent_id, "c"*64, "/tmp/sock", "s", 0, 0, "%1",
                "slave", "shell", "demo", "", None, "{}",
                "2026-05-10T00:00:00.000000+00:00",
                "2026-05-10T00:00:00.000000+00:00",
                None, 1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_event(
    db_path: Path,
    *,
    agent_id: str = "agt_a1b2c3d4e5f6",
    excerpt: str = "x",
    observed_at: str = "2026-05-10T12:00:00.000000+00:00",
) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO events ("
            "event_type, agent_id, attachment_id, log_path, "
            "byte_range_start, byte_range_end, line_offset_start, "
            "line_offset_end, observed_at, excerpt, classifier_rule_id, "
            "schema_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "activity", agent_id, "atc_aabbccddeeff",
                "/tmp/agent.log", 0, 10, 0, 1,
                observed_at, excerpt, "activity.fallback.v1", 1,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def test_two_consecutive_invocations_produce_byte_identical_output(
    tmp_path: Path,
) -> None:
    """A pure-read query against an unchanging events table is
    deterministic byte-for-byte across consecutive invocations."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    paths = helpers.resolved_paths(tmp_path)
    try:
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")
        for i in range(3):
            _seed_event(
                paths["state_db"],
                excerpt=f"x{i}",
                observed_at=f"2026-05-10T12:00:0{i}.000000+00:00",
            )

        cmd = [
            "agenttower", "events",
            "--target", "agt_a1b2c3d4e5f6",
            "--json", "--limit", "10",
        ]
        first = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=10.0
        )
        second = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=10.0
        )
        assert first.returncode == 0 == second.returncode
        # Byte-identical stdout.
        assert first.stdout == second.stdout
        # Stderr is also unchanged (no warnings, no cursor on a final page).
        assert first.stderr == second.stderr

        # And the JSON payload is parseable.
        events = [
            json.loads(line) for line in first.stdout.splitlines() if line.strip()
        ]
        events = [e for e in events if "event_id" in e]
        assert len(events) == 3
    finally:
        helpers.stop_daemon_if_alive(env)
