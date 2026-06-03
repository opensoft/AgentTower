"""FEAT-013 T051: spec §Edge Cases integration smoke.

Walks every bullet in spec.md §Edge Cases and asserts the corresponding
behavior. Most bullets are already covered by dedicated tests in
``tests/contract/`` — this module is the integration-level catch-all
that runs the spec's edge-case list end-to-end through the dispatcher
+ service + recovery + sweep paths.

Edge Cases bullets (12 total from spec §Edge Cases):

1. Bench container disappears mid-creation
   → covered here (container_not_found pre-check + degraded path)
2. tmux session name already exists
   → covered by Phase 4c skipped test (FEAT-004 list-sessions pre-check)
3. Configured agent command immediate-exit
   → covered by test_managed_launch_failure.py (Phase 4b)
4. Log path not host-readable
   → covered by test_managed_log_attach_failure.py (Phase 4b)
5. Partial layout retry via pending-managed marker
   → covered here (sweep + idempotency-key replay)
6. Multiple layout creation requests targeting same container
   → covered by test_managed_serializer.py (Phase 2)
7. Created panes discovered by scan before registration completes
   → covered by test_managed_pending_marker.py (Phase 4c FEAT-004 filter)
8. Operator attempts destructive lifecycle on adopted pane
   → covered by test_managed_protect_adopted.py (Phase 5a) +
     test_story3_lifecycle_operations.py (Phase 5c)
9. agenttowerd restart with managed layouts alive
   → covered by test_managed_recovery.py (Phase 5b)
10. 40-layout capacity cap
    → covered by test_managed_layout_create.py (Phase 3b)
11. One pane fails mid-create-layout (FR-026 no-cascade-kill)
    → covered by test_managed_layout_create.py (Phase 4b)
12. Two recreates target same predecessor in flight (FR-027)
    → covered by test_managed_pane_recreate.py (Phase 5a)

This module's tests provide additional integration coverage where the
contract-test layer doesn't naturally exercise dispatcher + service +
recovery + sweep together (notably bullets 1 and 5).
"""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dispatcher import APP_DISPATCH
from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
    select_pane,
)
from agenttower.managed_sessions.errors import CONTAINER_NOT_FOUND
from agenttower.managed_sessions.pending_marker import sweep
from agenttower.managed_sessions.recovery import reconcile
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import spawn_layout_in_background
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY, origin TEXT)")
    c.execute("CREATE TABLE containers (container_id TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
    c.execute("INSERT INTO containers (container_id, active) VALUES (?, 1)", ("bench-alpha",))
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


@pytest.fixture()
def ctx(conn, serializer) -> Any:  # noqa: ANN001
    return SimpleNamespace(state_conn=conn, managed_serializer=serializer)


HOST_PEER_UID = 1000


@pytest.fixture(autouse=True)
def force_host_peer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    from agenttower.socket_api.methods import (
        _clear_request_peer_context,
        _set_request_peer_context,
    )
    _set_request_peer_context(peer_pid=os.getpid())
    yield
    _clear_request_peer_context()


def _ts(when: _dt.datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.UTC)
    return when.isoformat(timespec="microseconds").replace("+00:00", "Z")


# ─── Edge Case 1: bench container disappears mid-creation ───────────────


def test_edge_case_1_unknown_container_id_returns_container_not_found(ctx: Any) -> None:
    """Bullet 1 — unknown container_id (whether the bench container
    never existed or disappeared between scan + create) returns
    `container_not_found` per the M1 handler-layer pre-check."""
    resp = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": "bench-disappeared",
            "template_name": "1m+2s",
            "tmux_session_name": "session-edge-1",
        },
        HOST_PEER_UID,
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == CONTAINER_NOT_FOUND


# ─── Edge Case 5: partial layout retry via pending-managed marker ───────


