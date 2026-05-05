"""SQLite registry schema for AgentTower."""

from __future__ import annotations

import errno
import os
import sqlite3
import stat
from pathlib import Path

from ..config import (
    _DIR_MODE,
    _FILE_MODE,
    _ensure_dir_chain,
    _verify_file_mode,
)

CURRENT_SCHEMA_VERSION = 1

_COMPANION_SUFFIXES = ("-journal", "-wal", "-shm")


def _companion_paths(state_db: Path) -> list[Path]:
    return [state_db.with_name(state_db.name + suffix) for suffix in _COMPANION_SUFFIXES]


def open_registry(
    state_db: Path,
    *,
    namespace_root: Path | None = None,
) -> tuple[sqlite3.Connection, str]:
    """Open or create the registry database at *state_db*.

    Returns ``(connection, status)`` where ``status`` is ``"created"`` when
    this call created the database file, ``"already initialized"`` otherwise.
    Raises ``OSError`` on filesystem errors or pre-existing weak modes on
    AgentTower-owned artifacts.
    """
    if namespace_root is None:
        namespace_root = state_db.parent

    _ensure_dir_chain(state_db.parent, namespace_root=namespace_root)

    pre_existing_companions: dict[Path, bool] = {p: p.exists() for p in _companion_paths(state_db)}
    pre_existed = state_db.exists()

    if pre_existed:
        _verify_file_mode(state_db, _FILE_MODE)
        for companion, was_present in pre_existing_companions.items():
            if was_present:
                _verify_file_mode(companion, _FILE_MODE)

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        if not pre_existed:
            os.chmod(state_db, _FILE_MODE)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        cur = conn.execute("SELECT COUNT(*) FROM schema_version")
        (count,) = cur.fetchone()
        if count == 0:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (CURRENT_SCHEMA_VERSION,),
            )

        for companion in _companion_paths(state_db):
            if not pre_existing_companions[companion] and companion.exists():
                os.chmod(companion, _FILE_MODE)
    except Exception:
        conn.close()
        raise

    return conn, "created" if not pre_existed else "already initialized"


def companion_paths_for(state_db: Path) -> list[Path]:
    """Return the SQLite companion paths AgentTower considers part of *state_db*."""
    return _companion_paths(state_db)
