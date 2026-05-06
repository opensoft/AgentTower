"""Typed dataclasses + read/write helpers for FEAT-003 SQLite tables.

Helpers accept an open `sqlite3.Connection` and do NOT begin or commit
transactions on their own (data-model.md §5). The DiscoveryService owns
the transaction boundary that wraps a full scan reconciliation.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContainerRow:
    container_id: str
    name: str
    image: str
    status: str
    labels: dict[str, str]
    mounts: list[dict[str, Any]]
    inspect: dict[str, Any]
    config_user: str | None
    working_dir: str | None
    active: bool
    first_seen_at: str
    last_scanned_at: str


@dataclass(frozen=True)
class ContainerScanRow:
    scan_id: str
    started_at: str
    completed_at: str
    status: str
    matched_count: int
    inactive_reconciled_count: int
    ignored_count: int
    error_code: str | None
    error_message: str | None
    error_details: list[dict[str, Any]] | None


def _row_to_container(row: sqlite3.Row | tuple) -> ContainerRow:
    return ContainerRow(
        container_id=row[0],
        name=row[1],
        image=row[2],
        status=row[3],
        labels=json.loads(row[4]),
        mounts=json.loads(row[5]),
        inspect=json.loads(row[6]),
        config_user=row[7],
        working_dir=row[8],
        active=bool(row[9]),
        first_seen_at=row[10],
        last_scanned_at=row[11],
    )


def select_containers(
    conn: sqlite3.Connection, *, active_only: bool = False
) -> list[ContainerRow]:
    if active_only:
        sql = (
            "SELECT container_id, name, image, status, labels_json, mounts_json, "
            "inspect_json, config_user, working_dir, active, first_seen_at, last_scanned_at "
            "FROM containers WHERE active = 1 "
            "ORDER BY active DESC, last_scanned_at DESC, container_id ASC"
        )
    else:
        sql = (
            "SELECT container_id, name, image, status, labels_json, mounts_json, "
            "inspect_json, config_user, working_dir, active, first_seen_at, last_scanned_at "
            "FROM containers ORDER BY active DESC, last_scanned_at DESC, container_id ASC"
        )
    return [_row_to_container(r) for r in conn.execute(sql).fetchall()]


def select_active_container_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT container_id FROM containers WHERE active = 1"
        ).fetchall()
    }


def select_known_container_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute("SELECT container_id FROM containers").fetchall()
    }


def upsert_container(
    conn: sqlite3.Connection,
    *,
    container_id: str,
    name: str,
    image: str,
    status: str,
    labels: dict[str, str],
    mounts: Sequence[dict[str, Any]],
    inspect: dict[str, Any],
    config_user: str | None,
    working_dir: str | None,
    active: bool,
    now_iso: str,
) -> None:
    """Insert or update a containers row, preserving `first_seen_at`."""
    labels_json = json.dumps(labels, separators=(",", ":"), ensure_ascii=False)
    mounts_json = json.dumps(list(mounts), separators=(",", ":"), ensure_ascii=False)
    inspect_json = json.dumps(inspect, separators=(",", ":"), ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO containers (
            container_id, name, image, status, labels_json, mounts_json,
            inspect_json, config_user, working_dir, active,
            first_seen_at, last_scanned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(container_id) DO UPDATE SET
            name = excluded.name,
            image = excluded.image,
            status = excluded.status,
            labels_json = excluded.labels_json,
            mounts_json = excluded.mounts_json,
            inspect_json = excluded.inspect_json,
            config_user = excluded.config_user,
            working_dir = excluded.working_dir,
            active = excluded.active,
            last_scanned_at = excluded.last_scanned_at
        """,
        (
            container_id,
            name,
            image,
            status,
            labels_json,
            mounts_json,
            inspect_json,
            config_user,
            working_dir,
            1 if active else 0,
            now_iso,
            now_iso,
        ),
    )


def mark_inactive(
    conn: sqlite3.Connection, *, container_ids: Iterable[str], now_iso: str
) -> int:
    ids = list(container_ids)
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    cur = conn.execute(
        f"UPDATE containers SET active = 0, last_scanned_at = ? "
        f"WHERE active = 1 AND container_id IN ({placeholders})",
        (now_iso, *ids),
    )
    return cur.rowcount or 0


def touch_last_scanned(
    conn: sqlite3.Connection, *, container_ids: Iterable[str], now_iso: str
) -> None:
    ids = list(container_ids)
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE containers SET last_scanned_at = ? "
        f"WHERE container_id IN ({placeholders})",
        (now_iso, *ids),
    )


def insert_container_scan(
    conn: sqlite3.Connection,
    *,
    scan_id: str,
    started_at: str,
    completed_at: str,
    status: str,
    matched_count: int,
    inactive_reconciled_count: int,
    ignored_count: int,
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
        INSERT INTO container_scans (
            scan_id, started_at, completed_at, status,
            matched_count, inactive_reconciled_count, ignored_count,
            error_code, error_message, error_details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_id,
            started_at,
            completed_at,
            status,
            matched_count,
            inactive_reconciled_count,
            ignored_count,
            error_code,
            error_message,
            details_json,
        ),
    )
