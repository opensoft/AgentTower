"""FEAT-013 SQLite DAO for managed_layout + managed_pane (T022 internal).

Thin row-shape conversion + insert / select helpers. The schema lives
in FEAT-001 ``state/schema.py`` (migration v9). This module owns the
read/write side; ``service.py`` orchestrates the calls.

All writes run inside the caller's transaction — this DAO does NOT
manage ``BEGIN`` / ``COMMIT``. The caller (service.create_layout)
holds the per-container lock + the SQLite immediate transaction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from .state_machine import FailedStage, ManagedState, _state_priority_sql_expr


@dataclass(frozen=True, slots=True)
class ManagedLayoutRow:
    """Row shape for ``managed_layout`` (data-model.md §DDL)."""

    id: str
    container_id: str
    template_name: str
    intended_pane_count: int
    state: ManagedState
    failed_stage: Optional[FailedStage]
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ManagedPaneRow:
    """Row shape for ``managed_pane`` (data-model.md §DDL)."""

    id: str
    layout_id: str
    container_id: str
    role: str
    capability: str
    label: str
    tmux_session_name: str
    tmux_pane_index: int
    state: ManagedState
    chain_depth: int
    created_at: str
    updated_at: str
    agent_id: Optional[str] = None
    launch_command_ref: Optional[str] = None
    pending_marker_token: Optional[str] = None
    failed_stage: Optional[FailedStage] = None
    predecessor_id: Optional[str] = None


# ─── managed_layout helpers ─────────────────────────────────────────────


def insert_layout(conn: sqlite3.Connection, row: ManagedLayoutRow) -> None:
    """Insert a new ``managed_layout`` row."""
    conn.execute(
        """
        INSERT INTO managed_layout (
            id, container_id, template_name, intended_pane_count, state,
            failed_stage, idempotency_key, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.container_id,
            row.template_name,
            row.intended_pane_count,
            row.state.value,
            row.failed_stage.value if row.failed_stage else None,
            row.idempotency_key,
            row.created_at,
            row.updated_at,
        ),
    )


