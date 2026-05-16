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

CURRENT_SCHEMA_VERSION = 7

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


def _apply_migration_v3(conn: sqlite3.Connection) -> None:
    """Create FEAT-004 tables. Idempotent because of IF NOT EXISTS guards.

    Adds two tables — ``panes`` and ``pane_scans`` — and three indexes.
    Touches no existing FEAT-003 table (FR-030).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS panes (
            container_id            TEXT NOT NULL,
            tmux_socket_path        TEXT NOT NULL,
            tmux_session_name       TEXT NOT NULL,
            tmux_window_index       INTEGER NOT NULL,
            tmux_pane_index         INTEGER NOT NULL,
            tmux_pane_id            TEXT NOT NULL,
            container_name          TEXT NOT NULL,
            container_user          TEXT NOT NULL,
            pane_pid                INTEGER NOT NULL,
            pane_tty                TEXT NOT NULL,
            pane_current_command    TEXT NOT NULL,
            pane_current_path       TEXT NOT NULL,
            pane_title              TEXT NOT NULL,
            pane_active             INTEGER NOT NULL CHECK(pane_active IN (0, 1)),
            active                  INTEGER NOT NULL CHECK(active IN (0, 1)),
            first_seen_at           TEXT NOT NULL,
            last_scanned_at         TEXT NOT NULL,
            PRIMARY KEY (
                container_id,
                tmux_socket_path,
                tmux_session_name,
                tmux_window_index,
                tmux_pane_index,
                tmux_pane_id
            )
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS panes_active_order
            ON panes(active DESC, container_id ASC, tmux_socket_path ASC,
                     tmux_session_name ASC, tmux_window_index ASC,
                     tmux_pane_index ASC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS panes_container_socket
            ON panes(container_id, tmux_socket_path)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pane_scans (
            scan_id                      TEXT PRIMARY KEY,
            started_at                   TEXT NOT NULL,
            completed_at                 TEXT NOT NULL,
            status                       TEXT NOT NULL CHECK(status IN ('ok', 'degraded')),
            containers_scanned           INTEGER NOT NULL,
            sockets_scanned              INTEGER NOT NULL,
            panes_seen                   INTEGER NOT NULL,
            panes_newly_active           INTEGER NOT NULL,
            panes_reconciled_inactive    INTEGER NOT NULL,
            containers_skipped_inactive  INTEGER NOT NULL,
            containers_tmux_unavailable  INTEGER NOT NULL,
            error_code                   TEXT,
            error_message                TEXT,
            error_details_json           TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS pane_scans_started
            ON pane_scans(started_at DESC)
        """
    )


def _apply_migration_v4(conn: sqlite3.Connection) -> None:
    """Create FEAT-006 ``agents`` table + indexes (data-model.md §2.1, §2.2).

    Idempotent because of IF NOT EXISTS guards. Touches no FEAT-001 /
    FEAT-002 / FEAT-003 / FEAT-004 table (FR-037).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            agent_id                 TEXT NOT NULL PRIMARY KEY,
            container_id             TEXT NOT NULL,
            tmux_socket_path         TEXT NOT NULL,
            tmux_session_name        TEXT NOT NULL,
            tmux_window_index        INTEGER NOT NULL,
            tmux_pane_index          INTEGER NOT NULL,
            tmux_pane_id             TEXT NOT NULL,
            role                     TEXT NOT NULL CHECK(role IN ('master','slave','swarm','test-runner','shell','unknown')),
            capability               TEXT NOT NULL CHECK(capability IN ('claude','codex','gemini','opencode','shell','test-runner','unknown')),
            label                    TEXT NOT NULL DEFAULT '',
            project_path             TEXT NOT NULL DEFAULT '',
            parent_agent_id          TEXT,
            effective_permissions    TEXT NOT NULL,
            created_at               TEXT NOT NULL,
            last_registered_at       TEXT NOT NULL,
            last_seen_at             TEXT,
            active                   INTEGER NOT NULL CHECK(active IN (0, 1)),
            UNIQUE (
                container_id,
                tmux_socket_path,
                tmux_session_name,
                tmux_window_index,
                tmux_pane_index,
                tmux_pane_id
            )
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS agents_active_order
            ON agents(active DESC, container_id ASC, parent_agent_id ASC,
                      label ASC, agent_id ASC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS agents_parent_lookup
            ON agents(parent_agent_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS agents_pane_lookup
            ON agents(container_id, tmux_socket_path, tmux_session_name,
                      tmux_window_index, tmux_pane_index, tmux_pane_id)
        """
    )


