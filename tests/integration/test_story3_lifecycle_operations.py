"""FEAT-013 US3 integration test (T041).

Covers the three US3 acceptance scenarios end-to-end through the M1 →
M6/M7 dispatcher path with canned spawn-pipeline backends:

1. **US3 AS-1**: After remove, AgentTower kills the underlying tmux
   pane (or the kill-pane idempotent path), stops managing it, cleans
   up routes/log state, and preserves audit history indefinitely
   (FR-010 + FR-021).
2. **US3 AS-2**: After recreate, a new managed-pane record exists
   linked to its predecessor via `predecessor_id`, with a fresh
   identity (new pane_id, fresh `agent_id` after spawn pipeline) but
   the intended template role and label pattern (FR-011).
3. **US3 AS-3**: When the operator attempts a destructive lifecycle
   action on a pane that was only adopted (not managed by AgentTower),
   the destructive action is refused (`managed_pane_protected_adopted`
   / `managed_pane_not_found` per the N38 split). Adopted-pane row is
   unchanged after the refused attempt (FR-012 + SC-005).

Plus a US3 AS-4 follow-up: full lifecycle (create → ready → remove →
recreate → ready) preserves the predecessor chain across two iterations,
verifying the M5 `predecessor_chain` traversal.

Uses the same fake-backend pattern Phase 4b/5a established. Production
end-to-end (real daemon socket + real tmux/docker-exec) is gated on the
spawn-backends daemon-boot wiring (the same follow-up as `test_story1`).
"""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dispatcher import APP_DISPATCH
from agenttower.managed_sessions.dao import select_pane
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import spawn_layout_in_background
from agenttower.state.schema import _apply_migration_v9


# ─── fixtures ────────────────────────────────────────────────────────────


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


# ─── canned backends ────────────────────────────────────────────────────


def _good_tmux(pane):  # noqa: ANN001
    return {
        "ok": True,
        "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
        "launch_alive": True,
    }


def _make_register_backend(conn):  # noqa: ANN001
    def register(pane, tmux_pane_id):  # noqa: ANN001
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute(
            "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
            (agent_id, "managed"),
        )
        return {"ok": True, "agent_id": agent_id}
    return register


def _good_log(pane, agent_id):  # noqa: ANN001
    return {"ok": True}


def _create_layout_and_drive_to_ready(ctx) -> str:  # noqa: ANN001
    """Create + spawn a 1m+2s layout end-to-end; return layout_id."""
    resp = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": "bench-alpha",
            "template_name": "1m+2s",
            "tmux_session_name": "us3-session",
        },
        HOST_PEER_UID,
    )
    assert resp["ok"] is True
    layout_id = resp["result"]["layout_id"]
    spawn_layout_in_background(
        layout_id,
        conn=ctx.state_conn,
        serializer=ctx.managed_serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(ctx.state_conn),
        log_attach_fn=_good_log,
    )
    return layout_id


# ─── US3 AS-1: remove preserves audit ───────────────────────────────────


def test_us3_as1_remove_kills_pane_and_preserves_managed_pane_row(ctx: Any) -> None:
    """After M6 remove, the managed_pane row stays in SQLite (FR-021
    indefinite retention) with state=removed; the tmux backend was
    invoked; the M3 detail surface still shows the layout."""
    layout_id = _create_layout_and_drive_to_ready(ctx)
    detail = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id, "include_terminal_panes": True}, HOST_PEER_UID,
    )
    assert detail["ok"] is True
    target = detail["result"]["panes"][0]["pane_id"]

    # Inject a tmux-kill backend on ctx so the M6 handler picks it up.
    # T059: the remove handler reads the backend from the
    # managed_spawn_backends dict (key "tmux_kill").
    kill_calls: list[str] = []
    ctx.managed_spawn_backends = {
        "tmux_kill": lambda pane: (kill_calls.append(pane.id), {"ok": True})[1]
    }

    rm = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": target}, HOST_PEER_UID,
    )
    assert rm["ok"] is True
    assert rm["result"]["pane_id"] == target
    assert rm["result"]["state"] == "removed"
    assert kill_calls == [target]

    # Audit retention (FR-021): the managed_pane row stays.
    row = select_pane(ctx.state_conn, target)
    assert row is not None
    assert row.state.value == "removed"
    assert row.pending_marker_token is None  # CHECK invariant

    # The M3 detail surface still includes the removed pane when
    # `include_terminal_panes=True` (per Phase 4a wiring).
    detail_after = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id, "include_terminal_panes": True}, HOST_PEER_UID,
    )
    panes_after = [p for p in detail_after["result"]["panes"] if p["pane_id"] == target]
    assert len(panes_after) == 1
    assert panes_after[0]["state"] == "removed"


