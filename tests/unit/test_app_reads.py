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


# ─── Pagination helpers — direct unit coverage ───────────────────────────


def test_validate_limit_default() -> None:
    """Absent limit → DEFAULT_LIMIT, no error."""
    limit, err = reads._validate_limit({})
    assert err is None
    assert limit == reads.DEFAULT_LIMIT


def test_validate_limit_rejects_bool() -> None:
    """bool is not accepted even though it subclasses int."""
    limit, err = reads._validate_limit({"limit": True})
    assert limit == 0
    assert err is not None
    assert err["error"]["details"]["field"] == "limit"
    assert err["error"]["details"]["reason"] == "must be an integer"


def test_validate_limit_accepts_max() -> None:
    limit, err = reads._validate_limit({"limit": reads.MAX_LIMIT})
    assert err is None
    assert limit == reads.MAX_LIMIT


def test_encode_decode_cursor_round_trip() -> None:
    cur = reads._encode_cursor(10, "default:asc", {"registered": True})
    assert cur is not None
    offset, err = reads._decode_cursor(
        cur, expected_order_by="default:asc", expected_filters={"registered": True}
    )
    assert err is None
    assert offset == 10


def test_encode_cursor_returns_none_when_too_long() -> None:
    """FR-020b cap: an oversized payload yields None (line 103)."""
    huge_filters = {f"k{i}": "x" * 50 for i in range(50)}
    cur = reads._encode_cursor(0, "default:asc", huge_filters)
    assert cur is None


def test_decode_cursor_none_returns_zero() -> None:
    offset, err = reads._decode_cursor(
        None, expected_order_by="default:asc", expected_filters={}
    )
    assert err is None
    assert offset == 0


