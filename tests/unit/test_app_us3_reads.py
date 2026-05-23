"""FEAT-011 T054..T058 unit tests — US3 entity-read handlers.

In-process tests for the five remaining ``app.<entity>.list``/``.detail``
read surfaces: ``container``, ``log_attachment``, ``event``, ``queue``,
and ``route``. Uses a real SQLite state DB built from the production
schema so the handlers exercise their direct-query / DAO paths
end-to-end. Handlers are called directly (no socket round-trip).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import reads, sessions
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_registry() -> None:
    sessions.set_registry(sessions.SessionRegistry())


@pytest.fixture
def host_peer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield os.geteuid()
    finally:
        _clear_request_peer_context()


@pytest.fixture
def daemon_ctx(tmp_path: Path) -> DaemonContext:
    """DaemonContext backed by a real state-db with the production schema."""
    from agenttower.state.schema import open_registry

    state_db = tmp_path / "registry.db"
    conn, _ = open_registry(state_db, namespace_root=tmp_path)
    conn.close()  # Reads open their own ephemeral connection.

    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=state_db,
        daemon_version="0.0.0-test",
        schema_version=10,
    )


@pytest.fixture
def host_session(daemon_ctx: DaemonContext, host_peer: int) -> tuple[int, str]:
    from agenttower.app_contract import hello as hello_mod

    env = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"], env
    return host_peer, env["result"]["app_session_token"]


# ─── Helpers — seed the state DB ─────────────────────────────────────────


def _seed_container(
    conn: sqlite3.Connection,
    *,
    container_id: str,
    name: str,
    active: bool = True,
    first_seen_at: str = "2026-05-19T00:00:00Z",
    last_scanned_at: str = "2026-05-19T00:00:00Z",
) -> None:
    conn.execute(
        """
        INSERT INTO containers
            (container_id, name, image, status, labels_json, mounts_json,
             inspect_json, config_user, working_dir, active,
             first_seen_at, last_scanned_at)
        VALUES (?, ?, 'img:latest', 'running', '{}', '[]', '{}',
                '', '/work', ?, ?, ?)
        """,
        (container_id, name, 1 if active else 0, first_seen_at, last_scanned_at),
    )


def _seed_agent(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    container_id: str = "ctr-1",
    pane_id: str = "p-1",
    role: str = "slave",
    capability: str = "claude",
) -> None:
    conn.execute(
        """
        INSERT INTO agents (
            agent_id, container_id, tmux_socket_path, tmux_session_name,
            tmux_window_index, tmux_pane_index, tmux_pane_id,
            role, capability, label, project_path, parent_agent_id,
            effective_permissions, created_at, last_registered_at,
            last_seen_at, active
        ) VALUES (?, ?, '/tmp/tmux-1000/default', 'main', 0, 0, ?,
                  ?, ?, 'lbl', '', NULL, '{}',
                  '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z',
                  '2026-05-19T00:00:00Z', 1)
        """,
        (agent_id, container_id, pane_id, role, capability),
    )


def _seed_log_attachment(
    conn: sqlite3.Connection,
    *,
    attachment_id: str,
    agent_id: str,
    container_id: str = "ctr-1",
    status: str = "active",
    source: str = "explicit",
    log_path: str | None = None,
    attached_at: str = "2026-05-19T00:00:00Z",
    last_status_at: str = "2026-05-19T00:00:00Z",
) -> None:
    conn.execute(
        """
        INSERT INTO log_attachments (
            attachment_id, agent_id, container_id, tmux_socket_path,
            tmux_session_name, tmux_window_index, tmux_pane_index,
            tmux_pane_id, log_path, status, source, pipe_pane_command,
            prior_pipe_target, attached_at, last_status_at,
            superseded_at, superseded_by, created_at
        ) VALUES (?, ?, ?, '/tmp/tmux-1000/default', 'main', 0, 0,
                  'p-1', ?, ?, ?, 'cat', NULL, ?, ?, NULL, NULL,
                  '2026-05-19T00:00:00Z')
        """,
        (
            attachment_id,
            agent_id,
            container_id,
            log_path or f"/logs/{attachment_id}.log",
            status,
            source,
            attached_at,
            last_status_at,
        ),
    )


def _seed_event(
    conn: sqlite3.Connection,
    *,
    event_type: str = "activity",
    agent_id: str = "agt-1",
    observed_at: str = "2026-05-19T00:00:00Z",
    excerpt: str = "some output",
    classifier_rule_id: str = "rule-1",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO events (
            event_type, agent_id, attachment_id, log_path,
            byte_range_start, byte_range_end, line_offset_start,
            line_offset_end, observed_at, record_at, excerpt,
            classifier_rule_id
        ) VALUES (?, ?, 'la-1', '/logs/x.log', 0, 1, 0, 1, ?, NULL, ?, ?)
        """,
        (event_type, agent_id, observed_at, excerpt, classifier_rule_id),
    )
    return int(cur.lastrowid)


