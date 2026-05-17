"""T004 — FEAT-010 v7 → v8 schema migration tests.

Mirrors the FEAT-009 v6 → v7 test pattern. Asserts:

(a) v7 → v8 upgrade applies the migration once and creates the routes
    table + the partial UNIQUE index on message_queue.
(b) v8-already-current re-open is a no-op (idempotent).
(c) An interrupted prior migration (column added, index not yet
    created) is safe to resume — re-running succeeds without error.
(d) Existing FEAT-009 message_queue rows get origin='direct' via the
    DEFAULT clause; no data loss.
(e) The partial UNIQUE index actually rejects duplicate
    (route_id, event_id) inserts when origin='route', and ignores
    duplicates when origin='direct' (because of the WHERE predicate).
(f) The routes-table CHECK constraints reject malformed source-scope /
    target-rule / master-rule combinations.

Test seam: builds a fresh DB stopped at schema v7 by running migrations
2..7 manually, then asserts pre/post state across `_apply_migration_v8`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _open_v7_only(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    """Create a fresh DB stopped at schema v7 (FEAT-009 head-of-tree)."""
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (7)")
    for v in (2, 3, 4, 5, 6, 7):
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


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _insert_minimal_direct_queue_row(
    conn: sqlite3.Connection, *, message_id: str = "msg_001"
) -> None:
    """Insert a minimal FEAT-009-shape direct-send message_queue row."""
    conn.execute(
        """
        INSERT INTO message_queue (
            message_id, state, sender_agent_id, sender_label, sender_role,
            target_agent_id, target_label, target_role,
            target_container_id, target_pane_id,
            envelope_body, envelope_body_sha256, envelope_size_bytes,
            enqueued_at, last_updated_at
        ) VALUES (?, 'queued', 'agt_master00001', 'm1', 'master',
                  'agt_slave000001', 's1', 'slave',
                  'ctn_x', 'pn_x',
                  X'68656c6c6f', 'sha', 5,
                  '2026-05-17T00:00:00.000Z', '2026-05-17T00:00:00.000Z')
        """,
        (message_id,),
    )


# ──────────────────────────────────────────────────────────────────────
# (a) v7 → v8 upgrade creates the routes table + indexes
# ──────────────────────────────────────────────────────────────────────


def test_migration_v8_creates_routes_table_and_indexes(tmp_path: Path) -> None:
    conn, _ = _open_v7_only(tmp_path)
    assert "routes" not in _table_names(conn)
    assert "idx_routes_created_at_route_id" not in _index_names(conn)
    assert "idx_message_queue_route_event" not in _index_names(conn)

    schema._apply_migration_v8(conn)

    assert "routes" in _table_names(conn)
    assert "idx_routes_created_at_route_id" in _index_names(conn)
    assert "idx_message_queue_route_event" in _index_names(conn)


def test_migration_v8_extends_message_queue_columns(tmp_path: Path) -> None:
    conn, _ = _open_v7_only(tmp_path)
    pre_cols = _column_names(conn, "message_queue")
    assert "origin" not in pre_cols
    assert "route_id" not in pre_cols
    assert "event_id" not in pre_cols

    schema._apply_migration_v8(conn)

    post_cols = _column_names(conn, "message_queue")
    assert "origin" in post_cols
    assert "route_id" in post_cols
    assert "event_id" in post_cols


# ──────────────────────────────────────────────────────────────────────
# (b) Idempotent re-apply
# ──────────────────────────────────────────────────────────────────────


def test_migration_v8_is_idempotent(tmp_path: Path) -> None:
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    # Second application MUST NOT raise (CREATE TABLE IF NOT EXISTS,
    # column-exists PRAGMA check, CREATE INDEX IF NOT EXISTS).
    schema._apply_migration_v8(conn)
    schema._apply_migration_v8(conn)
    # Schema is unchanged after multiple applications.
    assert "routes" in _table_names(conn)
    assert _column_names(conn, "message_queue") >= {"origin", "route_id", "event_id"}


# ──────────────────────────────────────────────────────────────────────
# (c) Interrupted prior application (column added, index missing) resumes
# ──────────────────────────────────────────────────────────────────────


def test_migration_v8_resumes_after_partial_application(tmp_path: Path) -> None:
    conn, _ = _open_v7_only(tmp_path)
    # Simulate an interrupted prior application: column added, index
    # not yet created.
    conn.execute(
        "ALTER TABLE message_queue "
        "ADD COLUMN origin TEXT NOT NULL DEFAULT 'direct'"
    )
    conn.execute("ALTER TABLE message_queue ADD COLUMN route_id TEXT")
    conn.execute("ALTER TABLE message_queue ADD COLUMN event_id INTEGER")
    # Routes table missing, partial UNIQUE index missing.
    assert "routes" not in _table_names(conn)

    schema._apply_migration_v8(conn)

    assert "routes" in _table_names(conn)
    assert "idx_message_queue_route_event" in _index_names(conn)


# ──────────────────────────────────────────────────────────────────────
# (d) Existing FEAT-009 rows get origin='direct'; no data loss
# ──────────────────────────────────────────────────────────────────────


def test_migration_v8_preserves_existing_direct_rows(tmp_path: Path) -> None:
    conn, _ = _open_v7_only(tmp_path)
    _insert_minimal_direct_queue_row(conn, message_id="msg_001")
    _insert_minimal_direct_queue_row(conn, message_id="msg_002")

    schema._apply_migration_v8(conn)

    rows = conn.execute(
        "SELECT message_id, origin, route_id, event_id "
        "FROM message_queue ORDER BY message_id"
    ).fetchall()
    assert rows == [
        ("msg_001", "direct", None, None),
        ("msg_002", "direct", None, None),
    ]


# ──────────────────────────────────────────────────────────────────────
# (e) Partial UNIQUE index — duplicate-routing defense
# ──────────────────────────────────────────────────────────────────────


def _insert_route_tagged_queue_row(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    route_id: str,
    event_id: int,
) -> None:
    """Insert a route-tagged message_queue row (origin='route')."""
    conn.execute(
        """
        INSERT INTO message_queue (
            message_id, state, sender_agent_id, sender_label, sender_role,
            target_agent_id, target_label, target_role,
            target_container_id, target_pane_id,
            envelope_body, envelope_body_sha256, envelope_size_bytes,
            enqueued_at, last_updated_at,
            origin, route_id, event_id
        ) VALUES (?, 'queued', 'agt_master00001', 'm1', 'master',
                  'agt_slave000001', 's1', 'slave',
                  'ctn_x', 'pn_x',
                  X'68656c6c6f', 'sha', 5,
                  '2026-05-17T00:00:00.000Z', '2026-05-17T00:00:00.000Z',
                  'route', ?, ?)
        """,
        (message_id, route_id, event_id),
    )


def test_partial_unique_index_rejects_duplicate_route_event(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    _insert_route_tagged_queue_row(
        conn, message_id="msg_001",
        route_id="11111111-2222-4333-8444-555555555555", event_id=42,
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _insert_route_tagged_queue_row(
            conn, message_id="msg_002",
            route_id="11111111-2222-4333-8444-555555555555", event_id=42,
        )


def test_partial_unique_index_ignores_direct_rows(tmp_path: Path) -> None:
    """Direct-send rows (origin='direct') always have NULL route_id /
    event_id; the WHERE-clause excludes them from the UNIQUE constraint
    so multiple direct rows can coexist freely."""
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    _insert_minimal_direct_queue_row(conn, message_id="msg_001")
    _insert_minimal_direct_queue_row(conn, message_id="msg_002")
    _insert_minimal_direct_queue_row(conn, message_id="msg_003")
    count = conn.execute("SELECT COUNT(*) FROM message_queue").fetchone()[0]
    assert count == 3


# ──────────────────────────────────────────────────────────────────────
# (f) routes-table CHECK constraints
# ──────────────────────────────────────────────────────────────────────


_INSERT_ROUTE_SQL = """
INSERT INTO routes (
    route_id, event_type,
    source_scope_kind, source_scope_value,
    target_rule, target_value,
    master_rule, master_value,
    template, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def test_routes_check_event_type_closed_set(tmp_path: Path) -> None:
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            _INSERT_ROUTE_SQL,
            ("r1", "not_a_real_event_type", "any", None,
             "explicit", "agt_slave000001", "auto", None,
             "tmpl {event_excerpt}",
             "2026-05-17T00:00:00.000Z", "2026-05-17T00:00:00.000Z"),
        )


