"""T014 — FEAT-008 v5 → v6 schema migration tests.

Mirrors the FEAT-007 v4 → v5 pattern. Asserts:

* idempotence (running ``_apply_migration_v6`` twice is a no-op)
* v5-only DB upgrades to v6 cleanly with the events table + 4 indexes
* v6-already-current re-open is a no-op
* forward-version refusal: a daemon with this build refuses to open
  a v7+ DB
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.state import schema


def _open_v5_only(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    """Create a fresh DB stopped at schema v5 (FEAT-007 head-of-tree)."""
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    # Apply every migration up to v5 (so the FEAT-001..007 tables exist).
    for v in (2, 3, 4, 5):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    return conn, state_db


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _index_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    }


def test_migration_v6_creates_events_table_and_four_indexes(tmp_path: Path) -> None:
    conn, _ = _open_v5_only(tmp_path)
    assert "events" not in _table_names(conn)

    schema._apply_migration_v6(conn)
    conn.commit()

    tables = _table_names(conn)
    assert "events" in tables

    indexes = _index_names(conn)
    expected_indexes = {
        "idx_events_agent_eventid",
        "idx_events_type_eventid",
        "idx_events_observedat_eventid",
        "idx_events_jsonl_pending",
    }
    assert expected_indexes <= indexes


def test_migration_v6_is_idempotent(tmp_path: Path) -> None:
    conn, _ = _open_v5_only(tmp_path)
    schema._apply_migration_v6(conn)
    schema._apply_migration_v6(conn)  # idempotent
    schema._apply_migration_v6(conn)  # idempotent
    conn.commit()
    # Still exactly one events table.
    cur = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='events'"
    )
    assert cur.fetchone()[0] == 1


def test_migration_v6_event_type_check_constraint_rejects_unknown(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v5_only(tmp_path)
    schema._apply_migration_v6(conn)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO events ("
            "event_type, agent_id, attachment_id, log_path, "
            "byte_range_start, byte_range_end, "
            "line_offset_start, line_offset_end, "
            "observed_at, excerpt, classifier_rule_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "not_a_real_type",  # violates CHECK
                "agt_a1b2c3d4e5f6",
                "atc_aabbccddeeff",
                "/tmp/x.log",
                0,
                10,
                0,
                1,
                "2026-05-10T12:00:00.000000+00:00",
                "x",
                "activity.fallback.v1",
            ),
        )


def test_migration_v6_event_id_autoincrement(tmp_path: Path) -> None:
    """Two consecutive inserts produce strictly-increasing event_id values."""
    conn, _ = _open_v5_only(tmp_path)
    schema._apply_migration_v6(conn)
    conn.commit()
    rows = []
    for i in range(3):
        cur = conn.execute(
            "INSERT INTO events ("
            "event_type, agent_id, attachment_id, log_path, "
            "byte_range_start, byte_range_end, "
            "line_offset_start, line_offset_end, "
            "observed_at, excerpt, classifier_rule_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "activity",
                "agt_a1b2c3d4e5f6",
                "atc_aabbccddeeff",
                "/tmp/x.log",
                i * 10,
                (i + 1) * 10,
                i,
                i + 1,
                "2026-05-10T12:00:00.000000+00:00",
                f"line {i}",
                "activity.fallback.v1",
            ),
        )
        rows.append(cur.lastrowid)
    assert rows == sorted(rows)
    assert rows[0] >= 1
    assert all(b > a for a, b in zip(rows, rows[1:]))


def test_apply_pending_migrations_v5_to_v6(tmp_path: Path) -> None:
    """Full ``_apply_pending_migrations`` happy-path from v5 to current."""
    conn, _ = _open_v5_only(tmp_path)
    target = schema._apply_pending_migrations(conn, current=5)
    assert target == schema.CURRENT_SCHEMA_VERSION == 6
    assert "events" in _table_names(conn)
    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == 6


def test_apply_pending_migrations_v6_already_current_is_noop(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v5_only(tmp_path)
    schema._apply_migration_v6(conn)
    conn.execute("UPDATE schema_version SET version = 6")
    conn.commit()

    before_indexes = _index_names(conn)
    target = schema._apply_pending_migrations(conn, current=6)
    after_indexes = _index_names(conn)
    assert target == 6
    assert before_indexes == after_indexes


def test_apply_pending_migrations_forward_version_refused(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v5_only(tmp_path)
    with pytest.raises(sqlite3.DatabaseError, match="newer than this build"):
        schema._apply_pending_migrations(conn, current=99)
