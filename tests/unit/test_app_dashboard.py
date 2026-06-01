"""FEAT-011 unit tests — ``app.dashboard`` handler.

Drives ``agenttower.app_contract.dashboard`` to >=90% line+branch
coverage. Self-contained: every fixture / helper this module needs is
copied in (pytest fixtures from other test modules are not auto-shared
unless they live in a conftest).

Coverage targets:
* the seven count helpers (containers / panes / agents / log_attachments
  / events / queue / routes) — both the populated and the empty paths;
* the ``conn is None`` short-circuit in every count + recent helper;
* the broad-except fallback in every count + recent helper (exercised by
  pointing ``state_conn`` at a connection whose tables are missing);
* ``_recent_events`` / ``_recent_queue`` / ``_recent_routes`` happy paths
  (a bespoke in-memory schema is used for events/queue because the
  production schema does not carry the columns those SELECTs name — see
  the module docstring of ``test_recent_*`` below);
* ``_coerce_recent_limit`` — default, valid-explicit, out-of-bounds
  low/high, and wrong-type rejections;
* the host-only + session-required + session-expired gate rejections;
* hint emission and the all-zero empty-system path.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import dashboard as dashboard_mod
from agenttower.app_contract import errors as app_errors
from agenttower.app_contract import hello as hello_mod
from agenttower.app_contract import sessions, versioning
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures (copied from test_app_contract_foundations.py) ───────────────────


@pytest.fixture(autouse=True)
def fresh_session_registry() -> None:
    """Each test sees a clean SessionRegistry."""
    sessions.set_registry(sessions.SessionRegistry())


@pytest.fixture
def host_peer(monkeypatch: pytest.MonkeyPatch):
    """Thread-local request peer = host process (FEAT-002 test seam)."""
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    uid = os.geteuid()
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield uid
    finally:
        _clear_request_peer_context()


@pytest.fixture
def daemon_ctx_with_db(tmp_path: Path) -> DaemonContext:
    """DaemonContext with a real SQLite schema applied + events_file."""
    from agenttower.state.schema import open_registry

    state_db = tmp_path / "registry.db"
    conn, _status = open_registry(state_db, namespace_root=tmp_path)
    events_file = tmp_path / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)

    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=state_db,
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
        events_file=events_file,
    )


@pytest.fixture
def host_session(daemon_ctx_with_db, host_peer):
    """Host peer + a freshly-minted app.hello session token.

    Returns ``(uid, token)``.
    """
    env = hello_mod.app_hello(daemon_ctx_with_db, {}, peer_uid=host_peer)
    assert env["ok"] is True, f"host_session setup failed: {env}"
    return host_peer, env["result"]["app_session_token"]


# ─── Helpers — call wrapper + state-DB seeders ───────────────────────────


def _dashboard_call(ctx, host_uid, recent_limit=None, token=None):
    params: dict = {}
    if token is not None:
        params["app_session_token"] = token
    if recent_limit is not None:
        params["recent_limit"] = recent_limit
    return dashboard_mod.app_dashboard(ctx, params, peer_uid=host_uid)


def _seed_container(
    conn: sqlite3.Connection, *, container_id: str, name: str, active: bool = True
) -> None:
    conn.execute(
        """
        INSERT INTO containers
            (container_id, name, image, status, labels_json, mounts_json,
             inspect_json, config_user, working_dir, active,
             first_seen_at, last_scanned_at)
        VALUES (?, ?, 'img:latest', 'running', '{}', '[]', '{}',
                '', '/work', ?,
                '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
        """,
        (container_id, name, 1 if active else 0),
    )


def _seed_pane(
    conn: sqlite3.Connection,
    *,
    container_id: str,
    container_name: str,
    pane_id: str,
    window_index: int = 0,
    pane_index: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO panes (
            container_id, tmux_socket_path, tmux_session_name,
            tmux_window_index, tmux_pane_index, tmux_pane_id,
            container_name, container_user, pane_pid, pane_tty,
            pane_current_command, pane_current_path, pane_title,
            pane_active, active, first_seen_at, last_scanned_at
        ) VALUES (?, '/tmp/tmux-1000/default', 'main', ?, ?, ?, ?, '',
                  0, '', '', '', '', 1, 1,
                  '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
        """,
        (container_id, window_index, pane_index, pane_id, container_name),
    )