def test_us3_as1_remove_tmux_already_gone_is_idempotent(ctx: Any) -> None:
    """Backend reporting `tmux_pane_not_found` counts as success — the
    operator intent ('pane is gone') is satisfied either way (FR-010)."""
    layout_id = _create_layout_and_drive_to_ready(ctx)
    target = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )["result"]["panes"][0]["pane_id"]

    ctx.managed_spawn_backends = {
        "tmux_kill": lambda pane: {
            "ok": False,
            "error": {"code": "tmux_pane_not_found", "message": "gone"},
        }
    }

    rm = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": target}, HOST_PEER_UID,
    )
    assert rm["ok"] is True
    assert rm["result"]["state"] == "removed"


def test_us3_as1_remove_threads_all_three_backends_from_dict(ctx: Any) -> None:
    """T059: the M6 handler threads tmux_kill + route_cleanup + log_detach
    from the managed_spawn_backends dict into remove_pane, and all three
    fire for the removed pane."""
    layout_id = _create_layout_and_drive_to_ready(ctx)
    target = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )["result"]["panes"][0]["pane_id"]

    killed: list[str] = []
    routes_cleaned: list[str] = []
    logs_detached: list[str] = []
    ctx.managed_spawn_backends = {
        "tmux_kill": lambda pane: (killed.append(pane.id), {"ok": True})[1],
        "route_cleanup": lambda pane: routes_cleaned.append(pane.id),
        "log_detach": lambda pane: logs_detached.append(pane.id),
    }

    rm = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": target}, HOST_PEER_UID,
    )
    assert rm["ok"] is True
    assert killed == [target]
    assert routes_cleaned == [target]
    assert logs_detached == [target]


# ─── US3 AS-2: recreate produces predecessor-linked row ─────────────────


def test_us3_as2_recreate_links_to_predecessor_with_fresh_identity(ctx: Any) -> None:
    """After remove → recreate, the new managed_pane has:
    - new pane_id (fresh identity)
    - predecessor_id pointing at the removed pane
    - chain_depth = 1
    - state = creating
    - role + label inherited from the predecessor's template position
    (FR-011)."""
    layout_id = _create_layout_and_drive_to_ready(ctx)
    target = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )["result"]["panes"][0]["pane_id"]
    target_row = select_pane(ctx.state_conn, target)
    assert target_row.role == "master"
    assert target_row.label == "m1"

    # Remove first (predecessor must be removed/failed for recreate).
    APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": target}, HOST_PEER_UID,
    )

    rc = APP_DISPATCH["app.managed_pane_recreate"](
        ctx, {"predecessor_pane_id": target}, HOST_PEER_UID,
    )
    assert rc["ok"] is True
    new_pane_id = rc["result"]["pane_id"]
    assert new_pane_id != target
    assert rc["result"]["predecessor_id"] == target
    assert rc["result"]["chain_depth"] == 1
    assert rc["result"]["state"] == "creating"

    # The new row inherits role + label from the predecessor's template
    # position (FR-011: "same intended role, capability, label pattern").
    new_row = select_pane(ctx.state_conn, new_pane_id)
    assert new_row.role == "master"
    assert new_row.label == "m1"
    assert new_row.predecessor_id == target


