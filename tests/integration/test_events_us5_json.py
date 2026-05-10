"""T072 / T073 / T074 — US5 acceptance scenarios + SC-011.

`agenttower events --json` produces one JSON object per event per line
in the FR-027 stable schema, validated against
`tests/integration/schemas/event-v1.schema.json`.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers


def _isolated_env_with_daemon(tmp_path: Path) -> dict[str, str]:
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    return env


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


def _seed_event(
    db_path: Path,
    *,
    agent_id: str = "agt_a1b2c3d4e5f6",
    event_type: str = "activity",
    excerpt: str = "x",
    classifier_rule_id: str = "activity.fallback.v1",
    observed_at: str | None = None,
) -> int:
    if observed_at is None:
        observed_at = "2026-05-10T12:00:00.000000+00:00"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO events ("
            "event_type, agent_id, attachment_id, log_path, "
            "byte_range_start, byte_range_end, "
            "line_offset_start, line_offset_end, "
            "observed_at, excerpt, classifier_rule_id, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_type,
                agent_id,
                "atc_aabbccddeeff",
                "/tmp/agent.log",
                0, 10, 0, 1,
                observed_at, excerpt, classifier_rule_id, 1,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def test_us5_as1_one_json_line_with_documented_fields(tmp_path: Path) -> None:
    """AS1: append known event-trigger line; ``events --target X --json
    --limit 1`` is exactly one JSON object on a single line containing
    the FR-027 fields and no fields beyond the schema."""
    env = _isolated_env_with_daemon(tmp_path)
    paths = helpers.resolved_paths(tmp_path)
    try:
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")
        _seed_event(
            paths["state_db"],
            event_type="error",
            classifier_rule_id="error.line.v1",
            excerpt="Error: division by zero",
        )

        result = subprocess.run(
            [
                "agenttower", "events",
                "--target", "agt_a1b2c3d4e5f6",
                "--json", "--limit", "1",
            ],
            env=env, capture_output=True, text=True, timeout=10.0,
        )
        assert result.returncode == 0, result.stderr
        line = result.stdout.strip()
        assert "\n" not in line, "expected exactly one JSON line"

        event = json.loads(line)
        # FR-027 required fields are all present.
        required = {
            "event_id", "event_type", "agent_id", "attachment_id",
            "log_path", "byte_range_start", "byte_range_end",
            "line_offset_start", "line_offset_end", "observed_at",
            "record_at", "excerpt", "classifier_rule_id", "debounce",
            "schema_version",
        }
        assert required.issubset(event.keys())
        # No fields beyond the documented schema.
        assert set(event.keys()) <= required
        # Debounce object has its 4 keys.
        assert set(event["debounce"].keys()) == {
            "window_id", "collapsed_count",
            "window_started_at", "window_ended_at",
        }
        # record_at is null in MVP per Clarifications Q3.
        assert event["record_at"] is None
        # schema_version is 1.
        assert event["schema_version"] == 1
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us5_sc_011_every_seeded_event_validates_against_schema(
    tmp_path: Path,
) -> None:
    """SC-011: every event parses against
    ``tests/integration/schemas/event-v1.schema.json`` with zero
    schema-validation failures."""
    env = _isolated_env_with_daemon(tmp_path)
    paths = helpers.resolved_paths(tmp_path)
    try:
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")
        # Seed one event of each FR-008 closed-set type.
        types = [
            ("activity", "activity.fallback.v1"),
            ("error", "error.line.v1"),
            ("test_passed", "test_passed.generic.v1"),
            ("test_failed", "test_failed.generic.v1"),
            ("completed", "completed.v1"),
            ("waiting_for_input", "waiting_for_input.v1"),
            ("manual_review_needed", "manual_review.v1"),
            ("swarm_member_reported", "swarm_member.v1"),
            ("long_running", "long_running.synth.v1"),
            ("pane_exited", "pane_exited.synth.v1"),
        ]
        for i, (et, rule_id) in enumerate(types):
            _seed_event(
                paths["state_db"],
                event_type=et,
                classifier_rule_id=rule_id,
                excerpt=f"line {i}",
                observed_at=f"2026-05-10T12:00:0{i}.000000+00:00",
            )

        result = subprocess.run(
            [
                "agenttower", "events",
                "--target", "agt_a1b2c3d4e5f6",
                "--json", "--limit", "50",
            ],
            env=env, capture_output=True, text=True, timeout=10.0,
        )
        assert result.returncode == 0, result.stderr

        validator = helpers.event_schema_validator()
        events = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if "next_cursor" in obj and len(obj) == 1:
                continue
            events.append(obj)

        assert len(events) == 10
        for event in events:
            errors = list(validator.iter_errors(event))
            assert not errors, (
                f"event failed schema validation:\n{event!r}\n"
                f"errors: {[e.message for e in errors]}"
            )
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us5_as2_follow_json_extends_with_new_events(tmp_path: Path) -> None:
    """AS2: ``--follow --json`` extends with new events as one JSON
    line per event, terminating ``\\n``."""
    import os
    import selectors
    import signal

    env = _isolated_env_with_daemon(tmp_path)
    paths = helpers.resolved_paths(tmp_path)
    try:
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")

        proc = subprocess.Popen(
            [
                "agenttower", "events", "--follow", "--json",
                "--since", "1970-01-01T00:00:00.000000+00:00",
                "--target", "agt_a1b2c3d4e5f6",
            ],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            fd = proc.stdout.fileno()
            sel = selectors.DefaultSelector()
            sel.register(fd, selectors.EVENT_READ)
            lines: list[str] = []
            pending = ""

            def _events_from_lines() -> list[dict[str, object]]:
                events: list[dict[str, object]] = []
                for line in lines:
                    if not line.startswith("{"):
                        continue
                    obj = json.loads(line)
                    if "event_id" in obj:
                        events.append(obj)
                return events

            def _read_until(timeout: float, predicate: Callable[[], bool]) -> bool:
                nonlocal pending
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if predicate():
                        return True
                    remaining = deadline - time.monotonic()
                    ready = sel.select(timeout=remaining)
                    if not ready:
                        break
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    pending += chunk.decode("utf-8", errors="replace")
                    while "\n" in pending:
                        line, _, pending = pending.partition("\n")
                        if line.strip():
                            lines.append(line)
                return predicate()

            # Synchronize with follow_open before seeding the live events.
            # With direct DB writes there is no reader notify, and an event
            # inserted before follow_open's live boundary is backlog rather
            # than live. ``--since`` makes the sentinel observable either way.
            _seed_event(
                paths["state_db"],
                event_type="error",
                classifier_rule_id="error.line.v1",
                excerpt="ready",
                observed_at="2026-05-10T11:59:59.000000+00:00",
            )
            assert _read_until(
                5.0,
                lambda: any(
                    event.get("excerpt") == "ready"
                    for event in _events_from_lines()
                ),
            ), "\n".join(lines)

            for i in range(3):
                _seed_event(
                    paths["state_db"],
                    event_type="error",
                    classifier_rule_id="error.line.v1",
                    excerpt=f"err {i}",
                    observed_at=f"2026-05-10T12:00:0{i}.000000+00:00",
                )
                time.sleep(0.4)

            assert _read_until(
                5.0,
                lambda: {"err 0", "err 1", "err 2"}.issubset(
                    {
                        event.get("excerpt")
                        for event in _events_from_lines()
                    }
                ),
            ), "\n".join(lines)
            events = [
                event for event in _events_from_lines()
                if str(event.get("excerpt", "")).startswith("err ")
            ]
            # All 3 events came through.
            assert len(events) >= 3
            assert {e["excerpt"] for e in events[-3:]} == {"err 0", "err 1", "err 2"}
            # Each event line ended with \n (already consumed by splitlines).
            assert pending == ""
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
    finally:
        helpers.stop_daemon_if_alive(env)
