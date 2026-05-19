"""FEAT-011 T039 + T040 unit tests — read handlers.

In-process tests for ``app.pane.list``/``.detail`` and
``app.agent.list``/``.detail``. Uses a real SQLite state DB so we can
exercise the DAO joins and FR-022/FR-023 derived fields end-to-end.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import reads, sessions
from agenttower.socket_api.methods import (
    DISPATCH,
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


def _seed_container(conn: sqlite3.Connection, *, container_id: str, name: str) -> None:
    conn.execute(
        """
        INSERT INTO containers
            (container_id, name, image, status, labels_json, mounts_json,
             inspect_json, config_user, working_dir, active,
             first_seen_at, last_scanned_at)
        VALUES (?, ?, 'img:latest', 'running', '{}', '[]', '{}',
                '', '/work', 1,
                '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
        """,
        (container_id, name),
    )


def _seed_pane(
    conn: sqlite3.Connection,
    *,
    container_id: str,
    container_name: str,
    pane_id: str,
    socket_path: str = "/tmp/tmux-1000/default",
    session_name: str = "main",
    window_index: int = 0,
    pane_index: int = 0,
    active: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO panes (
            container_id, tmux_socket_path, tmux_session_name,
            tmux_window_index, tmux_pane_index, tmux_pane_id,
            container_name, container_user, pane_pid, pane_tty,
            pane_current_command, pane_current_path, pane_title,
            pane_active, active, first_seen_at, last_scanned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '', 0, '', '', '', '',
                  1, ?, '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
        """,
        (
            container_id, socket_path, session_name,
            window_index, pane_index, pane_id,
            container_name, 1 if active else 0,
        ),
    )


def _seed_agent(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    container_id: str,
    pane_id: str,
    role: str = "slave",
    capability: str = "claude",
    label: str = "test",
    socket_path: str = "/tmp/tmux-1000/default",
    session_name: str = "main",
    window_index: int = 0,
    pane_index: int = 0,
    active: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO agents (
            agent_id, container_id, tmux_socket_path, tmux_session_name,
            tmux_window_index, tmux_pane_index, tmux_pane_id,
            role, capability, label, project_path, parent_agent_id,
            effective_permissions, created_at, last_registered_at,
            last_seen_at, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', NULL,
                  '{}', '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z',
                  '2026-05-19T00:00:00Z', ?)
        """,
        (
            agent_id, container_id, socket_path, session_name,
            window_index, pane_index, pane_id,
            role, capability, label,
            1 if active else 0,
        ),
    )


@pytest.fixture
def seeded_db(daemon_ctx: DaemonContext) -> DaemonContext:
    """State DB with 1 container, 3 panes, 1 registered agent."""
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        _seed_pane(
            conn,
            container_id="ctr-1",
            container_name="bench-1",
            pane_id="p-1",
            window_index=0,
        )
        _seed_pane(
            conn,
            container_id="ctr-1",
            container_name="bench-1",
            pane_id="p-2",
            window_index=1,
        )
        _seed_pane(
            conn,
            container_id="ctr-1",
            container_name="bench-1",
            pane_id="p-3",
            window_index=2,
        )
        # Register p-1 as an agent.
        _seed_agent(
            conn,
            agent_id="agt-1",
            container_id="ctr-1",
            pane_id="p-1",
            role="master",
            window_index=0,
        )
        conn.commit()
    finally:
        conn.close()
    return daemon_ctx


# ─── app.pane.list ───────────────────────────────────────────────────────


def test_pane_list_returns_all_three_panes(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(seeded_db, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True, env
    result = env["result"]
    assert result["total"] == 3
    assert len(result["rows"]) == 3
    pane_ids = sorted(row["pane_id"] for row in result["rows"])
    assert pane_ids == ["p-1", "p-2", "p-3"]


def test_pane_list_registered_flag_derived(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-022: registered/agent_id are derived from the agents join."""
    uid, token = host_session
    env = reads.app_pane_list(seeded_db, {"app_session_token": token}, peer_uid=uid)
    by_id = {row["pane_id"]: row for row in env["result"]["rows"]}
    assert by_id["p-1"]["registered"] is True
    assert by_id["p-1"]["agent_id"] == "agt-1"
    assert by_id["p-2"]["registered"] is False
    assert by_id["p-2"]["agent_id"] is None


def test_pane_list_filter_by_registered_true(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "filters": {"registered": True}},
        peer_uid=uid,
    )
    assert env["ok"] is True
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["pane_id"] == "p-1"