def test_routes_check_source_scope_kind_any_requires_null_value(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            _INSERT_ROUTE_SQL,
            ("r1", "waiting_for_input",
             "any", "role:slave",  # any kind must have NULL value
             "explicit", "agt_slave000001", "auto", None,
             "tmpl",
             "2026-05-17T00:00:00.000Z", "2026-05-17T00:00:00.000Z"),
        )


def test_routes_check_target_rule_source_requires_null_value(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            _INSERT_ROUTE_SQL,
            ("r1", "waiting_for_input", "any", None,
             "source", "agt_slave000001",  # source must have NULL target_value
             "auto", None,
             "tmpl",
             "2026-05-17T00:00:00.000Z", "2026-05-17T00:00:00.000Z"),
        )


def test_routes_check_master_rule_explicit_requires_master_value(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            _INSERT_ROUTE_SQL,
            ("r1", "waiting_for_input", "any", None,
             "explicit", "agt_slave000001",
             "explicit", None,  # explicit master must have master_value
             "tmpl",
             "2026-05-17T00:00:00.000Z", "2026-05-17T00:00:00.000Z"),
        )


def test_routes_accepts_well_formed_row(tmp_path: Path) -> None:
    conn, _ = _open_v7_only(tmp_path)
    schema._apply_migration_v8(conn)
    conn.execute(
        _INSERT_ROUTE_SQL,
        ("11111111-2222-4333-8444-555555555555",
         "waiting_for_input", "any", None,
         "explicit", "agt_slave000001",
         "auto", None,
         "respond to {source_label}: {event_excerpt}",
         "2026-05-17T00:00:00.000Z", "2026-05-17T00:00:00.000Z"),
    )
    row = conn.execute(
        "SELECT route_id, enabled, last_consumed_event_id FROM routes"
    ).fetchone()
    assert row == ("11111111-2222-4333-8444-555555555555", 1, 0)


# ──────────────────────────────────────────────────────────────────────
# Schema version contract
# ──────────────────────────────────────────────────────────────────────


def test_current_schema_version_is_eight() -> None:
    assert schema.CURRENT_SCHEMA_VERSION == 8


def test_migration_v8_is_registered() -> None:
    assert 8 in schema._MIGRATIONS
    assert schema._MIGRATIONS[8] is schema._apply_migration_v8


def test_pending_migrations_v7_to_v8_via_open(tmp_path: Path) -> None:
    """End-to-end: open_registry on a v7 DB upgrades to v8 atomically."""
    import os
    conn, state_db = _open_v7_only(tmp_path)
    conn.close()
    # Match the file-mode invariant enforced by open_registry (0o600).
    os.chmod(state_db, 0o600)
    opened, _status = schema.open_registry(state_db)
    try:
        version = opened.execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        assert version == 8
        assert "routes" in _table_names(opened)
    finally:
        opened.close()
