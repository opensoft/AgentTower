"""FEAT-010 routes-table CRUD (data-model.md §1).

Pure SQLite functions; callers open ``BEGIN IMMEDIATE`` if they want
write atomicity (DAO functions do NOT start a transaction).

The :class:`RouteRow` dataclass mirrors the SQLite schema exactly.
Identity / template / cursor fields are read by the routing worker on
every cycle (FR-010 / FR-042); ``enabled`` is the only field that
mutates through normal operation (via :func:`update_enabled`).

Functions:

* :func:`insert_route` — INSERT one route (FR-001, FR-002). Returns
  the row's ``route_id``.
* :func:`list_routes` — SELECT ordered by ``(created_at ASC,
  route_id ASC)`` (FR-042). Optional ``enabled_only`` filter.
* :func:`select_route` — point lookup by ``route_id`` (FR-047);
  returns ``None`` on miss.
* :func:`update_enabled` — flip the ``enabled`` flag idempotently
  (FR-009). Returns ``True`` iff the state changed.
* :func:`delete_route` — hard-delete (FR-003). Returns ``True`` iff
  a row was removed. Queue rows with this ``route_id`` survive as
  orphan references.
* :func:`advance_cursor` — UPDATE the ``last_consumed_event_id``
  monotonically (FR-012). Cursor MUST only increase.

No business logic, no audit emission, no JSON shaping. Higher layers
(routes_service.py, worker.py) coordinate audit + permission + the
cursor-advance-with-enqueue transaction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final, Iterable


# ──────────────────────────────────────────────────────────────────────
# Row dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouteRow:
    """One ``routes`` row, as read by the DAO and consumed by the routes
    service / worker.

    Mirrors the SQLite schema (data-model.md §1).
    """

    route_id: str
    event_type: str
    source_scope_kind: str  # 'any' | 'agent_id' | 'role'
    source_scope_value: str | None  # NULL when kind='any'
    target_rule: str  # 'explicit' | 'source' | 'role'
    target_value: str | None  # NULL when target_rule='source'
    master_rule: str  # 'auto' | 'explicit'
    master_value: str | None  # NULL when master_rule='auto'
    template: str
    enabled: bool
    last_consumed_event_id: int
    created_at: str  # ISO-8601 ms UTC
    updated_at: str  # ISO-8601 ms UTC
    created_by_agent_id: str | None


# ──────────────────────────────────────────────────────────────────────
# Column ordering (single source of truth for INSERT/SELECT)
# ──────────────────────────────────────────────────────────────────────


_COLUMNS: Final[tuple[str, ...]] = (
    "route_id",
    "event_type",
    "source_scope_kind",
    "source_scope_value",
    "target_rule",
    "target_value",
    "master_rule",
    "master_value",
    "template",
    "enabled",
    "last_consumed_event_id",
    "created_at",
    "updated_at",
    "created_by_agent_id",
)
_SELECT_COLS: Final[str] = ", ".join(_COLUMNS)


def _row_to_route_row(row: tuple) -> RouteRow:
    """Decode a SELECT result tuple into a :class:`RouteRow`."""
    return RouteRow(
        route_id=row[0],
        event_type=row[1],
        source_scope_kind=row[2],
        source_scope_value=row[3],
        target_rule=row[4],
        target_value=row[5],
        master_rule=row[6],
        master_value=row[7],
        template=row[8],
        enabled=bool(row[9]),
        last_consumed_event_id=int(row[10]),
        created_at=row[11],
        updated_at=row[12],
        created_by_agent_id=row[13],
    )


# ──────────────────────────────────────────────────────────────────────
# Mutations
# ──────────────────────────────────────────────────────────────────────


def insert_route(conn: sqlite3.Connection, row: RouteRow) -> str:
    """INSERT one route. Returns the row's ``route_id``.

    Caller MUST have opened the transaction (typically
    ``BEGIN IMMEDIATE``); this function does NOT commit.

    Raises :class:`sqlite3.IntegrityError` on PK collision or CHECK
    violation. The routes-service layer translates those to
    :class:`RouteCreationFailed`.
    """
    conn.execute(
        f"INSERT INTO routes ({_SELECT_COLS}) "
        f"VALUES ({', '.join('?' * len(_COLUMNS))})",
        (
            row.route_id,
            row.event_type,
            row.source_scope_kind,
            row.source_scope_value,
            row.target_rule,
            row.target_value,
            row.master_rule,
            row.master_value,
            row.template,
            1 if row.enabled else 0,
            int(row.last_consumed_event_id),
            row.created_at,
            row.updated_at,
            row.created_by_agent_id,
        ),
    )
    return row.route_id


def update_enabled(
    conn: sqlite3.Connection,
    route_id: str,
    *,
    enabled: bool,
    updated_at: str,
) -> bool:
    """Flip the ``enabled`` flag idempotently (FR-009).

    Returns ``True`` iff the state actually changed (used by the
    service layer to decide whether to emit a ``route_updated`` audit
    entry — idempotent no-op MUST NOT audit per FR-009).

    Returns ``False`` if the route does not exist OR if the route is
    already in the requested state. The service layer distinguishes
    "not found" from "already in state" via a separate
    :func:`select_route` call.
    """
    cur = conn.execute(
        "UPDATE routes SET enabled = ?, updated_at = ? "
        "WHERE route_id = ? AND enabled != ?",
        (1 if enabled else 0, updated_at, route_id, 1 if enabled else 0),
    )
    return cur.rowcount > 0


def delete_route(conn: sqlite3.Connection, route_id: str) -> bool:
    """Hard-delete one route (FR-003). Returns ``True`` if a row was
    removed.

    Queue rows whose ``route_id`` matches this id remain intact (orphan
    references per FR-003 / Edge Cases) — the foreign-key-less
    relationship in the schema is intentional.
    """
    cur = conn.execute("DELETE FROM routes WHERE route_id = ?", (route_id,))
    return cur.rowcount > 0


def advance_cursor(
    conn: sqlite3.Connection,
    route_id: str,
    event_id: int,
    *,
    updated_at: str,
) -> None:
    """Monotonically advance ``last_consumed_event_id`` (FR-012).

    Uses ``WHERE last_consumed_event_id < ?`` to enforce monotonicity
    at the storage layer — a buggy caller cannot accidentally move the
    cursor backwards. Silent no-op when the cursor is already at or
    beyond ``event_id`` (defensive; should not happen under correct
    worker operation).
    """
    conn.execute(
        "UPDATE routes "
        "SET last_consumed_event_id = ?, updated_at = ? "
        "WHERE route_id = ? AND last_consumed_event_id < ?",
        (int(event_id), updated_at, route_id, int(event_id)),
    )


# ──────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────


def select_route(conn: sqlite3.Connection, route_id: str) -> RouteRow | None:
    """Point lookup by ``route_id`` (FR-047). Returns ``None`` on miss."""
    row = conn.execute(
        f"SELECT {_SELECT_COLS} FROM routes WHERE route_id = ?",
        (route_id,),
    ).fetchone()
    return _row_to_route_row(row) if row else None


def list_routes(
    conn: sqlite3.Connection,
    *,
    enabled_only: bool = False,
) -> list[RouteRow]:
    """SELECT all routes ordered by ``(created_at ASC, route_id ASC)``
    (FR-042). When ``enabled_only=True``, restrict to
    ``enabled = 1`` rows.

    Order is the same one the routing worker uses to process routes
    per cycle, so the worker can iterate ``list_routes(enabled_only=
    True)`` directly.
    """
    if enabled_only:
        sql = (
            f"SELECT {_SELECT_COLS} FROM routes "
            f"WHERE enabled = 1 "
            f"ORDER BY created_at ASC, route_id ASC"
        )
        params: tuple = ()
    else:
        sql = (
            f"SELECT {_SELECT_COLS} FROM routes "
            f"ORDER BY created_at ASC, route_id ASC"
        )
        params = ()
    return [_row_to_route_row(r) for r in conn.execute(sql, params).fetchall()]


def select_max_event_id(conn: sqlite3.Connection) -> int:
    """Return ``MAX(events.event_id) OR 0`` (FR-002 cursor-at-creation).

    Lives in this module (rather than ``events.dao``) because it's a
    routes-service concern — used only by ``routes_service.add_route``
    to initialize a new route's cursor at the current event head.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(event_id), 0) FROM events"
    ).fetchone()
    return int(row[0]) if row else 0
