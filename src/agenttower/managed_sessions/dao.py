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

from .state_machine import FailedStage, ManagedState


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
