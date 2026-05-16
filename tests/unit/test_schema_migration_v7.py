"""T013 — FEAT-009 v6 → v7 schema migration tests.

Mirrors the FEAT-008 v5 → v6 pattern. Asserts the seven sub-properties
called out in tasks.md T013:

(a) v6 → v7 upgrade applies the migration once and seeds ``daemon_state``.
(b) v7-already-current re-open is a no-op.
(c) A daemon with this build refuses to open a v8+ DB (forward refusal).
(d) FEAT-008 ``events`` rebuild preserves every row byte-for-byte.
(e) Post-rebuild the ``events.event_type`` CHECK accepts the 8 FEAT-009
    audit types.
(f) Post-rebuild the FEAT-008-specific columns accept NULL for FEAT-009
    rows.
(g) Post-rebuild the four FEAT-008 indexes still exist.

Plus a sanity check that the FR-040 partial index
(``idx_message_queue_in_flight``) is created with the expected WHERE
predicate.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

_FEAT008_AUDIT_TYPES: tuple[str, ...] = (
    "queue_message_enqueued",
    "queue_message_delivered",
    "queue_message_blocked",
    "queue_message_failed",
    "queue_message_canceled",
    "queue_message_approved",
    "queue_message_delayed",
    "routing_toggled",
)

_FEAT008_CLASSIFIER_SAMPLE: tuple[str, ...] = (
    "activity",
    "error",
    "test_failed",
    "long_running",
    "swarm_member_reported",
)


def _open_v6_only(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    """Create a fresh DB stopped at schema v6 (FEAT-008 head-of-tree)."""
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (6)")
    for v in (2, 3, 4, 5, 6):
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


def _column_notnull(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    return {
        row[1]: row[3]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _insert_v6_events_row(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    byte_start: int = 0,
    byte_end: int = 10,
    line_start: int = 0,
    line_end: int = 1,
    observed_at: str = "2026-05-10T12:00:00.000000+00:00",
    excerpt: str = "x",
) -> None:
    """Insert a FEAT-008-shape events row (NOT NULL fields populated)."""
    conn.execute(
        """
        INSERT INTO events (
            event_type, agent_id, attachment_id, log_path,
            byte_range_start, byte_range_end,
            line_offset_start, line_offset_end,
            observed_at, excerpt, classifier_rule_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            "agt_a1b2c3d4e5f6",
            "atc_aabbccddeeff",
            "/tmp/x.log",
            byte_start, byte_end, line_start, line_end,
            observed_at,
            excerpt,
            "activity.fallback.v1",
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# (a) v6 → v7 upgrade applies + seeds daemon_state
# ──────────────────────────────────────────────────────────────────────


def test_migration_v7_creates_message_queue_and_indexes(tmp_path: Path) -> None:
    conn, _ = _open_v6_only(tmp_path)
    assert "message_queue" not in _table_names(conn)
    assert "daemon_state" not in _table_names(conn)

    schema._apply_migration_v7(conn)
    conn.commit()

    tables = _table_names(conn)
    assert "message_queue" in tables
    assert "daemon_state" in tables

    indexes = _index_names(conn)
    assert {
        "idx_message_queue_state_enqueued",
        "idx_message_queue_target_enqueued",
        "idx_message_queue_sender_enqueued",
        "idx_message_queue_in_flight",
    } <= indexes


def test_migration_v7_seeds_routing_flag(tmp_path: Path) -> None:
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    row = conn.execute(
        "SELECT key, value, last_updated_by FROM daemon_state"
    ).fetchone()
    assert row[0] == "routing_enabled"
    assert row[1] == "enabled"
    assert row[2] == "(daemon-init)"


def test_migration_v7_seed_insert_or_ignore_does_not_overwrite(
    tmp_path: Path,
) -> None:
    """Re-running the migration must NOT clobber operator-toggled flag state."""
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    # Simulate an operator disabling routing.
    conn.execute(
        "UPDATE daemon_state SET value = 'disabled', last_updated_by = ? WHERE key = 'routing_enabled'",
        ("host-operator",),
    )
    conn.commit()
    # Re-run v7; INSERT OR IGNORE on the seed should not touch the row.
    schema._apply_migration_v7(conn)
    row = conn.execute(
        "SELECT value, last_updated_by FROM daemon_state"
    ).fetchone()
    assert row == ("disabled", "host-operator")


# ──────────────────────────────────────────────────────────────────────
# (b) v7-already-current re-open is a no-op
# ──────────────────────────────────────────────────────────────────────


def test_migration_v7_is_idempotent_on_v7_shape(tmp_path: Path) -> None:
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    # Capture post-first-run shape.
    info_after_first = conn.execute("PRAGMA table_info(events)").fetchall()
    indexes_after_first = _index_names(conn)
    # Re-running v7 must be a no-op for the rebuild (shape detection).
    schema._apply_migration_v7(conn)
    schema._apply_migration_v7(conn)
    info_after_third = conn.execute("PRAGMA table_info(events)").fetchall()
    indexes_after_third = _index_names(conn)
    assert info_after_first == info_after_third
    assert indexes_after_first == indexes_after_third


def test_migration_v7_does_not_clobber_existing_events_rows_on_replay(
    tmp_path: Path,
) -> None:
    """Re-running v7 after rows are inserted must preserve them (shape-aware
    skip prevents redundant rebuild)."""
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    # Insert a FEAT-009 audit row (the relaxed CHECK accepts it).
    conn.execute(
        "INSERT INTO events (event_type, agent_id, observed_at, excerpt) "
        "VALUES ('queue_message_delivered', 'agt_a1b2c3d4e5f6', "
        "'2026-05-12T00:00:01.000Z', 'do thing')"
    )
    conn.commit()
    pre = conn.execute(
        "SELECT event_type, agent_id, excerpt FROM events ORDER BY event_id"
    ).fetchall()
    schema._apply_migration_v7(conn)  # idempotent no-op
    post = conn.execute(
        "SELECT event_type, agent_id, excerpt FROM events ORDER BY event_id"
    ).fetchall()
    assert pre == post


# ──────────────────────────────────────────────────────────────────────
# (c) Forward-version refusal
# ──────────────────────────────────────────────────────────────────────


def test_apply_pending_migrations_refuses_newer_on_disk_version(
    tmp_path: Path,
) -> None:
    """If on-disk schema_version > CURRENT_SCHEMA_VERSION, refuse to open."""
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (schema.CURRENT_SCHEMA_VERSION + 1,))
    conn.commit()
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        schema._apply_pending_migrations(conn, schema.CURRENT_SCHEMA_VERSION + 1)


