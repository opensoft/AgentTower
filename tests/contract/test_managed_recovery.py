"""FEAT-013 T038: daemon-boot recovery reconcile contract test.

Covers FR-020 + SC-008 + state-machine.md §Recovery:

- All-alive (every pane matches a live tmux entry) → state preserved,
  LAYOUT_RECOVERY_REATTACHED emitted.
- No-match (no tmux entry for a stored pane) → state=failed,
  failed_stage=recovery_reattach, LAYOUT_RECOVERY_FAILED emitted.
- creating + marker_fresh + tmux-alive → resume creating (no state
  change; the original or retry spawn task continues).
- creating + marker_stale (>5min) + tmux-alive → failed/recovery_reattach
  (TTL expired during the restart window).
- creating + tmux-missing (regardless of marker freshness) → failed.
- Idempotent: a second reconcile on a stable tree is a no-op.

Uses the injectable ``TmuxListPanesFn`` backend so the test can drive
the reconcile without needing a real tmux server.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
import uuid
from typing import Any

import pytest

from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
    select_pane,
)
from agenttower.managed_sessions.recovery import (
    ReconcileOutcome,
    reconcile,
)
from agenttower.managed_sessions.serializer import ContainerSerializer
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


def _ts(when: _dt.datetime) -> str:
    """RFC3339 UTC stamp helper."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.UTC)
    return when.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _seed_layout(
    conn: sqlite3.Connection,
    *,
    container_id: str = "bench-alpha",
    template_name: str = "1m+2s",
    layout_state: ManagedState = ManagedState.READY,
    pane_count: int = 3,
    pane_state: ManagedState = ManagedState.READY,
    session_name: str = "session-alpha",
    marker_token: str | None = None,
    created_at: _dt.datetime | None = None,
) -> tuple[str, list[str]]:
    """Insert a managed_layout + N managed_pane rows in the given state.

    Returns (layout_id, [pane_id, ...]).
    """
    layout_id = str(uuid.uuid4())
    now_str = _ts(created_at or _dt.datetime.now(_dt.UTC))
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id,
            container_id=container_id,
            template_name=template_name,
            intended_pane_count=pane_count,
            state=layout_state,
            failed_stage=None,
            idempotency_key=None,
            created_at=now_str,
            updated_at=now_str,
        ),
    )
    pane_ids: list[str] = []
    for i in range(pane_count):
        pane_id = str(uuid.uuid4())
        marker = marker_token if pane_state == ManagedState.CREATING else None
        insert_pane(
            conn,
            ManagedPaneRow(
                id=pane_id,
                layout_id=layout_id,
                container_id=container_id,
                agent_id=None,
                role="master" if i == 0 else "slave",
                capability="orchestrator" if i == 0 else "worker",
                label=("m" if i == 0 else "s") + str(i if i > 0 else 1),
                launch_command_ref=None,
                tmux_session_name=session_name,
                tmux_pane_index=i,
                pending_marker_token=marker,
                state=pane_state,
                failed_stage=None,
                predecessor_id=None,
                chain_depth=0,
                created_at=now_str,
                updated_at=now_str,
            ),
        )
        pane_ids.append(pane_id)
    conn.commit()
    return layout_id, pane_ids


# ─── All-alive happy path ────────────────────────────────────────────────


