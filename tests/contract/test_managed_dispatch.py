"""FEAT-013 Phase 3c dispatcher / handler contract test (T023 / T024 / T025).

Exercises the wire-shape surface for ``managed.layout.create`` (legacy
CLI handler) and ``app.managed_layout_create`` (FEAT-011 host-only
handler), plus the dispatcher registration that lets the FEAT-002 socket
server reach them.

Scoped to behaviors the synchronous service exposes today:

* Dispatcher registration sanity — both namespaces install all 5
  methods (create + list + detail + pane.list + pane.detail) at module-
  import time.
* Required-field validation (``container_id`` / ``template_name`` /
  ``tmux_session_name``) → ``validation_failed``.
* ``container_not_found`` pre-check when the FEAT-003 ``containers``
  registry has no row.
* Happy-path layout creation through both namespaces.
* FEAT-013 closed-set error translation (``managed_template_not_found``
  → both namespaces).

Behaviors that need the background spawn pipeline (Phase 4 T029/T030)
remain skip-marked in ``test_managed_layout_create.py``.
"""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dispatcher import APP_DISPATCH
from agenttower.managed_sessions.errors import (
    CONTAINER_NOT_FOUND,
    MANAGED_TEMPLATE_NOT_FOUND,
)
from agenttower.managed_sessions.handlers.app import (
    app_managed_layout_create,
)
from agenttower.managed_sessions.handlers.cli import register as cli_register
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.socket_api.methods import DISPATCH
from agenttower.state.schema import _apply_migration_v9


# ─── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory SQLite with the minimum tables FEAT-013 reads:
    a stub ``agents`` (FEAT-006 FK target), a ``containers`` row to make
    the container_not_found pre-check pass, and the FEAT-013 v9 schema.
    """
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    c.execute(
        "CREATE TABLE containers ("
        "  container_id TEXT PRIMARY KEY,"
        "  active INTEGER NOT NULL DEFAULT 1"
        ")"
    )
    c.executemany(
        "INSERT INTO containers (container_id, active) VALUES (?, 1)",
        [("bench-alpha",), ("bench-beta",)],
    )
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def ctx(conn: sqlite3.Connection) -> Any:
    """Minimum daemon context the FEAT-013 handlers reach for.

    ``SimpleNamespace`` is enough because the handlers only ``getattr``
    fields; they don't construct a full ``DaemonContext``.
    """
    return SimpleNamespace(
        state_conn=conn,
        managed_serializer=ContainerSerializer(),
    )


# Pretend-host peer_uid: any non-negative int that's not ``_NO_PEER_UID``.
HOST_PEER_UID = 1000


@pytest.fixture(autouse=True)
def force_host_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEAT-002's :func:`_peer_is_host_process` falls back to ``False`` for
    any unknown / sentinel pid, which makes the host-only gate refuse all
    in-process test calls. The integration-test harness uses the
    ``AGENTTOWER_TEST_FORCE_HOST_PEER=1`` env-var seam already documented
    in :func:`socket_api.methods._peer_is_host_process` — we set it here
    so the FEAT-011 + FEAT-013 host-only gates classify these test calls
    as host peers.

    We also seed the request-peer threadlocal with a non-zero pid so the
    primary FEAT-009 peer-detection short-circuit (``pid <= 0 → host``
    in our managed_sessions handler) doesn't bypass the env-var seam.
    """
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    from agenttower.socket_api.methods import _set_request_peer_context, _clear_request_peer_context

    _set_request_peer_context(peer_pid=os.getpid())
    yield
    _clear_request_peer_context()


# ─── Dispatcher registration sanity (T025) ───────────────────────────────


def test_legacy_managed_methods_registered() -> None:
    """T025 + T048: all 8 ``managed.*`` methods (M1-M8) reachable through
    FEAT-002 DISPATCH."""
    expected = {
        "managed.layout.create",
        "managed.layout.list",
        "managed.layout.detail",
        "managed.pane.list",
        "managed.pane.detail",
        "managed.pane.remove",
        "managed.pane.recreate",
        "managed.pane.promote_from_adopted",
    }
    assert expected.issubset(DISPATCH.keys())


def test_app_managed_methods_registered() -> None:
    """T025 + T048: all 8 ``app.managed_*`` methods (M1-M8) reachable
    through FEAT-011 APP_DISPATCH."""
    expected = {
        "app.managed_layout_create",
        "app.managed_layout_list",
        "app.managed_layout_detail",
        "app.managed_pane_list",
        "app.managed_pane_detail",
        "app.managed_pane_remove",
        "app.managed_pane_recreate",
        "app.managed_pane_promote_from_adopted",
    }
    assert expected.issubset(APP_DISPATCH.keys())


