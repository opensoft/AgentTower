"""FEAT-013 T036: managed.pane.recreate (M7) contract test.

Covers:
- FR-011: new managed_pane row with `predecessor_id` + `chain_depth+1`.
- FR-023 / R4: chain_depth ≤ 16; `managed_pane_recreate_chain_too_deep`
  at the boundary (predecessor.chain_depth >= 15).
- `managed_pane_illegal_recreate_source` for predecessor in
  ready/degraded/creating (must be removed/failed).
- FR-027: concurrent-recreate of the same predecessor returns
  `managed_pane_concurrent_recreate` with the in-flight successor's
  pane_id in details.
- T044 adopted-pane protection: predecessor_pane_id without a
  managed_pane row → `managed_pane_protected_adopted`.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from agenttower.managed_sessions.dao import (
    ManagedPaneRow,
    insert_pane,
    select_pane,
    select_panes_for_layout,
    update_pane_state,
)
from agenttower.managed_sessions.errors import (
    MANAGED_LAUNCH_COMMAND_NOT_FOUND,
    MANAGED_PANE_CONCURRENT_RECREATE,
    MANAGED_PANE_ILLEGAL_RECREATE_SOURCE,
    MANAGED_PANE_LABEL_CONFLICT,
    MANAGED_PANE_NOT_FOUND,
    MANAGED_PANE_PROTECTED_ADOPTED,
    MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP,
    MANAGED_SESSION_NAME_CONFLICT,
    ManagedSessionsError,
)
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    create_layout,
    recreate_pane,
    remove_pane,
    spawn_layout_in_background,
)
from agenttower.managed_sessions.state_machine import FailedStage, ManagedState
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


def _layout_with_removed_pane(conn, serializer):  # noqa: ANN001
    """Build a layout, spawn it healthy, then remove the master pane.
    Returns (layout_id, master_pane_id_removed)."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="recreate-test",
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
    )
    panes = select_panes_for_layout(conn, result.layout_id)
    master = next(p for p in panes if p.role == "master")
    remove_pane(
        conn=conn, serializer=serializer, pane_id=master.id,
        tmux_kill_fn=lambda p: {"ok": True},
    )
    return result.layout_id, master.id


# ─── T044 + N38: M7 contract error split ────────────────────────────────