def _apply_migration_v5(conn: sqlite3.Connection) -> None:
    """Create FEAT-007 ``log_attachments`` and ``log_offsets`` tables.

    Idempotent via IF NOT EXISTS. Touches no FEAT-001..006 table
    (data-model.md §1; spec FR-014..FR-017).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_attachments (
            attachment_id              TEXT PRIMARY KEY,
            agent_id                   TEXT NOT NULL,
            container_id               TEXT NOT NULL,
            tmux_socket_path           TEXT NOT NULL,
            tmux_session_name          TEXT NOT NULL,
            tmux_window_index          INTEGER NOT NULL,
            tmux_pane_index            INTEGER NOT NULL,
            tmux_pane_id               TEXT NOT NULL,
            log_path                   TEXT NOT NULL,
            status                     TEXT NOT NULL
                CHECK(status IN ('active','superseded','stale','detached')),
            source                     TEXT NOT NULL
                CHECK(source IN ('explicit','register_self')),
            pipe_pane_command          TEXT NOT NULL,
            prior_pipe_target          TEXT,
            attached_at                TEXT NOT NULL,
            last_status_at             TEXT NOT NULL,
            superseded_at              TEXT,
            superseded_by              TEXT,
            created_at                 TEXT NOT NULL,
            FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE RESTRICT,
            FOREIGN KEY (superseded_by) REFERENCES log_attachments(attachment_id) ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS log_attachments_agent_status
            ON log_attachments(agent_id, status, last_status_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS log_attachments_pane_status
            ON log_attachments(container_id, tmux_socket_path, tmux_session_name,
                               tmux_window_index, tmux_pane_index, tmux_pane_id,
                               status)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS log_attachments_active_log_path
            ON log_attachments(log_path) WHERE status = 'active'
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_offsets (
            agent_id                   TEXT NOT NULL,
            log_path                   TEXT NOT NULL,
            byte_offset                INTEGER NOT NULL DEFAULT 0,
            line_offset                INTEGER NOT NULL DEFAULT 0,
            last_event_offset          INTEGER NOT NULL DEFAULT 0,
            last_output_at             TEXT,
            file_inode                 TEXT,
            file_size_seen             INTEGER NOT NULL DEFAULT 0,
            created_at                 TEXT NOT NULL,
            updated_at                 TEXT NOT NULL,
            PRIMARY KEY (agent_id, log_path),
            FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS log_offsets_agent
            ON log_offsets(agent_id)
        """
    )


def _apply_migration_v6(conn: sqlite3.Connection) -> None:
    """FEAT-008 — add the durable ``events`` table and its indexes.

    See ``specs/008-event-ingestion-follow/data-model.md`` §2 for the
    column reference. Idempotent (``IF NOT EXISTS``); the table starts
    empty (no backfill).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type         TEXT NOT NULL CHECK (event_type IN (
                'activity', 'waiting_for_input', 'completed', 'error',
                'test_failed', 'test_passed', 'manual_review_needed',
                'long_running', 'pane_exited', 'swarm_member_reported'
            )),
            agent_id           TEXT NOT NULL,
            attachment_id      TEXT NOT NULL,
            log_path           TEXT NOT NULL,
            byte_range_start   INTEGER NOT NULL CHECK (byte_range_start >= 0),
            byte_range_end     INTEGER NOT NULL CHECK (byte_range_end >= byte_range_start),
            line_offset_start  INTEGER NOT NULL CHECK (line_offset_start >= 0),
            line_offset_end    INTEGER NOT NULL CHECK (line_offset_end >= line_offset_start),
            observed_at        TEXT NOT NULL,
            -- P7 (review MEDIUM) — record_at is reserved for a future
            -- non-breaking schema bump; in MVP it MUST always be NULL
            -- (Clarifications Q3). Defense-in-depth: enforce at the
            -- DB layer so a buggy client cannot accidentally write
            -- a non-NULL value.
            record_at          TEXT CHECK (record_at IS NULL),
            excerpt            TEXT NOT NULL,
            classifier_rule_id TEXT NOT NULL,
            debounce_window_id          TEXT,
            debounce_collapsed_count    INTEGER NOT NULL DEFAULT 1
                                        CHECK (debounce_collapsed_count >= 1),
            debounce_window_started_at  TEXT,
            debounce_window_ended_at    TEXT,
            schema_version     INTEGER NOT NULL DEFAULT 1
                               CHECK (schema_version >= 1),
            jsonl_appended_at  TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_events_agent_eventid
            ON events (agent_id, event_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_events_type_eventid
            ON events (event_type, event_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_events_observedat_eventid
            ON events (observed_at, event_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_events_jsonl_pending
            ON events (event_id) WHERE jsonl_appended_at IS NULL
        """
    )


