"""FEAT-013 T039: SC-009 recovery-outcome visibility contract test.

After reconcile completes, the recovery outcome (reattached / failed_stage =
recovery_reattach) for every recovered managed-layout and managed-pane
row is visible from the standard ``app.managed_layout_detail`` (M3) and
``app.managed_pane_detail`` (M5) surfaces — without log inspection.

T049 is implemented in the M3/M5 handlers via the Phase 4a pane payload
shape, which already projects ``failed_stage`` when set. This test
verifies the round-trip: reconcile writes ``failed_stage=recovery_reattach``
via ``dao.update_pane_state``, then the M3/M5 handlers read it back and
surface it on the wire.

The SC-009 5-second wall-clock budget is enforced operationally by the
boot wiring (T047 — reconcile runs before the socket opens, so by the
time M3/M5 are reachable the reconcile is already done). This test
covers the *shape* + *correctness* of the round-trip; the wall-clock
budget is the responsibility of the Phase 6 T056 perf-marker task.
"""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
)
from agenttower.managed_sessions.handlers.app import (
    app_managed_layout_detail,
    app_managed_pane_detail,
)
from agenttower.managed_sessions.recovery import reconcile
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


# ─── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE containers (container_id TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
    c.execute(
        "INSERT INTO containers (container_id, active) VALUES (?, 1)",
        ("bench-alpha",),
    )
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


@pytest.fixture(autouse=True)
def force_host_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same fixture pattern as test_managed_dispatch.py — force the
    host-only gate to pass for in-process M3/M5 calls."""
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    from agenttower.socket_api.methods import (
        _clear_request_peer_context,
        _set_request_peer_context,
    )
    _set_request_peer_context(peer_pid=os.getpid())
    yield
    _clear_request_peer_context()


HOST_PEER_UID = 1000


def _ts(when: _dt.datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.UTC)
    return when.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _seed_layout_with_panes_in_state(
    conn: sqlite3.Connection,
    *,
    pane_state: ManagedState = ManagedState.READY,
) -> tuple[str, list[str]]:
    layout_id = str(uuid.uuid4())
    now = _ts(_dt.datetime.now(_dt.UTC))
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id,
            container_id="bench-alpha",
            template_name="1m+2s",
            intended_pane_count=3,
            state=pane_state,
            failed_stage=None,
            idempotency_key=None,
            created_at=now,
            updated_at=now,
        ),
    )
    pane_ids: list[str] = []
    for i in range(3):
        pid = str(uuid.uuid4())
        insert_pane(
            conn,
            ManagedPaneRow(
                id=pid,
                layout_id=layout_id,
                container_id="bench-alpha",
                agent_id=None,
                role="master" if i == 0 else "slave",
                capability="orchestrator" if i == 0 else "worker",
                label="m1" if i == 0 else f"s{i}",
                launch_command_ref=None,
                tmux_session_name="session-recovery",
                tmux_pane_index=i,
                pending_marker_token=None,
                state=pane_state,
                failed_stage=None,
                predecessor_id=None,
                chain_depth=0,
                created_at=now,
                updated_at=now,
            ),
        )
        pane_ids.append(pid)
    conn.commit()
    return layout_id, pane_ids


# ─── SC-009: M3 detail surface round-trips recovery_reattach ────────────


def test_m3_detail_surfaces_failed_stage_recovery_reattach_after_reconcile(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """SC-009: after reconcile transitions panes to failed/recovery_reattach,
    M3 ``app.managed_layout_detail`` surfaces the outcome directly
    (failed_stage in the layout-level response + per-pane payload)."""
    layout_id, pane_ids = _seed_layout_with_panes_in_state(conn)

    # No live tmux → all panes transition to failed/recovery_reattach.
    reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [],
    )

    ctx = SimpleNamespace(state_conn=conn, managed_serializer=serializer)
    resp = app_managed_layout_detail(ctx, {"layout_id": layout_id}, HOST_PEER_UID)
    assert resp["ok"] is True
    result = resp["result"]

    # Layout-level: state=failed + failed_stage=recovery_reattach.
    assert result["state"] == "failed"
    assert result["failed_stage"] == "recovery_reattach"

    # Per-pane: every pane carries failed_stage=recovery_reattach.
    panes = result["panes"]
    assert len(panes) == 3
    for p in panes:
        assert p["state"] == "failed"
        assert p["failed_stage"] == "recovery_reattach"


def test_m5_detail_surfaces_failed_stage_recovery_reattach_after_reconcile(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """SC-009: M5 ``app.managed_pane_detail`` returns the same
    failed_stage=recovery_reattach for a single pane."""
    layout_id, pane_ids = _seed_layout_with_panes_in_state(conn)
    reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [],
    )

    ctx = SimpleNamespace(state_conn=conn, managed_serializer=serializer)
    resp = app_managed_pane_detail(ctx, {"pane_id": pane_ids[0]}, HOST_PEER_UID)
    assert resp["ok"] is True
    pane = resp["result"]
    assert pane["pane_id"] == pane_ids[0]
    assert pane["state"] == "failed"
    assert pane["failed_stage"] == "recovery_reattach"


def test_m3_detail_shows_recovered_panes_with_state_preserved(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """SC-009 happy path: when reconcile preserves state (all-alive
    case), M3 returns ``state=ready`` + no ``failed_stage`` per pane."""
    layout_id, pane_ids = _seed_layout_with_panes_in_state(conn)

    reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [
            {"tmux_session_name": "session-recovery", "tmux_pane_index": i}
            for i in range(3)
        ],
    )

    ctx = SimpleNamespace(state_conn=conn, managed_serializer=serializer)
    resp = app_managed_layout_detail(ctx, {"layout_id": layout_id}, HOST_PEER_UID)
    assert resp["ok"] is True
    result = resp["result"]
    assert result["state"] == "ready"
    assert result["failed_stage"] is None
    for p in result["panes"]:
        assert p["state"] == "ready"
        # Per the M3 payload shape, a `failed_stage` key is OMITTED
        # (not set to null) when there's no failed_stage to surface.
        assert "failed_stage" not in p


def test_m3_detail_mixed_outcome_surfaces_per_pane_failed_stage(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """SC-009 partial: when reconcile preserves some panes and fails
    others, M3 surfaces failed_stage per pane (not just layout-level)."""
    layout_id, pane_ids = _seed_layout_with_panes_in_state(conn)

    reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [
            # Only pane index 0 (master) is alive.
            {"tmux_session_name": "session-recovery", "tmux_pane_index": 0},
        ],
    )

    ctx = SimpleNamespace(state_conn=conn, managed_serializer=serializer)
    resp = app_managed_layout_detail(ctx, {"layout_id": layout_id}, HOST_PEER_UID)
    assert resp["ok"] is True
    result = resp["result"]
    # Layout aggregate: at-least-one failed → failed.
    assert result["state"] == "failed"
    assert result["failed_stage"] == "recovery_reattach"

    # Per-pane disposition.
    by_index = {p["tmux_pane_index"]: p for p in result["panes"]}
    # Pane 0 alive → ready preserved, no failed_stage.
    assert by_index[0]["state"] == "ready"
    assert "failed_stage" not in by_index[0]
    # Panes 1 + 2 → failed/recovery_reattach.
    for i in (1, 2):
        assert by_index[i]["state"] == "failed"
        assert by_index[i]["failed_stage"] == "recovery_reattach"