def test_recreate_truly_unknown_predecessor_returns_not_found(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """N38 (Pass 26 fix): predecessor_pane_id unknown to BOTH
    `managed_pane` AND `agents` → `managed_pane_not_found`."""
    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id="01HZ-NEVER-EXISTED",
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_NOT_FOUND
    assert exc.details == {"pane_id": "01HZ-NEVER-EXISTED"}


def test_recreate_adopted_predecessor_returns_protected_adopted(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """N38 (Pass 26 fix): predecessor_pane_id IS in `agents` (adopted)
    but NOT in `managed_pane` → `managed_pane_protected_adopted`."""
    conn.execute(
        "INSERT INTO agents (agent_id) VALUES (?)",
        ("01HZ-ADOPTED-PREDECESSOR",),
    )
    conn.commit()
    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id="01HZ-ADOPTED-PREDECESSOR",
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_PROTECTED_ADOPTED
    assert exc.details == {"agent_id": "01HZ-ADOPTED-PREDECESSOR", "is_adopted": True}


# ─── illegal_recreate_source: predecessor must be removed/failed ────────


def test_recreate_from_ready_predecessor_is_rejected(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """A `ready`-state predecessor returns
    ``managed_pane_illegal_recreate_source`` per state-machine.md
    §Recreate semantics (operator must `remove_pane` first)."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="recreate-ready",
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
    )
    ready_pane = next(
        p for p in select_panes_for_layout(conn, result.layout_id)
        if p.state == ManagedState.READY
    )
    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=ready_pane.id,
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_ILLEGAL_RECREATE_SOURCE
    assert exc.details["predecessor_pane_id"] == ready_pane.id
    assert exc.details["current_state"] == "ready"


def test_recreate_from_creating_predecessor_is_rejected(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """`creating` is also a forbidden source — recreate can't race with
    the in-flight spawn pipeline."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="recreate-creating",
    )
    creating_pane = result.panes[0]
    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=creating_pane.pane_id,
        )
    assert exc_info.value.code == MANAGED_PANE_ILLEGAL_RECREATE_SOURCE


# ─── FR-011 happy path: new row linked via predecessor_id + chain_depth+1


def test_recreate_from_removed_predecessor_inserts_linked_row(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-011 happy path: new managed_pane row with predecessor_id set
    + chain_depth = predecessor.chain_depth + 1 + state=creating +
    fresh pending_marker_token; managed_pane_recreated event emitted."""
    layout_id, removed_id = _layout_with_removed_pane(conn, serializer)

    events: list = []
    out = recreate_pane(
        conn=conn, serializer=serializer,
        predecessor_pane_id=removed_id,
        event_emitter=events.append,
    )

    assert out.predecessor_id == removed_id
    assert out.chain_depth == 1  # predecessor was at depth 0
    assert out.state == ManagedState.CREATING

    new_row = select_pane(conn, out.pane_id)
    assert new_row is not None
    assert new_row.predecessor_id == removed_id
    assert new_row.chain_depth == 1
    assert new_row.state == ManagedState.CREATING
    assert new_row.pending_marker_token is not None  # fresh token
    assert new_row.role == "master"  # inherited from predecessor
    assert new_row.label == "m1"  # label reuse (predecessor terminal)

    # PANE_RECREATED event payload carries the chain pointers.
    recreated = next(e for e in events if e["event_type"] == "managed_pane_recreated")
    assert recreated["payload"]["predecessor_id"] == removed_id
    assert recreated["payload"]["chain_depth"] == 1


def test_recreate_with_launch_command_override_threads_through(
    conn: sqlite3.Connection, serializer: ContainerSerializer, tmp_path
) -> None:
    """When the caller supplies `launch_command_override`, the new pane's
    `launch_command_ref` is the override (not the predecessor's value).

    Post-N39 (Pass 26): the override is resolved synchronously, so the
    profile must exist on disk. We seed a temp profile dir for the
    test so the resolver succeeds.
    """
    profile = tmp_path / "claude-worker-v2.yaml"
    profile.write_text('name: claude-worker-v2\ncommand: ["bash", "-lc", "echo v2"]\n')

    layout_id, removed_id = _layout_with_removed_pane(conn, serializer)
    out = recreate_pane(
        conn=conn, serializer=serializer,
        predecessor_pane_id=removed_id,
        launch_command_override="claude-worker-v2",
        profile_override_dir=tmp_path,
    )
    new_row = select_pane(conn, out.pane_id)
    assert new_row.launch_command_ref == "claude-worker-v2"


def test_recreate_with_bogus_override_returns_launch_command_not_found(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """N39 (Pass 26 fix): a non-resolvable ``launch_command_override``
    surfaces ``managed_launch_command_not_found`` SYNCHRONOUSLY (before
    the new managed_pane row is inserted), so the operator gets a
    clean rejection instead of a delayed background-spawn failure.
    Mirrors create_layout's upfront profile-resolution behavior.
    """
    layout_id, removed_id = _layout_with_removed_pane(conn, serializer)

    # No profile_override_dir → only built-in profiles (none in MVP);
    # "claude-worker-bogus" can't resolve.
    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=removed_id,
            launch_command_override="claude-worker-bogus",
        )
    exc = exc_info.value
    assert exc.code == MANAGED_LAUNCH_COMMAND_NOT_FOUND
    assert exc.details["profile_name"] == "claude-worker-bogus"

    # Critical: no new managed_pane row was inserted (the rejection
    # happens BEFORE the insert per the synchronous-error contract).
    successor_count = conn.execute(
        "SELECT COUNT(*) FROM managed_pane WHERE predecessor_id = ?",
        (removed_id,),
    ).fetchone()[0]
    assert successor_count == 0


# ─── FR-027: concurrent recreate of same predecessor ────────────────────


def test_concurrent_recreate_of_same_predecessor_returns_in_flight_id(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-027: two recreates of the same predecessor — first proceeds,
    second returns ``managed_pane_concurrent_recreate`` with the
    in-flight successor's pane_id in details."""
    layout_id, removed_id = _layout_with_removed_pane(conn, serializer)

    first = recreate_pane(
        conn=conn, serializer=serializer,
        predecessor_pane_id=removed_id,
    )

    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=removed_id,
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_CONCURRENT_RECREATE
    assert exc.details["predecessor_pane_id"] == removed_id
    assert exc.details["in_flight_successor_pane_id"] == first.pane_id


def test_review10_recreate_idempotency_key_replays_in_flight_successor(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Review #10: a recreate retried with the SAME idempotency_key returns
    the existing successor as a replay (R10 'same as create'), instead of
    rejecting the safe retry as managed_pane_concurrent_recreate."""
    _layout_id, removed_id = _layout_with_removed_pane(conn, serializer)

    first = recreate_pane(
        conn=conn, serializer=serializer,
        predecessor_pane_id=removed_id, idempotency_key="retry-key-1",
    )
    assert first.replay is False

    again = recreate_pane(
        conn=conn, serializer=serializer,
        predecessor_pane_id=removed_id, idempotency_key="retry-key-1",
    )
    assert again.replay is True
    assert again.pane_id == first.pane_id
    assert again.predecessor_id == removed_id


def test_review10_recreate_different_idempotency_key_still_concurrent(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """A DIFFERENT idempotency_key (genuine concurrent recreate, not a
    retry) while a successor is in-flight still returns concurrent_recreate."""
    _layout_id, removed_id = _layout_with_removed_pane(conn, serializer)
    recreate_pane(
        conn=conn, serializer=serializer,
        predecessor_pane_id=removed_id, idempotency_key="key-A",
    )
    with pytest.raises(ManagedSessionsError) as exc:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=removed_id, idempotency_key="key-B",
        )
    assert exc.value.code == MANAGED_PANE_CONCURRENT_RECREATE


def test_review6_recreate_with_ready_successor_rejects_not_integrityerror(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Review #6: a second recreate of a predecessor whose first successor
    is already READY (occupying the tmux-target/label slot) is rejected
    with the closed-set concurrent_recreate — NOT a raw IntegrityError."""
    _layout_id, removed_id = _layout_with_removed_pane(conn, serializer)
    first = recreate_pane(
        conn=conn, serializer=serializer, predecessor_pane_id=removed_id,
    )
    # Drive the successor to ready (clears its marker, keeps the slot).
    update_pane_state(
        conn, first.pane_id, state=ManagedState.READY,
        clear_marker=True, now="2026-06-01T00:00:00.000000Z",
    )
    conn.commit()

    with pytest.raises(ManagedSessionsError) as exc:
        recreate_pane(
            conn=conn, serializer=serializer, predecessor_pane_id=removed_id,
        )
    assert exc.value.code == MANAGED_PANE_CONCURRENT_RECREATE


def test_review6_recreate_slot_collision_translates_to_closed_set(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Review #6: if an UNRELATED live pane re-occupies the predecessor's
    freed (tmux_session_name, tmux_pane_index) slot, the insert's
    IntegrityError is translated to a closed-set conflict code (not leaked
    raw out of the M7 contract)."""
    _layout_id, removed_id = _layout_with_removed_pane(conn, serializer)
    pred = select_pane(conn, removed_id)
    # An unrelated ready pane (no predecessor link) occupying pred's slot.
    insert_pane(
        conn,
        ManagedPaneRow(
            id=str(uuid.uuid4()), layout_id=pred.layout_id,
            container_id=pred.container_id, agent_id=None,
            role="slave", capability="worker", label="unrelated-occupant",
            launch_command_ref=None,
            tmux_session_name=pred.tmux_session_name,
            tmux_pane_index=pred.tmux_pane_index,
            pending_marker_token=None, state=ManagedState.READY,
            failed_stage=None, predecessor_id=None, chain_depth=0,
            created_at="2026-06-01T00:00:00.000000Z",
            updated_at="2026-06-01T00:00:00.000000Z",
        ),
    )
    conn.commit()

    with pytest.raises(ManagedSessionsError) as exc:
        recreate_pane(
            conn=conn, serializer=serializer, predecessor_pane_id=removed_id,
        )
    assert exc.value.code in (
        MANAGED_SESSION_NAME_CONFLICT, MANAGED_PANE_LABEL_CONFLICT,
    )


# ─── FR-023 / R4: chain_depth bound ─────────────────────────────────────


def test_recreate_at_chain_depth_limit_is_rejected(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-023 / R4: when `predecessor.chain_depth >= 15`, the next
    recreate would be at depth 16 — the configured bound. Returns
    `managed_pane_recreate_chain_too_deep` with the bound + the
    predecessor's chain_depth in details."""
    # Seed a synthetic predecessor at chain_depth=15 directly via dao.
    layout_id, removed_id = _layout_with_removed_pane(conn, serializer)
    deep_pane_id = str(uuid.uuid4())
    deep_row = ManagedPaneRow(
        id=deep_pane_id,
        layout_id=layout_id,
        container_id="bench-alpha",
        agent_id=None,
        role="slave",
        capability="worker",
        label="deep-pane",
        launch_command_ref=None,
        tmux_session_name="deep-session",
        tmux_pane_index=42,
        pending_marker_token=None,
        state=ManagedState.FAILED,
        failed_stage=FailedStage.REGISTRATION,
        predecessor_id=removed_id,
        chain_depth=15,  # the rejection threshold
        created_at="2026-01-01T00:00:00.000000Z",
        updated_at="2026-01-01T00:00:00.000000Z",
    )
    insert_pane(conn, deep_row)
    conn.commit()

    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=deep_pane_id,
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP
    assert exc.details["predecessor_pane_id"] == deep_pane_id
    assert exc.details["predecessor_chain_depth"] == 15
    assert exc.details["limit"] == 16