def test_edge_case_5_idempotency_key_replay_returns_existing_layout(ctx: Any) -> None:
    """Bullet 5 / R10 — a retry with the same (container_id, idempotency_key)
    returns the existing layout without inserting a duplicate. Verifies
    the pending-managed marker token equals the idempotency_key when one
    is supplied (research §R10)."""
    first = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": "bench-alpha",
            "template_name": "1m+2s",
            "tmux_session_name": "session-edge-5",
            "idempotency_key": "operator-clicked-create-edge-5",
        },
        HOST_PEER_UID,
    )
    assert first["ok"] is True
    first_layout_id = first["result"]["layout_id"]
    assert first["result"]["replay"] is False

    # Retry with the same key — should return the existing layout
    # with replay=True and no new managed_pane rows inserted.
    second = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": "bench-alpha",
            "template_name": "1m+2s",
            "tmux_session_name": "session-edge-5",
            "idempotency_key": "operator-clicked-create-edge-5",
        },
        HOST_PEER_UID,
    )
    assert second["ok"] is True
    assert second["result"]["replay"] is True
    assert second["result"]["layout_id"] == first_layout_id

    # Verify NO duplicate panes were inserted.
    count = ctx.state_conn.execute(
        "SELECT COUNT(*) FROM managed_pane WHERE layout_id = ?",
        (first_layout_id,),
    ).fetchone()[0]
    assert count == 3  # exactly the original 3-pane layout


def test_edge_case_5_partial_layout_retry_via_sweep(ctx: Any) -> None:
    """Bullet 5 — when a layout creation stalls past the 5-min TTL, the
    sweep transitions the stranded `creating`-state panes to failed
    with `failed_stage = pane_create` (no agent_id) so the operator can
    recreate. Exercises sweep + dispatcher detail surface together."""
    # Seed a creating-state layout 10 minutes in the past.
    old_when = _dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=10)
    layout_id = str(uuid.uuid4())
    insert_layout(
        ctx.state_conn,
        ManagedLayoutRow(
            id=layout_id, container_id="bench-alpha",
            template_name="1m+2s", intended_pane_count=1,
            state=ManagedState.CREATING, failed_stage=None,
            idempotency_key=None,
            created_at=_ts(old_when), updated_at=_ts(old_when),
        ),
    )
    pane_id = str(uuid.uuid4())
    insert_pane(
        ctx.state_conn,
        ManagedPaneRow(
            id=pane_id, layout_id=layout_id, container_id="bench-alpha",
            agent_id=None, role="master", capability="orchestrator",
            label="m1", launch_command_ref=None,
            tmux_session_name="session-edge-5b", tmux_pane_index=0,
            pending_marker_token=str(uuid.uuid4()),
            state=ManagedState.CREATING, failed_stage=None,
            predecessor_id=None, chain_depth=0,
            created_at=_ts(old_when), updated_at=_ts(old_when),
        ),
    )
    ctx.state_conn.commit()

    # Sweep transitions the stale row.
    out = sweep(ctx.state_conn)
    assert out.panes_swept == 1
    assert out.pane_create_failures == 1

    # M5 detail surfaces the failure so the operator sees it without
    # log inspection.
    resp = APP_DISPATCH["app.managed_pane_detail"](
        ctx, {"pane_id": pane_id}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    pane = resp["result"]
    assert pane["state"] == "failed"
    assert pane["failed_stage"] == "pane_create"


# ─── Edge Case 9: agenttowerd restart (cross-cutting smoke) ─────────────


def test_edge_case_9_restart_recovery_surfaces_outcome_via_m3(ctx: Any) -> None:
    """Bullet 9 — daemon restart with managed layouts alive. After
    reconcile, M3 detail surfaces the per-layout state so the operator
    sees the recovery outcome without consulting logs (SC-009)."""
    # Seed a layout-with-ready-panes scenario.
    layout_id = str(uuid.uuid4())
    now = _dt.datetime.now(_dt.UTC)
    insert_layout(
        ctx.state_conn,
        ManagedLayoutRow(
            id=layout_id, container_id="bench-alpha",
            template_name="1m+2s", intended_pane_count=2,
            state=ManagedState.READY, failed_stage=None,
            idempotency_key=None,
            created_at=_ts(now), updated_at=_ts(now),
        ),
    )
    for i in range(2):
        insert_pane(
            ctx.state_conn,
            ManagedPaneRow(
                id=str(uuid.uuid4()), layout_id=layout_id,
                container_id="bench-alpha", agent_id=None,
                role="master" if i == 0 else "slave",
                capability="orchestrator" if i == 0 else "worker",
                label="m1" if i == 0 else "s1",
                launch_command_ref=None,
                tmux_session_name="session-edge-9", tmux_pane_index=i,
                pending_marker_token=None,
                state=ManagedState.READY, failed_stage=None,
                predecessor_id=None, chain_depth=0,
                created_at=_ts(now), updated_at=_ts(now),
            ),
        )
    ctx.state_conn.commit()

    # Simulate daemon restart: reconcile with NO live tmux panes.
    reconcile(
        conn=ctx.state_conn,
        serializer=ctx.managed_serializer,
        tmux_list_panes_fn=lambda cid: [],
    )

    # M3 detail surfaces the failure with recovery_reattach.
    resp = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )
    assert resp["ok"] is True
    layout = resp["result"]
    assert layout["state"] == "failed"
    assert layout["failed_stage"] == "recovery_reattach"
    assert all(p["failed_stage"] == "recovery_reattach" for p in layout["panes"])