def _seed_agent(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    container_id: str,
    pane_id: str,
    role: str = "slave",
    capability: str = "claude",
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
        ) VALUES (?, ?, '/tmp/tmux-1000/default', 'main', ?, ?, ?,
                  ?, ?, 'test', '', NULL,
                  '{}', '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z',
                  '2026-05-19T00:00:00Z', ?)
        """,
        (
            agent_id, container_id, window_index, pane_index, pane_id,
            role, capability, 1 if active else 0,
        ),
    )


def _seed_log_attachment(
    conn: sqlite3.Connection,
    *,
    attachment_id: str,
    agent_id: str,
    container_id: str,
    status: str = "active",
    pane_id: str = "p-1",
) -> None:
    conn.execute(
        """
        INSERT INTO log_attachments (
            attachment_id, agent_id, container_id, tmux_socket_path,
            tmux_session_name, tmux_window_index, tmux_pane_index,
            tmux_pane_id, log_path, status, source, pipe_pane_command,
            attached_at, last_status_at, created_at
        ) VALUES (?, ?, ?, '/tmp/tmux-1000/default', 'main', 0, 0,
                  ?, ?, ?, 'explicit', 'cat',
                  '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z',
                  '2026-05-19T00:00:00Z')
        """,
        (
            attachment_id, agent_id, container_id, pane_id,
            f"/logs/{attachment_id}.log", status,
        ),
    )


def _seed_event(
    conn: sqlite3.Connection,
    *,
    event_type: str = "activity",
    agent_id: str = "agt-1",
) -> None:
    conn.execute(
        """
        INSERT INTO events (
            event_type, agent_id, attachment_id, log_path,
            byte_range_start, byte_range_end, line_offset_start,
            line_offset_end, observed_at, excerpt, classifier_rule_id,
            schema_version
        ) VALUES (?, ?, 'att-1', '/logs/x.log', 0, 1, 0, 1,
                  '2026-05-19T00:00:00Z', 'excerpt', 'rule-1', 1)
        """,
        (event_type, agent_id),
    )


def _seed_queue_message(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    state: str,
    target_agent_id: str = "agt-1",
) -> None:
    delivered_at = "'2026-05-19T00:00:00Z'" if state == "delivered" else "NULL"
    conn.execute(
        f"""
        INSERT INTO message_queue (
            message_id, state, sender_agent_id, sender_label, sender_role,
            target_agent_id, target_label, target_role,
            target_container_id, target_pane_id, envelope_body,
            envelope_body_sha256, envelope_size_bytes, enqueued_at,
            delivered_at, last_updated_at, origin
        ) VALUES (?, ?, 'snd', 'snd-label', 'master',
                  ?, 'tgt-label', 'slave', 'ctr-1', 'p-1', X'00',
                  'sha', 1, '2026-05-19T00:00:00Z',
                  {delivered_at}, '2026-05-19T00:00:00Z', 'direct')
        """,
        (message_id, state, target_agent_id),
    )


def _seed_route(
    conn: sqlite3.Connection, *, route_id: str, enabled: bool
) -> None:
    conn.execute(
        """
        INSERT INTO routes (
            route_id, event_type, source_scope_kind, target_rule,
            target_value, master_rule, template, enabled,
            last_consumed_event_id, created_at, updated_at
        ) VALUES (?, 'activity', 'any', 'explicit', 'agt-x', 'auto',
                  '{}', ?, 0, '2026-05-19T00:00:00Z',
                  '2026-05-19T00:00:00Z')
        """,
        (route_id, 1 if enabled else 0),
    )


# ─── _coerce_recent_limit (unit) ─────────────────────────────────────────


def test_coerce_recent_limit_default_when_none() -> None:
    """recent_limit absent → default 10, no error."""
    value, err = dashboard_mod._coerce_recent_limit(None)
    assert value == 10
    assert err is None


def test_coerce_recent_limit_valid_explicit_value() -> None:
    """A valid explicit value passes through unchanged (line 72 path)."""
    value, err = dashboard_mod._coerce_recent_limit(25)
    assert value == 25
    assert err is None


@pytest.mark.parametrize("limit", [1, 50])
def test_coerce_recent_limit_accepts_boundary_values(limit: int) -> None:
    """The [1, 50] inclusive bounds are accepted."""
    value, err = dashboard_mod._coerce_recent_limit(limit)
    assert value == limit
    assert err is None


@pytest.mark.parametrize("limit", [0, -1, 51, 100])
def test_coerce_recent_limit_out_of_bounds(limit: int) -> None:
    """Out-of-bounds values → validation_failed envelope."""
    value, err = dashboard_mod._coerce_recent_limit(limit)
    assert value is None
    assert err is not None
    assert err["ok"] is False
    assert err["error"]["code"] == app_errors.VALIDATION_FAILED
    assert err["error"]["details"]["field"] == "recent_limit"


@pytest.mark.parametrize("bad", ["10", 10.0, True, [10], {"x": 1}])
def test_coerce_recent_limit_wrong_type(bad) -> None:
    """Non-int (incl. bool, which is an int subclass) → validation_failed."""
    value, err = dashboard_mod._coerce_recent_limit(bad)
    assert value is None
    assert err is not None
    assert err["error"]["code"] == app_errors.VALIDATION_FAILED
    assert err["error"]["details"]["field"] == "recent_limit"


# ─── Gate rejections ─────────────────────────────────────────────────────


def test_dashboard_host_only_rejects_non_host_peer(daemon_ctx_with_db) -> None:
    """FR-042: container / no-credentials peer → host_only."""
    env = _dashboard_call(daemon_ctx_with_db, -1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY


def test_dashboard_host_only_beats_session_gate(daemon_ctx_with_db) -> None:
    """FR-042 + FR-007 ordering: non-host peer gets host_only even with a token."""
    env = _dashboard_call(daemon_ctx_with_db, -1, token="looks-valid")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY


def test_dashboard_session_required_when_token_missing(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: host peer, no token → app_session_required."""
    env = _dashboard_call(daemon_ctx_with_db, host_peer)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_REQUIRED


def test_dashboard_session_required_on_non_string_token(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: malformed (non-string) token → app_session_required."""
    env = dashboard_mod.app_dashboard(
        daemon_ctx_with_db, {"app_session_token": 999}, peer_uid=host_peer
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_REQUIRED


def test_dashboard_session_expired_when_token_unknown(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: host peer with an unknown token → app_session_expired."""
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token="not-real")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_EXPIRED


# ─── recent_limit validation through the handler ─────────────────────────


