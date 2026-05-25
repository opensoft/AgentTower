"""FEAT-013 T035: managed.pane.remove (M6) contract test.

Covers FR-010 (kill underlying tmux pane + cleanup routes/logs + retain
audit) including the tmux-already-killed idempotent success path. Adopted-
pane protection (FR-012) is exercised here too because `remove_pane`'s
T044 missing-row probe is the natural test site.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from agenttower.managed_sessions.dao import (
    select_pane,
    select_panes_for_layout,
)
from agenttower.managed_sessions.errors import (
    MANAGED_PANE_ILLEGAL_TRANSITION,
    MANAGED_PANE_PROTECTED_ADOPTED,
    ManagedSessionsError,
)
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    create_layout,
    remove_pane,
    spawn_layout_in_background,
)
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


# ─── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    _apply_migration_v9(c)
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


def _good_tmux(pane):  # noqa: ANN001
    return {
        "ok": True,
        "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
        "launch_alive": True,
    }


def _make_register_backend(conn):  # noqa: ANN001
    def register(pane, tmux_pane_id):  # noqa: ANN001
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute("INSERT INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}
    return register


def _good_log(pane, agent_id):  # noqa: ANN001
    return {"ok": True}


def _build_ready_pane(conn, serializer):  # noqa: ANN001
    """Helper: create a 1m+2s layout and drive it to ``ready`` via the
    spawn pipeline with healthy backends. Returns the layout result so
    tests can grab a specific pane to operate on."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="remove-test",
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
    )
    return result


# ─── T044 adopted-pane protection ───────────────────────────────────────


def test_remove_unknown_pane_returns_protected_adopted(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """T044: a pane_id without a managed_pane row is treated as adopted
    (or non-existent — same operator-actionable answer); ``remove_pane``
    raises ``managed_pane_protected_adopted`` per FR-012."""
    with pytest.raises(ManagedSessionsError) as exc_info:
        remove_pane(
            conn=conn, serializer=serializer,
            pane_id="01HZ-NEVER-EXISTED",
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_PROTECTED_ADOPTED
    assert exc.details == {"agent_id": "01HZ-NEVER-EXISTED", "is_adopted": True}


# ─── FR-018 illegal-transition (creating state cannot be removed) ───────


def test_remove_creating_pane_returns_illegal_transition(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-018: cancellation of in-flight create is out of scope; ``remove
    while creating`` returns ``managed_pane_illegal_transition`` with
    `requested_action=remove` and `current_state=creating`."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="remove-creating",
    )
    creating_pane_id = result.panes[0].pane_id
    with pytest.raises(ManagedSessionsError) as exc_info:
        remove_pane(
            conn=conn, serializer=serializer, pane_id=creating_pane_id,
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_ILLEGAL_TRANSITION
    assert exc.details["pane_id"] == creating_pane_id
    assert exc.details["current_state"] == "creating"
    assert exc.details["requested_action"] == "remove"


# ─── FR-010 happy path ──────────────────────────────────────────────────


def test_remove_ready_pane_transitions_to_removed_and_emits_event(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-010: remove a ready pane → state=removed, tmux kill invoked,
    cleanup hooks called, managed_pane_removed event emitted."""
    result = _build_ready_pane(conn, serializer)
    target = result.panes[0].pane_id

    events: list[dict[str, Any]] = []
    kill_calls: list[str] = []
    route_calls: list[str] = []
    log_calls: list[str] = []

    out = remove_pane(
        conn=conn, serializer=serializer,
        pane_id=target,
        tmux_kill_fn=lambda p: (kill_calls.append(p.id), {"ok": True})[1],
        route_cleanup_fn=lambda p: route_calls.append(p.id),
        log_detach_fn=lambda p: log_calls.append(p.id),
        event_emitter=events.append,
    )

    assert out.pane_id == target
    assert out.state == ManagedState.REMOVED
    # SQLite row is now in 'removed' state with marker cleared.
    refreshed = select_pane(conn, target)
    assert refreshed.state == ManagedState.REMOVED
    assert refreshed.pending_marker_token is None  # CHECK invariant

    # tmux kill + cleanup called once for the target pane.
    assert kill_calls == [target]
    assert route_calls == [target]
    assert log_calls == [target]

    # Events: PANE_REMOVED + PANE_STATE_CHANGED (per-pane) + (optional)
    # LAYOUT_STATE_CHANGED if aggregate changed.
    event_types = [e["event_type"] for e in events]
    assert "managed_pane_removed" in event_types
    assert "managed_pane_state_changed" in event_types
    pane_removed = next(e for e in events if e["event_type"] == "managed_pane_removed")
    assert pane_removed["payload"]["tmux_kill_succeeded"] is True


def test_remove_when_tmux_pane_already_gone_is_idempotent(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-010 idempotency: backend reporting ``tmux_pane_not_found`` is
    treated as success (pane is gone — operator intent satisfied)."""
    result = _build_ready_pane(conn, serializer)
    target = result.panes[0].pane_id

    def already_gone_tmux(pane):  # noqa: ANN001
        return {"ok": False, "error": {"code": "tmux_pane_not_found", "message": "gone"}}

    events: list[dict[str, Any]] = []
    out = remove_pane(
        conn=conn, serializer=serializer,
        pane_id=target,
        tmux_kill_fn=already_gone_tmux,
        event_emitter=events.append,
    )
    assert out.state == ManagedState.REMOVED
    refreshed = select_pane(conn, target)
    assert refreshed.state == ManagedState.REMOVED

    # PANE_REMOVED event carries tmux_kill_succeeded=True because the
    # "already gone" outcome is treated as success.
    pane_removed = next(e for e in events if e["event_type"] == "managed_pane_removed")
    assert pane_removed["payload"]["tmux_kill_succeeded"] is True


def test_remove_already_removed_pane_is_no_op(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Removing a pane in ``removed`` state is a no-op (idempotent
    success). No new events emitted because no state transition
    occurred."""
    result = _build_ready_pane(conn, serializer)
    target = result.panes[0].pane_id

    # First remove (normal).
    remove_pane(
        conn=conn, serializer=serializer, pane_id=target,
        tmux_kill_fn=lambda p: {"ok": True},
    )
    # Second remove — should be a no-op.
    events: list[dict[str, Any]] = []
    out = remove_pane(
        conn=conn, serializer=serializer, pane_id=target,
        tmux_kill_fn=lambda p: {"ok": True},  # never called
        event_emitter=events.append,
    )
    assert out.state == ManagedState.REMOVED
    assert events == []  # no transition → no events


def test_remove_last_pane_in_layout_aggregates_layout_to_removed(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """data-model.md ManagedLayout lifecycle: when all panes are
    ``removed``, the layout aggregates to ``removed`` too."""
    result = _build_ready_pane(conn, serializer)
    panes = select_panes_for_layout(conn, result.layout_id)
    assert len(panes) == 3

    # Remove all three panes in sequence.
    for p in panes:
        remove_pane(
            conn=conn, serializer=serializer, pane_id=p.id,
            tmux_kill_fn=lambda pane: {"ok": True},
        )

    # Layout state should now be 'removed' (aggregate rule).
    refreshed = conn.execute(
        "SELECT state FROM managed_layout WHERE id = ?",
        (result.layout_id,),
    ).fetchone()
    assert refreshed[0] == "removed"
