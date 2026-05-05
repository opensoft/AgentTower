from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest

from agenttower.state.schema import CURRENT_SCHEMA_VERSION, open_registry


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_open_registry_creates_db_with_mode_0600(tmp_path: Path) -> None:
    state_dir = tmp_path / "opensoft/agenttower"
    state_db = state_dir / "agenttower.sqlite3"

    conn, status = open_registry(state_db, namespace_root=state_dir)
    try:
        assert status == "created"
        assert state_db.exists()
        assert _mode(state_db) == 0o600
        assert _mode(state_dir) == 0o700
    finally:
        conn.close()


def test_schema_version_inserted_on_fresh_db(tmp_path: Path) -> None:
    state_dir = tmp_path / "opensoft/agenttower"
    state_db = state_dir / "agenttower.sqlite3"
    conn, _ = open_registry(state_db, namespace_root=state_dir)
    try:
        rows = list(conn.execute("SELECT version FROM schema_version"))
        assert rows == [(CURRENT_SCHEMA_VERSION,)]
        ((count,),) = list(conn.execute("SELECT COUNT(*) FROM schema_version"))
        assert count == 1
    finally:
        conn.close()


def test_open_registry_is_idempotent_and_status_changes(tmp_path: Path) -> None:
    state_dir = tmp_path / "opensoft/agenttower"
    state_db = state_dir / "agenttower.sqlite3"

    conn, status = open_registry(state_db, namespace_root=state_dir)
    conn.close()
    assert status == "created"

    for _ in range(10):
        conn, status = open_registry(state_db, namespace_root=state_dir)
        try:
            assert status == "already initialized"
            ((count,),) = list(conn.execute("SELECT COUNT(*) FROM schema_version"))
            ((version,),) = list(conn.execute("SELECT version FROM schema_version"))
            assert count == 1
            assert version == CURRENT_SCHEMA_VERSION
        finally:
            conn.close()


def test_pragma_journal_mode_is_wal_after_open(tmp_path: Path) -> None:
    state_dir = tmp_path / "opensoft/agenttower"
    state_db = state_dir / "agenttower.sqlite3"
    conn, _ = open_registry(state_db, namespace_root=state_dir)
    try:
        ((mode,),) = list(conn.execute("PRAGMA journal_mode"))
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_open_registry_refuses_pre_existing_state_db_with_broader_mode(tmp_path: Path) -> None:
    state_dir = tmp_path / "opensoft/agenttower"
    state_dir.mkdir(parents=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    state_db = state_dir / "agenttower.sqlite3"
    state_db.touch()
    os.chmod(state_db, 0o644)  # NOSONAR - intentionally unsafe mode fixture.
    original_bytes = state_db.read_bytes()

    with pytest.raises(OSError):
        open_registry(state_db, namespace_root=state_dir)

    assert state_db.read_bytes() == original_bytes
    assert _mode(state_db) == 0o644


def test_open_registry_refuses_pre_existing_parent_dir_with_broader_mode(tmp_path: Path) -> None:
    state_dir = tmp_path / "opensoft/agenttower"
    state_dir.mkdir(parents=True, mode=0o755)  # NOSONAR - intentionally unsafe mode fixture.
    os.chmod(state_dir, 0o755)  # NOSONAR - intentionally unsafe mode fixture.
    state_db = state_dir / "agenttower.sqlite3"

    with pytest.raises(OSError):
        open_registry(state_db, namespace_root=state_dir)

    assert not state_db.exists()
    assert _mode(state_dir) == 0o755


def test_open_registry_does_not_double_seed_after_external_open(tmp_path: Path) -> None:
    state_dir = tmp_path / "opensoft/agenttower"
    state_db = state_dir / "agenttower.sqlite3"
    conn, _ = open_registry(state_db, namespace_root=state_dir)
    conn.close()

    raw = sqlite3.connect(str(state_db))
    rows_before = list(raw.execute("SELECT version FROM schema_version"))
    raw.close()

    conn, status = open_registry(state_db, namespace_root=state_dir)
    try:
        ((count,),) = list(conn.execute("SELECT COUNT(*) FROM schema_version"))
        assert count == 1
        assert status == "already initialized"
    finally:
        conn.close()

    assert rows_before == [(CURRENT_SCHEMA_VERSION,)]