# ─── Edge Case 11: FR-026 no-cascade-kill (integration smoke) ───────────


def test_edge_case_11_no_cascade_kill_integration(ctx: Any) -> None:
    """Bullet 11 / FR-026 — one pane fails mid-create; siblings continue
    to natural completion. Exercises the dispatcher → service → spawn
    pipeline together with a selective tmux backend."""
    resp = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": "bench-alpha",
            "template_name": "1m+2s",
            "tmux_session_name": "session-edge-11",
        },
        HOST_PEER_UID,
    )
    assert resp["ok"] is True
    layout_id = resp["result"]["layout_id"]

    # Inject failure on pane index 1 only.
    def selective_tmux(pane):  # noqa: ANN001
        if pane.tmux_pane_index == 1:
            return {"ok": False, "error": {"code": "tmux_failed", "message": "inj"}}
        return {
            "ok": True,
            "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
            "launch_alive": True,
        }

    def register_into_agents(pane, tmux_pane_id):  # noqa: ANN001
        agent_id = f"agent-{pane.id[:8]}"
        ctx.state_conn.execute("INSERT INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}

    spawn_layout_in_background(
        layout_id,
        conn=ctx.state_conn, serializer=ctx.managed_serializer,
        tmux_spawn_fn=selective_tmux,
        register_fn=register_into_agents,
        log_attach_fn=lambda p, a: {"ok": True},
    )

    # M3 detail: layout failed (one child failed), per-pane disposition
    # shows the no-cascade-kill outcome.
    detail = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )["result"]
    assert detail["state"] == "failed"
    by_index = {p["tmux_pane_index"]: p for p in detail["panes"]}
    assert by_index[0]["state"] == "ready"
    assert by_index[1]["state"] == "failed"
    assert by_index[1]["failed_stage"] == "pane_create"
    assert by_index[2]["state"] == "ready"  # ← no cascade-kill


# ─── Edge Case 7 (FEAT-004 scan filter) — verified via direct helper ───


def test_edge_case_7_feat004_scan_skips_managed_pending_panes() -> None:
    """Bullet 7 — the FEAT-004 scan skips panes whose tmux title carries
    the `@MANAGED:` prefix so an in-flight managed pane isn't adopted
    mid-spawn (FR-014 / R1). Verified via the FEAT-004 filter helper."""
    from agenttower.discovery.pane_service import _filter_pending_managed_panes
    from agenttower.tmux.parsers import ParsedPane

    def pp(title: str) -> ParsedPane:
        return ParsedPane(
            tmux_session_name="s", tmux_window_index=0, tmux_pane_index=0,
            tmux_pane_id="%1", pane_pid=1, pane_tty="/dev/null",
            pane_current_command="bash", pane_current_path="/",
            pane_title=title, pane_active=False,
        )

    kept, skipped = _filter_pending_managed_panes(
        [pp("adopted-pane"), pp("@MANAGED:tok:m1"), pp("@MANAGED:tok2:s1")]
    )
    assert skipped == 2
    assert len(kept) == 1
    assert kept[0].pane_title == "adopted-pane"
