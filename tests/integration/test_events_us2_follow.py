"""T054 / T055 / T056 / T057 — US2 acceptance scenarios.

The follow stream is a long-poll loop on ``events.follow_next``.
These tests drive a real daemon, manually seed events into the
``events`` SQLite table after ``follow_open``, and assert the
``events.follow_next`` long-poll surfaces them.

Each test uses subprocess.Popen for the ``--follow`` CLI so we can
capture incremental stdout and signal it.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

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
    agent_id: str = "agt_a1b2c3d4e5f6",
    excerpt: str = "test event",
    observed_at: str | None = None,
    classifier_rule_id: str = "activity.fallback.v1",
    byte_start: int = 0,
    byte_end: int = 10,
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
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO agents (agent_id, container_id, tmux_socket_path, "
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


def _read_stdout_until(proc: subprocess.Popen[str], timeout: float) -> list[str]:
    """Read all currently-available stdout lines, up to ``timeout``.

    Uses ``os.read`` on the underlying fd to avoid TextIOWrapper's
    blocking-until-buffer-full behavior that would defeat the
    selector-based polling.
    """
    import selectors

    fd = proc.stdout.fileno()
    sel = selectors.DefaultSelector()
    sel.register(fd, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    lines: list[str] = []
    buf = ""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        events = sel.select(timeout=remaining)
        if not events:
            break
        try:
            chunk = os.read(fd, 1024)
        except (BlockingIOError, OSError):
            break
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, _, buf = buf.partition("\n")
            lines.append(line)
    return lines


def test_us2_as1_no_target_streams_any_agents_event(tmp_path: Path) -> None:
    """AS1: ``events --follow`` (no target) prints any attached agent's
    new event within ≤ 1 reader cycle."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")

        proc = subprocess.Popen(
            ["agenttower", "events", "--follow", "--json"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.5)  # let follow_open complete
            _seed_event(
                paths["state_db"],
                event_type="error",
                excerpt="boom",
                observed_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%S.000000+00:00", time.gmtime()
                ),
            )
            # The reader thread's notify path requires the SQLite
            # commit to go through the reader's notify call. Since
            # we seeded directly, the follower's long-poll will
            # discover the new event on its next DAO query (the
            # follow_next loop does not depend on notify for
            # correctness — notify is just a wakeup).
            lines = _read_stdout_until(proc, timeout=3.5)
            events = [
                json.loads(ln) for ln in lines if ln.strip().startswith("{")
            ]
            events = [e for e in events if "event_id" in e]
            assert len(events) >= 1
            assert events[0]["event_type"] == "error"
            assert events[0]["excerpt"] == "boom"
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us2_as2_target_filter_excludes_other_agent(tmp_path: Path) -> None:
    """AS2: ``events --follow --target X`` does NOT print events from
    agent Y."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")
        _seed_agent(paths["state_db"], "agt_bbbbbbbbbbbb")

        proc = subprocess.Popen(
            [
                "agenttower", "events", "--follow", "--json",
                "--target", "agt_a1b2c3d4e5f6",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.5)
            # Seed an event for the OTHER agent.
            _seed_event(
                paths["state_db"],
                agent_id="agt_bbbbbbbbbbbb",
                event_type="error",
                excerpt="other-agent",
            )
            time.sleep(1.0)
            lines = _read_stdout_until(proc, timeout=2.0)
            events = [
                json.loads(ln) for ln in lines if ln.strip().startswith("{")
            ]
            events = [e for e in events if "event_id" in e]
            # Filter excludes the other agent's event.
            assert len(events) == 0
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()


    finally:
        helpers.stop_daemon_if_alive(env)


def test_us2_as3_sigint_exits_cleanly(tmp_path: Path) -> None:
    """AS3: SIGINT after idle exits 0, no further output on stdout."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")

        proc = subprocess.Popen(
            [
                "agenttower", "events", "--follow", "--json",
                "--target", "agt_a1b2c3d4e5f6",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.5)
            proc.send_signal(signal.SIGINT)
            stdout, stderr = proc.communicate(timeout=10.0)
            assert proc.returncode == 0, (
                f"expected clean exit; got {proc.returncode}; stderr={stderr!r}"
            )
            # No event lines should have been emitted in the idle window.
            lines = [
                ln for ln in stdout.splitlines() if ln.strip().startswith("{")
            ]
            assert lines == []
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2.0)
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us2_since_then_live_ordering(tmp_path: Path) -> None:
    """``--since`` prints bounded backlog FIRST, live events SECOND,
    no overlap (uses ``live_starting_event_id``)."""
    env = _isolated_env_with_daemon(tmp_path)
    try:
        paths = helpers.resolved_paths(tmp_path)
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")

        # Seed some pre-follow_open backlog events.
        backlog_id1 = _seed_event(
            paths["state_db"], excerpt="b1", observed_at="2026-05-10T11:00:00.000000+00:00"
        )
        backlog_id2 = _seed_event(
            paths["state_db"], excerpt="b2", observed_at="2026-05-10T11:00:01.000000+00:00"
        )

        proc = subprocess.Popen(
            [
                "agenttower", "events", "--follow", "--json",
                "--target", "agt_a1b2c3d4e5f6",
                "--since", "2026-05-10T10:00:00Z",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # Wait until the backlog has been printed; that proves
            # follow_open completed before we seed the live event.
            lines: list[str] = []
            events: list[dict] = []
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                lines.extend(_read_stdout_until(proc, timeout=0.25))
                events = [
                    json.loads(ln) for ln in lines if ln.strip().startswith("{")
                ]
                events = [e for e in events if "event_id" in e]
                if {"b1", "b2"}.issubset({e["excerpt"] for e in events}):
                    break
            assert {"b1", "b2"}.issubset({e["excerpt"] for e in events})

            # Seed a live event AFTER follow_open. Use a future
            # timestamp so default ordering keeps it last.
            live_id = _seed_event(
                paths["state_db"],
                excerpt="live",
                observed_at="2026-05-10T12:00:00.000000+00:00",
            )
            lines.extend(_read_stdout_until(proc, timeout=3.0))
            events = [
                json.loads(ln) for ln in lines if ln.strip().startswith("{")
            ]
            events = [e for e in events if "event_id" in e]
            excerpts = [e["excerpt"] for e in events]
            # Backlog comes first then live.
            assert "b1" in excerpts
            assert "b2" in excerpts
            assert "live" in excerpts
            # Backlog excerpts precede the live one in the stream.
            assert excerpts.index("b1") < excerpts.index("live")
            assert excerpts.index("b2") < excerpts.index("live")
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
    finally:
        helpers.stop_daemon_if_alive(env)