@pytest.mark.parametrize("limit", [0, -1, 51, 200])
def test_dashboard_recent_limit_out_of_bounds_via_handler(
    daemon_ctx_with_db, host_session, limit: int
) -> None:
    """Handler surfaces the out-of-bounds validation_failed envelope."""
    host_peer, token = host_session
    env = _dashboard_call(
        daemon_ctx_with_db, host_peer, recent_limit=limit, token=token
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED
    assert env["error"]["details"]["field"] == "recent_limit"


@pytest.mark.parametrize("bad", ["10", 9.5, True])
def test_dashboard_recent_limit_wrong_type_via_handler(
    daemon_ctx_with_db, host_session, bad
) -> None:
    """Handler rejects a non-int recent_limit with validation_failed."""
    host_peer, token = host_session
    env = _dashboard_call(
        daemon_ctx_with_db, host_peer, recent_limit=bad, token=token
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED


def test_dashboard_recent_limit_valid_explicit_accepted(
    daemon_ctx_with_db, host_session
) -> None:
    """An in-bounds explicit recent_limit is accepted by the handler."""
    host_peer, token = host_session
    env = _dashboard_call(
        daemon_ctx_with_db, host_peer, recent_limit=5, token=token
    )
    assert env["ok"] is True


# ─── Empty-system path ───────────────────────────────────────────────────


def test_dashboard_empty_system_all_zero_counts(
    daemon_ctx_with_db, host_session
) -> None:
    """Empty DB → every count surface is zero, recents are empty lists."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    r = env["result"]
    c = r["counts"]
    assert c["containers"] == {"active": 0, "inactive": 0, "degraded_scan": 0}
    # FEAT-014 v1.1 additive bump: `panes` gains a `by_state` sub-dict.
    # v1.0 keys still hold their expected values; the v1.0 compat test
    # asserts the v1.0 subset rather than strict-equality.
    assert c["panes"]["total"] == 0
    assert c["panes"]["registered"] == 0
    assert c["panes"]["unregistered"] == 0
    assert c["agents"]["total"] == 0
    assert all(v == 0 for v in c["agents"]["by_role"].values())
    assert set(c["agents"]["by_role"].keys()) == set(versioning.AGENT_ROLES)
    assert c["log_attachments"] == {"active": 0, "degraded": 0, "none": 0}
    assert c["events"] == {"total": 0}
    assert all(v == 0 for v in c["queue"].values())
    # FEAT-014 v1.1 additive bump: `routes` gains `recently_skipped_count`
    # and `recently_skipped_window_ms`. v1.0 keys still hold their expected
    # values; the v1.0 compat assertion is field-by-field, not strict-eq.
    assert c["routes"]["enabled"] == 0
    assert c["routes"]["disabled"] == 0
    assert r["recent"]["events"] == []
    assert r["recent"]["queue"] == []
    assert r["recent"]["routes"] == []
    assert isinstance(r["hints"], list)


# ─── Populated count helpers ─────────────────────────────────────────────


def test_dashboard_counts_with_seeded_data(
    daemon_ctx_with_db, host_session
) -> None:
    """Seed every surface; verify the populated count branches.

    Exercises the data-bearing loop bodies in ``_container_counts``,
    ``_agent_counts``, ``_pane_counts``, ``_log_attachment_counts``,
    ``_event_count``, ``_queue_counts`` and ``_route_counts``.
    """
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn

    # 2 active + 1 inactive container.
    _seed_container(conn, container_id="ctr-1", name="bench-1", active=True)
    _seed_container(conn, container_id="ctr-2", name="bench-2", active=True)
    _seed_container(conn, container_id="ctr-3", name="bench-3", active=False)

    # 3 panes; only p-1 is bound to an active agent → registered.
    _seed_pane(conn, container_id="ctr-1", container_name="bench-1",
               pane_id="p-1", window_index=0)
    _seed_pane(conn, container_id="ctr-1", container_name="bench-1",
               pane_id="p-2", window_index=1)
    _seed_pane(conn, container_id="ctr-1", container_name="bench-1",
               pane_id="p-3", window_index=2)

    # Agents across several roles to exercise the by_role breakdown,
    # including a role outside AGENT_ROLES coercion path is covered by
    # the dedicated unknown-role test below.
    _seed_agent(conn, agent_id="agt-1", container_id="ctr-1", pane_id="p-1",
                role="master", window_index=0)
    _seed_agent(conn, agent_id="agt-2", container_id="ctr-1", pane_id="p-9",
                role="slave", window_index=1, pane_index=5)
    _seed_agent(conn, agent_id="agt-3", container_id="ctr-1", pane_id="p-8",
                role="swarm", window_index=2, pane_index=6)

    # Log attachments: 1 active + 1 superseded (the latter is neither
    # active nor degraded → contributes to the "none" arithmetic).
    _seed_log_attachment(conn, attachment_id="la-1", agent_id="agt-1",
                         container_id="ctr-1", status="active")
    _seed_log_attachment(conn, attachment_id="la-2", agent_id="agt-2",
                         container_id="ctr-1", status="superseded")

    # Events.
    _seed_event(conn, event_type="activity", agent_id="agt-1")
    _seed_event(conn, event_type="error", agent_id="agt-2")

    # Queue: 3 rows across 3 of the 5 FEAT-009 states (Round-5
    # corrected vocabulary — queued/blocked/delivered/canceled/failed).
    _seed_queue_message(conn, message_id="m-1", state="blocked")
    _seed_queue_message(conn, message_id="m-2", state="delivered")
    _seed_queue_message(conn, message_id="m-3", state="queued")

    # Routes: 1 enabled + 1 disabled.
    _seed_route(conn, route_id="rt-1", enabled=True)
    _seed_route(conn, route_id="rt-2", enabled=False)
    conn.commit()

    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    c = env["result"]["counts"]

    assert c["containers"] == {"active": 2, "inactive": 1, "degraded_scan": 0}
    assert c["panes"]["total"] == 3
    assert c["panes"]["registered"] == 1
    assert c["panes"]["unregistered"] == 2
    assert c["agents"]["total"] == 3
    assert c["agents"]["by_role"]["master"] == 1
    assert c["agents"]["by_role"]["slave"] == 1
    assert c["agents"]["by_role"]["swarm"] == 1
    assert c["agents"]["by_role"]["test-runner"] == 0
    assert c["log_attachments"]["active"] == 1
    assert c["log_attachments"]["degraded"] == 0
    # 3 agents - 1 active - 0 degraded = 2 with "none".
    assert c["log_attachments"]["none"] == 2
    assert c["events"]["total"] == 2
    # All 5 FEAT-009 states are surfaced; 3 are populated, 2 are zero.
    assert c["queue"] == {
        "queued": 1,
        "blocked": 1,
        "delivered": 1,
        "canceled": 0,
        "failed": 0,
    }
    # FEAT-014 v1.1 additive bump: see comment in the empty-system test above.
    assert c["routes"]["enabled"] == 1
    assert c["routes"]["disabled"] == 1


def test_dashboard_agent_counts_coerces_unknown_role(
    daemon_ctx_with_db, host_session
) -> None:
    """A role string outside AGENT_ROLES is folded into 'unknown'.

    The agents CHECK set permits 'unknown'; we additionally insert a
    raw row with a non-closed-set role string via a direct write to
    confirm ``_agent_counts`` re-buckets it.
    """
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn
    _seed_container(conn, container_id="ctr-1", name="bench-1")
    _seed_pane(conn, container_id="ctr-1", container_name="bench-1",
               pane_id="p-1")
    _seed_agent(conn, agent_id="agt-1", container_id="ctr-1", pane_id="p-1",
                role="unknown")
    conn.commit()
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    c = env["result"]["counts"]
    assert c["agents"]["total"] == 1
    assert c["agents"]["by_role"]["unknown"] == 1


def test_agent_counts_rebuckets_non_closed_set_role() -> None:
    """``_agent_counts`` folds a role string outside AGENT_ROLES into
    'unknown' (line 152). The production CHECK set forbids such a value,
    so a bespoke ``agents`` table without the CHECK is used."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE agents (agent_id TEXT, role TEXT)")
    conn.execute("INSERT INTO agents VALUES ('agt-1', 'gremlin')")
    conn.execute("INSERT INTO agents VALUES ('agt-2', 'master')")
    conn.commit()
    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
    )
    counts = dashboard_mod._agent_counts(ctx)
    assert counts["total"] == 2
    # 'gremlin' is not in AGENT_ROLES → re-bucketed into 'unknown'.
    assert counts["by_role"]["unknown"] == 1
    assert counts["by_role"]["master"] == 1