def test_pane_list_filter_by_registered_false(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "filters": {"registered": False}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert {r["pane_id"] for r in rows} == {"p-2", "p-3"}


def test_pane_list_pagination_via_cursor(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-020a: limit honored. FR-020b: cursor_next round-trips."""
    uid, token = host_session
    page1 = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "limit": 2},
        peer_uid=uid,
    )
    assert page1["ok"] is True
    assert len(page1["result"]["rows"]) == 2
    cursor = page1["result"]["cursor_next"]
    assert cursor is not None

    page2 = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "limit": 2, "cursor_next": cursor},
        peer_uid=uid,
    )
    assert page2["ok"] is True
    assert len(page2["result"]["rows"]) == 1
    assert page2["result"]["cursor_next"] is None


def test_pane_list_rejects_limit_out_of_bounds(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-020a: limit out of bounds → validation_failed.details.field == "limit"."""
    uid, token = host_session
    for bad in (0, -1, 201, "fifty"):
        env = reads.app_pane_list(
            seeded_db,
            {"app_session_token": token, "limit": bad},
            peer_uid=uid,
        )
        assert env["ok"] is False, (bad, env)
        assert env["error"]["code"] == "validation_failed"
        assert env["error"]["details"]["field"] == "limit"


def test_pane_list_rejects_unknown_filter(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "filters": {"frobnicated": True}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "frobnicated"


def test_pane_list_cursor_rejected_on_filter_change(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-020b: a cursor issued under one filter set is rejected when
    presented with a different filter set."""
    uid, token = host_session
    page1 = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "limit": 1},
        peer_uid=uid,
    )
    cursor = page1["result"]["cursor_next"]
    env = reads.app_pane_list(
        seeded_db,
        {
            "app_session_token": token,
            "limit": 1,
            "cursor_next": cursor,
            "filters": {"registered": True},
        },
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "cursor_next"


def test_pane_list_order_by_invalid_direction(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-021b: unknown direction suffix → validation_failed."""
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "order_by": "discovered_at:nope"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "order_by"


# ─── app.pane.detail ─────────────────────────────────────────────────────


def test_pane_detail_returns_full_view(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_detail(
        seeded_db,
        {"app_session_token": token, "pane_id": "p-1"},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    row = env["result"]["row"]
    assert row["pane_id"] == "p-1"
    assert row["registered"] is True
    assert row["agent_id"] == "agt-1"
    assert row["container_name"] == "bench-1"


def test_pane_detail_unknown_id_returns_pane_not_found(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_detail(
        seeded_db,
        {"app_session_token": token, "pane_id": "p-no-such"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "pane_not_found"
    assert env["error"]["details"]["pane_id"] == "p-no-such"


def test_pane_detail_missing_param_returns_validation_failed(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_detail(
        seeded_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "pane_id"


# ─── app.agent.list ──────────────────────────────────────────────────────


def test_agent_list_returns_seeded_agent(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(seeded_db, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True, env
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "agt-1"
    assert rows[0]["role"] == "master"
    assert rows[0]["role_priority"] == 1  # FR-021a
    assert rows[0]["log_attached"] is False
    # pane_active should reflect the active pane in the seeded DB.
    assert rows[0]["pane_active"] is True


def test_agent_list_default_ordering_role_priority(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-021/021a: default ordering is (role_priority, registered_at) ASC."""
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        # Seed agents in REVERSE priority order; the handler must
        # re-sort to (master, slave, swarm, ...).
        for i, role in enumerate(("swarm", "slave", "master")):
            _seed_pane(
                conn,
                container_id="ctr-1",
                container_name="bench-1",
                pane_id=f"p-{i}",
                window_index=i,
            )
            _seed_agent(
                conn,
                agent_id=f"agt-{i}",
                container_id="ctr-1",
                pane_id=f"p-{i}",
                role=role,
                window_index=i,
            )
        conn.commit()
    finally:
        conn.close()

    env = reads.app_agent_list(daemon_ctx, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True
    rows = env["result"]["rows"]
    roles_in_order = [r["role"] for r in rows]
    # FR-021a: master(1) < slave(2) < swarm(3).
    assert roles_in_order == ["master", "slave", "swarm"]


def test_agent_list_filter_by_role(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        for i, role in enumerate(("master", "slave")):
            _seed_pane(
                conn,
                container_id="ctr-1",
                container_name="bench-1",
                pane_id=f"p-{i}",
                window_index=i,
            )
            _seed_agent(
                conn,
                agent_id=f"agt-{i}",
                container_id="ctr-1",
                pane_id=f"p-{i}",
                role=role,
                window_index=i,
            )
        conn.commit()
    finally:
        conn.close()

    env = reads.app_agent_list(
        daemon_ctx,
        {"app_session_token": token, "filters": {"role": "slave"}},
        peer_uid=uid,
    )
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["role"] == "slave"


def test_agent_list_filter_log_attached(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """log_attached:false matches the seeded agent (no log attachment)."""
    uid, token = host_session
    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "filters": {"log_attached": False}},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert len(env["result"]["rows"]) == 1

    env2 = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "filters": {"log_attached": True}},
        peer_uid=uid,
    )
    assert env2["ok"] is True
    assert env2["result"]["rows"] == []


# ─── app.agent.detail ────────────────────────────────────────────────────


def test_agent_detail_returns_view_with_derived_fields(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_detail(
        seeded_db,
        {"app_session_token": token, "agent_id": "agt-1"},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    row = env["result"]["row"]
    assert row["agent_id"] == "agt-1"
    assert row["role"] == "master"
    assert row["role_priority"] == 1
    assert row["pane_id"] == "p-1"
    assert row["container_id"] == "ctr-1"
    assert row["log_attached"] is False
    assert row["pane_active"] is True


def test_agent_detail_unknown_id_returns_agent_not_found(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_detail(
        seeded_db,
        {"app_session_token": token, "agent_id": "agt-nope"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "agent_not_found"
    assert env["error"]["details"]["agent_id"] == "agt-nope"


# ─── Dispatcher wiring ───────────────────────────────────────────────────


def test_read_handlers_are_registered_in_dispatch() -> None:
    """T039/T040: handlers reach the FEAT-002 dispatcher."""
    for method in (
        "app.pane.list",
        "app.pane.detail",
        "app.agent.list",
        "app.agent.detail",
    ):
        assert method in DISPATCH, f"missing dispatch entry: {method}"
