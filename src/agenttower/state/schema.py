"""SQLite registry schema for AgentTower."""

from __future__ import annotations

import errno
import os
import sqlite3
import stat
from pathlib import Path
from typing import Callable

from ..config import (
    _DIR_MODE,
    _FILE_MODE,
    _ensure_dir_chain,
    _verify_file_mode,
)

CURRENT_SCHEMA_VERSION = 2

_COMPANION_SUFFIXES = ("-journal", "-wal", "-shm")


def _companion_paths(state_db: Path) -> list[Path]:
    return [state_db.with_name(state_db.name + suffix) for suffix in _COMPANION_SUFFIXES]


def _apply_migration_v2(conn: sqlite3.Connection) -> None:
    """Create FEAT-003 tables. Idempotent because of IF NOT EXISTS guards."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS containers (
            container_id      TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            image             TEXT NOT NULL,
            status            TEXT NOT NULL,
            labels_json       TEXT NOT NULL DEFAULT '{}',
            mounts_json       TEXT NOT NULL DEFAULT '[]',
            inspect_json      TEXT NOT NULL DEFAULT '{}',
            config_user       TEXT,
            working_dir       TEXT,
            active            INTEGER NOT NULL CHECK(active IN (0, 1)),
            first_seen_at     TEXT NOT NULL,
            last_scanned_at   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS containers_active_lastscan
            ON containers(active DESC, last_scanned_at DESC, container_id ASC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS container_scans (
            scan_id                    TEXT PRIMARY KEY,
            started_at                 TEXT NOT NULL,
            completed_at               TEXT NOT NULL,
            status                     TEXT NOT NULL CHECK(status IN ('ok', 'degraded')),
            matched_count              INTEGER NOT NULL,
            inactive_reconciled_count  INTEGER NOT NULL,
            ignored_count              INTEGER NOT NULL,
            error_code                 TEXT,
            error_message              TEXT,
            error_details_json         TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS container_scans_started
            ON container_scans(started_at DESC)
        """
    )


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _apply_migration_v2,
}


def _apply_pending_migrations(conn: sqlite3.Connection, current: int) -> int:
    """Apply every migration from `current+1` up to CURRENT_SCHEMA_VERSION.

    Runs under a single transaction. Returns the new schema version.
    Refuses (raises sqlite3.DatabaseError) if a future version is already on disk.
    """
    if current > CURRENT_SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"on-disk schema_version={current} is newer than this build supports "
            f"({CURRENT_SCHEMA_VERSION}); refusing to open"
        )
    if current == CURRENT_SCHEMA_VERSION:
        return current

    conn.execute("BEGIN IMMEDIATE")
    try:
        target = current
        for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
            migration = _MIGRATIONS[version]
            migration(conn)
            target = version
        conn.execute(
            "UPDATE schema_version SET version = ?",
            (target,),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return target


def _verify_existing_registry_files(
    state_db: Path, pre_existing_companions: dict[Path, bool]
) -> None:
    if not state_db.exists():
        return
    _verify_file_mode(state_db, _FILE_MODE)
    for companion, was_present in pre_existing_companions.items():
        if was_present:
            _verify_file_mode(companion, _FILE_MODE)


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")


def _read_or_create_schema_version(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM schema_version")
    (count,) = cur.fetchone()
    if count == 0:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (CURRENT_SCHEMA_VERSION,),
        )
        return CURRENT_SCHEMA_VERSION
    return int(conn.execute("SELECT version FROM schema_version").fetchone()[0])


def _ensure_current_schema(conn: sqlite3.Connection, current_version: int) -> None:
    if current_version < CURRENT_SCHEMA_VERSION:
        _apply_pending_migrations(conn, current_version)
        return
    if current_version > CURRENT_SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"on-disk schema_version={current_version} is newer than this "
            f"build supports ({CURRENT_SCHEMA_VERSION}); refusing to open"
        )
    # Existing DB at current version: ensure FEAT-003 tables exist in case
    # the row got there ahead of the tables (defensive).
    _apply_migration_v2(conn)


def _chmod_new_companions(
    state_db: Path, pre_existing_companions: dict[Path, bool]
) -> None:
    for companion in _companion_paths(state_db):
        if not pre_existing_companions[companion] and companion.exists():
            os.chmod(companion, _FILE_MODE)


def open_registry(
    state_db: Path,
    *,
    namespace_root: Path | None = None,
) -> tuple[sqlite3.Connection, str]:
    """Open or create the registry database at *state_db*.

    Returns ``(connection, status)`` where ``status`` is ``"created"`` when
    this call created the database file, ``"already initialized"`` otherwise.
    Raises ``OSError`` on filesystem errors or pre-existing weak modes on
    AgentTower-owned artifacts. Raises ``sqlite3.DatabaseError`` if the
    on-disk schema version is greater than this build supports.
    """
    if namespace_root is None:
        namespace_root = state_db.parent

    _ensure_dir_chain(state_db.parent, namespace_root=namespace_root)

    pre_existing_companions: dict[Path, bool] = {p: p.exists() for p in _companion_paths(state_db)}
    pre_existed = state_db.exists()

    _verify_existing_registry_files(state_db, pre_existing_companions)

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        if not pre_existed:
            os.chmod(state_db, _FILE_MODE)
        _configure_connection(conn)
        _ensure_current_schema(conn, _read_or_create_schema_version(conn))
        _chmod_new_companions(state_db, pre_existing_companions)
    except Exception:
        conn.close()
        raise

    return conn, "created" if not pre_existed else "already initialized"


def companion_paths_for(state_db: Path) -> list[Path]:
    """Return the SQLite companion paths AgentTower considers part of *state_db*."""
    return _companion_paths(state_db)
