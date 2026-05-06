"""Typed dataclasses + read/write helpers for FEAT-004 SQLite tables.

Helpers accept an open ``sqlite3.Connection`` and do NOT begin or commit
transactions on their own (data-model.md §5). The PaneDiscoveryService owns
the transaction boundary that wraps a full pane scan reconciliation
(FR-024).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any


# Composite primary key for the ``panes`` table (data-model §3.7).
PaneCompositeKey = tuple[str, str, str, int, int, str]


@dataclass(frozen=True)
class PaneRow:
    """One row of the ``panes`` table, post-sanitization."""

    container_id: str
    tmux_socket_path: str
    tmux_session_name: str
    tmux_window_index: int
    tmux_pane_index: int
    tmux_pane_id: str
    container_name: str
    container_user: str
    pane_pid: int
    pane_tty: str
    pane_current_command: str
    pane_current_path: str
    pane_title: str
    pane_active: bool
    active: bool
    first_seen_at: str
    last_scanned_at: str

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


@dataclass(frozen=True)
class PriorPaneRow:
    """Reduced view of a ``panes`` row used by the reconciler."""

    active: bool
    first_seen_at: str


@dataclass(frozen=True)
class PaneUpsert:
    """A full-row write produced by the reconciler (data-model §3.6)."""

    container_id: str
    tmux_socket_path: str
    tmux_session_name: str
    tmux_window_index: int
    tmux_pane_index: int
    tmux_pane_id: str
    container_name: str
    container_user: str
    pane_pid: int
    pane_tty: str
    pane_current_command: str
    pane_current_path: str
    pane_title: str
    pane_active: bool
    last_scanned_at: str

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


@dataclass(frozen=True)
class PaneTruncationNote:
    container_id: str
    tmux_socket_path: str
    tmux_pane_id: str
    field: str
    original_len: int


@dataclass(frozen=True)
class PerScopeError:
    container_id: str
    tmux_socket_path: str | None
    error_code: str
    error_message: str
    pane_truncations: tuple[PaneTruncationNote, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PaneScanRow:
    scan_id: str
    started_at: str
    completed_at: str
    status: str
    containers_scanned: int
    sockets_scanned: int
    panes_seen: int
    panes_newly_active: int
    panes_reconciled_inactive: int
    containers_skipped_inactive: int
    containers_tmux_unavailable: int
    error_code: str | None
    error_message: str | None
    error_details: tuple[PerScopeError, ...]


@dataclass(frozen=True)
class PaneReconcileWriteSet:
    upserts: list[PaneUpsert] = field(default_factory=list)
    touch_only: list[PaneCompositeKey] = field(default_factory=list)
    inactivate: list[PaneCompositeKey] = field(default_factory=list)
    pane_truncations: list[PaneTruncationNote] = field(default_factory=list)
    panes_seen: int = 0
    panes_newly_active: int = 0
    panes_reconciled_inactive: int = 0
    containers_skipped_inactive: int = 0
    containers_tmux_unavailable: int = 0


_PANE_COLUMNS = (
    "container_id, tmux_socket_path, tmux_session_name, tmux_window_index, "
    "tmux_pane_index, tmux_pane_id, container_name, container_user, pane_pid, "
    "pane_tty, pane_current_command, pane_current_path, pane_title, pane_active, "
    "active, first_seen_at, last_scanned_at"
)


def _row_to_pane(row: tuple) -> PaneRow:
    return PaneRow(
        container_id=row[0],
        tmux_socket_path=row[1],
        tmux_session_name=row[2],
        tmux_window_index=int(row[3]),
        tmux_pane_index=int(row[4]),
        tmux_pane_id=row[5],
        container_name=row[6],
        container_user=row[7],
        pane_pid=int(row[8]),
        pane_tty=row[9],
        pane_current_command=row[10],
        pane_current_path=row[11],
        pane_title=row[12],
        pane_active=bool(row[13]),
        active=bool(row[14]),
        first_seen_at=row[15],
        last_scanned_at=row[16],
    )


def select_all_panes(conn: sqlite3.Connection) -> dict[PaneCompositeKey, PriorPaneRow]:
    """Return every ``panes`` row indexed by composite key (data-model §5)."""
    cursor = conn.execute(
        "SELECT container_id, tmux_socket_path, tmux_session_name, "
        "tmux_window_index, tmux_pane_index, tmux_pane_id, active, first_seen_at "
        "FROM panes"
    )
    out: dict[PaneCompositeKey, PriorPaneRow] = {}
    for r in cursor.fetchall():
        key: PaneCompositeKey = (r[0], r[1], r[2], int(r[3]), int(r[4]), r[5])
        out[key] = PriorPaneRow(active=bool(r[6]), first_seen_at=r[7])
    return out


_LIST_ORDER_BY = (
    "ORDER BY active DESC, container_id ASC, tmux_socket_path ASC, "
    "tmux_session_name ASC, tmux_window_index ASC, tmux_pane_index ASC"
)


def select_panes_for_listing(
    conn: sqlite3.Connection,
    *,
    active_only: bool = False,
    container_filter: str | None = None,
) -> list[PaneRow]:
    """Return rows in the deterministic FR-016 order, optionally filtered.

    ``container_filter`` resolves on the daemon side (data-model §6 note 4):
    a 64-char hex argument is matched against ``panes.container_id``;
    otherwise the value is matched against ``containers.name`` and the
    resulting id set is intersected with ``panes.container_id``.

    Defensive: only panes whose ``container_id`` is present in
    ``containers`` are returned (orphan-row safety; contracts/socket-api.md §4.3).
    """
    where: list[str] = ["panes.container_id IN (SELECT container_id FROM containers)"]
    params: list[Any] = []
    if active_only:
        where.append("panes.active = 1")
    if container_filter is not None:
        if _looks_like_container_id(container_filter):
            where.append("panes.container_id = ?")
            params.append(container_filter)
        else:
            where.append(
                "panes.container_id IN (SELECT container_id FROM containers WHERE name = ?)"
            )
            params.append(container_filter)
    sql = f"SELECT {_PANE_COLUMNS} FROM panes WHERE {' AND '.join(where)} {_LIST_ORDER_BY}"
    return [_row_to_pane(r) for r in conn.execute(sql, params).fetchall()]


def _looks_like_container_id(value: str) -> bool:
    """Return True if *value* matches the 64-char hex container-id shape."""
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def apply_pane_reconcile_writeset(
    conn: sqlite3.Connection,
    *,
    write_set: PaneReconcileWriteSet,
    now_iso: str,
) -> None:
    """Apply upserts / touch-only / inactivate within an active transaction.

    The caller MUST hold a transaction (typically ``BEGIN IMMEDIATE``); this
    helper does not begin or commit.
    """
    for upsert in write_set.upserts:
        conn.execute(
            f"""
            INSERT INTO panes ({_PANE_COLUMNS})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(container_id, tmux_socket_path, tmux_session_name,
                        tmux_window_index, tmux_pane_index, tmux_pane_id) DO UPDATE SET
                container_name = excluded.container_name,
                container_user = excluded.container_user,
                pane_pid = excluded.pane_pid,
                pane_tty = excluded.pane_tty,
                pane_current_command = excluded.pane_current_command,
                pane_current_path = excluded.pane_current_path,
                pane_title = excluded.pane_title,
                pane_active = excluded.pane_active,
                active = 1,
                last_scanned_at = excluded.last_scanned_at
            """,
            (
                upsert.container_id,
                upsert.tmux_socket_path,
                upsert.tmux_session_name,
                upsert.tmux_window_index,
                upsert.tmux_pane_index,
                upsert.tmux_pane_id,
                upsert.container_name,
                upsert.container_user,
                upsert.pane_pid,
                upsert.pane_tty,
                upsert.pane_current_command,
                upsert.pane_current_path,
                upsert.pane_title,
                1 if upsert.pane_active else 0,
                1,
                upsert.last_scanned_at,
                upsert.last_scanned_at,
            ),
        )
    if write_set.touch_only:
        _execute_composite_keys_update(
            conn,
            "UPDATE panes SET last_scanned_at = ? WHERE ",
            keys=write_set.touch_only,
            now_iso=now_iso,
        )
    if write_set.inactivate:
        _execute_composite_keys_update(
            conn,
            "UPDATE panes SET active = 0, last_scanned_at = ? WHERE ",
            keys=write_set.inactivate,
            now_iso=now_iso,
        )


def _execute_composite_keys_update(
    conn: sqlite3.Connection,
    prefix_sql: str,
    *,
    keys: Sequence[PaneCompositeKey],
    now_iso: str,
) -> None:
    """Run a parameterized UPDATE filtered by a list of composite keys."""
    if not keys:
        return
    clauses = [
        "(container_id = ? AND tmux_socket_path = ? AND tmux_session_name = ? "
        "AND tmux_window_index = ? AND tmux_pane_index = ? AND tmux_pane_id = ?)"
    ] * len(keys)
    sql = prefix_sql + " OR ".join(clauses)
    params: list[Any] = [now_iso]
    for key in keys:
        params.extend(key)
    conn.execute(sql, params)


def insert_pane_scan(
    conn: sqlite3.Connection,
    *,
    scan_id: str,
    started_at: str,
    completed_at: str,
    status: str,
    containers_scanned: int,
    sockets_scanned: int,
    panes_seen: int,
    panes_newly_active: int,
    panes_reconciled_inactive: int,
    containers_skipped_inactive: int,
    containers_tmux_unavailable: int,
    error_code: str | None,
    error_message: str | None,
    error_details: Sequence[dict[str, Any]] | None,
) -> None:
    details_json = (
        None
        if error_details is None
        else json.dumps(list(error_details), separators=(",", ":"), ensure_ascii=False)
    )
    conn.execute(
        """
        INSERT INTO pane_scans (
            scan_id, started_at, completed_at, status,
            containers_scanned, sockets_scanned, panes_seen,
            panes_newly_active, panes_reconciled_inactive,
            containers_skipped_inactive, containers_tmux_unavailable,
            error_code, error_message, error_details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_id,
            started_at,
            completed_at,
            status,
            containers_scanned,
            sockets_scanned,
            panes_seen,
            panes_newly_active,
            panes_reconciled_inactive,
            containers_skipped_inactive,
            containers_tmux_unavailable,
            error_code,
            error_message,
            details_json,
        ),
    )
