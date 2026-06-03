"""FEAT-010 integration coverage for route execution + restart dedupe.

These tests fill the biggest remaining harness gap after FEAT-010:
the live daemon had no integration coverage for route-triggered queue
creation, duplicate-route recovery across restart, or per-target FIFO
under concurrent masters.

Scope:

* Route creation via the FEAT-002 socket surface (``routes.add``)
* Route consumption of live ``events`` rows from SQLite
* Route-generated FEAT-009 queue rows (``origin='route'``)
* JSONL route / queue audit emission
* Restart recovery when the routing worker dies after queue insert but
  before cursor advance (fault-injection hook)
* Direct-send per-target FIFO under concurrent master senders
"""

from __future__ import annotations

import base64
import concurrent.futures
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from agenttower.socket_api.client import send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_A = "agt_aaaaaaaaaaaa"
_MASTER_B = "agt_cccccccccccc"
_SLAVE = "agt_bbbbbbbbbbbb"


def _seed_two_masters_and_slave(state_db: Path) -> None:
    f9.seed_container(state_db)
    f9.seed_pane(
        state_db,
        tmux_pane_id="%master-a",
        tmux_window_index=0,
        tmux_pane_index=0,
    )
    f9.seed_pane(
        state_db,
        tmux_pane_id="%master-b",
        tmux_window_index=0,
        tmux_pane_index=1,
    )
    f9.seed_pane(
        state_db,
        tmux_pane_id="%slave",
        tmux_window_index=0,
        tmux_pane_index=2,
    )
    f9.seed_agent(
        state_db,
        agent_id=_MASTER_A,
        role="master",
        label="queen-a",
        tmux_pane_id="%master-a",
        tmux_window_index=0,
        tmux_pane_index=0,
    )
    f9.seed_agent(
        state_db,
        agent_id=_MASTER_B,
        role="master",
        label="queen-b",
        tmux_pane_id="%master-b",
        tmux_window_index=0,
        tmux_pane_index=1,
    )
    f9.seed_agent(
        state_db,
        agent_id=_SLAVE,
        role="slave",
        label="worker-1",
        tmux_pane_id="%slave",
        tmux_window_index=0,
        tmux_pane_index=2,
    )


def _seed_event(
    state_db: Path,
    *,
    agent_id: str,
    event_type: str = "waiting_for_input",
    excerpt: str = "Need operator input",
    observed_at: str = "2026-05-17T12:00:00.000Z",
) -> int:
    conn = sqlite3.connect(state_db)
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
                0,
                10,
                0,
                1,
                observed_at,
                excerpt,
                "waiting_for_input.line.v1",
                1,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def _add_route(
    socket_path: Path,
    *,
    target_value: str = _SLAVE,
    template: str = "respond to {source_label}: {event_excerpt}",
) -> dict:
    return send_request(
        socket_path,
        "routes.add",
        {
            "event_type": "waiting_for_input",
            "source_scope_kind": "any",
            "source_scope_value": None,
            "target_rule": "explicit",
            "target_value": target_value,
            "master_rule": "auto",
            "master_value": None,
            "template": template,
        },
        connect_timeout=2.0,
        read_timeout=5.0,
    )


def _send_input(
    socket_path: Path,
    state_db: Path,
    *,
    sender_agent_id: str,
    target: str,
    body: bytes,
) -> dict:
    return send_request(
        socket_path,
        "queue.send_input",
        {
            "target": target,
            "body_bytes": base64.b64encode(body).decode("ascii"),
            "caller_pane": f9.caller_pane_from_db(state_db, sender_agent_id),
            "wait": False,
        },
        connect_timeout=2.0,
        read_timeout=10.0,
    )


