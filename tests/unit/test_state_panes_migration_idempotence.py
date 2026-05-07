"""Strong idempotence tests for the v1->v3 migration body (T047 / R-016 / FR-029).

Companion to ``tests/unit/test_state_panes.py::test_v3_reopen_is_idempotent``.

These tests pin down the property that, once a database has been migrated to
the current schema version, re-opening the registry MUST NOT change anything
on disk -- not the schema (every CREATE has ``IF NOT EXISTS`` guards) and not
any data row written by the caller.  They also cover the FR-029 future-version
refusal explicitly for v3 builds.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from agenttower.state import schema


# --------------------------------------------------------------------------- #
# Fixtures (mirroring patterns from test_state_panes.py / test_state_containers.py)
# --------------------------------------------------------------------------- #

def _make_state_db(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    return state_dir / "agenttower.sqlite3"


def _seed_v1(state_db: Path) -> None:
    """Build a v1-shaped database (FEAT-001) without FEAT-003/004 tables."""
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    finally:
        conn.close()
    os.chmod(state_db, 0o600)


def _open(state_db: Path):
    return schema.open_registry(state_db, namespace_root=state_db.parent)


def _sqlite_master_snapshot(state_db: Path) -> list[tuple]:
    """Return a deterministic snapshot of (type, name, tbl_name, sql) rows.

    We open a fresh read-only connection (separate from the one the registry
    opens) so we don't perturb anything.  Sorting by (type, name) gives a
    canonical ordering for byte-for-byte comparison.
    """
    conn = sqlite3.connect(str(state_db))
    try:
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()
    return rows


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_v1_to_v3_migrates_in_one_open(tmp_path: Path) -> None:
    """A single ``open_registry`` call must take a v1 DB to v3 with all tables
    and indexes the FEAT-003 + FEAT-004 schemas demand."""
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)

    conn, status = _open(state_db)
    try:
        assert status == "already initialized"
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        # FEAT-006 bumped CURRENT_SCHEMA_VERSION to 4; the v1→current migration
        # still needs to land all FEAT-003 + FEAT-004 tables in one open call.
        assert version == schema.CURRENT_SCHEMA_VERSION

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # FEAT-003 + FEAT-004 tables must all be present after a single open.
        assert {"containers", "container_scans", "panes", "pane_scans"}.issubset(tables)

        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        # FEAT-003 + FEAT-004 indexes.
        assert {
            "containers_active_lastscan",
            "container_scans_started",
            "panes_active_order",
            "panes_container_socket",
            "pane_scans_started",
        }.issubset(indexes)
    finally:
        conn.close()


def test_v3_reopen_does_not_create_or_alter_anything(tmp_path: Path) -> None:
    """Strongest idempotence assertion: re-opening a v3 DB must leave
    ``sqlite_master`` byte-for-byte identical.  Catches any DDL drift in the
    migration body even when the migration is re-run defensively (R-016)."""
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)

    # First open performs v1 -> v3 migration.
    conn, _ = _open(state_db)
    conn.close()

    before = _sqlite_master_snapshot(state_db)

    # Second open: ``_ensure_current_schema`` calls ``_apply_migration_v2`` and
    # ``_apply_migration_v3`` defensively -- but every CREATE has ``IF NOT
    # EXISTS`` so the snapshot must not change.
    conn2, _ = _open(state_db)
    try:
        # Sanity: still at the build's current version.
        assert (
            conn2.execute("SELECT version FROM schema_version").fetchone()[0]
            == schema.CURRENT_SCHEMA_VERSION
        )
    finally:
        conn2.close()

    after = _sqlite_master_snapshot(state_db)
    assert before == after, (
        "Re-opening a v3 registry mutated sqlite_master.\n"
        f"before: {before!r}\n"
        f"after:  {after!r}"
    )


def test_v3_reopen_does_not_modify_seeded_pane_rows(tmp_path: Path) -> None:
    """Re-opening a v3 registry must not touch any existing pane row.

    Mirrors R-016: the migration body is a no-op for current-version DBs, so
    user data inserted between opens must round-trip exactly.
    """
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)

    conn, _ = _open(state_db)
    try:
        # Seed one container so the FK-style guard (in select_panes_for_listing)
        # would consider the pane joinable, and one pane row.
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, labels_json, "
            "mounts_json, inspect_json, config_user, working_dir, active, "
            "first_seen_at, last_scanned_at) VALUES "
            "('c1', 'b', 'i', 'running', '{}', '[]', '{}', 'u', '/w', 1, "
            "'2026-05-06T10:00:00.000000+00:00', '2026-05-06T10:00:00.000000+00:00')"
        )
        conn.execute(
            "INSERT INTO panes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "c1", "/tmp/tmux-1000/default", "work", 0, 0, "%0",
                "bench", "user", 1234, "/dev/pts/0", "bash", "/workspace",
                "title", 1, 1,
                "2026-05-06T10:00:00.000000+00:00",
                "2026-05-06T10:00:00.000000+00:00",
            ),
        )
    finally:
        conn.close()

    # Snapshot the row before reopen.
    conn = sqlite3.connect(str(state_db))
    try:
        before = conn.execute("SELECT * FROM panes").fetchall()
    finally:
        conn.close()
    assert len(before) == 1

    # Reopen -- defensive migration call must not mutate the row.
    conn2, _ = _open(state_db)
    try:
        after = conn2.execute("SELECT * FROM panes").fetchall()
    finally:
        conn2.close()

    assert after == before, (
        "Re-opening a v3 registry modified an existing pane row.\n"
        f"before: {before!r}\n"
        f"after:  {after!r}"
    )


def test_apply_migration_v3_is_idempotent_when_called_directly(tmp_path: Path) -> None:
    """``_apply_migration_v3`` must be safely re-runnable on its own, both
    against a fresh DB and against one that already has data in it.  Every
    CREATE is guarded by ``IF NOT EXISTS`` so additional invocations are
    pure no-ops."""
    state_db = _make_state_db(tmp_path)
    _seed_v1(state_db)

    # Bring the DB to v3 the normal way, then keep a connection open for direct
    # migration calls.
    conn, _ = _open(state_db)
    try:
        # First and second direct calls -- both must succeed without raising.
        schema._apply_migration_v3(conn)
        schema._apply_migration_v3(conn)

        # Now insert a pane row, then re-run the migration body a third time.
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, labels_json, "
            "mounts_json, inspect_json, config_user, working_dir, active, "
            "first_seen_at, last_scanned_at) VALUES "
            "('cZ', 'b', 'i', 'running', '{}', '[]', '{}', 'u', '/w', 1, "
            "'2026-05-06T10:00:00.000000+00:00', '2026-05-06T10:00:00.000000+00:00')"
        )
        conn.execute(
            "INSERT INTO panes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cZ", "/tmp/tmux-1000/default", "s", 0, 0, "%0",
                "bench", "user", 7777, "/dev/pts/0", "bash", "/workspace",
                "title", 1, 1,
                "2026-05-06T10:00:00.000000+00:00",
                "2026-05-06T10:00:00.000000+00:00",
            ),
        )
        before = conn.execute("SELECT * FROM panes").fetchall()

        schema._apply_migration_v3(conn)

        after = conn.execute("SELECT * FROM panes").fetchall()
        assert after == before, (
            "Direct re-call of _apply_migration_v3 mutated existing pane data.\n"
            f"before: {before!r}\n"
            f"after:  {after!r}"
        )
    finally:
        conn.close()


def test_v3_to_v4_future_version_refuses_to_open(tmp_path: Path) -> None:
    """FR-029 -- on-disk schema_version newer than this build (here v3) must
    cause ``open_registry`` to raise ``sqlite3.DatabaseError``."""
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
        _open(state_db)