def test_dashboard_log_attachment_degraded_bucket(
    daemon_ctx_with_db, host_session, monkeypatch
) -> None:
    """``_log_attachment_counts`` 'degraded' bucket maps to FEAT-007
    ``status == 'stale'`` (the real CHECK set is
    {active, superseded, stale, detached} — no 'degraded' literal).
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE log_attachments (attachment_id TEXT, status TEXT)"
    )
    conn.execute("CREATE TABLE agents (agent_id TEXT)")
    conn.execute("INSERT INTO log_attachments VALUES ('la-1', 'active')")
    # 'stale' is what the dashboard counts as degraded.
    conn.execute("INSERT INTO log_attachments VALUES ('la-2', 'stale')")
    # 'superseded' / 'detached' are neither active nor degraded.
    conn.execute("INSERT INTO log_attachments VALUES ('la-3', 'superseded')")
    conn.execute("INSERT INTO agents VALUES ('agt-1')")
    conn.execute("INSERT INTO agents VALUES ('agt-2')")
    conn.execute("INSERT INTO agents VALUES ('agt-3')")
    conn.commit()

    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=daemon_ctx_with_db.socket_path,
        state_path=daemon_ctx_with_db.state_path,
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
    )
    counts = dashboard_mod._log_attachment_counts(ctx)
    assert counts["active"] == 1
    assert counts["degraded"] == 1  # the 'stale' row
    # 3 agents - 1 active - 1 degraded = 1.
    assert counts["none"] == 1


# ─── conn-is-None short-circuit on every helper ──────────────────────────


def test_count_helpers_return_zero_when_state_conn_missing() -> None:
    """Every count helper short-circuits to zero when ctx has no state_conn."""
    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=None,
    )
    assert dashboard_mod._container_counts(ctx) == {
        "active": 0, "inactive": 0, "degraded_scan": 0
    }
    assert dashboard_mod._pane_counts(ctx) == {
        "total": 0, "registered": 0, "unregistered": 0
    }
    agents = dashboard_mod._agent_counts(ctx)
    assert agents["total"] == 0
    assert set(agents["by_role"].keys()) == set(versioning.AGENT_ROLES)
    assert dashboard_mod._log_attachment_counts(ctx) == {
        "active": 0, "degraded": 0, "none": 0
    }
    assert dashboard_mod._event_count(ctx) == 0
    queue = dashboard_mod._queue_counts(ctx)
    assert set(queue.keys()) == set(versioning.QUEUE_STATES)
    assert all(v == 0 for v in queue.values())
    assert dashboard_mod._route_counts(ctx) == {"enabled": 0, "disabled": 0}


def test_recent_helpers_return_empty_when_state_conn_missing() -> None:
    """Every recent helper returns [] when ctx has no state_conn."""
    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=None,
    )
    assert dashboard_mod._recent_events(ctx, 10) == []
    assert dashboard_mod._recent_queue(ctx, 10) == []
    assert dashboard_mod._recent_routes(ctx, 10) == []


# ─── broad-except fallback on every helper ───────────────────────────────


def _ctx_with_empty_db() -> DaemonContext:
    """A ctx whose state_conn points at a DB with NO tables — every
    helper's SQL raises sqlite3.OperationalError, exercising the
    broad-except fallback path."""
    conn = sqlite3.connect(":memory:")  # empty: no tables at all
    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
    )


def test_count_helpers_fallback_on_sql_error() -> None:
    """Missing tables → each count helper returns its zero default."""
    ctx = _ctx_with_empty_db()
    assert dashboard_mod._container_counts(ctx) == {
        "active": 0, "inactive": 0, "degraded_scan": 0
    }
    assert dashboard_mod._pane_counts(ctx) == {
        "total": 0, "registered": 0, "unregistered": 0
    }
    agents = dashboard_mod._agent_counts(ctx)
    assert agents["total"] == 0
    assert dashboard_mod._log_attachment_counts(ctx) == {
        "active": 0, "degraded": 0, "none": 0
    }
    assert dashboard_mod._event_count(ctx) == 0
    queue = dashboard_mod._queue_counts(ctx)
    assert all(v == 0 for v in queue.values())
    assert dashboard_mod._route_counts(ctx) == {"enabled": 0, "disabled": 0}


def test_pane_counts_fallback_when_only_panes_table_missing() -> None:
    """If ``panes`` exists but ``agents`` does not, the registered-count
    sub-query fails independently and falls back to 0 while total still
    resolves (exercises the second except block in ``_pane_counts``)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE panes (container_id TEXT, tmux_pane_id TEXT)")
    conn.execute("INSERT INTO panes VALUES ('ctr-1', 'p-1')")
    conn.execute("INSERT INTO panes VALUES ('ctr-1', 'p-2')")
    conn.commit()
    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
    )
    counts = dashboard_mod._pane_counts(ctx)
    assert counts["total"] == 2
    assert counts["registered"] == 0
    assert counts["unregistered"] == 2


def test_log_attachment_counts_fallback_when_agents_table_missing() -> None:
    """``log_attachments`` resolves but ``agents`` is missing → the
    agent-count sub-query falls back to 0 (third except in helper)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE log_attachments (attachment_id TEXT, status TEXT)")
    conn.execute("INSERT INTO log_attachments VALUES ('la-1', 'active')")
    conn.commit()
    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
    )
    counts = dashboard_mod._log_attachment_counts(ctx)
    assert counts["active"] == 1
    assert counts["degraded"] == 0
    assert counts["none"] == 0


def test_recent_helpers_fallback_on_sql_error() -> None:
    """Missing tables → every recent helper returns []."""
    ctx = _ctx_with_empty_db()
    assert dashboard_mod._recent_events(ctx, 10) == []
    assert dashboard_mod._recent_queue(ctx, 10) == []
    assert dashboard_mod._recent_routes(ctx, 10) == []


# ─── recent-helper happy paths ───────────────────────────────────────────


def test_recent_routes_returns_compact_rows(
    daemon_ctx_with_db, host_session
) -> None:
    """``_recent_routes`` projects seeded routes through compact_route.

    The production ``routes`` table carries ``created_at`` so this
    helper's success path runs against the real schema.
    """
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn
    _seed_route(conn, route_id="rt-1", enabled=True)
    _seed_route(conn, route_id="rt-2", enabled=False)
    conn.commit()
    rows = dashboard_mod._recent_routes(daemon_ctx_with_db, 10)
    assert len(rows) == 2
    ids = {row["id"] for row in rows}
    assert ids == {"rt-1", "rt-2"}
    for row in rows:
        assert row["type"] == "route"
        assert "enabled" in row
        assert "summary" in row

    # And through the full handler.
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    assert len(env["result"]["recent"]["routes"]) == 2


def test_recent_events_happy_path_with_compatible_schema() -> None:
    """``_recent_events`` success path against the REAL FEAT-008
    ``events`` column set: ``event_id, event_type, agent_id,
    observed_at`` (no ``origin``, no ``created_at``).
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY,
            event_type TEXT, agent_id TEXT, observed_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO events VALUES (1, 'activity', 'agt-1', '2026-05-19T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO events VALUES (2, 'error', 'agt-2', '2026-05-19T00:01:00Z')"
    )
    conn.commit()
    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
    )
    rows = dashboard_mod._recent_events(ctx, 10)
    assert len(rows) == 2
    # ORDER BY event_id DESC → newest (id 2) first.
    assert rows[0]["id"] == 2
    assert rows[0]["type"] == "error"
    assert rows[1]["id"] == 1
    # events carry no origin column → projected as "".
    assert rows[0]["origin"] == ""

    # LIMIT is honoured.
    assert len(dashboard_mod._recent_events(ctx, 1)) == 1


def test_recent_queue_happy_path_with_compatible_schema() -> None:
    """``_recent_queue`` success path against the REAL FEAT-009
    ``message_queue`` column set: ``message_id, state, target_agent_id,
    enqueued_at`` (no ``origin``, no ``created_at``).
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE message_queue (
            message_id TEXT, state TEXT,
            target_agent_id TEXT, enqueued_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO message_queue VALUES "
        "('m-1', 'blocked', 'agt-1', '2026-05-19T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO message_queue VALUES "
        "('m-2', 'delivered', 'agt-2', '2026-05-19T00:01:00Z')"
    )
    conn.commit()
    ctx = DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=Path("/tmp/x.sock"),
        state_path=Path("/tmp/x.db"),
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
    )
    rows = dashboard_mod._recent_queue(ctx, 10)
    assert len(rows) == 2
    # ORDER BY enqueued_at DESC → newest (m-2) first.
    assert rows[0]["id"] == "m-2"
    assert rows[0]["state"] == "delivered"
    assert rows[1]["id"] == "m-1"

    assert len(dashboard_mod._recent_queue(ctx, 1)) == 1


# ─── Full-envelope shape + hints ─────────────────────────────────────────


def test_dashboard_envelope_shape_and_hints(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-015..FR-017: full envelope — counts + recents + hints present."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    # FEAT-014 bump (FR-013): use the constant rather than a hardcoded
    # version string so this test survives future minor bumps automatically.
    assert env["app_contract_version"] == versioning.APP_CONTRACT_VERSION
    r = env["result"]
    assert set(r["counts"].keys()) == {
        "containers", "panes", "agents", "log_attachments",
        "events", "queue", "routes",
    }
    assert set(r["recent"].keys()) == {"events", "queue", "routes"}
    assert isinstance(r["hints"], list)
    # Each hint is a dict (emit_hints → Hint.to_dict()).
    for hint in r["hints"]:
        assert isinstance(hint, dict)
        assert "code" in hint


def test_dashboard_emits_docker_unavailable_hint_when_unwired(
    daemon_ctx_with_db, host_session
) -> None:
    """Docker is unwired in the test ctx → docker_unavailable_hint emitted."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    codes = {h["code"] for h in env["result"]["hints"]}
    assert "docker_unavailable_hint" in codes