def test_us3_as2_recreate_chain_traversal_via_m5_detail(ctx: Any) -> None:
    """M5 ``app.managed_pane_detail`` with ``include_predecessor_chain=True``
    returns the recreate chain (FR-011 + M5 contract)."""
    layout_id = _create_layout_and_drive_to_ready(ctx)
    original = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )["result"]["panes"][0]["pane_id"]

    # Iterate: remove → recreate → drive new pane to ready → repeat.
    panes = [original]
    for _ in range(2):
        APP_DISPATCH["app.managed_pane_remove"](
            ctx, {"pane_id": panes[-1]}, HOST_PEER_UID,
        )
        rc = APP_DISPATCH["app.managed_pane_recreate"](
            ctx, {"predecessor_pane_id": panes[-1]}, HOST_PEER_UID,
        )
        new_id = rc["result"]["pane_id"]
        # Drive it to ready (so the next remove can pick it up).
        spawn_layout_in_background(
            layout_id,
            conn=ctx.state_conn,
            serializer=ctx.managed_serializer,
            tmux_spawn_fn=_good_tmux,
            register_fn=_make_register_backend(ctx.state_conn),
            log_attach_fn=_good_log,
        )
        panes.append(new_id)

    # Final pane has chain_depth = 2 (two recreate iterations).
    final = panes[-1]
    detail = APP_DISPATCH["app.managed_pane_detail"](
        ctx, {"pane_id": final, "include_predecessor_chain": True}, HOST_PEER_UID,
    )
    assert detail["ok"] is True
    pane = detail["result"]
    assert pane["chain_depth"] == 2
    assert pane["predecessor_id"] == panes[-2]
    chain = pane["predecessor_chain"]
    assert len(chain) == 2  # two-step chain back to the original
    assert chain[0]["pane_id"] == panes[-2]  # most-recent predecessor first
    assert chain[1]["pane_id"] == panes[-3]  # then original


# ─── US3 AS-3: adopted-pane protection ──────────────────────────────────


def test_us3_as3_remove_adopted_pane_id_returns_protected_adopted(ctx: Any) -> None:
    """FR-012: a pane_id that's only in the FEAT-006 agents table
    (adopted, not managed by FEAT-013) cannot be removed via the
    managed.* path."""
    ctx.state_conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-ADOPTED-WORKER", "adopted"),
    )
    ctx.state_conn.commit()

    rm = APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": "01HZ-ADOPTED-WORKER"}, HOST_PEER_UID,
    )
    assert rm["ok"] is False
    assert rm["error"]["code"] == "managed_pane_protected_adopted"
    assert rm["error"]["details"] == {
        "agent_id": "01HZ-ADOPTED-WORKER",
        "is_adopted": True,
    }


def test_us3_as3_adopted_row_unchanged_after_refused_remove(ctx: Any) -> None:
    """The adopted agent's row is unchanged after the refused remove
    (SC-005: managed remove never affects adopted-pane state)."""
    ctx.state_conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-ADOPTED-PROTECTED", "adopted"),
    )
    ctx.state_conn.commit()
    before = ctx.state_conn.execute(
        "SELECT agent_id, origin FROM agents WHERE agent_id = ?",
        ("01HZ-ADOPTED-PROTECTED",),
    ).fetchone()

    APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": "01HZ-ADOPTED-PROTECTED"}, HOST_PEER_UID,
    )

    after = ctx.state_conn.execute(
        "SELECT agent_id, origin FROM agents WHERE agent_id = ?",
        ("01HZ-ADOPTED-PROTECTED",),
    ).fetchone()
    assert before == after


def test_us3_as3_recreate_against_adopted_id_returns_protected_adopted(ctx: Any) -> None:
    """Same protection extends to M7 recreate — adopted id can't be used
    as a predecessor."""
    ctx.state_conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-ADOPTED-PREDECESSOR", "adopted"),
    )
    ctx.state_conn.commit()

    rc = APP_DISPATCH["app.managed_pane_recreate"](
        ctx, {"predecessor_pane_id": "01HZ-ADOPTED-PREDECESSOR"}, HOST_PEER_UID,
    )
    assert rc["ok"] is False
    assert rc["error"]["code"] == "managed_pane_protected_adopted"


def test_us3_managed_remove_does_not_disturb_coexisting_adopted_row(ctx: Any) -> None:
    """FR-009 + SC-005: a managed pane and an adopted pane coexist in
    the same container; removing the managed pane leaves the adopted
    row untouched."""
    ctx.state_conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-ADOPTED-COEXIST", "adopted"),
    )
    ctx.state_conn.commit()

    layout_id = _create_layout_and_drive_to_ready(ctx)
    managed_target = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )["result"]["panes"][0]["pane_id"]

    APP_DISPATCH["app.managed_pane_remove"](
        ctx, {"pane_id": managed_target}, HOST_PEER_UID,
    )

    # Adopted row still there + still origin=adopted.
    adopted = ctx.state_conn.execute(
        "SELECT origin FROM agents WHERE agent_id = ?",
        ("01HZ-ADOPTED-COEXIST",),
    ).fetchone()
    assert adopted == ("adopted",)