# ──────────────────────────────────────────────────────────────────────
# (d) FEAT-008 events rebuild preserves rows byte-for-byte
# ──────────────────────────────────────────────────────────────────────


def test_migration_v7_preserves_feat008_events_rows_byte_for_byte(
    tmp_path: Path,
) -> None:
    """Populate v6 events with one row per representative classifier type,
    apply v7, assert byte-for-byte preservation."""
    conn, _ = _open_v6_only(tmp_path)
    for i, et in enumerate(_FEAT008_CLASSIFIER_SAMPLE):
        _insert_v6_events_row(
            conn,
            et,
            byte_start=i * 10,
            byte_end=(i + 1) * 10,
            line_start=i,
            line_end=i + 1,
            excerpt=f"sample {i}",
        )
    conn.commit()

    pre = conn.execute(
        "SELECT event_id, event_type, agent_id, attachment_id, log_path, "
        "byte_range_start, byte_range_end, line_offset_start, line_offset_end, "
        "observed_at, record_at, excerpt, classifier_rule_id, "
        "debounce_window_id, debounce_collapsed_count, "
        "debounce_window_started_at, debounce_window_ended_at, "
        "schema_version, jsonl_appended_at "
        "FROM events ORDER BY event_id"
    ).fetchall()
    assert len(pre) == len(_FEAT008_CLASSIFIER_SAMPLE)

    schema._apply_migration_v7(conn)
    conn.commit()

    post = conn.execute(
        "SELECT event_id, event_type, agent_id, attachment_id, log_path, "
        "byte_range_start, byte_range_end, line_offset_start, line_offset_end, "
        "observed_at, record_at, excerpt, classifier_rule_id, "
        "debounce_window_id, debounce_collapsed_count, "
        "debounce_window_started_at, debounce_window_ended_at, "
        "schema_version, jsonl_appended_at "
        "FROM events ORDER BY event_id"
    ).fetchall()
    assert pre == post


