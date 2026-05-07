"""Unit tests for FEAT-004 SQLite schema migration + panes helpers (T017 / FR-024 / FR-029 / FR-016)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from agenttower.state import panes as state_panes
from agenttower.state import schema
from agenttower.state.panes import (
    PaneReconcileWriteSet,
    PaneUpsert,
)


def _make_state_db(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    return state_dir / "agenttower.sqlite3"


def _seed_v2(state_db: Path) -> None:
    """Build a v2-shaped database (FEAT-003) without FEAT-004 tables."""
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        # Apply v2 body so containers / container_scans tables exist.
        schema._apply_migration_v2(conn)
    finally:
        conn.close()
    os.chmod(state_db, 0o600)


def _open(state_db: Path):
    return schema.open_registry(state_db, namespace_root=state_db.parent)


def test_v2_to_v3_migration_creates_panes_and_pane_scans(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v2(state_db)
    conn, status = _open(state_db)
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        # FEAT-006 bumped CURRENT_SCHEMA_VERSION to 4; v2→current still creates panes/pane_scans.
        assert version == schema.CURRENT_SCHEMA_VERSION
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"panes", "pane_scans", "containers", "container_scans"}.issubset(tables)
    finally:
        conn.close()


def test_v3_reopen_is_idempotent(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v2(state_db)
    _open(state_db)[0].close()
    conn, _ = _open(state_db)
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        # FEAT-006 bumped CURRENT_SCHEMA_VERSION to 4; v2→current still creates panes/pane_scans.
        assert version == schema.CURRENT_SCHEMA_VERSION
        # Both new indexes should exist after re-open.
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "panes_active_order" in indexes
        assert "pane_scans_started" in indexes
    finally:
        conn.close()


def test_open_registry_refuses_future_version(tmp_path: Path) -> None:
    """A schema_version newer than CURRENT_SCHEMA_VERSION must be refused.

    Originally written as ``test_open_registry_refuses_future_v4`` when
    ``CURRENT_SCHEMA_VERSION=3``; FEAT-006 bumped to 4 so the test now
    seeds ``CURRENT_SCHEMA_VERSION + 1`` to keep the forward-compat
    invariant testable independent of the build version.
    """
    state_db = _make_state_db(tmp_path)
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (schema.CURRENT_SCHEMA_VERSION + 1,),
        )
    finally:
        conn.close()
    os.chmod(state_db, 0o600)
    with pytest.raises(sqlite3.DatabaseError, match="newer than this build"):
        _open(state_db)


def test_panes_composite_upsert_preserves_first_seen_at(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v2(state_db)
    conn, _ = _open(state_db)
    try:
        upsert = PaneUpsert(
            container_id="c1",
            tmux_socket_path="/tmp/tmux-1000/default",
            tmux_session_name="work",
            tmux_window_index=0,
            tmux_pane_index=0,
            tmux_pane_id="%0",
            container_name="bench",
            container_user="user",
            pane_pid=1234,
            pane_tty="/dev/pts/0",
            pane_current_command="bash",
            pane_current_path="/workspace",
            pane_title="t",
            pane_active=True,
            last_scanned_at="2026-05-06T10:00:00.000000+00:00",
        )
        conn.execute("BEGIN IMMEDIATE")
        state_panes.apply_pane_reconcile_writeset(
            conn,
            write_set=PaneReconcileWriteSet(upserts=[upsert]),
            now_iso="2026-05-06T10:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
        first_row = conn.execute(
            "SELECT first_seen_at, last_scanned_at FROM panes"
        ).fetchone()
        assert first_row[0] == "2026-05-06T10:00:00.000000+00:00"

        # Second upsert with a different last_scanned_at must preserve first_seen_at.
        upsert2 = PaneUpsert(
            **{**upsert.__dict__, "pane_pid": 9999, "last_scanned_at": "2026-05-06T11:00:00.000000+00:00"}
        )
        conn.execute("BEGIN IMMEDIATE")
        state_panes.apply_pane_reconcile_writeset(
            conn,
            write_set=PaneReconcileWriteSet(upserts=[upsert2]),
            now_iso="2026-05-06T11:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
        row = conn.execute(
            "SELECT first_seen_at, last_scanned_at, pane_pid FROM panes"
        ).fetchone()
        assert row[0] == "2026-05-06T10:00:00.000000+00:00"  # preserved
        assert row[1] == "2026-05-06T11:00:00.000000+00:00"  # advanced
        assert row[2] == 9999  # other fields refreshed
    finally:
        conn.close()


def test_select_panes_for_listing_returns_deterministic_fr016_order(
    tmp_path: Path,
) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v2(state_db)
    conn, _ = _open(state_db)
    try:
        # Seed a containers row so the JOIN-safety guard passes.
        conn.execute(
            """
            INSERT INTO containers (container_id, name, image, status, labels_json,
                mounts_json, inspect_json, config_user, working_dir, active,
                first_seen_at, last_scanned_at)
            VALUES ('c1', 'bench', 'img', 'running', '{}', '[]', '{}', 'user',
                '/workspace', 1, '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00')
            """
        )
        # Three panes: inactive on socket /work, active on socket /default,
        # active on socket /default with a higher pane_index.
        keys = [
            ("c1", "/tmp/tmux-1000/work", "scratch", 0, 0, "%0", 0),
            ("c1", "/tmp/tmux-1000/default", "work", 0, 1, "%1", 1),
            ("c1", "/tmp/tmux-1000/default", "work", 0, 0, "%0", 1),
        ]
        for c, sock, sess, w, p, pid, active in keys:
            conn.execute(
                """
                INSERT INTO panes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c, sock, sess, w, p, pid, "bench", "user", 100, "/dev/pts/0",
                    "bash", "/workspace", "title", 0, active, "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
        rows = state_panes.select_panes_for_listing(conn)
        assert [(r.tmux_socket_path, r.tmux_pane_index, r.active) for r in rows] == [
            ("/tmp/tmux-1000/default", 0, True),
            ("/tmp/tmux-1000/default", 1, True),
            ("/tmp/tmux-1000/work", 0, False),
        ]
    finally:
        conn.close()