def test_decode_cursor_rejects_non_string() -> None:
    offset, err = reads._decode_cursor(
        12345, expected_order_by="default:asc", expected_filters={}
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["details"]["reason"] == "wrong type"


def test_decode_cursor_rejects_oversized_string() -> None:
    offset, err = reads._decode_cursor(
        "a" * (reads.MAX_CURSOR_BYTES + 1),
        expected_order_by="default:asc",
        expected_filters={},
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["details"]["reason"] == "too long"


def test_decode_cursor_rejects_non_base64() -> None:
    offset, err = reads._decode_cursor(
        "not-valid-base64-!!!",
        expected_order_by="default:asc",
        expected_filters={},
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["details"]["reason"] == "malformed"


def test_decode_cursor_rejects_non_object_payload() -> None:
    """A valid base64 JSON that decodes to a non-dict is malformed."""
    import base64 as _b64
    import json as _json

    raw = _b64.urlsafe_b64encode(_json.dumps([1, 2, 3]).encode()).decode("ascii")
    offset, err = reads._decode_cursor(
        raw, expected_order_by="default:asc", expected_filters={}
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["details"]["reason"] == "malformed"


def test_decode_cursor_rejects_order_by_change() -> None:
    cur = reads._encode_cursor(5, "default:asc", {})
    offset, err = reads._decode_cursor(
        cur, expected_order_by="discovered_at:desc", expected_filters={}
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["details"]["reason"] == "order_by changed mid-pagination"


def test_decode_cursor_rejects_bad_offset() -> None:
    """A tampered cursor with a negative offset is rejected (line 164)."""
    import base64 as _b64
    import json as _json

    payload = _json.dumps(
        {"offset": -1, "order_by": "default:asc", "filters": {}}
    )
    raw = _b64.urlsafe_b64encode(payload.encode()).decode("ascii")
    offset, err = reads._decode_cursor(
        raw, expected_order_by="default:asc", expected_filters={}
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["details"]["reason"] == "bad offset"


def test_validate_order_by_default() -> None:
    field, direction, canonical, err = reads._validate_order_by(
        None,
        field_set=reads._PANE_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    assert err is None
    assert (field, direction, canonical) == ("default", "asc", "default:asc")


def test_validate_order_by_rejects_non_string() -> None:
    field, direction, canonical, err = reads._validate_order_by(
        123,
        field_set=reads._PANE_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    assert err is not None
    assert err["error"]["details"]["reason"] == "wrong type"


def test_validate_order_by_rejects_empty_string() -> None:
    field, direction, canonical, err = reads._validate_order_by(
        "",
        field_set=reads._PANE_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    assert err is not None
    assert err["error"]["details"]["reason"] == "wrong type"


def test_validate_order_by_rejects_unknown_field() -> None:
    field, direction, canonical, err = reads._validate_order_by(
        "bogus_field",
        field_set=reads._PANE_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    assert err is not None
    assert err["error"]["details"]["reason"] == "unknown field"


def test_validate_order_by_bare_field_uses_default_direction() -> None:
    """A bare field with no ``:dir`` suffix takes the default direction."""
    field, direction, canonical, err = reads._validate_order_by(
        "role",
        field_set=reads._AGENT_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    assert err is None
    assert (field, direction, canonical) == ("role", "asc", "role:asc")


# ─── state-db path resolution ────────────────────────────────────────────


def test_resolve_state_db_path_none(daemon_ctx: DaemonContext) -> None:
    """state_path None → resolver returns None (line 236)."""
    ctx = DaemonContext(
        pid=daemon_ctx.pid,
        start_time_utc=daemon_ctx.start_time_utc,
        socket_path=daemon_ctx.socket_path,
        state_path=None,
        daemon_version=daemon_ctx.daemon_version,
        schema_version=daemon_ctx.schema_version,
    )
    assert reads._resolve_state_db_path(ctx) is None
    assert reads._connect_state_db(ctx) is None


def test_resolve_state_db_path_directory(daemon_ctx: DaemonContext, tmp_path: Path) -> None:
    """A directory state_path resolves to <dir>/agenttower.sqlite3 (line 239)."""
    ctx = DaemonContext(
        pid=daemon_ctx.pid,
        start_time_utc=daemon_ctx.start_time_utc,
        socket_path=daemon_ctx.socket_path,
        state_path=tmp_path,
        daemon_version=daemon_ctx.daemon_version,
        schema_version=daemon_ctx.schema_version,
    )
    resolved = reads._resolve_state_db_path(ctx)
    assert resolved is not None
    assert str(resolved).endswith("agenttower.sqlite3")


# ─── internal_error — state_path unwired ─────────────────────────────────


def _unwired_ctx(base: DaemonContext) -> DaemonContext:
    return DaemonContext(
        pid=base.pid,
        start_time_utc=base.start_time_utc,
        socket_path=base.socket_path,
        state_path=None,
        daemon_version=base.daemon_version,
        schema_version=base.schema_version,
    )


def test_pane_list_internal_error_when_state_path_unwired(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        _unwired_ctx(daemon_ctx), {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_pane_detail_internal_error_when_state_path_unwired(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_detail(
        _unwired_ctx(daemon_ctx),
        {"app_session_token": token, "pane_id": "p-1"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_agent_list_internal_error_when_state_path_unwired(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        _unwired_ctx(daemon_ctx), {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_agent_detail_internal_error_when_state_path_unwired(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_detail(
        _unwired_ctx(daemon_ctx),
        {"app_session_token": token, "agent_id": "agt-1"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


# ─── sqlite error handling — corrupt state DB ────────────────────────────


def _corrupt_db_ctx(base: DaemonContext, tmp_path: Path) -> DaemonContext:
    """A state_path pointing at a file that exists but is not a SQLite DB.

    ``sqlite3.connect`` succeeds lazily; the first query then raises
    ``sqlite3.DatabaseError`` (a subclass of ``sqlite3.Error``).
    """
    bad = tmp_path / "not-a-db.sqlite3"
    bad.write_text("this is plainly not a sqlite database file\n")
    return DaemonContext(
        pid=base.pid,
        start_time_utc=base.start_time_utc,
        socket_path=base.socket_path,
        state_path=bad,
        daemon_version=base.daemon_version,
        schema_version=base.schema_version,
    )


def test_pane_list_sqlite_error_returns_internal_error(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], tmp_path: Path
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        _corrupt_db_ctx(daemon_ctx, tmp_path),
        {"app_session_token": token},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "state-db query failed" in env["error"]["message"]


def test_agent_list_sqlite_error_returns_internal_error(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], tmp_path: Path
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        _corrupt_db_ctx(daemon_ctx, tmp_path),
        {"app_session_token": token},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "state-db query failed" in env["error"]["message"]


def test_agent_detail_sqlite_error_returns_internal_error(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], tmp_path: Path
) -> None:
    uid, token = host_session
    env = reads.app_agent_detail(
        _corrupt_db_ctx(daemon_ctx, tmp_path),
        {"app_session_token": token, "agent_id": "agt-1"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "state-db query failed" in env["error"]["message"]


# ─── pane.list — filter type validation ──────────────────────────────────


def test_pane_list_rejects_non_object_filters(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "filters": ["not", "an", "object"]},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "filters"


def test_pane_list_rejects_non_string_container_id_filter(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "filters": {"container_id": 99}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "container_id"


def test_pane_list_rejects_non_bool_registered_filter(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "filters": {"registered": "yes"}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "registered"


def test_pane_list_filter_by_container_id(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """A non-hex container_id arg resolves against containers.name (DAO note 4)."""
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "filters": {"container_id": "bench-1"}},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert env["result"]["total"] == 3


def test_pane_list_order_by_explicit_field(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """A valid explicit order_by passes validation end-to-end."""
    uid, token = host_session
    env = reads.app_pane_list(
        seeded_db,
        {"app_session_token": token, "order_by": "discovered_at:desc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert env["result"]["ordering"] == "discovered_at:desc"


def test_pane_list_empty_db_returns_no_rows(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_list(daemon_ctx, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True
    assert env["result"]["total"] == 0
    assert env["result"]["rows"] == []
    assert env["result"]["cursor_next"] is None


# ─── pane.detail — gating / validation ───────────────────────────────────


def test_pane_detail_host_only_rejects_container_peer(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """A non-host peer is rejected before any DB access."""
    _uid, token = host_session
    env = reads.app_pane_detail(
        seeded_db,
        {"app_session_token": token, "pane_id": "p-1"},
        peer_uid=-1,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "host_only"


def test_pane_detail_empty_string_pane_id_rejected(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_pane_detail(
        seeded_db,
        {"app_session_token": token, "pane_id": ""},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "pane_id"


# ─── agent.list — filter type validation ─────────────────────────────────


def test_agent_list_rejects_non_object_filters(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "filters": "nope"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "filters"


def test_agent_list_rejects_unknown_filter(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "filters": {"frobnicated": True}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "frobnicated"


def test_agent_list_rejects_non_string_role_filter(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "filters": {"role": 7}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "role"


def test_agent_list_rejects_non_bool_log_attached_filter(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "filters": {"log_attached": "true"}},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "log_attached"


def test_agent_list_rejects_limit_out_of_bounds(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "limit": 999},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "limit"


def test_agent_list_rejects_bad_order_by(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "order_by": "something:sideways"},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "order_by"


def test_agent_list_default_ordering_desc_branch(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """order_by ``default:desc`` reverses the role-priority sort (line 661+)."""
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        for i, role in enumerate(("master", "slave", "swarm")):
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
        {"app_session_token": token, "order_by": "default:desc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    roles = [r["role"] for r in env["result"]["rows"]]
    assert roles == ["swarm", "slave", "master"]


def test_agent_list_filter_by_capability(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        for i, cap in enumerate(("claude", "codex")):
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
                capability=cap,
                window_index=i,
            )
        conn.commit()
    finally:
        conn.close()

    env = reads.app_agent_list(
        daemon_ctx,
        {"app_session_token": token, "filters": {"capability": "codex"}},
        peer_uid=uid,
    )
    assert env["ok"] is True
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["capability"] == "codex"


def test_agent_list_log_attached_true_when_attachment_active(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """An ``active`` log_attachments row makes log_attached True (FR-023)."""
    uid, token = host_session
    conn = sqlite3.connect(str(seeded_db.state_path))
    try:
        conn.execute(
            """
            INSERT INTO log_attachments (
                attachment_id, agent_id, container_id, tmux_socket_path,
                tmux_session_name, tmux_window_index, tmux_pane_index,
                tmux_pane_id, log_path, status, source, pipe_pane_command,
                prior_pipe_target, attached_at, last_status_at,
                superseded_at, superseded_by, created_at
            ) VALUES (
                'la-1', 'agt-1', 'ctr-1', '/tmp/tmux-1000/default',
                'main', 0, 0, 'p-1', '/logs/agt-1.log', 'active',
                'explicit', 'cat', NULL, '2026-05-19T00:00:00Z',
                '2026-05-19T00:00:00Z', NULL, NULL, '2026-05-19T00:00:00Z'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    env = reads.app_agent_list(
        seeded_db,
        {"app_session_token": token, "filters": {"log_attached": True}},
        peer_uid=uid,
    )
    assert env["ok"] is True
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "agt-1"
    assert rows[0]["log_attached"] is True


def test_agent_list_empty_db_returns_no_rows(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_list(daemon_ctx, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True
    assert env["result"]["total"] == 0
    assert env["result"]["rows"] == []


def test_agent_list_pagination_via_cursor(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        for i, role in enumerate(("master", "slave", "swarm")):
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

    page1 = reads.app_agent_list(
        daemon_ctx, {"app_session_token": token, "limit": 2}, peer_uid=uid
    )
    assert page1["ok"] is True
    assert len(page1["result"]["rows"]) == 2
    cursor = page1["result"]["cursor_next"]
    assert cursor is not None

    page2 = reads.app_agent_list(
        daemon_ctx,
        {"app_session_token": token, "limit": 2, "cursor_next": cursor},
        peer_uid=uid,
    )
    assert page2["ok"] is True
    assert len(page2["result"]["rows"]) == 1
    assert page2["result"]["cursor_next"] is None


# ─── agent.detail — gating / validation ──────────────────────────────────


def test_agent_detail_host_only_rejects_container_peer(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    _uid, token = host_session
    env = reads.app_agent_detail(
        seeded_db,
        {"app_session_token": token, "agent_id": "agt-1"},
        peer_uid=-1,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "host_only"


def test_agent_detail_missing_param_returns_validation_failed(
    seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = reads.app_agent_detail(
        seeded_db, {"app_session_token": token}, peer_uid=uid
    )
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "agent_id"


# ─── session-gate rejection (no token) ───────────────────────────────────


def test_pane_list_session_gate_rejects_missing_token(
    seeded_db: DaemonContext, host_peer: int
) -> None:
    """No app_session_token → session gate rejects before any work."""
    env = reads.app_pane_list(seeded_db, {}, peer_uid=host_peer)
    assert env["ok"] is False
    assert env["error"]["code"] in ("app_session_required", "app_session_expired")


def test_agent_list_session_gate_rejects_missing_token(
    seeded_db: DaemonContext, host_peer: int
) -> None:
    env = reads.app_agent_list(seeded_db, {}, peer_uid=host_peer)
    assert env["ok"] is False
    assert env["error"]["code"] in ("app_session_required", "app_session_expired")


# ─── connect-time sqlite error (unopenable path) ─────────────────────────


def test_connect_state_db_returns_none_on_connect_error(
    daemon_ctx: DaemonContext,
) -> None:
    """A path under a non-existent directory raises OperationalError on
    connect; ``_connect_state_db`` swallows it and returns None (line 255)."""
    ctx = DaemonContext(
        pid=daemon_ctx.pid,
        start_time_utc=daemon_ctx.start_time_utc,
        socket_path=daemon_ctx.socket_path,
        state_path=Path("/nonexistent-dir-xyz-12345/nested/state.sqlite3"),
        daemon_version=daemon_ctx.daemon_version,
        schema_version=daemon_ctx.schema_version,
    )
    assert reads._connect_state_db(ctx) is None


def test_pane_list_internal_error_on_unopenable_state_path(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    ctx = DaemonContext(
        pid=daemon_ctx.pid,
        start_time_utc=daemon_ctx.start_time_utc,
        socket_path=daemon_ctx.socket_path,
        state_path=Path("/nonexistent-dir-xyz-12345/nested/state.sqlite3"),
        daemon_version=daemon_ctx.daemon_version,
        schema_version=daemon_ctx.schema_version,
    )
    env = reads.app_pane_list(ctx, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


# ─── _fetch_* helpers tolerate absent FEAT-007/004 tables ────────────────


def _agents_only_db(tmp_path: Path) -> Path:
    """A state DB containing ONLY an ``agents`` table — no ``log_attachments``
    and no ``panes``. Exercises the OperationalError fallbacks in
    ``_fetch_log_attached_set`` / ``_fetch_active_pane_keys``."""
    db = tmp_path / "agents-only.sqlite3"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            CREATE TABLE agents (
                agent_id TEXT PRIMARY KEY, container_id TEXT,
                tmux_socket_path TEXT, tmux_session_name TEXT,
                tmux_window_index INTEGER, tmux_pane_index INTEGER,
                tmux_pane_id TEXT, role TEXT, capability TEXT, label TEXT,
                project_path TEXT, parent_agent_id TEXT,
                effective_permissions TEXT, created_at TEXT,
                last_registered_at TEXT, last_seen_at TEXT, active INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO agents VALUES (
                'agt-x', 'ctr-x', '/tmp/tmux-1000/default', 'main',
                0, 0, 'p-x', 'master', 'claude', 'lbl', '', NULL,
                '{}', '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z',
                '2026-05-19T00:00:00Z', 1
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db


def test_fetch_helpers_tolerate_missing_tables(tmp_path: Path) -> None:
    """Directly exercise both helpers against a DB without their tables."""
    db = _agents_only_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        assert reads._fetch_log_attached_set(conn) == set()
        assert reads._fetch_active_pane_keys(conn) == set()
    finally:
        conn.close()


def test_agent_list_tolerates_missing_feat007_feat004_tables(
    daemon_ctx: DaemonContext, host_session: tuple[int, str], tmp_path: Path
) -> None:
    """app.agent.list still succeeds when log_attachments/panes are absent."""
    uid, token = host_session
    db = _agents_only_db(tmp_path)
    ctx = DaemonContext(
        pid=daemon_ctx.pid,
        start_time_utc=daemon_ctx.start_time_utc,
        socket_path=daemon_ctx.socket_path,
        state_path=db,
        daemon_version=daemon_ctx.daemon_version,
        schema_version=daemon_ctx.schema_version,
    )
    env = reads.app_agent_list(ctx, {"app_session_token": token}, peer_uid=uid)
    assert env["ok"] is True
    rows = env["result"]["rows"]
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "agt-x"
    assert rows[0]["log_attached"] is False
    assert rows[0]["pane_active"] is False


def test_agent_list_cursor_rejected_on_order_by_change(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-020b: an agent cursor issued under one order_by is rejected when
    re-presented under a different order_by (covers the _decode_cursor
    error return in app_agent_list)."""
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

    page1 = reads.app_agent_list(
        daemon_ctx, {"app_session_token": token, "limit": 1}, peer_uid=uid
    )
    cursor = page1["result"]["cursor_next"]
    assert cursor is not None
    env = reads.app_agent_list(
        daemon_ctx,
        {
            "app_session_token": token,
            "limit": 1,
            "cursor_next": cursor,
            "order_by": "role:desc",
        },
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "cursor_next"


def test_agent_list_non_default_order_skips_resort(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """A non-``default`` order_by skips the role-priority re-sort branch
    (the 661->670 branch where canonical_order != default:*)."""
    uid, token = host_session
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        for i, role in enumerate(("swarm", "master")):
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
        {"app_session_token": token, "order_by": "registered_at:asc"},
        peer_uid=uid,
    )
    assert env["ok"] is True
    assert env["result"]["ordering"] == "registered_at:asc"
    # Re-sort skipped: DAO insertion order preserved (swarm seeded first).
    assert len(env["result"]["rows"]) == 2
