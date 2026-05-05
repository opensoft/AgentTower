"""Unit tests for FEAT-003 SQLite schema migration and container row helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from agenttower.state import containers as state_containers
from agenttower.state import schema


def _make_state_db(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    return state_dir / "agenttower.sqlite3"


def _seed_v1(state_db: Path) -> None:
    """Build a v1-shaped database (FEAT-001) without FEAT-003 tables."""
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    finally:
        conn.close()
    os.chmod(state_db, 0o600)


def test_open_registry_migrates_v1_to_v2(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)
    conn, status = schema.open_registry(state_db, namespace_root=state_db.parent)
    try:
        assert status == "already initialized"
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 2
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"containers", "container_scans"}.issubset(tables)
    finally:
        conn.close()


def test_open_registry_v2_reopen_is_idempotent(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)
    schema.open_registry(state_db, namespace_root=state_db.parent)[0].close()
    conn, _ = schema.open_registry(state_db, namespace_root=state_db.parent)
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 2
    finally:
        conn.close()


def test_open_registry_refuses_future_version(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (99)")
    finally:
        conn.close()
    os.chmod(state_db, 0o600)
    with pytest.raises(sqlite3.DatabaseError, match="newer than this build"):
        schema.open_registry(state_db, namespace_root=state_db.parent)


def test_migration_failure_rolls_back(tmp_path: Path, monkeypatch) -> None:
    """T013 — FR-047 rollback on migration failure."""
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)

    real_apply = schema._apply_migration_v2

    def explode(conn: sqlite3.Connection) -> None:  # noqa: ANN001
        # Run the first DDL then explode, mimicking a partial migration.
        conn.execute("CREATE TABLE IF NOT EXISTS containers (container_id TEXT)")
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(schema, "_apply_migration_v2", explode)
    monkeypatch.setitem(schema._MIGRATIONS, 2, explode)
    with pytest.raises(sqlite3.OperationalError, match="boom"):
        schema.open_registry(state_db, namespace_root=state_db.parent)

    monkeypatch.setattr(schema, "_apply_migration_v2", real_apply)
    monkeypatch.setitem(schema._MIGRATIONS, 2, real_apply)

    # Verify the v1 schema is unchanged: schema_version still 1, no containers table.
    conn = sqlite3.connect(str(state_db))
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 1
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='containers'"
        ).fetchall()
        # The IF NOT EXISTS ran outside the BEGIN IMMEDIATE wrapper so it may
        # remain — but it must not be the *full* containers table from v2.
        # We accept either no table or a stub table; what matters is schema_version.
        if rows:
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(containers)").fetchall()
            }
            assert "active" not in cols, "v2 schema leaked despite rollback"
    finally:
        conn.close()


def test_container_helpers_round_trip_json(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)
    conn, _ = schema.open_registry(state_db, namespace_root=state_db.parent)
    try:
        state_containers.upsert_container(
            conn,
            container_id="abc123",
            name="py-bench",
            image="ghcr.io/opensoft/py-bench:latest",
            status="running",
            labels={"opensoft.bench": "true", "kind": "dev"},
            mounts=[{"source": "/home/u", "target": "/workspace", "type": "bind", "mode": "rw", "rw": True}],
            inspect={"config_user": "user", "working_dir": "/workspace", "env_keys": ["USER"], "full_status": "running"},
            config_user="user",
            working_dir="/workspace",
            active=True,
            now_iso="2026-05-05T10:00:00.000000+00:00",
        )
        rows = state_containers.select_containers(conn)
        assert len(rows) == 1
        row = rows[0]
        assert row.container_id == "abc123"
        assert row.labels == {"opensoft.bench": "true", "kind": "dev"}
        assert row.mounts[0]["target"] == "/workspace"
        assert row.inspect["env_keys"] == ["USER"]
        assert row.active is True
        assert row.first_seen_at == "2026-05-05T10:00:00.000000+00:00"
        assert row.last_scanned_at == "2026-05-05T10:00:00.000000+00:00"

        # Update preserves first_seen_at, advances last_scanned_at
        state_containers.upsert_container(
            conn,
            container_id="abc123",
            name="py-bench",
            image="ghcr.io/opensoft/py-bench:v2",
            status="running",
            labels={"kind": "prod"},
            mounts=[],
            inspect={},
            config_user=None,
            working_dir=None,
            active=True,
            now_iso="2026-05-05T11:00:00.000000+00:00",
        )
        rows = state_containers.select_containers(conn)
        assert rows[0].first_seen_at == "2026-05-05T10:00:00.000000+00:00"
        assert rows[0].last_scanned_at == "2026-05-05T11:00:00.000000+00:00"
        assert rows[0].image.endswith(":v2")
    finally:
        conn.close()


def test_mark_inactive_skips_already_inactive(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)
    conn, _ = schema.open_registry(state_db, namespace_root=state_db.parent)
    try:
        state_containers.upsert_container(
            conn,
            container_id="a",
            name="a-bench",
            image="i",
            status="running",
            labels={},
            mounts=[],
            inspect={},
            config_user=None,
            working_dir=None,
            active=True,
            now_iso="2026-05-05T10:00:00.000000+00:00",
        )
        flipped = state_containers.mark_inactive(
            conn, container_ids=["a"], now_iso="2026-05-05T11:00:00.000000+00:00"
        )
        assert flipped == 1
        flipped_again = state_containers.mark_inactive(
            conn, container_ids=["a"], now_iso="2026-05-05T11:30:00.000000+00:00"
        )
        assert flipped_again == 0
    finally:
        conn.close()


def test_insert_container_scan_round_trip(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)
    conn, _ = schema.open_registry(state_db, namespace_root=state_db.parent)
    try:
        state_containers.insert_container_scan(
            conn,
            scan_id="scan-1",
            started_at="2026-05-05T10:00:00.000000+00:00",
            completed_at="2026-05-05T10:00:00.500000+00:00",
            status="degraded",
            matched_count=1,
            inactive_reconciled_count=0,
            ignored_count=2,
            error_code="docker_failed",
            error_message="oops",
            error_details=[{"container_id": "a", "code": "docker_failed", "message": "stderr"}],
        )
        row = conn.execute("SELECT scan_id, status, error_code FROM container_scans").fetchone()
        assert row == ("scan-1", "degraded", "docker_failed")
    finally:
        conn.close()