def _wait_for_route_row(
    state_db: Path,
    *,
    route_id: str,
    event_id: int,
    expected_state: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        conn = sqlite3.connect(state_db)
        try:
            cur = conn.execute(
                "SELECT * FROM message_queue "
                "WHERE route_id = ? AND event_id = ? "
                "ORDER BY enqueued_at ASC, message_id ASC",
                (route_id, event_id),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()
        if rows:
            last = rows[0]
            if expected_state is None or last["state"] == expected_state:
                return last
        time.sleep(0.05)
    return last or {}


def _route_queue_rows(
    state_db: Path, *, route_id: str, event_id: int,
) -> list[dict[str, object]]:
    conn = sqlite3.connect(state_db)
    try:
        cur = conn.execute(
            "SELECT * FROM message_queue "
            "WHERE route_id = ? AND event_id = ? "
            "ORDER BY enqueued_at ASC, message_id ASC",
            (route_id, event_id),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _route_cursor(state_db: Path, *, route_id: str) -> int:
    conn = sqlite3.connect(state_db)
    try:
        row = conn.execute(
            "SELECT last_consumed_event_id FROM routes WHERE route_id = ?",
            (route_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        conn.close()


def _rows_for_message_ids(
    state_db: Path, *, message_ids: list[str],
) -> list[dict[str, object]]:
    placeholders = ", ".join("?" for _ in message_ids)
    conn = sqlite3.connect(state_db)
    try:
        cur = conn.execute(
            "SELECT * FROM message_queue "
            f"WHERE message_id IN ({placeholders}) "
            "ORDER BY enqueued_at ASC, message_id ASC",
            tuple(message_ids),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


@pytest.fixture()
def daemon_with_master_and_slave(tmp_path: Path):
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(
            paths["state_db"],
            master_agent_id=_MASTER_A,
            slave_agent_id=_SLAVE,
            master_label="queen-a",
            slave_label="worker-1",
        )
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


@pytest.fixture()
def daemon_with_two_masters_and_slave(tmp_path: Path):
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        _seed_two_masters_and_slave(paths["state_db"])
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


def test_route_generated_queue_row_reaches_delivered_and_emits_audit(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    route = _add_route(paths["socket"])
    route_id = route["route_id"]

    event_id = _seed_event(
        paths["state_db"],
        agent_id=_SLAVE,
        excerpt="Need reviewer input",
        observed_at="2026-05-17T12:00:01.000Z",
    )

    row = _wait_for_route_row(
        paths["state_db"],
        route_id=route_id,
        event_id=event_id,
        expected_state="delivered",
    )
    assert row["origin"] == "route"
    assert row["route_id"] == route_id
    assert row["event_id"] == event_id
    assert row["sender_agent_id"] == _MASTER_A
    assert row["target_agent_id"] == _SLAVE
    assert _route_cursor(paths["state_db"], route_id=route_id) >= event_id

    deadline = time.monotonic() + 10.0
    route_matched = []
    queue_enqueued = []
    queue_delivered = []
    while time.monotonic() < deadline:
        records = f9.read_audit_jsonl(paths["events_file"])
        route_matched = [
            r for r in records
            if r.get("event_type") == "route_matched"
            and r.get("route_id") == route_id
            and r.get("event_id") == event_id
        ]
        queue_enqueued = [
            r for r in records
            if r.get("event_type") == "queue_message_enqueued"
            and r.get("message_id") == row["message_id"]
        ]
        queue_delivered = [
            r for r in records
            if r.get("event_type") == "queue_message_delivered"
            and r.get("message_id") == row["message_id"]
        ]
        if route_matched and queue_enqueued and queue_delivered:
            break
        time.sleep(0.05)

    assert len(route_matched) == 1, route_matched
    assert len(queue_enqueued) == 1, queue_enqueued
    assert len(queue_delivered) == 1, queue_delivered


def test_route_duplicate_insert_recovers_cleanly_after_restart(tmp_path: Path) -> None:
    env = helpers.isolated_env(tmp_path)
    env["_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT"] = "after_commit"
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(
            paths["state_db"],
            master_agent_id=_MASTER_A,
            slave_agent_id=_SLAVE,
            master_label="queen-a",
            slave_label="worker-1",
        )
        route = _add_route(paths["socket"])
        route_id = route["route_id"]
        event_id = _seed_event(
            paths["state_db"],
            agent_id=_SLAVE,
            excerpt="Restart dedupe trigger",
            observed_at="2026-05-17T12:00:02.000Z",
        )

        first_row = _wait_for_route_row(
            paths["state_db"],
            route_id=route_id,
            event_id=event_id,
            timeout_seconds=10.0,
        )
        assert first_row, "routing worker never inserted the first queue row"
    finally:
        helpers.stop_daemon_if_alive(env)

    env.pop("_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT", None)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        deadline = time.monotonic() + 5.0
        rows: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            rows = _route_queue_rows(
                paths["state_db"],
                route_id=route_id,
                event_id=event_id,
            )
            if len(rows) == 1 and _route_cursor(paths["state_db"], route_id=route_id) >= event_id:
                break
            time.sleep(0.05)

        assert len(rows) == 1, rows
        assert rows[0]["origin"] == "route"
        assert rows[0]["route_id"] == route_id
        assert rows[0]["event_id"] == event_id
        assert _route_cursor(paths["state_db"], route_id=route_id) >= event_id

        records = f9.read_audit_jsonl(paths["events_file"])
        route_matched = [
            r for r in records
            if r.get("event_type") == "route_matched"
            and r.get("route_id") == route_id
            and r.get("event_id") == event_id
        ]
        assert len(route_matched) == 1, route_matched
    finally:
        helpers.stop_daemon_if_alive(env)


def test_per_target_fifo_preserved_under_concurrent_masters(
    daemon_with_two_masters_and_slave,
) -> None:
    env, paths = daemon_with_two_masters_and_slave
    barrier = threading.Barrier(2)

    def _burst(sender_agent_id: str, prefix: str) -> list[str]:
        barrier.wait(timeout=5.0)
        out: list[str] = []
        for i in range(5):
            row = _send_input(
                paths["socket"],
                paths["state_db"],
                sender_agent_id=sender_agent_id,
                target=_SLAVE,
                body=f"{prefix}-{i}".encode("utf-8"),
            )
            out.append(str(row["message_id"]))
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_burst, _MASTER_A, "a"),
            pool.submit(_burst, _MASTER_B, "b"),
        ]
        message_ids: list[str] = []
        for future in concurrent.futures.as_completed(futures):
            message_ids.extend(future.result())

    assert len(message_ids) == 10
    assert len(set(message_ids)) == 10

    for message_id in message_ids:
        row = f9.wait_for_queue_state(
            paths["state_db"],
            message_id=message_id,
            expected_state="delivered",
            timeout_seconds=10.0,
        )
        assert row["state"] == "delivered", row

    rows = _rows_for_message_ids(paths["state_db"], message_ids=message_ids)
    assert len(rows) == 10

    enqueued_order = [(r["enqueued_at"], r["message_id"]) for r in rows]
    started_order = [(r["delivery_attempt_started_at"], r["message_id"]) for r in rows]
    delivered_order = [(r["delivered_at"], r["message_id"]) for r in rows]

    assert started_order == sorted(started_order), started_order
    assert delivered_order == sorted(delivered_order), delivered_order
    assert [r["message_id"] for r in rows] == [mid for _, mid in sorted(enqueued_order)]