# ═════════════════════════════════════════════════════════════════════════
# FEAT-014 T005 — v1.1 contract assertions
#
# All assertions below are marked @pytest.mark.v1_1 per tasks.md §Notes
# 'v1.1 marker rule'. T023's SC-004 v1.0-compat regression filters them
# out with `pytest -m 'not v1_1'`. These tests do NOT modify any
# existing FEAT-011 function above — they are pure additions.
# ═════════════════════════════════════════════════════════════════════════


from agenttower.app_contract.dashboard import (  # noqa: E402  (intentional bottom import for v1.1 section)
    AGENT_STATE_KEYS,
    PANE_STATE_KEYS,
)


@pytest.mark.v1_1
def test_dashboard_v1_1_advertises_contract_version_1_1(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-013: daemon advertises ``app_contract_version == "1.1"`` post-bump."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["app_contract_version"] == "1.1"
    assert versioning.APP_CONTRACT_VERSION == "1.1"
    assert versioning.APP_CONTRACT_MINOR == 1


@pytest.mark.v1_1
def test_dashboard_v1_1_panes_by_state_present_when_empty(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-002 / FR-003: ``counts.panes.by_state`` has all 4 keys with
    integer ``0`` on an empty database."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    by_state = env["result"]["counts"]["panes"]["by_state"]
    assert set(by_state.keys()) == set(PANE_STATE_KEYS)
    for key in PANE_STATE_KEYS:
        assert isinstance(by_state[key], int)
        assert by_state[key] == 0


@pytest.mark.v1_1
def test_dashboard_v1_1_agents_by_state_present_when_empty(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-005 / FR-003: ``counts.agents.by_state`` has all 5 keys with
    integer ``0`` on an empty database."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    by_state = env["result"]["counts"]["agents"]["by_state"]
    assert set(by_state.keys()) == set(AGENT_STATE_KEYS)
    for key in AGENT_STATE_KEYS:
        assert isinstance(by_state[key], int)
        assert by_state[key] == 0


@pytest.mark.v1_1
def test_dashboard_v1_1_us1_acceptance_one_registered_two_unadopted(
    daemon_ctx_with_db, host_session
) -> None:
    """US1 acceptance scenario #1 at the wire level: 1 registered + 2
    unadopted panes on an active container → ``by_state`` = ``{dau:2,
    dar:1, ios:0, dd:0}``. Plus FR-019 cross-check at the wire level."""
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn
    _seed_container(conn, container_id="c1", name="container-c1", active=True)
    _seed_pane(conn, container_id="c1", container_name="container-c1", pane_id="%0", pane_index=0)
    _seed_pane(conn, container_id="c1", container_name="container-c1", pane_id="%1", pane_index=1)
    _seed_pane(conn, container_id="c1", container_name="container-c1", pane_id="%2", pane_index=2)
    _seed_agent(conn, agent_id="a1", container_id="c1", pane_id="%0", pane_index=0)

    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    panes = env["result"]["counts"]["panes"]

    # v1.0 fields unchanged.
    assert panes["total"] == 3
    assert panes["registered"] == 1
    assert panes["unregistered"] == 2

    # v1.1 by_state bucket counts.
    assert panes["by_state"] == {
        "discovered-and-unmanaged": 2,
        "discovered-and-registered": 1,
        "inactive-or-stale": 0,
        "discovery-degraded": 0,
    }

    # FR-019 cross-check at the wire level (three equalities).
    assert panes["by_state"]["discovered-and-registered"] == panes["registered"]
    assert (
        panes["by_state"]["discovered-and-unmanaged"]
        + panes["by_state"]["inactive-or-stale"]
        + panes["by_state"]["discovery-degraded"]
    ) == panes["unregistered"]
    assert sum(panes["by_state"].values()) == panes["total"]


@pytest.mark.v1_1
def test_dashboard_v1_1_fr020_agent_partition_at_wire(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-020 strict partition at the wire level:
    ``active + inactive + partially_configured == total agents``.
    Mixed fixture: active agent on active container; partially_configured
    agent (role='unknown') on active container."""
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn
    _seed_container(conn, container_id="c-act", name="c-act", active=True)
    _seed_pane(conn, container_id="c-act", container_name="c-act", pane_id="%0", pane_index=0)
    _seed_pane(conn, container_id="c-act", container_name="c-act", pane_id="%1", pane_index=1)
    _seed_agent(conn, agent_id="a-act", container_id="c-act", pane_id="%0", pane_index=0)
    _seed_agent(
        conn,
        agent_id="a-pc",
        container_id="c-act",
        pane_id="%1",
        pane_index=1,
        role="unknown",  # → partially_configured
    )

    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    agents = env["result"]["counts"]["agents"]

    # v1.0 total unchanged.
    assert agents["total"] == 2

    # v1.1 by_state partition.
    by_state = agents["by_state"]
    assert by_state["active"] == 1, "fully-configured agent on active container → active"
    assert by_state["inactive"] == 0
    assert by_state["partially_configured"] == 1, "role='unknown' → partially_configured"

    # FR-020 strict configuration partition.
    assert (
        by_state["active"]
        + by_state["inactive"]
        + by_state["partially_configured"]
    ) == agents["total"]

    # FR-006 orthogonal log-state partition (no log_attachments seeded → all detached).
    assert by_state["log-attached"] == 0
    assert by_state["log-detached"] == 2
    assert (
        by_state["log-attached"] + by_state["log-detached"]
    ) == agents["total"]


# ═════════════════════════════════════════════════════════════════════════
# FEAT-014 T024 — FR-027 latency-WARN unit test (caplog-based)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.v1_1
def test_dashboard_v1_1_fr027_warn_when_latency_exceeds_budget(
    daemon_ctx_with_db, host_session, monkeypatch, caplog
) -> None:
    """FR-027 + SC-006: when ``app.dashboard`` end-to-end latency exceeds
    the 500 ms budget, the handler emits a single WARN log line with the
    stable event name ``app_dashboard_latency_exceeded`` AND the response
    is returned best-effort (no error envelope, all v1.1 fields present).

    Implementation note (post-swarm M2 fix): we monkey-patch
    ``time.monotonic_ns`` inside the dashboard module so the latency
    measurement bookends observe a 600 ms gap WITHOUT actually sleeping
    600 ms wall-clock. The test runs in microseconds and is timing-noise-
    immune.
    """
    import logging

    from agenttower.app_contract import dashboard as dashboard_mod

    # Fake a 600 ms latency without real sleep. The handler reads
    # monotonic_ns THREE times on the success path: the _t0 capture
    # (dashboard.py), the skip-window clock inside the body
    # (skip_counter.count_in_window), and the finally-block bookend. Only
    # the FIRST read must be t=0; every later read returns t0+600ms so the
    # finally computes _latency_ms = 600 > 500 ms budget → WARN. Keyed off an
    # explicit iterator (not call positions) so the test does not depend on
    # how many interior reads the body makes, nor on _t0 being literally the
    # 1st-and-only pre-body read (swarm: the old comment mis-counted the calls
    # as a 2-call bookend).
    _values = iter([0])  # _t0

    def _fake_monotonic_ns() -> int:
        return next(_values, 600_000_000)  # every read after _t0 → 600 ms

    monkeypatch.setattr(
        dashboard_mod.time, "monotonic_ns", _fake_monotonic_ns
    )
    caplog.set_level(logging.WARNING, logger="agenttower.app_contract.dashboard")

    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)

    # FR-027 best-effort: response still returns successfully with v1.1
    # fields intact (no latency_budget_exceeded error envelope).
    assert env["ok"] is True
    result = env["result"]
    assert "by_state" in result["counts"]["panes"]
    assert "by_state" in result["counts"]["agents"]
    assert "recently_skipped_count" in result["counts"]["routes"]

    # WARN log line emitted with the stable event name + latency_ms field.
    warn_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "app_dashboard_latency_exceeded" in r.getMessage()
    ]
    assert warn_records, (
        "FR-027 violation: no WARN log emitted despite ~600ms injected "
        f"latency. Captured records: {[r.getMessage() for r in caplog.records]!r}"
    )
    # The message includes the actual measured latency in ms.
    assert "latency_ms=" in warn_records[0].getMessage()


# ═════════════════════════════════════════════════════════════════════════
# FEAT-014 T025 — Polish SC-005 single-envelope shape assertion
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.v1_1
def test_dashboard_v1_1_sc005_single_envelope_shape_all_fields_present(
    daemon_ctx_with_db, host_session
) -> None:
    """SC-005: a single v1.1 ``app.dashboard`` call against a populated
    daemon returns every new v1.1 field present and correctly typed in
    one response envelope. This is the omnibus shape assertion for the
    v1.1 wire contract — it catches a future regression that silently
    omits a field, even if every individual field test still passes."""
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn

    # Populated daemon: 1 active container + 1 registered pane + 1
    # unadopted pane + 1 agent + 1 enabled route. Just enough to make
    # every v1.1 surface non-trivial.
    _seed_container(conn, container_id="c1", name="c1", active=True)
    _seed_pane(conn, container_id="c1", container_name="c1",
               pane_id="%0", pane_index=0)
    _seed_pane(conn, container_id="c1", container_name="c1",
               pane_id="%1", pane_index=1)
    _seed_agent(conn, agent_id="a1", container_id="c1",
                pane_id="%0", pane_index=0)
    _seed_route(conn, route_id="r1", enabled=True)
    conn.commit()

    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    result = env["result"]

    # ─ v1.1 envelope-level fields ───────────────────────────────────────
    assert "recommended_next_action" in result
    assert "recommended_next_action_refreshed_at" in result
    # Paired non-null on a healthy populated daemon (floor is all_clear).
    if result["recommended_next_action"] is None:
        assert result["recommended_next_action_refreshed_at"] is None
    else:
        assert result["recommended_next_action_refreshed_at"] is not None
        # Shape check (full schema verified in T017's dedicated tests).
        rec = result["recommended_next_action"]
        assert set(rec.keys()) == {"code", "title", "detail", "target"}

    # ─ v1.1 counts.panes.by_state ───────────────────────────────────────
    panes_by_state = result["counts"]["panes"]["by_state"]
    assert set(panes_by_state.keys()) == set(PANE_STATE_KEYS)
    for key in PANE_STATE_KEYS:
        assert isinstance(panes_by_state[key], int)
    # Cross-check sum-equals-total (FR-019 strict leg).
    assert sum(panes_by_state.values()) == result["counts"]["panes"]["total"]

    # ─ v1.1 counts.agents.by_state ──────────────────────────────────────
    agents_by_state = result["counts"]["agents"]["by_state"]
    assert set(agents_by_state.keys()) == set(AGENT_STATE_KEYS)
    for key in AGENT_STATE_KEYS:
        assert isinstance(agents_by_state[key], int)

    # ─ v1.1 counts.routes.recently_skipped_* ────────────────────────────
    routes = result["counts"]["routes"]
    assert "recently_skipped_count" in routes
    assert "recently_skipped_window_ms" in routes
    assert isinstance(routes["recently_skipped_count"], int)
    assert routes["recently_skipped_count"] >= 0
    assert routes["recently_skipped_window_ms"] == 300_000

    # ─ v1.0 fields untouched (FR-014 additive-minor) ────────────────────
    assert "total" in result["counts"]["panes"]
    assert "registered" in result["counts"]["panes"]
    assert "unregistered" in result["counts"]["panes"]
    assert "enabled" in routes
    assert "disabled" in routes


# ═════════════════════════════════════════════════════════════════════════
# FEAT-014 T022 — US4 v1.0-reader + FR-012 symmetric forward-compat
#
# Two sub-tests. Both expected GREEN at landing — they verify behavior
# that is already true at the current branch state (the v1.0 keys are
# emitted bit-identically per FR-014, and the dashboard handler reads
# only known params via params.get() so unknown fields are silently
# ignored). The tests document the contract so any future regression
# would be caught.
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.v1_1
def test_dashboard_v1_1_v1_0_only_reader_unaffected_by_v1_1_additions(
    daemon_ctx_with_db, host_session
) -> None:
    """US4 acceptance #1: a v1.0 client that reads only v1.0 keys
    (``counts.panes.{total,registered,unregistered}``, ``counts.agents.total``,
    ``counts.agents.by_role``, ``counts.routes.{enabled,disabled}``,
    ``recent``, ``hints``) gets bit-identical v1.0 values even when the
    daemon emits v1.1 additions (``by_state``, ``recently_skipped_*``) in
    the same envelope. The v1.1 fields exist but they don't disturb the
    v1.0 surface."""
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn
    # Minimal mixed-state fixture: 1 active container + 1 registered pane +
    # 1 unadopted pane + 2 agents + 1 enabled route.
    _seed_container(conn, container_id="c1", name="c1", active=True)
    _seed_pane(conn, container_id="c1", container_name="c1", pane_id="%0", pane_index=0)
    _seed_pane(conn, container_id="c1", container_name="c1", pane_id="%1", pane_index=1)
    _seed_agent(conn, agent_id="a1", container_id="c1", pane_id="%0", pane_index=0)
    _seed_route(conn, route_id="r1", enabled=True)
    conn.commit()

    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    result = env["result"]

    # v1.0 panes surface unchanged.
    assert result["counts"]["panes"]["total"] == 2
    assert result["counts"]["panes"]["registered"] == 1
    assert result["counts"]["panes"]["unregistered"] == 1

    # v1.0 agents surface unchanged.
    assert result["counts"]["agents"]["total"] == 1
    assert "by_role" in result["counts"]["agents"]
    assert isinstance(result["counts"]["agents"]["by_role"], dict)

    # v1.0 routes surface unchanged (the {enabled, disabled} numbers).
    assert result["counts"]["routes"]["enabled"] == 1
    assert result["counts"]["routes"]["disabled"] == 0

    # v1.0 recents + hints surfaces present and well-typed.
    assert isinstance(result["recent"]["events"], list)
    assert isinstance(result["recent"]["queue"], list)
    assert isinstance(result["recent"]["routes"], list)
    assert isinstance(result["hints"], list)

    # The v1.1 additions ARE emitted (additive-minor; v1.0 reader ignores
    # them) — verify they exist as expected types so a v1.0 client reading
    # only the v1.0 keys cannot accidentally trip over them.
    assert isinstance(result["counts"]["panes"]["by_state"], dict)
    assert isinstance(result["counts"]["agents"]["by_state"], dict)
    assert isinstance(result["counts"]["routes"]["recently_skipped_count"], int)
    assert isinstance(result["counts"]["routes"]["recently_skipped_window_ms"], int)


@pytest.mark.v1_1
def test_dashboard_v1_1_fr012_daemon_ignores_unknown_request_fields(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-012 R2 / Clarifications R2 Q3 — symmetric forward-compat: a v1.1+
    client sending an unknown future request field MUST NOT cause the daemon
    to reject the call or return an error envelope. The daemon silently
    ignores unknown fields, returning the standard v1.1 success envelope.

    This establishes the symmetric forward-compat convention BEFORE any
    future v1.x minor introduces request parameters. Without this rule,
    daemons that strict-validate the request dict would force a synchronized
    client-daemon upgrade for any future minor that adds a request param —
    breaking the additive-minor evolution model FR-013/FR-014 promise."""
    host_peer, token = host_session
    # Synthetic unknown future fields. The daemon must silently ignore them.
    params = {
        "app_session_token": token,
        "unknown_future_field": True,
        "another_v1_2_param": "future-value",
        "nested_unknown": {"deep": {"foo": "bar"}},
        "recent_limit": 10,  # known field, should still be honored
    }
    env = dashboard_mod.app_dashboard(
        daemon_ctx_with_db, params, peer_uid=host_peer
    )

    # Daemon accepts the call.
    assert env["ok"] is True, (
        f"FR-012 R2 violation: unknown request fields caused error: "
        f"{env.get('error')!r}"
    )

    # The v1.1 success envelope is intact.
    result = env["result"]
    assert "counts" in result
    assert "panes" in result["counts"]
    assert "by_state" in result["counts"]["panes"], (
        "v1.1 fields must be present despite unknown request fields"
    )
    assert "agents" in result["counts"]
    assert "by_state" in result["counts"]["agents"]

    # No error code surfaced.
    assert "error" not in env or env.get("error") is None


# ═════════════════════════════════════════════════════════════════════════
# FEAT-014 T017 — US3 wire-level assertions (recommended_next_action)
#
# All assertions are @pytest.mark.v1_1. They pin the US3 wire-level contract
# for `recommended_next_action` (now wired in dashboard.py envelope assembly,
# alongside the FR-021 compute-failure null pathway); any future regression
# that omits the field would be caught here.
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.v1_1
def test_dashboard_v1_1_recommended_next_action_shape(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-011: ``recommended_next_action`` wire-shape — ``code`` is a
    closed-set string, ``title`` is ≤128 chars, ``detail`` is ≤512 chars
    or null, ``target`` is the closed-shape object or null. Also asserts
    the field is present (never omitted, never null when refreshed_at is
    set)."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    result = env["result"]

    assert "recommended_next_action" in result
    rec = result["recommended_next_action"]
    assert rec is not None, "empty daemon should produce no_containers, not null"

    valid_codes = {
        "subsystem_degraded",
        "no_containers",
        "no_panes_discovered",
        "unadopted_panes_present",
        "blocked_queue_drain",
        "no_routes_configured",
        "all_clear",
    }
    assert rec["code"] in valid_codes
    assert isinstance(rec["title"], str) and 0 < len(rec["title"]) <= 128
    if rec["detail"] is not None:
        assert isinstance(rec["detail"], str) and len(rec["detail"]) <= 512
    if rec["target"] is not None:
        assert isinstance(rec["target"], dict)
        assert set(rec["target"].keys()) == {"kind", "id"}
        valid_kinds = {
            "container", "pane", "agent", "route", "message", "event", "subsystem",
        }
        assert rec["target"]["kind"] in valid_kinds
        assert isinstance(rec["target"]["id"], str)


@pytest.mark.v1_1
def test_dashboard_v1_1_recommendation_paired_null_invariant(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-021 + Research §FE paired-null invariant: when ``recommended_
    next_action`` is null, ``recommended_next_action_refreshed_at`` MUST
    also be null. Conversely, when one is populated, both are populated.
    On a healthy daemon the floor is ``all_clear`` (never null), so on
    this success path both fields are non-null."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    result = env["result"]

    rec = result["recommended_next_action"]
    refreshed_at = result["recommended_next_action_refreshed_at"]

    # Paired-null: both null OR both populated.
    if rec is None:
        assert refreshed_at is None
    else:
        assert refreshed_at is not None


@pytest.mark.v1_1
def test_dashboard_v1_1_recommendation_refreshed_at_iso_8601_utc_ms(
    daemon_ctx_with_db, host_session
) -> None:
    """Research §TS: ``recommended_next_action_refreshed_at`` is an ISO-8601
    UTC string with millisecond precision, e.g. "2026-05-25T17:23:45.123Z".
    Wall-clock source, not monotonic (Research §TS rationale)."""
    import re

    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    refreshed_at = env["result"]["recommended_next_action_refreshed_at"]

    if refreshed_at is not None:
        # ISO-8601 UTC ms shape: YYYY-MM-DDTHH:MM:SS.sssZ
        iso_ms_utc = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
        assert iso_ms_utc.match(refreshed_at), (
            f"refreshed_at not ISO-8601 UTC ms format: {refreshed_at!r}"
        )


@pytest.mark.v1_1
def test_dashboard_v1_1_target_id_opacity_no_display_chars(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-011 / FR-024 + Clarifications R1 Q14: when ``target`` is non-null,
    ``target.id`` is an opaque internal identifier. It MUST NOT contain
    operator-readable display characters like spaces, slashes, or
    container-label punctuation that would suggest a human-readable name.

    Seed an active container with a display-char-laden ``name`` but an
    opaque ``container_id`` and NO panes — that drives the recommendation
    engine to ``no_panes_discovered`` with ``target={"kind":"container",
    "id": <container_id>}`` (recommendations.py), so the opacity assertions
    below actually execute against a non-null target. Calling against an
    empty daemon would yield ``no_containers`` (target=None) and skip every
    assertion, making the test vacuous."""
    host_peer, token = host_session
    conn = daemon_ctx_with_db.state_conn
    # name carries display chars (space + slash); container_id stays opaque.
    _seed_container(conn, container_id="ctr-opaque-1", name="bench 1/dev", active=True)
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    rec = env["result"]["recommended_next_action"]

    assert rec is not None and rec["target"] is not None, (
        "fixture must drive a non-null recommendation target so the opacity "
        f"assertions are actually exercised; got rec={rec!r}"
    )
    target_id = rec["target"]["id"]
    assert " " not in target_id, (
        f"target.id leaks display character (space): {target_id!r}"
    )
    assert "/" not in target_id, (
        f"target.id leaks display character (slash): {target_id!r}"
    )
    assert "\\" not in target_id, (
        f"target.id leaks display character (backslash): {target_id!r}"
    )


@pytest.mark.v1_1
def test_dashboard_v1_1_fr026_non_suppression_during_subsystem_degraded(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-026 (Clarifications R1 Q7): even when the recommendation is
    ``subsystem_degraded``, ``counts.panes.by_state`` and
    ``counts.agents.by_state`` MUST STILL be emitted with all 4-key /
    5-key vocabularies. Count values may be best-effort during
    degradation, but the keys themselves are unconditional.

    This drives an ACTUAL degraded state (swarm: the test must enter the
    `subsystem_degraded` branch it is named for, not pass vacuously on a
    healthy ctx). Setting `routing_shared_state.routing_worker_degraded`
    makes the dashboard union `routing_worker` into `degraded_subsystems`, so
    `compute_recommendation` returns `subsystem_degraded` (precedence #1)."""
    from types import SimpleNamespace as _NS

    daemon_ctx_with_db.routing_shared_state = _NS(routing_worker_degraded=True)
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    result = env["result"]

    # The recommendation MUST actually be subsystem_degraded here — otherwise
    # the by_state assertions below would be vacuous (true on every code).
    assert result["recommended_next_action"]["code"] == "subsystem_degraded"

    # by_state keys MUST be present unconditionally — and specifically still
    # present DURING degradation (FR-026 non-suppression).
    panes_by_state = result["counts"]["panes"]["by_state"]
    agents_by_state = result["counts"]["agents"]["by_state"]
    assert set(panes_by_state.keys()) == set(PANE_STATE_KEYS)
    assert set(agents_by_state.keys()) == set(AGENT_STATE_KEYS)
    for key in PANE_STATE_KEYS:
        assert isinstance(panes_by_state[key], int)
    for key in AGENT_STATE_KEYS:
        assert isinstance(agents_by_state[key], int)


@pytest.mark.v1_1
def test_dashboard_v1_1_fr021_compute_failure_leaves_other_v1_1_fields_intact(
    daemon_ctx_with_db, host_session, monkeypatch
) -> None:
    """FR-021 + Research §FE: when ``compute_recommendation`` raises, the
    dashboard handler catches the exception, sets BOTH
    ``recommended_next_action`` and ``recommended_next_action_refreshed_at``
    to null (paired-null), AND leaves every other v1.1 field populated:
    ``counts.panes.by_state``, ``counts.agents.by_state``,
    ``counts.routes.recently_skipped_*``. No new error code is emitted —
    the response is still a success envelope."""
    from agenttower.app_contract import recommendations

    def _boom(_state: recommendations.RecommendationState) -> None:
        raise RuntimeError("simulated compute failure")

    monkeypatch.setattr(recommendations, "compute_recommendation", _boom)

    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True, "FR-021: compute failure MUST NOT propagate as error"
    result = env["result"]

    # Paired-null pathway.
    assert result["recommended_next_action"] is None
    assert result["recommended_next_action_refreshed_at"] is None

    # Other v1.1 fields all present and well-typed.
    assert isinstance(result["counts"]["panes"]["by_state"], dict)
    assert set(result["counts"]["panes"]["by_state"].keys()) == set(PANE_STATE_KEYS)
    assert isinstance(result["counts"]["agents"]["by_state"], dict)
    assert set(result["counts"]["agents"]["by_state"].keys()) == set(AGENT_STATE_KEYS)
    assert isinstance(result["counts"]["routes"]["recently_skipped_count"], int)
    assert isinstance(result["counts"]["routes"]["recently_skipped_window_ms"], int)


# ═════════════════════════════════════════════════════════════════════════
# FEAT-014 T011 — US2 wire-level assertions (recently_skipped_*)
#
# All assertions below are @pytest.mark.v1_1 per the v1.1 marker rule. They
# pin the US2 wire-level contract for
# counts.routes.recently_skipped_count + .recently_skipped_window_ms (now
# wired into the dashboard.py response envelope, backed by the skip_counter
# module); any regression that drops these fields would be caught here —
# the wire surface FR-007 / FR-008 demand.
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.v1_1
def test_dashboard_v1_1_routes_recently_skipped_window_ms_is_300000(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-008 + Clarifications Q6: ``counts.routes.recently_skipped_window_ms``
    is the exact literal ``300_000`` ms (5 min, fixed daemon-side, not
    client-tunable in v1.1)."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    routes = env["result"]["counts"]["routes"]
    assert routes["recently_skipped_window_ms"] == 300_000


@pytest.mark.v1_1
def test_dashboard_v1_1_routes_recently_skipped_count_is_non_negative_int(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-007 / FR-004 typing: ``counts.routes.recently_skipped_count`` is a
    non-negative integer. On an empty daemon with no skip events recorded
    (post-construction / post-restart per FR-008) the value MUST be ``0``."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    routes = env["result"]["counts"]["routes"]
    assert isinstance(routes["recently_skipped_count"], int)
    assert routes["recently_skipped_count"] >= 0
    # Empty daemon, no record_skip calls yet → 0.
    assert routes["recently_skipped_count"] == 0


@pytest.mark.v1_1
def test_dashboard_v1_1_routes_recently_skipped_fields_present_even_when_zero(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-003 (generalized to v1.1 route fields): both ``recently_skipped_count``
    and ``recently_skipped_window_ms`` MUST be present as keys with integer
    values, NEVER omitted and NEVER ``null`` — even on an empty daemon where
    the count is ``0``. This mirrors FR-003's by_state key-presence guarantee
    for the route surface."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    routes = env["result"]["counts"]["routes"]

    # Both keys MUST be present.
    assert "recently_skipped_count" in routes, (
        "FR-003: recently_skipped_count key MUST be present (not omitted)"
    )
    assert "recently_skipped_window_ms" in routes, (
        "FR-003: recently_skipped_window_ms key MUST be present (not omitted)"
    )

    # Neither field is ever null.
    assert routes["recently_skipped_count"] is not None, "FR-003: never null"
    assert routes["recently_skipped_window_ms"] is not None, "FR-003: never null"

    # Both are integer-typed.
    assert isinstance(routes["recently_skipped_count"], int)
    assert isinstance(routes["recently_skipped_window_ms"], int)