def _migration_v7_now_iso_ms_utc() -> str:
    """Local helper for the v7 seed row.

    Returns the canonical FEAT-009 timestamp form (FR-012b):
    ``YYYY-MM-DDTHH:MM:SS.sssZ`` in UTC with millisecond resolution.
    Implemented locally to avoid an import-order dependency on the
    ``routing.timestamps`` module during schema setup.
    """
    from datetime import datetime, UTC

    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _apply_migration_v7(conn: sqlite3.Connection) -> None:
    """FEAT-009 — three-part migration v6 → v7.

    Part 1: add the ``message_queue`` and ``daemon_state`` tables plus
    four supporting indexes (data-model.md §2). Seed the ``daemon_state``
    routing flag row with ``INSERT OR IGNORE`` so re-running on a v7 DB
    is a no-op.

    Part 2: rebuild the FEAT-008 ``events`` table to (a) widen its
    ``event_type`` CHECK to accept the 8 FEAT-009 audit types, and
    (b) make the FEAT-008-specific NOT NULL columns nullable so the
    FR-046 dual-write path can insert queue audit rows that omit them.
    Uses the standard SQLite ``CREATE TABLE …_new`` → ``INSERT INTO
    …_new SELECT * FROM events`` → ``DROP TABLE events`` → ``ALTER
    TABLE …_new RENAME TO events`` rebuild pattern. Existing FEAT-008
    rows survive byte-for-byte (asserted by test_schema_migration_v7).

    Part 3: recreate the four FEAT-008 indexes that ``DROP TABLE``
    dropped.

    The whole migration runs under the existing ``BEGIN IMMEDIATE``
    transaction in ``_apply_pending_migrations``; partial application
    is impossible.
    """
    # ─────────────────────────────────────────────────────────────────
    # Part 1: message_queue + daemon_state + four indexes + seed row
    # ─────────────────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS message_queue (
            message_id                   TEXT PRIMARY KEY,
            state                        TEXT NOT NULL CHECK (state IN (
                'queued', 'blocked', 'delivered', 'canceled', 'failed'
            )),
            block_reason                 TEXT CHECK (
                block_reason IS NULL OR block_reason IN (
                    'sender_role_not_permitted',
                    'target_role_not_permitted',
                    'target_not_active',
                    'target_pane_missing',
                    'target_container_inactive',
                    'kill_switch_off',
                    'operator_delayed'
                )
            ),
            failure_reason               TEXT CHECK (
                failure_reason IS NULL OR failure_reason IN (
                    'attempt_interrupted',
                    'tmux_paste_failed',
                    'docker_exec_failed',
                    'tmux_send_keys_failed',
                    'pane_disappeared_mid_attempt',
                    'sqlite_lock_conflict'
                )
            ),
            sender_agent_id              TEXT NOT NULL,
            sender_label                 TEXT NOT NULL,
            sender_role                  TEXT NOT NULL,
            sender_capability            TEXT,
            target_agent_id              TEXT NOT NULL,
            target_label                 TEXT NOT NULL,
            target_role                  TEXT NOT NULL,
            target_capability            TEXT,
            target_container_id          TEXT NOT NULL,
            target_pane_id               TEXT NOT NULL,
            envelope_body                BLOB NOT NULL,
            envelope_body_sha256         TEXT NOT NULL,
            envelope_size_bytes          INTEGER NOT NULL CHECK (envelope_size_bytes > 0),
            enqueued_at                  TEXT NOT NULL,
            delivery_attempt_started_at  TEXT,
            delivered_at                 TEXT,
            failed_at                    TEXT,
            canceled_at                  TEXT,
            last_updated_at              TEXT NOT NULL,
            operator_action              TEXT CHECK (operator_action IS NULL OR operator_action IN (
                'approved', 'delayed', 'canceled'
            )),
            operator_action_at           TEXT,
            operator_action_by           TEXT,
            CHECK (block_reason IS NULL OR state = 'blocked'),
            CHECK (failure_reason IS NULL OR state = 'failed'),
            CHECK (
                (operator_action IS NULL AND operator_action_at IS NULL AND operator_action_by IS NULL)
                OR
                (operator_action IS NOT NULL AND operator_action_at IS NOT NULL AND operator_action_by IS NOT NULL)
            ),
            CHECK (state != 'delivered' OR delivered_at IS NOT NULL),
            CHECK (state != 'failed'    OR failed_at    IS NOT NULL),
            CHECK (state != 'canceled'  OR canceled_at  IS NOT NULL)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_message_queue_state_enqueued
            ON message_queue (state, enqueued_at, message_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_message_queue_target_enqueued
            ON message_queue (target_agent_id, enqueued_at, message_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_message_queue_sender_enqueued
            ON message_queue (sender_agent_id, enqueued_at, message_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_message_queue_in_flight
            ON message_queue (target_agent_id)
            WHERE delivery_attempt_started_at IS NOT NULL
              AND delivered_at IS NULL
              AND failed_at   IS NULL
              AND canceled_at IS NULL
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daemon_state (
            key             TEXT PRIMARY KEY CHECK (key IN ('routing_enabled')),
            value           TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            last_updated_by TEXT NOT NULL,
            CHECK (
                (key = 'routing_enabled' AND value IN ('enabled', 'disabled'))
            )
        )
        """
    )
    # Seed routing flag (idempotent on re-migration via INSERT OR IGNORE).
    # `last_updated_by='(daemon-init)'` distinguishes the migration-created
    # default from real operator toggles (which write 'host-operator' for
    # host-side toggles or an `agt_<12-hex>` agent_id for in-container
    # callers — though `routing.enable`/`disable` are host-only in MVP).
    conn.execute(
        """
        INSERT OR IGNORE INTO daemon_state (key, value, last_updated_at, last_updated_by)
        VALUES ('routing_enabled', 'enabled', ?, '(daemon-init)')
        """,
        (_migration_v7_now_iso_ms_utc(),),
    )

    # ─────────────────────────────────────────────────────────────────
    # Part 2: rebuild FEAT-008 events table (idempotent — skip if already
    # in v7 shape)
    # ─────────────────────────────────────────────────────────────────
    # The v6 schema (see _apply_migration_v6 above) declared the
    # FEAT-008-specific columns as NOT NULL and pinned event_type to
    # the FEAT-008 closed set. FEAT-009's FR-046 dual-write requires:
    #   - event_type CHECK widened to include 8 FEAT-009 audit types
    #   - attachment_id, log_path, byte_range_*, line_offset_*,
    #     classifier_rule_id → NULLABLE (FEAT-009 rows omit them)
    # SQLite cannot ALTER CHECK or NULLABLE in place; rebuild required.
    #
    # Idempotency: the fresh-DB seed path in `_ensure_current_schema`
    # re-runs every migration on every boot of an at-current-version
    # DB. We must not rebuild a table that is already in v7 shape.
    # Use PRAGMA table_info to detect: in v6 shape `attachment_id`
    # has notnull=1; in v7 shape it has notnull=0.
    pragma = conn.execute("PRAGMA table_info(events)").fetchall()
    if not pragma:
        # Defensive: events table does not exist yet (v6 migration
        # ran in this same transaction immediately before, but a
        # caller could in theory invoke v7 in isolation). Skip the
        # rebuild — Part 2/3 require an existing table.
        return
    column_notnull = {row[1]: row[3] for row in pragma}
    if column_notnull.get("attachment_id", 0) == 0:
        # Already nullable → already in v7 shape (or beyond). Skip.
        return

    conn.execute(
        """
        CREATE TABLE events_new (
            event_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type         TEXT NOT NULL CHECK (event_type IN (
                -- FEAT-008 durable classifier types (10)
                'activity', 'waiting_for_input', 'completed', 'error',
                'test_failed', 'test_passed', 'manual_review_needed',
                'long_running', 'pane_exited', 'swarm_member_reported',
                -- FEAT-009 audit types (8)
                'queue_message_enqueued', 'queue_message_delivered',
                'queue_message_blocked', 'queue_message_failed',
                'queue_message_canceled', 'queue_message_approved',
                'queue_message_delayed', 'routing_toggled'
            )),
            agent_id           TEXT NOT NULL,
            attachment_id      TEXT,
            log_path           TEXT,
            -- FEAT-009 audit rows insert NULL for all four range columns.
            -- FEAT-008 classifier rows insert non-NULL pairs only. The
            -- conditional ranges guard the FEAT-008 invariant
            -- (end >= start) WHILE preserving the FEAT-009 NULL-pair
            -- shape. Both columns of a pair MUST be set together — a
            -- per-column CHECK can't enforce that on its own (it only
            -- sees its own value), so we add a table-level CHECK
            -- below that pins the paired-nullability invariant.
            byte_range_start   INTEGER CHECK (byte_range_start IS NULL OR byte_range_start >= 0),
            byte_range_end     INTEGER CHECK (
                byte_range_end IS NULL
                OR (byte_range_start IS NOT NULL AND byte_range_end >= byte_range_start)
            ),
            line_offset_start  INTEGER CHECK (line_offset_start IS NULL OR line_offset_start >= 0),
            line_offset_end    INTEGER CHECK (
                line_offset_end IS NULL
                OR (line_offset_start IS NOT NULL AND line_offset_end >= line_offset_start)
            ),
            observed_at        TEXT NOT NULL,
            -- record_at remains MVP-locked to NULL (FEAT-008 invariant).
            record_at          TEXT CHECK (record_at IS NULL),
            excerpt            TEXT NOT NULL,
            classifier_rule_id TEXT,
            debounce_window_id          TEXT,
            debounce_collapsed_count    INTEGER NOT NULL DEFAULT 1
                                        CHECK (debounce_collapsed_count >= 1),
            debounce_window_started_at  TEXT,
            debounce_window_ended_at    TEXT,
            schema_version     INTEGER NOT NULL DEFAULT 1
                               CHECK (schema_version >= 1),
            jsonl_appended_at  TEXT,
            -- Paired-nullability invariants for the FEAT-008 byte/line
            -- range columns. Per-column CHECKs above guard ``>= 0`` and
            -- ``end >= start`` shapes, but only a table-level CHECK can
            -- enforce "both NULL or both non-NULL" — the per-column
            -- forms can't see the other column. Without this constraint
            -- a row could insert with only one half of a pair populated
            -- (start without end OR end without start), breaking the
            -- FEAT-008 invariant that classifier rows always have both
            -- bounds.
            CHECK (
                (byte_range_start IS NULL AND byte_range_end IS NULL)
                OR (byte_range_start IS NOT NULL AND byte_range_end IS NOT NULL)
            ),
            CHECK (
                (line_offset_start IS NULL AND line_offset_end IS NULL)
                OR (line_offset_start IS NOT NULL AND line_offset_end IS NOT NULL)
            )
        )
        """
    )
    conn.execute("INSERT INTO events_new SELECT * FROM events")
    conn.execute("DROP TABLE events")
    conn.execute("ALTER TABLE events_new RENAME TO events")

    # ─────────────────────────────────────────────────────────────────
    # Part 3: recreate the four FEAT-008 indexes (DROP TABLE removed them).
    # ─────────────────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE INDEX idx_events_agent_eventid
            ON events (agent_id, event_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX idx_events_type_eventid
            ON events (event_type, event_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX idx_events_observedat_eventid
            ON events (observed_at, event_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX idx_events_jsonl_pending
            ON events (event_id) WHERE jsonl_appended_at IS NULL
        """
    )


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _apply_migration_v2,
    3: _apply_migration_v3,
    4: _apply_migration_v4,
    5: _apply_migration_v5,
    6: _apply_migration_v6,
    7: _apply_migration_v7,
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
    # Existing DB at current version: ensure FEAT-003 + FEAT-004 + FEAT-006
    # + FEAT-007 + FEAT-008 tables exist in case the schema_version row got
    # there ahead of the tables (defensive — every migration body uses
    # IF NOT EXISTS). This ALSO applies on fresh databases: a brand-new
    # registry has its schema_version row inserted at CURRENT_SCHEMA_VERSION
    # (so ``_apply_pending_migrations`` is skipped) and relies on this
    # branch to create every per-feature table.
    _apply_migration_v2(conn)
    _apply_migration_v3(conn)
    _apply_migration_v4(conn)
    _apply_migration_v5(conn)
    _apply_migration_v6(conn)
    _apply_migration_v7(conn)


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