def _seed_queue_message(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    state: str = "queued",
    sender_agent_id: str = "agt-sender",
    target_agent_id: str = "agt-target",
    enqueued_at: str = "2026-05-19T00:00:00Z",
    last_updated_at: str = "2026-05-19T00:00:00Z",
    block_reason: str | None = None,
    failure_reason: str | None = None,
) -> None:
    terminal_cols = ""
    terminal_vals: tuple = ()
    if state == "delivered":
        terminal_cols = ", delivered_at"
        terminal_vals = (enqueued_at,)
    elif state == "failed":
        terminal_cols = ", failed_at"
        terminal_vals = (enqueued_at,)
    elif state == "canceled":
        terminal_cols = ", canceled_at"
        terminal_vals = (enqueued_at,)
    conn.execute(
        f"""
        INSERT INTO message_queue (
            message_id, state, block_reason, failure_reason,
            sender_agent_id, sender_label, sender_role, sender_capability,
            target_agent_id, target_label, target_role, target_capability,
            target_container_id, target_pane_id, envelope_body,
            envelope_body_sha256, envelope_size_bytes, enqueued_at,
            last_updated_at{terminal_cols}
        ) VALUES (?, ?, ?, ?, ?, 'snd', 'master', 'claude',
                  ?, 'tgt', 'slave', 'claude', 'ctr-1', 'p-1',
                  X'00', 'sha', 1, ?, ?{', ?' * len(terminal_vals)})
        """,
        (
            message_id,
            state,
            block_reason,
            failure_reason,
            sender_agent_id,
            target_agent_id,
            enqueued_at,
            last_updated_at,
            *terminal_vals,
        ),
    )


def _seed_route(
    conn: sqlite3.Connection,
    *,
    route_id: str,
    event_type: str = "activity",
    enabled: bool = True,
    created_at: str = "2026-05-19T00:00:00Z",
    updated_at: str = "2026-05-19T00:00:00Z",
) -> None:
    conn.execute(
        """
        INSERT INTO routes (
            route_id, event_type, source_scope_kind, source_scope_value,
            target_rule, target_value, master_rule, master_value,
            template, enabled, last_consumed_event_id,
            created_at, updated_at, created_by_agent_id
        ) VALUES (?, ?, 'any', NULL, 'role', 'master', 'auto', NULL,
                  'tmpl', ?, 0, ?, ?, NULL)
        """,
        (route_id, event_type, 1 if enabled else 0, created_at, updated_at),
    )


# ─── app.container.list / detail (T054) ──────────────────────────────────


@pytest.fixture
def container_db(daemon_ctx: DaemonContext) -> DaemonContext:
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-a", name="charlie", active=True)
        _seed_container(conn, container_id="ctr-b", name="alpha", active=False)
        _seed_container(conn, container_id="ctr-c", name="bravo", active=True)
        conn.commit()
    finally:
        conn.close()
    return daemon_ctx


