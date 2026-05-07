"""Typed dataclasses + read/write helpers for the FEAT-006 ``agents`` table.

Helpers accept an open ``sqlite3.Connection`` and do NOT begin or commit
transactions on their own. The :class:`agenttower.agents.service.AgentService`
owns the transaction boundary that wraps each ``register_agent`` /
``set_role`` / ``set_label`` / ``set_capability`` call.

This module is pure data-access: no validation, no mutex acquisition,
no business rules. Validators live in
:mod:`agenttower.agents.validation`; mutexes in
:mod:`agenttower.agents.mutex`; orchestration in
:mod:`agenttower.agents.service`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..agents.mutex import PaneCompositeKey


@dataclass(frozen=True)
class AgentRecord:
    """One row of the ``agents`` table, post-sanitization (data-model §4.1)."""

    agent_id: str
    container_id: str
    tmux_socket_path: str
    tmux_session_name: str
    tmux_window_index: int
    tmux_pane_index: int
    tmux_pane_id: str
    role: str
    capability: str
    label: str
    project_path: str
    parent_agent_id: str | None
    effective_permissions: dict[str, Any]
    created_at: str
    last_registered_at: str
    last_seen_at: str | None
    active: bool

    @property
    def composite_key(self) -> PaneCompositeKey:
        return (
            self.container_id,
            self.tmux_socket_path,
            self.tmux_session_name,
            self.tmux_window_index,
            self.tmux_pane_index,
            self.tmux_pane_id,
        )


_AGENT_COLUMNS = (
    "agent_id, container_id, tmux_socket_path, tmux_session_name, "
    "tmux_window_index, tmux_pane_index, tmux_pane_id, role, capability, "
    "label, project_path, parent_agent_id, effective_permissions, "
    "created_at, last_registered_at, last_seen_at, active"
)


def _row_to_agent(row: tuple) -> AgentRecord:
    return AgentRecord(
        agent_id=row[0],
        container_id=row[1],
        tmux_socket_path=row[2],
        tmux_session_name=row[3],
        tmux_window_index=int(row[4]),
        tmux_pane_index=int(row[5]),
        tmux_pane_id=row[6],
        role=row[7],
        capability=row[8],
        label=row[9],
        project_path=row[10],
        parent_agent_id=row[11],
        effective_permissions=json.loads(row[12]),
        created_at=row[13],
        last_registered_at=row[14],
        last_seen_at=row[15],
        active=bool(row[16]),
    )


def insert_agent(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    pane_key: PaneCompositeKey,
    role: str,
    capability: str,
    label: str,
    project_path: str,
    parent_agent_id: str | None,
    effective_permissions_json: str,
    created_at: str,
    last_registered_at: str,
    active: bool,
) -> None:
    """INSERT a new ``agents`` row (callers MUST hold a transaction).

    ``last_seen_at`` is set to NULL on creation per data-model §2.1 — the
    FEAT-004 reconciliation transaction populates it on the next scan
    that observes the bound pane (FR-009a).
    """
    conn.execute(
        f"""
        INSERT INTO agents ({_AGENT_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_id,
            pane_key[0],
            pane_key[1],
            pane_key[2],
            int(pane_key[3]),
            int(pane_key[4]),
            pane_key[5],
            role,
            capability,
            label,
            project_path,
            parent_agent_id,
            effective_permissions_json,
            created_at,
            last_registered_at,
            None,
            1 if active else 0,
        ),
    )


def update_agent_mutable_fields(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    role: str,
    capability: str,
    label: str,
    project_path: str,
    effective_permissions_json: str,
    last_registered_at: str,
    active: bool,
) -> None:
    """UPDATE the mutable fields on an existing ``agents`` row.

    ``created_at``, ``parent_agent_id``, ``last_seen_at``, and the pane
    composite key MUST NOT be modified here (FR-002, FR-009a). Callers
    MUST hold a transaction.
    """
    conn.execute(
        """
        UPDATE agents SET
            role = ?,
            capability = ?,
            label = ?,
            project_path = ?,
            effective_permissions = ?,
            last_registered_at = ?,
            active = ?
        WHERE agent_id = ?
        """,
        (
            role,
            capability,
            label,
            project_path,
            effective_permissions_json,
            last_registered_at,
            1 if active else 0,
            agent_id,
        ),
    )


def update_agent_role(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    role: str,
    effective_permissions_json: str,
) -> None:
    """UPDATE only the role + recomputed effective_permissions for set_role."""
    conn.execute(
        "UPDATE agents SET role = ?, effective_permissions = ? WHERE agent_id = ?",
        (role, effective_permissions_json, agent_id),
    )


def update_agent_label(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    label: str,
) -> None:
    conn.execute("UPDATE agents SET label = ? WHERE agent_id = ?", (label, agent_id))


def update_agent_capability(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    capability: str,
) -> None:
    conn.execute(
        "UPDATE agents SET capability = ? WHERE agent_id = ?",
        (capability, agent_id),
    )


# Each PaneCompositeKey contributes 6 placeholders. SQLite's default
# ``SQLITE_MAX_VARIABLE_NUMBER`` is 999 on builds older than 3.32 (and
# 32766 on newer ones — we don't want to bet on the runtime version).
# 100 keys × 6 = 600 placeholders leaves headroom for an additional
# scalar in the UPDATE (``now_iso``).
_PANE_KEY_BATCH = 100

_PANE_KEY_PREDICATE = (
    "(container_id = ? AND tmux_socket_path = ? AND tmux_session_name = ? "
    "AND tmux_window_index = ? AND tmux_pane_index = ? AND tmux_pane_id = ?)"
)