def test_cli_register_returns_full_method_set() -> None:
    """T025 + T048: ``cli.register()`` returns the closed 8-method mapping
    (M1-M8). Was 5 in Phase 3c (T025 registered M1 + M2-M5 stubs); Phase 5c
    (T048) added M6/M7/M8."""
    mapping = cli_register()
    assert set(mapping.keys()) == {
        "managed.layout.create",
        "managed.layout.list",
        "managed.layout.detail",
        "managed.pane.list",
        "managed.pane.detail",
        "managed.pane.remove",
        "managed.pane.recreate",
        "managed.pane.promote_from_adopted",
    }


# ─── legacy CLI handler (T023) ──────────────────────────────────────────


def _legacy_create(ctx: Any, **params: Any) -> dict[str, Any]:
    """Invoke ``managed.layout.create`` through the dispatcher."""
    return DISPATCH["managed.layout.create"](ctx, params, HOST_PEER_UID)


def test_legacy_create_missing_container_id_fails_validation(ctx: Any) -> None:
    resp = _legacy_create(
        ctx,
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "container_id"


def test_legacy_create_unknown_container_returns_container_not_found(
    ctx: Any,
) -> None:
    resp = _legacy_create(
        ctx,
        container_id="bench-unknown",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == CONTAINER_NOT_FOUND
    assert resp["error"]["details"] == {"container_id": "bench-unknown"}


def test_legacy_create_happy_path_returns_creating_state(ctx: Any) -> None:
    resp = _legacy_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is True
    result = resp["result"]
    assert result["state"] == "creating"
    assert result["intended_pane_count"] == 3
    assert len(result["panes"]) == 3
    assert [p["role"] for p in result["panes"]] == ["master", "slave", "slave"]
    assert [p["label"] for p in result["panes"]] == ["m1", "s1", "s2"]
    assert all(p["state"] == "creating" for p in result["panes"])
    assert result["replay"] is False


def test_legacy_create_unknown_template_returns_closed_set_code(ctx: Any) -> None:
    resp = _legacy_create(
        ctx,
        container_id="bench-alpha",
        template_name="not-a-real-template",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == MANAGED_TEMPLATE_NOT_FOUND


# ─── FEAT-011 app handler (T024) ────────────────────────────────────────


def _app_create(ctx: Any, **params: Any) -> dict[str, Any]:
    """Invoke ``app.managed_layout_create`` directly.

    Bypasses the dispatcher's ``_wrap_handler`` because that wrapper
    only adds a safety-net for unhandled exceptions; the handler's own
    envelope is what we want to assert.
    """
    return app_managed_layout_create(ctx, params, HOST_PEER_UID)


def test_app_create_missing_container_id_fails_validation(ctx: Any) -> None:
    resp = _app_create(
        ctx,
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["app_contract_version"] == "1.0"
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "container_id"


def test_app_create_unknown_container_returns_container_not_found(
    ctx: Any,
) -> None:
    resp = _app_create(
        ctx,
        container_id="bench-unknown",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["app_contract_version"] == "1.0"
    assert resp["error"]["code"] == CONTAINER_NOT_FOUND
    assert resp["error"]["details"] == {"container_id": "bench-unknown"}


def test_app_create_happy_path_returns_feat011_envelope(ctx: Any) -> None:
    resp = _app_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is True
    assert resp["app_contract_version"] == "1.0"
    result = resp["result"]
    assert result["state"] == "creating"
    assert result["intended_pane_count"] == 3
    assert len(result["panes"]) == 3
    assert result["replay"] is False


def test_app_create_idempotency_replay_returns_replay_true(ctx: Any) -> None:
    """R10: same (container_id, idempotency_key) returns the existing layout
    untouched with ``replay: True``."""
    first = _app_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
        idempotency_key="op-12345",
    )
    assert first["ok"] is True
    assert first["result"]["replay"] is False
    first_layout_id = first["result"]["layout_id"]

    second = _app_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
        idempotency_key="op-12345",
    )
    assert second["ok"] is True
    assert second["result"]["replay"] is True
    assert second["result"]["layout_id"] == first_layout_id


# ─── M2-M5 list / detail handlers (T033 — Phase 4a) ─────────────────────


def _create_two_layouts(ctx: Any) -> tuple[str, str]:
    """Seed two layouts in DIFFERENT containers (per FR-003 the per-container
    label-uniqueness index would reject two layouts in the same container
    sharing template labels). Returns (layout_in_alpha, layout_in_beta).
    """
    r1 = _app_create(
        ctx, container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-a",
    )
    r2 = _app_create(
        ctx, container_id="bench-beta", template_name="2m+2s",
        tmux_session_name="session-b",
    )
    assert r1["ok"] is True, f"first create failed: {r1}"
    assert r2["ok"] is True, f"second create failed: {r2}"
    return r1["result"]["layout_id"], r2["result"]["layout_id"]


# M2 — layout.list


def test_app_layout_list_returns_seeded_layouts(ctx: Any) -> None:
    """M2: ``app.managed_layout_list`` returns both layouts with ready_pane_count + origin."""
    layout1_id, layout2_id = _create_two_layouts(ctx)
    resp = APP_DISPATCH["app.managed_layout_list"](ctx, {}, HOST_PEER_UID)
    assert resp["ok"] is True
    items = resp["result"]["items"]
    assert {item["layout_id"] for item in items} == {layout1_id, layout2_id}
    for item in items:
        assert item["origin"] == "managed"
        assert item["state"] == "creating"
        assert item["ready_pane_count"] == 0  # background spawn not yet wired (Phase 4b)
        assert "container_id" in item
        assert "template_name" in item


def test_app_layout_list_filters_by_container(ctx: Any) -> None:
    layout_alpha, layout_beta = _create_two_layouts(ctx)
    resp = APP_DISPATCH["app.managed_layout_list"](
        ctx, {"container_id": "bench-alpha"}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    items = resp["result"]["items"]
    assert len(items) == 1
    assert items[0]["layout_id"] == layout_alpha
    assert items[0]["container_id"] == "bench-alpha"


def test_app_layout_list_filters_by_state(ctx: Any) -> None:
    _create_two_layouts(ctx)
    # No layouts in 'ready' yet because spawn pipeline is Phase 4b.
    resp = APP_DISPATCH["app.managed_layout_list"](
        ctx, {"state": "ready"}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    assert resp["result"]["items"] == []


def test_app_layout_list_rejects_unknown_state_value(ctx: Any) -> None:
    resp = APP_DISPATCH["app.managed_layout_list"](
        ctx, {"state": "exploded"}, HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "state"


# M3 — layout.detail


def test_app_layout_detail_returns_full_pane_list(ctx: Any) -> None:
    """M3: detail returns ``managed_pane`` rows projected with origin + agent_id NULL."""
    r = _app_create(
        ctx, container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-x",
    )
    layout_id = r["result"]["layout_id"]
    resp = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    result = resp["result"]
    assert result["layout_id"] == layout_id
    assert result["template_name"] == "1m+2s"
    assert result["state"] == "creating"
    assert result["origin"] == "managed"
    assert len(result["panes"]) == 3
    assert [p["role"] for p in result["panes"]] == ["master", "slave", "slave"]
    assert all(p["origin"] == "managed" for p in result["panes"])
    assert all(p["agent_id"] is None for p in result["panes"])  # background pipeline is Phase 4b


def test_app_layout_detail_unknown_layout_returns_closed_set_code(ctx: Any) -> None:
    resp = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": "01HZ-DOES-NOT-EXIST"}, HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "managed_layout_not_found"
    assert resp["error"]["details"] == {"layout_id": "01HZ-DOES-NOT-EXIST"}


def test_app_layout_detail_missing_layout_id_fails_validation(ctx: Any) -> None:
    resp = APP_DISPATCH["app.managed_layout_detail"](ctx, {}, HOST_PEER_UID)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "layout_id"


# M4 — pane.list


def test_app_pane_list_returns_all_panes_across_layouts(ctx: Any) -> None:
    """M4: pane.list returns every pane from every layout, ordered by (layout_id, pane_index)."""
    layout1_id, layout2_id = _create_two_layouts(ctx)
    resp = APP_DISPATCH["app.managed_pane_list"](ctx, {}, HOST_PEER_UID)
    assert resp["ok"] is True
    items = resp["result"]["items"]
    # 3 panes (1m+2s) + 4 panes (2m+2s) = 7 total
    assert len(items) == 7
    assert all(p["origin"] == "managed" for p in items)
    # Ordering: layout_id ASC then tmux_pane_index ASC
    for layout_id in sorted([layout1_id, layout2_id]):
        layout_panes = [p for p in items if p["layout_id"] == layout_id]
        indices = [p["tmux_pane_index"] for p in layout_panes]
        assert indices == sorted(indices)


def test_app_pane_list_filters_by_layout_id(ctx: Any) -> None:
    layout1_id, _ = _create_two_layouts(ctx)
    resp = APP_DISPATCH["app.managed_pane_list"](
        ctx, {"layout_id": layout1_id}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    items = resp["result"]["items"]
    assert len(items) == 3
    assert all(p["layout_id"] == layout1_id for p in items)


# M5 — pane.detail


def test_app_pane_detail_returns_pane_with_origin_managed(ctx: Any) -> None:
    r = _app_create(
        ctx, container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-y",
    )
    pane_id = r["result"]["panes"][0]["pane_id"]
    resp = APP_DISPATCH["app.managed_pane_detail"](
        ctx, {"pane_id": pane_id}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    pane = resp["result"]
    assert pane["pane_id"] == pane_id
    assert pane["origin"] == "managed"
    assert pane["role"] == "master"
    assert pane["state"] == "creating"
    assert pane["chain_depth"] == 0
    assert pane["predecessor_id"] is None
    # No predecessor_chain key unless explicitly requested + predecessor exists.
    assert "predecessor_chain" not in pane


def test_app_pane_detail_unknown_pane_returns_closed_set_code(ctx: Any) -> None:
    resp = APP_DISPATCH["app.managed_pane_detail"](
        ctx, {"pane_id": "01HZ-NOPE"}, HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "managed_pane_not_found"
    assert resp["error"]["details"] == {"pane_id": "01HZ-NOPE"}


# ─── M2/M4 state_priority ordering (N33 fix) ─────────────────────────────


def test_app_layout_list_orders_by_state_priority_first(ctx: Any) -> None:
    """N33 / contracts/managed-methods.md §M2: layouts are returned in
    ``(state_priority ASC, created_at DESC, id DESC)`` order — operational
    states (creating / degraded / ready) before terminal (failed / removed),
    most-recent first within a state band.

    Forces multiple states by direct SQL UPDATE (the spawn pipeline that
    naturally drives state transitions lands in Phase 4b — for an
    ordering test we don't need the full pipeline).
    """
    layout_creating, layout_removed = _create_two_layouts(ctx)
    # Force the second layout (in bench-beta) to ``removed`` via direct UPDATE.
    # In production the only path to ``removed`` is the operator-driven
    # remove_pane → archive flow (Phase 5 T042); for an ordering test we
    # bypass and write directly to the column.
    ctx.state_conn.execute(
        "UPDATE managed_layout SET state = 'removed' WHERE id = ?",
        (layout_removed,),
    )
    ctx.state_conn.commit()

    resp = APP_DISPATCH["app.managed_layout_list"](ctx, {}, HOST_PEER_UID)
    assert resp["ok"] is True
    items = resp["result"]["items"]
    layout_ids_in_order = [item["layout_id"] for item in items]
    # The creating layout MUST appear before the removed one despite
    # being older (created earlier in the test). state_priority is 1
    # for creating and 5 for removed, so creating sorts first regardless
    # of created_at.
    assert layout_ids_in_order.index(layout_creating) < layout_ids_in_order.index(
        layout_removed
    ), (
        f"Expected creating layout {layout_creating} to sort before removed "
        f"layout {layout_removed}, got order {layout_ids_in_order}"
    )


def test_app_pane_list_orders_by_state_priority_first(ctx: Any) -> None:
    """N33 / contracts/managed-methods.md §M4: panes are returned in
    ``(state_priority ASC, layout_id ASC, tmux_pane_index ASC, id ASC)``.
    A degraded pane in a later layout MUST appear before a creating pane
    of a higher state_priority — wait, creating has lower state_priority
    than degraded, so creating wins. Test the inverse:
    A creating pane in the lexicographically-greater layout_id MUST
    still appear before a degraded pane in the lexicographically-smaller
    layout_id, because state_priority (1=creating) wins over layout_id
    in the ordering.
    """
    layout_creating, layout_other = _create_two_layouts(ctx)
    # Force every pane in layout_other to degraded; the panes in
    # layout_creating stay in creating. Pending-marker token MUST be
    # cleared first per the CHECK constraint
    # `pending_marker_token IS NULL OR state = 'creating'`.
    ctx.state_conn.execute(
        "UPDATE managed_pane SET pending_marker_token = NULL, state = 'degraded' "
        "WHERE layout_id = ?",
        (layout_other,),
    )
    ctx.state_conn.commit()

    resp = APP_DISPATCH["app.managed_pane_list"](ctx, {}, HOST_PEER_UID)
    assert resp["ok"] is True
    items = resp["result"]["items"]
    # All creating panes (state_priority=1) must appear before any
    # degraded pane (state_priority=2), regardless of layout_id ordering.
    states = [item["state"] for item in items]
    last_creating = max(
        (i for i, s in enumerate(states) if s == "creating"), default=-1
    )
    first_degraded = next(
        (i for i, s in enumerate(states) if s == "degraded"), len(states)
    )
    assert last_creating < first_degraded, (
        f"Expected all creating panes before any degraded pane, got states: {states}"
    )


# ─── Synchronous event emission (T032 — Phase 4a) ───────────────────────


def test_app_create_emits_synchronous_lifecycle_events(ctx: Any) -> None:
    """T032: ``create_layout`` emits LAYOUT_CREATED + PANE_CREATED + PANE_PENDING_MARKER_SET
    once per pane via the ``event_emitter`` callback the handler passes through.

    The handler layer doesn't currently take an event_emitter; this test
    drives the service entry point directly to assert the event shape.
    Phase 4b will thread the FEAT-008 JSONL writer through DaemonContext.
    """
    from agenttower.managed_sessions.service import create_layout

    events: list[dict[str, Any]] = []
    result = create_layout(
        conn=ctx.state_conn,
        serializer=ctx.managed_serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-events",
        event_emitter=events.append,
    )
    assert result.state.value == "creating"
    # 1 layout_created + 3 panes × (pane_created + pending_marker_set) = 7 events
    assert len(events) == 7
    types = [e["event_type"] for e in events]
    assert types[0] == "managed_layout_created"
    # Each pane emits PANE_CREATED then PANE_PENDING_MARKER_SET in order.
    for i in range(3):
        assert types[1 + 2 * i] == "managed_pane_created"
        assert types[2 + 2 * i] == "managed_pane_pending_marker_set"

    # FR-015: every event carries origin=managed, an actor, a timestamp,
    # and a per-scope sequence counter.
    for e in events:
        assert e["origin"] == "managed"
        assert e["actor"] == "operator"
        assert "timestamp" in e
        assert "sequence" in e
    assert events[0]["layout_id"] == result.layout_id
    # Pane events carry both layout_id and pane_id (pane-scoped events).
    pane_events = [e for e in events if e["event_type"].startswith("managed_pane_")]
    assert all(e["pane_id"] is not None for e in pane_events)


# ─── M6 / M7 / M8 dispatcher tests (T048 — Phase 5c) ────────────────────


def _seed_and_drive_to_ready(ctx: Any, container_id: str = "bench-alpha",
                              session: str = "session-m6") -> dict[str, Any]:
    """Create a layout via the dispatcher, then drive it to ready via the
    spawn pipeline with canned backends. Returns the M1 result payload
    so tests can pick a pane_id to operate on."""
    from agenttower.managed_sessions.service import spawn_layout_in_background

    resp = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": container_id,
            "template_name": "1m+2s",
            "tmux_session_name": session,
        },
        HOST_PEER_UID,
    )
    assert resp["ok"] is True
    layout_id = resp["result"]["layout_id"]

    def _good_tmux(pane):
        return {
            "ok": True,
            "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
            "launch_alive": True,
        }

    def _register(pane, tmux_pane_id):
        agent_id = f"agent-{pane.id[:8]}"
        ctx.state_conn.execute("INSERT INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}

    def _log_ok(pane, agent_id):
        return {"ok": True}

    spawn_layout_in_background(
        layout_id,
        conn=ctx.state_conn,
        serializer=ctx.managed_serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_register,
        log_attach_fn=_log_ok,
    )
    return resp["result"]


# M6 — managed.pane.remove


def test_app_pane_remove_missing_pane_id_fails_validation(ctx: Any) -> None:
    resp = APP_DISPATCH["app.managed_pane_remove"](ctx, {}, HOST_PEER_UID)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "pane_id"


def test_app_pane_remove_unknown_pane_returns_not_found(ctx: Any) -> None:
    """Per N38: unknown pane_id (not in agents either) → managed_pane_not_found."""
    resp = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": "01HZ-NEVER"}, HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "managed_pane_not_found"


def test_app_pane_remove_happy_path(ctx: Any) -> None:
    result = _seed_and_drive_to_ready(ctx)
    target_pane_id = result["panes"][0]["pane_id"]
    resp = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": target_pane_id}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    assert resp["result"]["pane_id"] == target_pane_id
    assert resp["result"]["state"] == "removed"


def test_app_pane_remove_in_creating_state_returns_illegal_transition(ctx: Any) -> None:
    """FR-018: pane in `creating` state cannot be removed (cancel-in-flight
    is out of scope)."""
    resp = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": "bench-alpha",
            "template_name": "1m+2s",
            "tmux_session_name": "session-creating-rm",
        },
        HOST_PEER_UID,
    )
    creating_pane_id = resp["result"]["panes"][0]["pane_id"]
    # Don't drive it to ready — remove while still in 'creating'.
    rm = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": creating_pane_id}, HOST_PEER_UID,
    )
    assert rm["ok"] is False
    assert rm["error"]["code"] == "managed_pane_illegal_transition"
    assert rm["error"]["details"]["current_state"] == "creating"
    assert rm["error"]["details"]["requested_action"] == "remove"


# M7 — managed.pane.recreate


def test_app_pane_recreate_missing_predecessor_id_fails_validation(ctx: Any) -> None:
    resp = APP_DISPATCH["app.managed_pane_recreate"](ctx, {}, HOST_PEER_UID)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "predecessor_pane_id"


def test_app_pane_recreate_unknown_predecessor_returns_not_found(ctx: Any) -> None:
    resp = APP_DISPATCH["app.managed_pane_recreate"](
        ctx, {"predecessor_pane_id": "01HZ-NEVER"}, HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "managed_pane_not_found"


def test_app_pane_recreate_happy_path(ctx: Any) -> None:
    """Drive a pane to ready → remove it → recreate it. Verify the new
    pane has predecessor_id set + chain_depth=1 + state=creating."""
    result = _seed_and_drive_to_ready(ctx, session="session-recreate")
    target_pane_id = result["panes"][0]["pane_id"]

    # Remove the pane so it becomes a valid recreate source.
    rm = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": target_pane_id}, HOST_PEER_UID,
    )
    assert rm["ok"] is True

    # Recreate from the removed pane.
    rc = APP_DISPATCH["app.managed_pane_recreate"](
        ctx, {"predecessor_pane_id": target_pane_id}, HOST_PEER_UID,
    )
    assert rc["ok"] is True
    assert rc["result"]["predecessor_id"] == target_pane_id
    assert rc["result"]["chain_depth"] == 1
    assert rc["result"]["state"] == "creating"
    assert rc["result"]["pane_id"] != target_pane_id  # fresh id


def test_app_pane_recreate_from_ready_returns_illegal_recreate_source(ctx: Any) -> None:
    """Predecessor must be in `removed` or `failed` — `ready` is rejected."""
    result = _seed_and_drive_to_ready(ctx, session="session-rc-ready")
    ready_pane_id = result["panes"][0]["pane_id"]
    rc = APP_DISPATCH["app.managed_pane_recreate"](
        ctx, {"predecessor_pane_id": ready_pane_id}, HOST_PEER_UID,
    )
    assert rc["ok"] is False
    assert rc["error"]["code"] == "managed_pane_illegal_recreate_source"


# M8 — managed.pane.promote_from_adopted (stub)


def test_app_pane_promote_from_adopted_returns_not_implemented(ctx: Any) -> None:
    """Stub always returns not_implemented + reserved_since=FEAT-013."""
    resp = APP_DISPATCH["app.managed_pane_promote_from_adopted"](
        ctx, {"agent_id": "01HZ-ANY-ADOPTED"}, HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["app_contract_version"] == "1.0"
    assert resp["error"]["code"] == "not_implemented"
    assert resp["error"]["details"] == {"reserved_since": "FEAT-013"}


def test_legacy_pane_promote_from_adopted_returns_not_implemented(ctx: Any) -> None:
    """Same stub through the FEAT-002 legacy CLI namespace."""
    resp = DISPATCH["managed.pane.promote_from_adopted"](
        ctx, {"agent_id": "01HZ-ANY-ADOPTED"}, HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "not_implemented"
    assert resp["error"]["details"] == {"reserved_since": "FEAT-013"}