def select_layout(conn: sqlite3.Connection, layout_id: str) -> Optional[ManagedLayoutRow]:
    """Return one layout by id, or ``None`` if not found."""
    cur = conn.execute(
        "SELECT id, container_id, template_name, intended_pane_count, state, "
        "failed_stage, idempotency_key, created_at, updated_at "
        "FROM managed_layout WHERE id = ?",
        (layout_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_layout(row)


def select_layout_by_idempotency_key(
    conn: sqlite3.Connection, container_id: str, idempotency_key: str
) -> Optional[ManagedLayoutRow]:
    """Return the layout matching (container_id, idempotency_key), or ``None``.

    Used by ``service.create_layout`` for the R10 replay semantics.
    """
    cur = conn.execute(
        "SELECT id, container_id, template_name, intended_pane_count, state, "
        "failed_stage, idempotency_key, created_at, updated_at "
        "FROM managed_layout "
        "WHERE container_id = ? AND idempotency_key = ?",
        (container_id, idempotency_key),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_layout(row)


def count_active_layouts(conn: sqlite3.Connection) -> int:
    """Return the number of non-terminal ``managed_layout`` rows.

    Used by ``service.create_layout`` for the FR-025 capacity check.
    "Active" excludes ``removed`` (terminal); ``failed`` and ``creating``
    both count against the 40-layout cap (operator must remove failed
    layouts to free capacity).
    """
    cur = conn.execute(
        "SELECT COUNT(*) FROM managed_layout WHERE state != 'removed'"
    )
    (n,) = cur.fetchone()
    return int(n)


# ─── managed_pane helpers ───────────────────────────────────────────────


def insert_pane(conn: sqlite3.Connection, row: ManagedPaneRow) -> None:
    """Insert a new ``managed_pane`` row."""
    conn.execute(
        """
        INSERT INTO managed_pane (
            id, layout_id, container_id, agent_id, role, capability, label,
            launch_command_ref, tmux_session_name, tmux_pane_index,
            pending_marker_token, state, failed_stage, predecessor_id,
            chain_depth, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.layout_id,
            row.container_id,
            row.agent_id,
            row.role,
            row.capability,
            row.label,
            row.launch_command_ref,
            row.tmux_session_name,
            row.tmux_pane_index,
            row.pending_marker_token,
            row.state.value,
            row.failed_stage.value if row.failed_stage else None,
            row.predecessor_id,
            row.chain_depth,
            row.created_at,
            row.updated_at,
        ),
    )


def select_panes_for_layout(
    conn: sqlite3.Connection, layout_id: str
) -> list[ManagedPaneRow]:
    """Return all panes belonging to a layout, ordered by tmux_pane_index."""
    cur = conn.execute(
        "SELECT id, layout_id, container_id, agent_id, role, capability, label, "
        "launch_command_ref, tmux_session_name, tmux_pane_index, "
        "pending_marker_token, state, failed_stage, predecessor_id, "
        "chain_depth, created_at, updated_at "
        "FROM managed_pane WHERE layout_id = ? "
        "ORDER BY tmux_pane_index ASC",
        (layout_id,),
    )
    return [_row_to_pane(row) for row in cur.fetchall()]


def select_pane(conn: sqlite3.Connection, pane_id: str) -> Optional[ManagedPaneRow]:
    """Return one pane by id, or ``None`` if not found (M5 detail)."""
    cur = conn.execute(
        "SELECT id, layout_id, container_id, agent_id, role, capability, label, "
        "launch_command_ref, tmux_session_name, tmux_pane_index, "
        "pending_marker_token, state, failed_stage, predecessor_id, "
        "chain_depth, created_at, updated_at "
        "FROM managed_pane WHERE id = ?",
        (pane_id,),
    )
    row = cur.fetchone()
    return _row_to_pane(row) if row is not None else None


def select_predecessor_chain(
    conn: sqlite3.Connection, predecessor_id: str
) -> list[ManagedPaneRow]:
    """Walk the ``predecessor_id`` chain from a starting pane (M5).

    Returns the chain in descending chain-depth order (most-recent
    predecessor first). The chain is bounded at 17 hops (one more than
    FR-023's depth=16 cap) as defensive infinite-loop protection — a
    well-formed chain never exceeds 16 entries.
    """
    chain: list[ManagedPaneRow] = []
    current: Optional[str] = predecessor_id
    seen: set[str] = set()
    for _ in range(17):
        if current is None or current in seen:
            break
        seen.add(current)
        row = select_pane(conn, current)
        if row is None:
            break
        chain.append(row)
        current = row.predecessor_id
    return chain


# ─── M2 / M4 list helpers ───────────────────────────────────────────────


_LIST_LIMIT_DEFAULT: int = 50
_LIST_LIMIT_CAP: int = 200


def list_layouts(
    conn: sqlite3.Connection,
    *,
    container_id: Optional[str] = None,
    state: Optional[ManagedState] = None,
    limit: int = _LIST_LIMIT_DEFAULT,
    after: Optional[str] = None,
) -> tuple[list[ManagedLayoutRow], Optional[str]]:
    """Paginated layout listing for ``managed.layout.list`` (M2).

    Ordering: ``(state_priority ASC, created_at DESC, id DESC)`` per
    contracts/managed-methods.md §M2 — operationally-first (creating /
    degraded / ready first, terminal failed / removed last) with the
    most-recent layout breaking state ties, and the row id breaking
    timestamp ties for determinism. ``state_priority`` mapping lives in
    ``state_machine.MANAGED_STATE_PRIORITY``.

    Pagination uses ``id`` as the opaque cursor; ``after`` is the last
    seen ``id`` from the prior page. Returns ``(rows, next_cursor)``
    where ``next_cursor`` is the last row's id if there might be more
    results, else ``None``.

    ``limit`` is clamped to ``[1, 200]`` per FEAT-011's pagination cap
    (inherited from FR-020a).
    """
    limit = max(1, min(int(limit), _LIST_LIMIT_CAP))
    sp_expr = _state_priority_sql_expr("state")
    where: list[str] = []
    params: list[object] = []
    if container_id is not None:
        where.append("container_id = ?")
        params.append(container_id)
    if state is not None:
        where.append("state = ?")
        params.append(state.value)
    if after is not None:
        # Cursor: skip rows that come at or before the cursor row in the
        # ORDER BY direction `(sp ASC, created_at DESC, id DESC)`. Encoded
        # as three OR-clauses (SQLite tuple comparison doesn't support
        # mixed-direction ASC/DESC). The cursor row's (sp, created_at, id)
        # are looked up via subqueries on the after id.
        sp_cursor = _state_priority_sql_expr(
            "(SELECT state FROM managed_layout WHERE id = ?)"
        )
        where.append(
            f"({sp_expr} > {sp_cursor}"
            f" OR ({sp_expr} = {sp_cursor}"
            f"     AND created_at < (SELECT created_at FROM managed_layout WHERE id = ?))"
            f" OR ({sp_expr} = {sp_cursor}"
            f"     AND created_at = (SELECT created_at FROM managed_layout WHERE id = ?)"
            f"     AND id < ?))"
        )
        # The sp_cursor expression embeds the `?` placeholder for the
        # cursor id; we need it 4× because sp_cursor is referenced 4
        # times above. Then created_at appears 2× and id appears 1×.
        params.extend([after, after, after, after, after, after, after])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    cur = conn.execute(
        f"SELECT id, container_id, template_name, intended_pane_count, state, "
        f"failed_stage, idempotency_key, created_at, updated_at "
        f"FROM managed_layout"
        + where_sql
        + f" ORDER BY {sp_expr} ASC, created_at DESC, id DESC LIMIT ?",
        (*params, limit + 1),
    )
    rows = cur.fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    layouts = [_row_to_layout(r) for r in rows]
    next_cursor = layouts[-1].id if has_more and layouts else None
    return layouts, next_cursor


def list_panes(
    conn: sqlite3.Connection,
    *,
    container_id: Optional[str] = None,
    layout_id: Optional[str] = None,
    state: Optional[ManagedState] = None,
    limit: int = _LIST_LIMIT_DEFAULT,
    after: Optional[str] = None,
) -> tuple[list[ManagedPaneRow], Optional[str]]:
    """Paginated pane listing for ``managed.pane.list`` (M4).

    Ordering: ``(state_priority ASC, layout_id ASC, tmux_pane_index ASC,
    id ASC)`` — operationally-first by state per contracts/managed-methods.md
    §M4 "Same shape as M2" + the M4-specific ``(layout_id, tmux_pane_index)``
    secondary ordering. ``state_priority`` mapping lives in
    ``state_machine.MANAGED_STATE_PRIORITY``. Cursor is ``id``.
    """
    limit = max(1, min(int(limit), _LIST_LIMIT_CAP))
    sp_expr = _state_priority_sql_expr("state")
    where: list[str] = []
    params: list[object] = []
    if container_id is not None:
        where.append("container_id = ?")
        params.append(container_id)
    if layout_id is not None:
        where.append("layout_id = ?")
        params.append(layout_id)
    if state is not None:
        where.append("state = ?")
        params.append(state.value)
    if after is not None:
        # ORDER BY direction is all-ASC across (sp, layout_id, tmux_pane_index, id),
        # so tuple comparison works directly.
        sp_cursor = _state_priority_sql_expr(
            "(SELECT state FROM managed_pane WHERE id = ?)"
        )
        where.append(
            f"({sp_expr}, layout_id, tmux_pane_index, id) > "
            f"({sp_cursor}, "
            f"(SELECT layout_id FROM managed_pane WHERE id = ?), "
            f"(SELECT tmux_pane_index FROM managed_pane WHERE id = ?), "
            f"(SELECT id FROM managed_pane WHERE id = ?))"
        )
        params.extend([after, after, after, after])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    cur = conn.execute(
        f"SELECT id, layout_id, container_id, agent_id, role, capability, label, "
        f"launch_command_ref, tmux_session_name, tmux_pane_index, "
        f"pending_marker_token, state, failed_stage, predecessor_id, "
        f"chain_depth, created_at, updated_at "
        f"FROM managed_pane"
        + where_sql
        + f" ORDER BY {sp_expr} ASC, layout_id ASC, tmux_pane_index ASC, id ASC LIMIT ?",
        (*params, limit + 1),
    )
    rows = cur.fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    panes = [_row_to_pane(r) for r in rows]
    next_cursor = panes[-1].id if has_more and panes else None
    return panes, next_cursor


def count_ready_panes_for_layout(
    conn: sqlite3.Connection, layout_id: str
) -> int:
    """Return the count of ``ready``-state panes for a layout (M2 summary)."""
    cur = conn.execute(
        "SELECT COUNT(*) FROM managed_pane WHERE layout_id = ? AND state = 'ready'",
        (layout_id,),
    )
    (n,) = cur.fetchone()
    return int(n)


# ─── Background spawn pipeline mutation helpers (T029 / T030) ───────────


def update_pane_state(
    conn: sqlite3.Connection,
    pane_id: str,
    *,
    state: ManagedState,
    failed_stage: Optional[FailedStage] = None,
    agent_id: Optional[str] = None,
    clear_marker: bool = False,
    now: str,
) -> None:
    """Mutate a ``managed_pane`` row's state-track fields.

    Used by the background spawn pipeline to transition panes from
    ``creating`` → ``ready`` / ``degraded`` / ``failed``. Per the data-
    model CHECK constraint ``pending_marker_token IS NULL OR
    state = 'creating'``, callers MUST set ``clear_marker=True`` when
    transitioning to any non-``creating`` state. This helper enforces
    that invariant by raising ``ValueError`` on mismatched usage.

    ``agent_id`` is set when the FEAT-006 registration succeeded.
    ``failed_stage`` is set per FR-013's closed enum.
    """
    if state != ManagedState.CREATING and not clear_marker:
        raise ValueError(
            f"transition to {state.value!r} requires clear_marker=True "
            "(CHECK constraint pending_marker_token IS NULL OR state = 'creating')"
        )
    sets = ["state = ?", "updated_at = ?"]
    params: list[object] = [state.value, now]
    if clear_marker:
        sets.append("pending_marker_token = NULL")
    if failed_stage is not None:
        sets.append("failed_stage = ?")
        params.append(failed_stage.value)
    if agent_id is not None:
        sets.append("agent_id = ?")
        params.append(agent_id)
    params.append(pane_id)
    conn.execute(
        f"UPDATE managed_pane SET {', '.join(sets)} WHERE id = ?",
        tuple(params),
    )


def select_non_terminal_layouts(
    conn: sqlite3.Connection,
) -> list[ManagedLayoutRow]:
    """Return every layout in a non-terminal state (creating / ready /
    degraded / failed) for the boot-time recovery reconcile (T046).

    ``removed`` is excluded — terminal layouts don't participate in
    reconcile (their panes are archived).
    """
    cur = conn.execute(
        "SELECT id, container_id, template_name, intended_pane_count, state, "
        "failed_stage, idempotency_key, created_at, updated_at "
        "FROM managed_layout "
        "WHERE state != 'removed' "
        "ORDER BY container_id ASC, id ASC"
    )
    return [_row_to_layout(r) for r in cur.fetchall()]


def select_non_terminal_panes_for_container(
    conn: sqlite3.Connection, container_id: str
) -> list[ManagedPaneRow]:
    """Return every pane in container ``container_id`` in a non-terminal
    state (creating / ready / degraded). The reconcile groups panes by
    container so the tmux list-panes RPC is issued once per container.

    ``failed`` is excluded too because already-failed rows are not
    reattach candidates — they were already in a terminal-from-tmux
    standpoint. The only exception is FR-022 sweep targets, which
    Phase 6 T050 handles separately.
    """
    cur = conn.execute(
        "SELECT id, layout_id, container_id, agent_id, role, capability, label, "
        "launch_command_ref, tmux_session_name, tmux_pane_index, "
        "pending_marker_token, state, failed_stage, predecessor_id, "
        "chain_depth, created_at, updated_at "
        "FROM managed_pane "
        "WHERE container_id = ? "
        "AND state IN ('creating', 'ready', 'degraded') "
        "ORDER BY tmux_session_name ASC, tmux_pane_index ASC",
        (container_id,),
    )
    return [_row_to_pane(r) for r in cur.fetchall()]


def clear_pending_marker_token(
    conn: sqlite3.Connection, pane_id: str, *, now: str
) -> None:
    """Set ``managed_pane.pending_marker_token = NULL`` for a single row.

    Used by the recovery reconcile (T046) to drop stale markers for
    rows that the reconcile transitions to a non-``creating`` state.
    Does not touch state — caller has already done that via
    ``update_pane_state(clear_marker=True, ...)`` or equivalent.
    """
    conn.execute(
        "UPDATE managed_pane SET pending_marker_token = NULL, updated_at = ? "
        "WHERE id = ?",
        (now, pane_id),
    )


def update_layout_state(
    conn: sqlite3.Connection,
    layout_id: str,
    *,
    state: ManagedState,
    failed_stage: Optional[FailedStage] = None,
    now: str,
) -> None:
    """Mutate ``managed_layout`` state + failed_stage + updated_at.

    Used by the background spawn pipeline to write the aggregate layout
    state derived from pane outcomes (state_machine.aggregate_layout_state).
    """
    sets = ["state = ?", "updated_at = ?"]
    params: list[object] = [state.value, now]
    if failed_stage is not None:
        sets.append("failed_stage = ?")
        params.append(failed_stage.value)
    else:
        # Explicitly clear failed_stage when the layout aggregates to a
        # non-failed state — otherwise a transient ``failed`` recorded
        # earlier could linger on a recovered layout.
        sets.append("failed_stage = NULL")
    params.append(layout_id)
    conn.execute(
        f"UPDATE managed_layout SET {', '.join(sets)} WHERE id = ?",
        tuple(params),
    )


# ─── internal row converters ────────────────────────────────────────────


def _row_to_layout(row: tuple) -> ManagedLayoutRow:
    (
        id_,
        container_id,
        template_name,
        intended_pane_count,
        state,
        failed_stage,
        idempotency_key,
        created_at,
        updated_at,
    ) = row
    return ManagedLayoutRow(
        id=id_,
        container_id=container_id,
        template_name=template_name,
        intended_pane_count=int(intended_pane_count),
        state=ManagedState(state),
        failed_stage=FailedStage(failed_stage) if failed_stage else None,
        idempotency_key=idempotency_key,
        created_at=created_at,
        updated_at=updated_at,
    )


def _row_to_pane(row: tuple) -> ManagedPaneRow:
    (
        id_,
        layout_id,
        container_id,
        agent_id,
        role,
        capability,
        label,
        launch_command_ref,
        tmux_session_name,
        tmux_pane_index,
        pending_marker_token,
        state,
        failed_stage,
        predecessor_id,
        chain_depth,
        created_at,
        updated_at,
    ) = row
    return ManagedPaneRow(
        id=id_,
        layout_id=layout_id,
        container_id=container_id,
        agent_id=agent_id,
        role=role,
        capability=capability,
        label=label,
        launch_command_ref=launch_command_ref,
        tmux_session_name=tmux_session_name,
        tmux_pane_index=int(tmux_pane_index),
        pending_marker_token=pending_marker_token,
        state=ManagedState(state),
        failed_stage=FailedStage(failed_stage) if failed_stage else None,
        predecessor_id=predecessor_id,
        chain_depth=int(chain_depth),
        created_at=created_at,
        updated_at=updated_at,
    )