def _chunk(items: list[Any], size: int) -> Iterable[list[Any]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def update_last_seen_at(
    conn: sqlite3.Connection,
    *,
    pane_keys: Iterable[PaneCompositeKey],
    now_iso: str,
) -> None:
    """UPDATE ``last_seen_at`` on every agent bound to a pane in *pane_keys*.

    Used by the FEAT-004 pane reconciliation transaction (FR-009a /
    Clarifications Q2). Caller MUST hold a transaction. *pane_keys* is
    chunked at ``_PANE_KEY_BATCH`` per UPDATE so a large scan never
    trips SQLite's ``SQLITE_MAX_VARIABLE_NUMBER`` ceiling at runtime.
    """
    keys = list(pane_keys)
    if not keys:
        return
    for batch in _chunk(keys, _PANE_KEY_BATCH):
        sql = (
            "UPDATE agents SET last_seen_at = ? WHERE "
            + " OR ".join([_PANE_KEY_PREDICATE] * len(batch))
        )
        params: list[Any] = [now_iso]
        for key in batch:
            params.extend(key)
        conn.execute(sql, params)


def cascade_agents_active_from_pane(
    conn: sqlite3.Connection,
    *,
    pane_keys: Iterable[PaneCompositeKey],
) -> None:
    """Set ``agents.active = 0`` for every agent bound to a pane in *pane_keys*.

    Used by the FEAT-004 reconciliation when a pane transitions
    active→inactive (FR-009). Caller MUST hold a transaction. Same
    batching strategy as :func:`update_last_seen_at`.
    """
    keys = list(pane_keys)
    if not keys:
        return
    for batch in _chunk(keys, _PANE_KEY_BATCH):
        sql = (
            "UPDATE agents SET active = 0 WHERE "
            + " OR ".join([_PANE_KEY_PREDICATE] * len(batch))
        )
        params: list[Any] = []
        for key in batch:
            params.extend(key)
        conn.execute(sql, params)


def select_agent_by_id(
    conn: sqlite3.Connection, *, agent_id: str
) -> AgentRecord | None:
    row = conn.execute(
        f"SELECT {_AGENT_COLUMNS} FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    return _row_to_agent(row) if row is not None else None


def select_agent_by_pane_key(
    conn: sqlite3.Connection, *, pane_key: PaneCompositeKey
) -> AgentRecord | None:
    row = conn.execute(
        f"SELECT {_AGENT_COLUMNS} FROM agents WHERE "
        "container_id = ? AND tmux_socket_path = ? AND tmux_session_name = ? "
        "AND tmux_window_index = ? AND tmux_pane_index = ? AND tmux_pane_id = ?",
        pane_key,
    ).fetchone()
    return _row_to_agent(row) if row is not None else None


def select_active_for_role_and_container(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
) -> tuple[bool, bool | None] | None:
    """Atomic re-check helper for FR-011 master-promotion.

    Returns ``(agent_active, container_active)`` where *container_active*
    is ``True`` / ``False`` based on the bound container's ``active``
    column, or ``None`` if no container row exists. Returns ``None`` for
    the whole tuple if the agent does not exist.
    """
    row = conn.execute(
        """
        SELECT agents.active, containers.active
        FROM agents
        LEFT JOIN containers ON containers.container_id = agents.container_id
        WHERE agents.agent_id = ?
        """,
        (agent_id,),
    ).fetchone()
    if row is None:
        return None
    agent_active = bool(row[0])
    container_active: bool | None = None
    if row[1] is not None:
        container_active = bool(row[1])
    return (agent_active, container_active)


# Mirror the column list of the agents_active_order index exactly so the
# planner can satisfy the sort directly from it. SQLite's default ASC
# sorts NULLs first, so ``parent_agent_id ASC`` already gives the
# documented "NULLS FIRST" semantics without the redundant
# ``(parent_agent_id IS NULL) DESC`` expression which defeats the index.
_LIST_ORDER_BY = (
    "ORDER BY active DESC, container_id ASC, "
    "parent_agent_id ASC, label ASC, agent_id ASC"
)


def list_agents(
    conn: sqlite3.Connection,
    *,
    role: list[str] | None = None,
    container_id: str | None = None,
    active_only: bool = False,
    parent_agent_id: str | None = None,
) -> list[AgentRecord]:
    """Return rows in the FR-025 deterministic order with AND-composed filters.

    *container_id* is matched as an exact id OR as a 12-char short prefix
    (FR-026). All other filter values are matched verbatim
    (case-sensitive per Clarifications Q2).
    """
    where: list[str] = []
    params: list[Any] = []
    if active_only:
        where.append("active = 1")
    if role:
        placeholders = ",".join("?" * len(role))
        where.append(f"role IN ({placeholders})")
        params.extend(role)
    if container_id is not None:
        if len(container_id) == 64:
            where.append("container_id = ?")
            params.append(container_id)
        else:
            # 12-char short prefix match (FR-026).
            where.append("substr(container_id, 1, ?) = ?")
            params.append(len(container_id))
            params.append(container_id)
    if parent_agent_id is not None:
        where.append("parent_agent_id = ?")
        params.append(parent_agent_id)
    where_clause = "WHERE " + " AND ".join(where) if where else ""
    sql = f"SELECT {_AGENT_COLUMNS} FROM agents {where_clause} {_LIST_ORDER_BY}"
    return [_row_to_agent(r) for r in conn.execute(sql, params).fetchall()]