def test_reconcile_all_alive_preserves_state_and_emits_reattached_event(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Every pane matches a live tmux entry → state preserved (ready
    stays ready), LAYOUT_RECOVERY_REATTACHED emitted with the pane id
    list, no state mutation."""
    layout_id, pane_ids = _seed_layout(conn)

    events: list[dict[str, Any]] = []

    def all_alive(container_id: str) -> list[dict]:
        # Match each pane by (session, pane_index).
        return [
            {"tmux_session_name": "session-alpha", "tmux_pane_index": i}
            for i in range(3)
        ]

    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=all_alive,
        event_emitter=events.append,
    )

    assert isinstance(outcome, ReconcileOutcome)
    assert outcome.layouts_examined == 1
    assert outcome.panes_examined == 3
    assert outcome.panes_reattached == 3
    assert outcome.panes_failed == 0
    assert outcome.panes_resumed_creating == 0

    # State preserved.
    for pid in pane_ids:
        row = select_pane(conn, pid)
        assert row.state == ManagedState.READY
        assert row.failed_stage is None

    # LAYOUT_RECOVERY_REATTACHED emitted once, carries all 3 pane ids.
    reattached = [e for e in events if e["event_type"] == "managed_layout_recovery_reattached"]
    assert len(reattached) == 1
    assert set(reattached[0]["payload"]["reattached_pane_ids"]) == set(pane_ids)


# ─── No-match → failed (recovery_reattach) ──────────────────────────────


def test_reconcile_missing_tmux_pane_marks_failed_recovery_reattach(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """No live tmux entry → pane transitions to failed + recovery_reattach
    + LAYOUT_RECOVERY_FAILED emitted."""
    layout_id, pane_ids = _seed_layout(conn)

    events: list[dict[str, Any]] = []

    def none_alive(container_id: str) -> list[dict]:
        return []

    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=none_alive,
        event_emitter=events.append,
    )

    assert outcome.panes_failed == 3
    assert outcome.panes_reattached == 0

    for pid in pane_ids:
        row = select_pane(conn, pid)
        assert row.state == ManagedState.FAILED
        assert row.failed_stage == FailedStage.RECOVERY_REATTACH
        assert row.pending_marker_token is None  # CHECK invariant

    # Layout aggregates to failed; layout-level failed_stage is
    # recovery_reattach too.
    layout_row = conn.execute(
        "SELECT state, failed_stage FROM managed_layout WHERE id = ?",
        (layout_id,),
    ).fetchone()
    assert layout_row[0] == "failed"
    assert layout_row[1] == "recovery_reattach"

    # LAYOUT_RECOVERY_FAILED carries the pane id list + failed_stage.
    failed_evts = [e for e in events if e["event_type"] == "managed_layout_recovery_failed"]
    assert len(failed_evts) == 1
    assert set(failed_evts[0]["payload"]["failed_pane_ids"]) == set(pane_ids)
    assert failed_evts[0]["payload"]["failed_stage"] == "recovery_reattach"


def test_reconcile_partial_match_layout_aggregates_to_failed(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """One pane alive + two missing → 1 reattached + 2 failed. Layout
    aggregates to failed because at-least-one-pane-failed per
    data-model.md aggregation rules."""
    layout_id, pane_ids = _seed_layout(conn)

    def partial(container_id: str) -> list[dict]:
        # Only pane index 0 (master) is alive.
        return [{"tmux_session_name": "session-alpha", "tmux_pane_index": 0}]

    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=partial,
    )
    assert outcome.panes_reattached == 1
    assert outcome.panes_failed == 2

    layout_row = conn.execute(
        "SELECT state FROM managed_layout WHERE id = ?",
        (layout_id,),
    ).fetchone()
    assert layout_row[0] == "failed"


# ─── creating + marker freshness rules ──────────────────────────────────


def test_reconcile_creating_fresh_marker_resumes_without_state_change(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """creating + matched in tmux + marker is fresh (<5min) → resume
    creating (no state change; spawn pipeline will continue). No event
    emitted because nothing transitioned."""
    layout_id, pane_ids = _seed_layout(
        conn,
        layout_state=ManagedState.CREATING,
        pane_state=ManagedState.CREATING,
        marker_token="fresh-token-abc",
        created_at=_dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=10),  # 10s ago
    )

    events: list[dict[str, Any]] = []

    def all_alive(container_id: str) -> list[dict]:
        return [
            {"tmux_session_name": "session-alpha", "tmux_pane_index": i}
            for i in range(3)
        ]

    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=all_alive,
        event_emitter=events.append,
    )

    assert outcome.panes_resumed_creating == 3
    assert outcome.panes_failed == 0
    assert outcome.panes_reattached == 0

    # State unchanged.
    for pid in pane_ids:
        row = select_pane(conn, pid)
        assert row.state == ManagedState.CREATING
        assert row.pending_marker_token == "fresh-token-abc"

    # No state-change or recovery events.
    assert all(e["event_type"] not in (
        "managed_pane_state_changed",
        "managed_layout_recovery_reattached",
        "managed_layout_recovery_failed",
    ) for e in events)


def test_reconcile_creating_stale_marker_transitions_to_failed(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """creating + matched in tmux + marker is stale (≥5min) → failed
    (recovery_reattach)."""
    layout_id, pane_ids = _seed_layout(
        conn,
        layout_state=ManagedState.CREATING,
        pane_state=ManagedState.CREATING,
        marker_token="stale-token-xyz",
        created_at=_dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=10),  # 10min ago
    )

    def all_alive(container_id: str) -> list[dict]:
        return [
            {"tmux_session_name": "session-alpha", "tmux_pane_index": i}
            for i in range(3)
        ]

    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=all_alive,
    )
    assert outcome.panes_failed == 3
    assert outcome.panes_resumed_creating == 0

    for pid in pane_ids:
        row = select_pane(conn, pid)
        assert row.state == ManagedState.FAILED
        assert row.failed_stage == FailedStage.RECOVERY_REATTACH
        assert row.pending_marker_token is None


def test_reconcile_creating_missing_tmux_marks_failed_regardless_of_marker(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """creating + tmux missing → failed (recovery_reattach) even with
    a fresh marker — no point resuming a spawn against an empty tmux."""
    layout_id, pane_ids = _seed_layout(
        conn,
        layout_state=ManagedState.CREATING,
        pane_state=ManagedState.CREATING,
        marker_token="fresh-token-but-no-pane",
        created_at=_dt.datetime.now(_dt.UTC),
    )

    def none_alive(container_id: str) -> list[dict]:
        return []

    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=none_alive,
    )
    assert outcome.panes_failed == 3


# ─── Idempotency ────────────────────────────────────────────────────────


def test_reconcile_is_idempotent_on_stable_tree(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """A second reconcile on a tree that's already settled is a no-op
    (no panes touched, no events emitted)."""
    _seed_layout(conn)

    events_first: list[dict] = []
    reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [
            {"tmux_session_name": "session-alpha", "tmux_pane_index": i}
            for i in range(3)
        ],
        event_emitter=events_first.append,
    )
    assert len(events_first) >= 1

    # Second reconcile — same backend, same tree.
    events_second: list[dict] = []
    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [
            {"tmux_session_name": "session-alpha", "tmux_pane_index": i}
            for i in range(3)
        ],
        event_emitter=events_second.append,
    )
    # Panes were already ready; the second pass re-emits the
    # LAYOUT_RECOVERY_REATTACHED audit event per state-machine.md
    # ("re-emit the audit event") but doesn't transition any rows.
    assert outcome.panes_reattached == 3
    assert outcome.panes_failed == 0


def test_reconcile_list_panes_failure_skips_container_and_counts_it(
    conn: sqlite3.Connection, serializer: ContainerSerializer,
    caplog,
) -> None:
    """Review P2#6/P2#7: a raising list-panes RPC must skip that container
    (rows untouched), count it in ``containers_skipped``, and log the
    exception class + message so the degraded boot recovery is
    diagnosable rather than looking like 'nothing to recover'."""
    import logging

    layout_id, pane_ids = _seed_layout(conn)

    def boom(container_id: str) -> list[dict]:
        raise RuntimeError("docker daemon unreachable")

    events: list[dict] = []
    with caplog.at_level(logging.WARNING):
        outcome = reconcile(
            conn=conn, serializer=serializer,
            tmux_list_panes_fn=boom,
            event_emitter=events.append,
        )

    # Container skipped: no rows touched, no events, and the skip counted.
    assert outcome.containers_skipped == 1
    assert outcome.panes_failed == 0
    assert outcome.panes_reattached == 0
    assert events == []
    for pid in pane_ids:
        row = select_pane(conn, pid)
        assert row.state == ManagedState.READY  # untouched

    # Diagnostics: the warning carries the exception class + message.
    assert any(
        "RuntimeError" in rec.message and "docker daemon unreachable" in rec.message
        for rec in caplog.records
    ), [rec.message for rec in caplog.records]


# ─── Removed layouts excluded ────────────────────────────────────────────


def test_reconcile_skips_removed_layouts(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Layouts in terminal `removed` state are not examined by the
    reconcile (their panes are archived; nothing to reattach)."""
    _seed_layout(
        conn,
        layout_state=ManagedState.REMOVED,
        pane_state=ManagedState.REMOVED,
    )

    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [],
    )
    assert outcome.layouts_examined == 0
    assert outcome.panes_examined == 0