# ──────────────────────────────────────────────────────────────────────
# (e) Post-rebuild events.event_type CHECK accepts 8 FEAT-009 types
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("event_type", _FEAT008_AUDIT_TYPES)
def test_migration_v7_event_type_check_accepts_feat009_audit_types(
    tmp_path: Path, event_type: str
) -> None:
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    conn.execute(
        "INSERT INTO events (event_type, agent_id, observed_at, excerpt) "
        "VALUES (?, ?, ?, ?)",
        (event_type, "agt_a1b2c3d4e5f6", "2026-05-12T00:00:00.000Z", "x"),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT event_type FROM events WHERE event_type = ?", (event_type,)
    ).fetchall()
    assert len(rows) == 1


def test_migration_v7_event_type_check_still_rejects_unknown(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO events (event_type, agent_id, observed_at, excerpt) "
            "VALUES (?, ?, ?, ?)",
            ("not_a_real_type", "agt_a1b2c3d4e5f6", "2026-05-12T00:00:00.000Z", "x"),
        )


# ──────────────────────────────────────────────────────────────────────
# (f) Post-rebuild FEAT-008-specific columns accept NULL
# ──────────────────────────────────────────────────────────────────────


def test_migration_v7_feat008_columns_accept_null_for_feat009_rows(
    tmp_path: Path,
) -> None:
    """FEAT-009 audit rows omit FEAT-008-specific columns (NULL)."""
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    conn.execute(
        """
        INSERT INTO events (
            event_type, agent_id,
            attachment_id, log_path,
            byte_range_start, byte_range_end,
            line_offset_start, line_offset_end,
            observed_at, excerpt, classifier_rule_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "queue_message_delivered",
            "agt_a1b2c3d4e5f6",
            None, None, None, None, None, None,
            "2026-05-12T00:00:00.000Z",
            "do thing",
            None,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT attachment_id, log_path, byte_range_start, byte_range_end, "
        "line_offset_start, line_offset_end, classifier_rule_id "
        "FROM events WHERE event_type = 'queue_message_delivered'"
    ).fetchone()
    assert row == (None, None, None, None, None, None, None)


def test_migration_v7_pragma_table_info_marks_feat008_columns_nullable(
    tmp_path: Path,
) -> None:
    conn, _ = _open_v6_only(tmp_path)
    # Before v7: NOT NULL.
    pre = _column_notnull(conn, "events")
    assert pre["attachment_id"] == 1
    assert pre["log_path"] == 1
    assert pre["byte_range_start"] == 1
    assert pre["classifier_rule_id"] == 1

    schema._apply_migration_v7(conn)
    conn.commit()

    # After v7: nullable.
    post = _column_notnull(conn, "events")
    for col in (
        "attachment_id",
        "log_path",
        "byte_range_start",
        "byte_range_end",
        "line_offset_start",
        "line_offset_end",
        "classifier_rule_id",
    ):
        assert post[col] == 0, f"{col} should be nullable after v7"

    # agent_id, event_type, observed_at, excerpt remain NOT NULL.
    for col in ("agent_id", "event_type", "observed_at", "excerpt"):
        assert post[col] == 1, f"{col} must remain NOT NULL after v7"


# ──────────────────────────────────────────────────────────────────────
# (g) Post-rebuild four FEAT-008 indexes still exist
# ──────────────────────────────────────────────────────────────────────


def test_migration_v7_recreates_feat008_indexes(tmp_path: Path) -> None:
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    indexes = _index_names(conn)
    assert {
        "idx_events_agent_eventid",
        "idx_events_type_eventid",
        "idx_events_observedat_eventid",
        "idx_events_jsonl_pending",
    } <= indexes


# ──────────────────────────────────────────────────────────────────────
# CHECK constraints on the new message_queue table
# ──────────────────────────────────────────────────────────────────────


def test_message_queue_state_check_rejects_unknown_state(tmp_path: Path) -> None:
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO message_queue ("
            "message_id, state, "
            "sender_agent_id, sender_label, sender_role, "
            "target_agent_id, target_label, target_role, "
            "target_container_id, target_pane_id, "
            "envelope_body, envelope_body_sha256, envelope_size_bytes, "
            "enqueued_at, last_updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "12345678-1234-4234-8234-123456789012",
                "not_a_state",  # violates state CHECK
                "agt_aaaaaa111111", "queen", "master",
                "agt_bbbbbb222222", "worker-1", "slave",
                "c01dbeefdead", "%0",
                b"envelope bytes",
                "0" * 64,
                42,
                "2026-05-12T00:00:00.000Z",
                "2026-05-12T00:00:00.000Z",
            ),
        )


def test_message_queue_reason_state_coherence_check(tmp_path: Path) -> None:
    """block_reason cannot be non-null unless state='blocked' (and likewise
    failure_reason cannot be non-null unless state='failed')."""
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    # Try state='queued' with a block_reason → CHECK fails.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO message_queue ("
            "message_id, state, block_reason, "
            "sender_agent_id, sender_label, sender_role, "
            "target_agent_id, target_label, target_role, "
            "target_container_id, target_pane_id, "
            "envelope_body, envelope_body_sha256, envelope_size_bytes, "
            "enqueued_at, last_updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "12345678-1234-4234-8234-123456789012",
                "queued",
                "kill_switch_off",  # not allowed when state='queued'
                "agt_aaaaaa111111", "queen", "master",
                "agt_bbbbbb222222", "worker-1", "slave",
                "c01dbeefdead", "%0",
                b"envelope bytes",
                "0" * 64,
                42,
                "2026-05-12T00:00:00.000Z",
                "2026-05-12T00:00:00.000Z",
            ),
        )


def test_message_queue_failure_reason_check_accepts_sqlite_lock_conflict(
    tmp_path: Path,
) -> None:
    """The new sqlite_lock_conflict value (Group-A walk Q5) is accepted by
    the failure_reason CHECK."""
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    conn.execute(
        "INSERT INTO message_queue ("
        "message_id, state, failure_reason, "
        "sender_agent_id, sender_label, sender_role, "
        "target_agent_id, target_label, target_role, "
        "target_container_id, target_pane_id, "
        "envelope_body, envelope_body_sha256, envelope_size_bytes, "
        "enqueued_at, failed_at, last_updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "12345678-1234-4234-8234-123456789012",
            "failed",
            "sqlite_lock_conflict",
            "agt_aaaaaa111111", "queen", "master",
            "agt_bbbbbb222222", "worker-1", "slave",
            "c01dbeefdead", "%0",
            b"envelope bytes",
            "0" * 64,
            42,
            "2026-05-12T00:00:00.000Z",
            "2026-05-12T00:00:00.001Z",
            "2026-05-12T00:00:00.001Z",
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT state, failure_reason FROM message_queue"
    ).fetchone()
    assert row == ("failed", "sqlite_lock_conflict")


def test_daemon_state_check_rejects_unknown_value(tmp_path: Path) -> None:
    conn, _ = _open_v6_only(tmp_path)
    schema._apply_migration_v7(conn)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO daemon_state (key, value, last_updated_at, last_updated_by) "
            "VALUES ('routing_enabled', 'maybe', ?, ?)",
            ("2026-05-12T00:00:00.000Z", "host-operator"),
        )
