"""Unit tests for the FEAT-006 v3 → v4 SQLite migration (T016 / FR-036 / FR-037).

Covers:
* Fresh DB → v4 (table + indexes present).
* v3-only DB upgrades to v4 in one transaction.
* ``agents`` table + indexes are created on otherwise-unchanged FEAT-005 DBs.
* FEAT-001..004 tables remain byte-identical pre/post migration.
* ``_apply_migration_v4`` is idempotent (re-call after success is a no-op).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from agenttower.state import schema


def _make_state_db(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    return state_dir / "agenttower.sqlite3"


def _seed_v3(state_db: Path) -> None:
    """Build a v3-shaped database (FEAT-001 + 003 + 004 schema)."""
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        schema._apply_migration_v2(conn)
        schema._apply_migration_v3(conn)
    finally:
        conn.close()
    os.chmod(state_db, 0o600)


def _open(state_db: Path):
    return schema.open_registry(state_db, namespace_root=state_db.parent)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _index_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _sqlite_master_snapshot_for(
    state_db: Path, predicate_sql: str
) -> list[tuple]:
    conn = sqlite3.connect(str(state_db))
    try:
        return conn.execute(
            f"SELECT type, name, tbl_name, sql FROM sqlite_master "
            f"WHERE name NOT LIKE 'sqlite_%' AND {predicate_sql} "
            f"ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()


def test_current_schema_version_is_at_least_4() -> None:
    """The v3→v4 migration entry MUST exist; later FEATs may bump CURRENT_SCHEMA_VERSION higher."""
    assert schema.CURRENT_SCHEMA_VERSION >= 4
    assert 4 in schema._MIGRATIONS


def test_fresh_db_lands_at_current_with_agents_table(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    conn, status = _open(state_db)
    try:
        assert status == "created"
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == schema.CURRENT_SCHEMA_VERSION
        tables = _table_names(conn)
        assert {
            "containers",
            "container_scans",
            "panes",
            "pane_scans",
            "agents",
        }.issubset(tables)
        indexes = _index_names(conn)
        assert {
            "agents_active_order",
            "agents_parent_lookup",
            "agents_pane_lookup",
        }.issubset(indexes)
    finally:
        conn.close()


def test_v3_to_current_preserves_feat001_through_feat004_tables(tmp_path: Path) -> None:
    """SC-010: v3-only DB upgrades to current cleanly; FEAT-001..004 tables are
    byte-identical."""
    state_db = _make_state_db(tmp_path)
    _seed_v3(state_db)

    # Exclude every later-FEAT artifact from the byte-identity check.
    later_artifacts = (
        "agents",
        "agents_active_order",
        "agents_parent_lookup",
        "agents_pane_lookup",
        "log_attachments",
        "log_attachments_active_log_path",
        "log_attachments_agent_status",
        "log_attachments_pane_status",
        "log_offsets",
        "log_offsets_agent",
        "schema_version",
    )
    name_filter = (
        "name NOT IN ("
        + ",".join(f"'{n}'" for n in later_artifacts)
        + ")"
    )
    before = _sqlite_master_snapshot_for(state_db, name_filter)

    conn, _ = _open(state_db)
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == schema.CURRENT_SCHEMA_VERSION
        assert "agents" in _table_names(conn)
    finally:
        conn.close()

    after = _sqlite_master_snapshot_for(state_db, name_filter)
    assert before == after, (
        "v3 → current migration mutated FEAT-001..004 schema rows.\n"
        f"before: {before!r}\n"
        f"after:  {after!r}"
    )


def test_apply_migration_v4_is_idempotent(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    conn, _ = _open(state_db)
    try:
        before = sorted(_table_names(conn) | _index_names(conn))
        schema._apply_migration_v4(conn)
        schema._apply_migration_v4(conn)
        after = sorted(_table_names(conn) | _index_names(conn))
        assert before == after
    finally:
        conn.close()


def test_current_reopen_is_a_noop(tmp_path: Path) -> None:
    """SC-010: re-opening an already-current DB is a clean no-op (defensive migration call)."""
    state_db = _make_state_db(tmp_path)
    _open(state_db)[0].close()

    before = _sqlite_master_snapshot_for(state_db, "1=1")

    conn, _ = _open(state_db)
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == schema.CURRENT_SCHEMA_VERSION
    finally:
        conn.close()

    after = _sqlite_master_snapshot_for(state_db, "1=1")
    assert before == after


def test_agents_table_uniqueness_constraint_on_pane_key(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    conn, _ = _open(state_db)
    try:
        conn.execute(
            "INSERT INTO agents ("
            "agent_id, container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, role, capability, "
            "label, project_path, parent_agent_id, effective_permissions, "
            "created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "agt_aaaaaaaaaaaa",
                "c1", "/tmp/tmux-1000/default", "main", 0, 0, "%0",
                "slave", "codex", "lbl", "/w", None, "{}",
                "2026-05-07T00:00:00.000000+00:00",
                "2026-05-07T00:00:00.000000+00:00",
                None, 1,
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            # Same composite pane key, different agent_id — rejected by UNIQUE.
            conn.execute(
                "INSERT INTO agents ("
                "agent_id, container_id, tmux_socket_path, tmux_session_name, "
                "tmux_window_index, tmux_pane_index, tmux_pane_id, role, capability, "
                "label, project_path, parent_agent_id, effective_permissions, "
                "created_at, last_registered_at, last_seen_at, active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "agt_bbbbbbbbbbbb",
                    "c1", "/tmp/tmux-1000/default", "main", 0, 0, "%0",
                    "slave", "codex", "lbl", "/w", None, "{}",
                    "2026-05-07T00:00:00.000000+00:00",
                    "2026-05-07T00:00:00.000000+00:00",
                    None, 1,
                ),
            )
    finally:
        conn.close()


def test_agents_table_role_check_constraint_rejects_invalid(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    conn, _ = _open(state_db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO agents ("
                "agent_id, container_id, tmux_socket_path, tmux_session_name, "
                "tmux_window_index, tmux_pane_index, tmux_pane_id, role, capability, "
                "label, project_path, parent_agent_id, effective_permissions, "
                "created_at, last_registered_at, last_seen_at, active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "agt_aaaaaaaaaaaa",
                    "c1", "/tmp/tmux-1000/default", "main", 0, 0, "%0",
                    "Slave",  # mixed-case rejected at the SQL CHECK level too
                    "codex", "lbl", "/w", None, "{}",
                    "2026-05-07T00:00:00.000000+00:00",
                    "2026-05-07T00:00:00.000000+00:00",
                    None, 1,
                ),
            )
    finally:
        conn.close()