# ─── Atomicity: pane transitions + layout aggregate commit together ──────


def test_reconcile_aggregate_failure_rolls_back_pane_transitions(
    conn: sqlite3.Connection,
    serializer: ContainerSerializer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure during the layout-aggregate write rolls back the pane
    transitions made in the same per-container transaction.

    Regression guard for the review P1 atomicity fix: pane-state writes
    and the layout aggregate recompute share one ``BEGIN IMMEDIATE``. If
    they were split across transactions, the panes would be left ``failed``
    while the layout stayed ``ready`` — and a later reconcile could not
    repair it (already-``failed`` panes are excluded from the non-terminal
    recovery query). Here every pane would transition to ``failed`` (no
    live tmux entry), but ``update_layout_state`` raises mid-transaction;
    both the pane rows AND the layout row must revert to ``ready``.
    """
    layout_id, pane_ids = _seed_layout(conn)

    # Fail the aggregate write that runs after the pane transitions, still
    # inside the open BEGIN IMMEDIATE.
    def boom(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error (injected)")

    monkeypatch.setattr(
        "agenttower.managed_sessions.recovery.update_layout_state", boom
    )

    events: list[dict[str, Any]] = []
    with pytest.raises(sqlite3.OperationalError):
        reconcile(
            conn=conn, serializer=serializer,
            tmux_list_panes_fn=lambda cid: [],  # nothing alive → all would fail
            event_emitter=events.append,
        )

    # Panes rolled back to their seeded ready state — NOT left failed.
    for pid in pane_ids:
        row = select_pane(conn, pid)
        assert row.state == ManagedState.READY
        assert row.failed_stage is None

    # Layout aggregate unchanged.
    layout_row = conn.execute(
        "SELECT state, failed_stage FROM managed_layout WHERE id = ?",
        (layout_id,),
    ).fetchone()
    assert layout_row[0] == "ready"
    assert layout_row[1] is None

    # No layout-scoped recovery event escaped — those emit only after the
    # combined transaction commits, which never happened here.
    assert not [
        e for e in events
        if e["event_type"].startswith("managed_layout_recovery_")
    ]