def test_container_list_happy_path(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_list(
        container_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is True, env
    result = env["result"]
    assert result["total"] == 3
    # Default order is name ASC.
    assert [r["name"] for r in result["rows"]] == ["alpha", "bravo", "charlie"]
    assert result["ordering"] == "name:asc"


def test_container_list_derived_state(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_list(
        container_db, {"app_session_token": token}, peer_uid=uid
    )
    by_id = {r["container_id"]: r for r in env["result"]["rows"]}
    assert by_id["ctr-a"]["state"] == "active"
    assert by_id["ctr-b"]["state"] == "inactive"


def test_container_list_filter_by_state(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_list(
        container_db,
        {"app_session_token": token, "filters": {"state": "inactive"}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["container_id"] == "ctr-b"


def test_container_list_rejects_unknown_filter(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_list(
        container_db,
        {"app_session_token": token, "filters": {"frob": True}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "frob"


def test_container_list_rejects_unknown_state_value(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_list(
        container_db,
        {"app_session_token": token, "filters": {"state": "exploded"}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "state"


def test_container_list_rejects_limit_out_of_bounds(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    for bad in (0, 201, "fifty"):
        env = reads.app_container_list(
            container_db,
            {"app_session_token": token, "limit": bad},
            peer_uid=uid,
        )
        assert env["ok"] is False, (bad, env)
        assert env["error"]["details"]["field"] == "limit"


def test_container_list_order_by_first_seen_desc(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(
            conn, container_id="c1", name="z", first_seen_at="2026-01-01T00:00:00Z"
        )
        _seed_container(
            conn, container_id="c2", name="a", first_seen_at="2026-03-01T00:00:00Z"
        )
        conn.commit()
    finally:
        conn.close()
    env = reads.app_container_list(
        daemon_ctx,
        {"app_session_token": token, "order_by": "first_seen_at:desc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert [r["container_id"] for r in env["result"]["rows"]] == ["c2", "c1"]


def test_container_detail_happy_path(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_detail(
        container_db,
        {"app_session_token": token, "container_id": "ctr-c"},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["name"] == "bravo"


def test_container_detail_not_found(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_detail(
        container_db,
        {"app_session_token": token, "container_id": "ctr-nope"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "not_found"


def test_container_detail_missing_param(
    container_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_container_detail(
        container_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "container_id"


# ─── app.log_attachment.list / detail (T055) ─────────────────────────────


@pytest.fixture
def log_attachment_db(daemon_ctx: DaemonContext) -> DaemonContext:
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        _seed_agent(conn, agent_id="agt-1")
        _seed_agent(conn, agent_id="agt-2", pane_id="p-2")
        _seed_log_attachment(
            conn,
            attachment_id="la-1",
            agent_id="agt-1",
            status="active",
            last_status_at="2026-05-19T03:00:00Z",
        )
        _seed_log_attachment(
            conn,
            attachment_id="la-2",
            agent_id="agt-2",
            status="stale",
            last_status_at="2026-05-19T01:00:00Z",
        )
        conn.commit()
    finally:
        conn.close()
    return daemon_ctx


def test_log_attachment_list_happy_path(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_list(
        log_attachment_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is True, env
    assert env["result"]["total"] == 2
    # Default order last_status_at DESC → la-1 (03:00) before la-2 (01:00).
    assert [r["attachment_id"] for r in env["result"]["rows"]] == ["la-1", "la-2"]
    assert env["result"]["ordering"] == "last_status_at:desc"


def test_log_attachment_list_filter_by_agent(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_list(
        log_attachment_db,
        {"app_session_token": token, "filters": {"agent_id": "agt-2"}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "agt-2"


def test_log_attachment_list_filter_by_status(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_list(
        log_attachment_db,
        {"app_session_token": token, "filters": {"status": "active"}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "active"


def test_log_attachment_list_rejects_unknown_filter(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_list(
        log_attachment_db,
        {"app_session_token": token, "filters": {"bogus": "x"}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "bogus"


def test_log_attachment_list_order_by_status(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_list(
        log_attachment_db,
        {"app_session_token": token, "order_by": "status:asc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert [r["status"] for r in env["result"]["rows"]] == ["active", "stale"]


def test_log_attachment_list_rejects_limit(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_list(
        log_attachment_db,
        {"app_session_token": token, "limit": 999},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "limit"


def test_log_attachment_detail_happy_path(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_detail(
        log_attachment_db,
        {"app_session_token": token, "attachment_id": "la-1"},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["agent_id"] == "agt-1"


def test_log_attachment_detail_not_found(
    log_attachment_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_log_attachment_detail(
        log_attachment_db,
        {"app_session_token": token, "attachment_id": "la-nope"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "not_found"


# ─── app.event.list / detail (T056) ──────────────────────────────────────


@pytest.fixture
def event_db(daemon_ctx: DaemonContext) -> tuple[DaemonContext, list[int]]:
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    ids: list[int] = []
    try:
        ids.append(
            _seed_event(
                conn,
                event_type="activity",
                agent_id="agt-1",
                observed_at="2026-05-19T01:00:00Z",
            )
        )
        ids.append(
            _seed_event(
                conn,
                event_type="error",
                agent_id="agt-2",
                observed_at="2026-05-19T02:00:00Z",
            )
        )
        ids.append(
            _seed_event(
                conn,
                event_type="completed",
                agent_id="agt-1",
                observed_at="2026-05-19T03:00:00Z",
            )
        )
        conn.commit()
    finally:
        conn.close()
    return daemon_ctx, ids


def test_event_list_happy_path(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, ids = event_db
    uid, token = host_session
    env = reads.app_event_list(ctx, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True, env
    assert env["result"]["total"] == 3
    # Default order event_id DESC.
    returned = [r["event_id"] for r in env["result"]["rows"]]
    assert returned == sorted(ids, reverse=True)
    assert env["result"]["ordering"] == "event_id:desc"


def test_event_list_filter_by_type(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx,
        {"app_session_token": token, "filters": {"event_type": "error"}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["event_type"] == "error"


def test_event_list_filter_by_agent(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx,
        {"app_session_token": token, "filters": {"agent_id": "agt-1"}},
        peer_uid=uid,
    )
    assert env["result"]["total"] == 2
    assert all(r["agent_id"] == "agt-1" for r in env["result"]["rows"])


def test_event_list_filter_since_until(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx,
        {
            "app_session_token": token,
            "filters": {
                "since": "2026-05-19T01:30:00Z",
                "until": "2026-05-19T02:30:00Z",
            },
        },
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["event_type"] == "error"


def test_event_list_rejects_since_after_until(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx,
        {
            "app_session_token": token,
            "filters": {"since": "2026-05-20T00:00:00Z", "until": "2026-05-19T00:00:00Z"},
        },
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "since"


def test_event_list_rejects_unknown_filter(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx,
        {"app_session_token": token, "filters": {"origin": "x"}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "origin"


@pytest.mark.parametrize(
    ("filter_field", "operator_value"),
    [
        ("event_type", "err*"),
        ("event_type", "%error"),
        ("agent_id", "agt-1~"),
        ("agent_id", "agt<1"),
        ("event_type", "type LIKE foo"),
    ],
)
def test_event_list_rejects_operator_laden_filter_value(
    event_db: tuple[DaemonContext, list[int]],
    host_session: tuple[int, str],
    filter_field: str,
    operator_value: str,
) -> None:
    """SC-018 / FR-024a: v1.0 filters are exact-match only. A filter value
    carrying operator-like syntax must be rejected with validation_failed
    and details.field naming the offending filter."""
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx,
        {"app_session_token": token, "filters": {filter_field: operator_value}},
        peer_uid=uid,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == filter_field
    assert env["error"]["details"]["reason"] == "operator syntax not supported"


def test_event_list_order_by_observed_at_asc(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx,
        {"app_session_token": token, "order_by": "observed_at:asc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    types = [r["event_type"] for r in env["result"]["rows"]]
    assert types == ["activity", "error", "completed"]


def test_event_list_rejects_limit(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_list(
        ctx, {"app_session_token": token, "limit": 0}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "limit"


def test_event_detail_happy_path(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, ids = event_db
    uid, token = host_session
    env = reads.app_event_detail(
        ctx, {"app_session_token": token, "event_id": ids[1]}, peer_uid=uid
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["event_id"] == ids[1]
    assert env["result"]["row"]["event_type"] == "error"


def test_event_detail_accepts_string_id(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, ids = event_db
    uid, token = host_session
    env = reads.app_event_detail(
        ctx, {"app_session_token": token, "event_id": str(ids[0])}, peer_uid=uid
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["event_id"] == ids[0]


def test_event_detail_not_found(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_detail(
        ctx, {"app_session_token": token, "event_id": 999999}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "not_found"


def test_event_detail_rejects_non_numeric_id(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_detail(
        ctx, {"app_session_token": token, "event_id": "not-a-number"}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "event_id"


def test_event_detail_rejects_bool_id(
    event_db: tuple[DaemonContext, list[int]], host_session: tuple[int, str]
) -> None:
    """A bool is not a valid event_id even though it subclasses int."""
    ctx, _ = event_db
    uid, token = host_session
    env = reads.app_event_detail(
        ctx, {"app_session_token": token, "event_id": True}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "event_id"


# ─── app.queue.list / detail (T057) ──────────────────────────────────────


@pytest.fixture
def queue_db(daemon_ctx: DaemonContext) -> DaemonContext:
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_queue_message(
            conn,
            message_id="msg-delivered",
            state="delivered",
            enqueued_at="2026-05-19T00:00:00Z",
        )
        _seed_queue_message(
            conn,
            message_id="msg-queued",
            state="queued",
            enqueued_at="2026-05-19T02:00:00Z",
        )
        _seed_queue_message(
            conn,
            message_id="msg-blocked",
            state="blocked",
            block_reason="operator_delayed",
            enqueued_at="2026-05-19T01:00:00Z",
        )
        conn.commit()
    finally:
        conn.close()
    return daemon_ctx


def test_queue_list_happy_path_default_priority_order(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is True, env
    assert env["result"]["total"] == 3
    # Default order (state_priority, enqueued_at) ASC:
    # queued(1) < blocked(2) < delivered(4).
    assert [r["message_id"] for r in env["result"]["rows"]] == [
        "msg-queued",
        "msg-blocked",
        "msg-delivered",
    ]
    assert env["result"]["ordering"] == "default:asc"


def test_queue_list_filter_by_state(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db,
        {"app_session_token": token, "filters": {"state": "blocked"}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["state"] == "blocked"
    assert rows[0]["block_reason"] == "operator_delayed"


def test_queue_list_filter_by_target(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_queue_message(
            conn, message_id="m1", target_agent_id="agt-x"
        )
        _seed_queue_message(
            conn, message_id="m2", target_agent_id="agt-y"
        )
        conn.commit()
    finally:
        conn.close()
    env = reads.app_queue_list(
        daemon_ctx,
        {"app_session_token": token, "filters": {"target_agent_id": "agt-y"}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["message_id"] == "m2"


def test_queue_list_filter_since_until(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """since/until are matched against enqueued_at."""
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db,
        {
            "app_session_token": token,
            "filters": {
                "since": "2026-05-19T00:30:00Z",
                "until": "2026-05-19T01:30:00Z",
            },
        },
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["message_id"] == "msg-blocked"


def test_queue_list_rejects_since_after_until(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db,
        {
            "app_session_token": token,
            "filters": {"since": "2026-05-20T00:00:00Z", "until": "2026-05-19T00:00:00Z"},
        },
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "since"


def test_queue_list_rejects_unknown_filter(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db,
        {"app_session_token": token, "filters": {"route_id": "r"}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "route_id"


@pytest.mark.parametrize(
    ("filter_field", "operator_value"),
    [
        ("state", "blocked%"),
        ("sender_agent_id", "agt<x"),
        ("target_agent_id", "agt-y*"),
        ("target_agent_id", "id ~ pattern"),
    ],
)
def test_queue_list_rejects_operator_laden_filter_value(
    queue_db: DaemonContext,
    host_session: tuple[int, str],
    filter_field: str,
    operator_value: str,
) -> None:
    """SC-018 / FR-024a: app.queue.list filters are exact-match only."""
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db,
        {"app_session_token": token, "filters": {filter_field: operator_value}},
        peer_uid=uid,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == filter_field
    assert env["error"]["details"]["reason"] == "operator syntax not supported"


def test_queue_list_payload_preview_redacted(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """v1.0 simplification: payload_preview is "" (raw bytes never exposed)."""
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db, {"app_session_token": token}, peer_uid=uid
    )
    assert all(r["payload_preview"] == "" for r in env["result"]["rows"])


def test_queue_list_order_by_enqueued_at(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db,
        {"app_session_token": token, "order_by": "enqueued_at:asc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert [r["message_id"] for r in env["result"]["rows"]] == [
        "msg-delivered",
        "msg-blocked",
        "msg-queued",
    ]


def test_queue_list_rejects_limit(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_list(
        queue_db, {"app_session_token": token, "limit": -5}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "limit"


def test_queue_detail_happy_path(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_detail(
        queue_db,
        {"app_session_token": token, "message_id": "msg-queued"},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    row = env["result"]["row"]
    assert row["message_id"] == "msg-queued"
    assert row["state"] == "queued"
    assert row["state_priority"] == 1


def test_queue_detail_not_found(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_detail(
        queue_db,
        {"app_session_token": token, "message_id": "msg-nope"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "queue_message_not_found"
    assert env["error"]["details"]["message_id"] == "msg-nope"


def test_queue_detail_missing_param(
    queue_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_queue_detail(
        queue_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "message_id"


# ─── app.route.list / detail (T058) ──────────────────────────────────────


@pytest.fixture
def route_db(daemon_ctx: DaemonContext) -> DaemonContext:
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_route(
            conn,
            route_id="rt-b",
            enabled=True,
            created_at="2026-05-19T02:00:00Z",
        )
        _seed_route(
            conn,
            route_id="rt-a",
            enabled=False,
            created_at="2026-05-19T01:00:00Z",
        )
        _seed_route(
            conn,
            route_id="rt-c",
            enabled=True,
            created_at="2026-05-19T03:00:00Z",
        )
        conn.commit()
    finally:
        conn.close()
    return daemon_ctx


def test_route_list_happy_path(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_list(
        route_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is True, env
    assert env["result"]["total"] == 3
    # Default order (created_at, route_id) ASC.
    assert [r["route_id"] for r in env["result"]["rows"]] == [
        "rt-a",
        "rt-b",
        "rt-c",
    ]
    assert env["result"]["ordering"] == "default:asc"


def test_route_list_filter_by_enabled(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_list(
        route_db,
        {"app_session_token": token, "filters": {"enabled": True}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert {r["route_id"] for r in rows} == {"rt-b", "rt-c"}
    assert all(r["enabled"] is True for r in rows)


def test_route_list_filter_enabled_false(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_list(
        route_db,
        {"app_session_token": token, "filters": {"enabled": False}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["route_id"] == "rt-a"


def test_route_list_rejects_non_bool_enabled(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_list(
        route_db,
        {"app_session_token": token, "filters": {"enabled": "yes"}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "enabled"


def test_route_list_rejects_unknown_filter(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_list(
        route_db,
        {"app_session_token": token, "filters": {"bad": 1}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "bad"


@pytest.mark.parametrize("operator_value", ["<true", "true*", "en~abled"])
def test_route_list_rejects_operator_laden_filter_value(
    route_db: DaemonContext,
    host_session: tuple[int, str],
    operator_value: str,
) -> None:
    """SC-018 / FR-024a: app.route.list's only filter (`enabled`) is
    exact-match only; an operator-laden string value is rejected before
    the boolean-type check."""
    uid, token = host_session
    env = reads.app_route_list(
        route_db,
        {"app_session_token": token, "filters": {"enabled": operator_value}},
        peer_uid=uid,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "enabled"
    assert env["error"]["details"]["reason"] == "operator syntax not supported"


def test_route_list_order_by_updated_at_desc(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_list(
        route_db,
        {"app_session_token": token, "order_by": "created_at:desc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert [r["route_id"] for r in env["result"]["rows"]] == [
        "rt-c",
        "rt-b",
        "rt-a",
    ]


def test_route_list_rejects_limit(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_list(
        route_db, {"app_session_token": token, "limit": 500}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "limit"


def test_route_list_pagination_via_cursor(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    page1 = reads.app_route_list(
        route_db, {"app_session_token": token, "limit": 2}, peer_uid=uid
    )
    assert len(page1["result"]["rows"]) == 2
    cursor = page1["result"]["cursor_next"]
    assert cursor is not None
    page2 = reads.app_route_list(
        route_db,
        {"app_session_token": token, "limit": 2, "cursor_next": cursor},
        peer_uid=uid,
    )
    assert len(page2["result"]["rows"]) == 1
    assert page2["result"]["cursor_next"] is None


def test_route_detail_happy_path(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_detail(
        route_db,
        {"app_session_token": token, "route_id": "rt-b"},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    row = env["result"]["row"]
    assert row["route_id"] == "rt-b"
    assert row["source_scope"] == {"kind": "any", "value": None}
    assert row["target"] == {"rule": "role", "value": "master"}


def test_route_detail_not_found(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_detail(
        route_db,
        {"app_session_token": token, "route_id": "rt-nope"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "route_not_found"
    assert env["error"]["details"]["route_id"] == "rt-nope"


def test_route_detail_missing_param(
    route_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_route_detail(
        route_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "route_id"


# ─── Cross-cutting: session gate + host-only + internal_error ────────────


def _unwired_ctx(base: DaemonContext) -> DaemonContext:
    return DaemonContext(
        pid=base.pid,
        start_time_utc=base.start_time_utc,
        socket_path=base.socket_path,
        state_path=None,
        daemon_version=base.daemon_version,
        schema_version=base.schema_version,
    )


@pytest.mark.parametrize(
    "handler,extra",
    [
        (reads.app_container_list, {}),
        (reads.app_container_detail, {"container_id": "x"}),
        (reads.app_log_attachment_list, {}),
        (reads.app_log_attachment_detail, {"attachment_id": "x"}),
        (reads.app_event_list, {}),
        (reads.app_event_detail, {"event_id": 1}),
        (reads.app_queue_list, {}),
        (reads.app_queue_detail, {"message_id": "x"}),
        (reads.app_route_list, {}),
        (reads.app_route_detail, {"route_id": "x"}),
    ],
)
def test_us3_handlers_session_gate_rejects_missing_token(
    daemon_ctx: DaemonContext, host_peer: int, handler, extra: dict
) -> None:
    env = handler(daemon_ctx, dict(extra), peer_uid=host_peer)
    assert env["ok"] is False
    assert env["error"]["code"] in (
        "app_session_required",
        "app_session_expired",
    )


@pytest.mark.parametrize(
    "handler,extra",
    [
        (reads.app_container_list, {}),
        (reads.app_container_detail, {"container_id": "x"}),
        (reads.app_log_attachment_list, {}),
        (reads.app_event_list, {}),
        (reads.app_queue_detail, {"message_id": "x"}),
        (reads.app_route_list, {}),
    ],
)
def test_us3_handlers_host_only_rejects_container_peer(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], handler, extra: dict
) -> None:
    _uid, token = host_session
    env = handler(
        daemon_ctx, {"app_session_token": token, **extra}, peer_uid=-1
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "host_only"


@pytest.mark.parametrize(
    "handler,extra",
    [
        (reads.app_container_list, {}),
        (reads.app_container_detail, {"container_id": "x"}),
        (reads.app_log_attachment_list, {}),
        (reads.app_log_attachment_detail, {"attachment_id": "x"}),
        (reads.app_event_list, {}),
        (reads.app_event_detail, {"event_id": 1}),
        (reads.app_queue_list, {}),
        (reads.app_queue_detail, {"message_id": "x"}),
        (reads.app_route_list, {}),
        (reads.app_route_detail, {"route_id": "x"}),
    ],
)
def test_us3_handlers_internal_error_when_state_path_unwired(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], handler, extra: dict
) -> None:
    uid, token = host_session
    env = handler(
        _unwired_ctx(daemon_ctx),
        {"app_session_token": token, **extra},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def _corrupt_db_ctx(base: DaemonContext, tmp_path: Path) -> DaemonContext:
    bad = tmp_path / "not-a-db.sqlite3"
    bad.write_text("definitely not a sqlite database\n")
    return DaemonContext(
        pid=base.pid,
        start_time_utc=base.start_time_utc,
        socket_path=base.socket_path,
        state_path=bad,
        daemon_version=base.daemon_version,
        schema_version=base.schema_version,
    )


@pytest.mark.parametrize(
    "handler,extra",
    [
        (reads.app_container_list, {}),
        (reads.app_container_detail, {"container_id": "x"}),
        (reads.app_log_attachment_list, {}),
        (reads.app_log_attachment_detail, {"attachment_id": "x"}),
        (reads.app_event_list, {}),
        (reads.app_event_detail, {"event_id": 1}),
        (reads.app_queue_list, {}),
        (reads.app_queue_detail, {"message_id": "x"}),
        (reads.app_route_list, {}),
        (reads.app_route_detail, {"route_id": "x"}),
    ],
)
def test_us3_handlers_sqlite_error_returns_internal_error(
    daemon_ctx: DaemonContext,
    host_session: tuple[int, str],
    tmp_path: Path,
    handler,
    extra: dict,
) -> None:
    uid, token = host_session
    env = handler(
        _corrupt_db_ctx(daemon_ctx, tmp_path),
        {"app_session_token": token, **extra},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "state-db query failed" in env["error"]["message"]


@pytest.mark.parametrize(
    "handler",
    [
        reads.app_container_list,
        reads.app_log_attachment_list,
        reads.app_event_list,
        reads.app_queue_list,
        reads.app_route_list,
    ],
)
def test_us3_lists_empty_db_returns_no_rows(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], handler
) -> None:
    uid, token = host_session
    env = handler(daemon_ctx, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True
    assert env["result"]["total"] == 0
    assert env["result"]["rows"] == []
    assert env["result"]["cursor_next"] is None


@pytest.mark.parametrize(
    "handler",
    [
        reads.app_container_list,
        reads.app_log_attachment_list,
        reads.app_event_list,
        reads.app_queue_list,
        reads.app_route_list,
    ],
)
def test_us3_lists_reject_bad_order_by(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], handler
) -> None:
    uid, token = host_session
    env = handler(
        daemon_ctx,
        {"app_session_token": token, "order_by": "nonsense_field"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "order_by"


@pytest.mark.parametrize(
    "handler",
    [
        reads.app_container_list,
        reads.app_log_attachment_list,
        reads.app_event_list,
        reads.app_queue_list,
        reads.app_route_list,
    ],
)
def test_us3_lists_reject_non_object_filters(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], handler
) -> None:
    uid, token = host_session
    env = handler(
        daemon_ctx,
        {"app_session_token": token, "filters": ["not", "object"]},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "filters"