def test_select_panes_for_listing_active_only(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path)
    _seed_v2(state_db)
    conn, _ = _open(state_db)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, labels_json, "
            "mounts_json, inspect_json, config_user, working_dir, active, "
            "first_seen_at, last_scanned_at) VALUES "
            "('c', 'b', 'i', 's', '{}', '[]', '{}', 'u', '/w', 1, "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        for active in (1, 0):
            conn.execute(
                "INSERT INTO panes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "c", f"/tmp/tmux-1000/s{active}", "ses", 0, 0, f"%{active}",
                    "b", "u", 1, "/d", "bash", "/w", "t", 0, active,
                    "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
                ),
            )
        rows = state_panes.select_panes_for_listing(conn, active_only=True)
        assert len(rows) == 1
        assert rows[0].active is True
    finally:
        conn.close()


def test_select_panes_for_listing_excludes_orphan_panes(tmp_path: Path) -> None:
    """data-model §6 note 4 + contracts/socket-api.md §4.3 — panes whose
    container_id is not in containers are filtered out."""
    state_db = _make_state_db(tmp_path)
    _seed_v2(state_db)
    conn, _ = _open(state_db)
    try:
        conn.execute(
            "INSERT INTO panes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "orphan", "/tmp/tmux-1000/default", "s", 0, 0, "%0", "x", "u", 1,
                "/d", "bash", "/w", "t", 0, 1, "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        assert state_panes.select_panes_for_listing(conn) == []
    finally:
        conn.close()


def test_apply_pane_reconcile_writeset_rolls_back_on_failure(tmp_path: Path) -> None:
    """FR-024 — failed transaction must roll back; no partial pane row commits."""
    state_db = _make_state_db(tmp_path)
    _seed_v2(state_db)
    conn, _ = _open(state_db)
    try:
        good = PaneUpsert(
            container_id="c", tmux_socket_path="/tmp/tmux-1000/default",
            tmux_session_name="s", tmux_window_index=0, tmux_pane_index=0,
            tmux_pane_id="%0", container_name="b", container_user="u",
            pane_pid=1, pane_tty="/d", pane_current_command="bash",
            pane_current_path="/w", pane_title="t", pane_active=True,
            last_scanned_at="2026-05-06T10:00:00.000000+00:00",
        )
        conn.execute("BEGIN IMMEDIATE")
        state_panes.apply_pane_reconcile_writeset(
            conn, write_set=PaneReconcileWriteSet(upserts=[good]), now_iso="x"
        )
        # Force a failure inside the same transaction.
        try:
            conn.execute("INSERT INTO pane_scans (scan_id) VALUES (?)", ("missing-cols",))
            conn.execute("COMMIT")
        except (sqlite3.OperationalError, sqlite3.IntegrityError):
            conn.execute("ROLLBACK")
        # The pane row should NOT be committed.
        rows = conn.execute("SELECT COUNT(*) FROM panes").fetchone()
        assert rows[0] == 0
    finally:
        conn.close()
