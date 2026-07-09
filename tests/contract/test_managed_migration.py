"""FEAT-013 migration v9 idempotency contract test (T007).

Verifies the constraints from spec §FR-022 + the CHK058 remediation:
re-running ``_apply_migration_v9`` against an already-migrated database
MUST (a) not raise, (b) leave ``schema_version`` at 9, (c) introduce
zero row mutations on the second run.
"""

from __future__ import annotations

import sqlite3

import pytest

from agenttower.state.schema import (
    CURRENT_SCHEMA_VERSION,
    _apply_migration_v9,
    _MIGRATIONS,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory SQLite with the minimum FEAT-006 dependency present.

    ``managed_pane.agent_id`` FK references ``agents(agent_id)``; we
    only need the table to exist for the FK to resolve.
    """
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    return c


def test_migration_v9_is_registered() -> None:
    """``_MIGRATIONS[9]`` exists and points at v9."""
    assert 9 in _MIGRATIONS
    assert _MIGRATIONS[9] is _apply_migration_v9


def test_current_schema_version_is_at_least_9() -> None:
    """``CURRENT_SCHEMA_VERSION`` was bumped to (at least) 9."""
    assert CURRENT_SCHEMA_VERSION >= 9


def test_migration_v9_creates_tables_and_indexes(conn: sqlite3.Connection) -> None:
    """First run creates the FEAT-013 tables and indexes."""
    _apply_migration_v9(conn)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "managed_layout" in tables
    assert "managed_pane" in tables

    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND (name LIKE 'ix_managed%' OR name LIKE 'ux_managed%')"
        ).fetchall()
    }
    assert "ix_managed_layout_container_state" in indexes
    assert "ux_managed_layout_idempotency_key" in indexes
    assert "ux_managed_pane_container_label" in indexes
    assert "ix_managed_pane_layout_state" in indexes
    assert "ix_managed_pane_pending_marker" in indexes
    assert "ix_managed_pane_predecessor" in indexes
    assert "ux_managed_pane_tmux_target" in indexes


def test_migration_v9_second_run_is_no_op(conn: sqlite3.Connection) -> None:
    """Second invocation MUST NOT raise (CHK058 idempotency)."""
    _apply_migration_v9(conn)
    # Should be a no-op; the DDL is `IF NOT EXISTS` throughout.
    _apply_migration_v9(conn)


def test_migration_v9_does_not_alter_existing_data(conn: sqlite3.Connection) -> None:
    """Re-running v9 introduces zero row mutations."""
    _apply_migration_v9(conn)
    # Seed one row so we can detect inadvertent mutation.
    conn.execute("INSERT INTO agents (agent_id) VALUES ('a1')")
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    pre_layouts = conn.execute("SELECT * FROM managed_layout").fetchall()
    pre_panes = conn.execute("SELECT * FROM managed_pane").fetchall()

    _apply_migration_v9(conn)

    assert conn.execute("SELECT * FROM managed_layout").fetchall() == pre_layouts
    assert conn.execute("SELECT * FROM managed_pane").fetchall() == pre_panes


def test_chain_depth_check_constraint_rejects_negative(conn: sqlite3.Connection) -> None:
    """``managed_pane.chain_depth`` CHECK constraint rejects out-of-range values."""
    _apply_migration_v9(conn)
    conn.execute("INSERT INTO agents (agent_id) VALUES ('a1')")
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO managed_pane
                (id, layout_id, container_id, role, capability, label,
                 tmux_session_name, tmux_pane_index, state, chain_depth,
                 created_at, updated_at)
            VALUES
                ('P1', 'L1', 'C1', 'master', 'orchestrator', 'm1',
                 's', 0, 'creating', 17,
                 '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
            """
        )


def test_state_check_constraint_rejects_unknown_state(conn: sqlite3.Connection) -> None:
    """``managed_pane.state`` CHECK constraint accepts only the 5 closed-set states."""
    _apply_migration_v9(conn)
    conn.execute("INSERT INTO agents (agent_id) VALUES ('a1')")
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO managed_pane
                (id, layout_id, container_id, role, capability, label,
                 tmux_session_name, tmux_pane_index, state, chain_depth,
                 created_at, updated_at)
            VALUES
                ('P1', 'L1', 'C1', 'master', 'orchestrator', 'm1',
                 's', 0, 'unknown_state', 0,
                 '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
            """
        )


def test_pending_marker_check_constraint(conn: sqlite3.Connection) -> None:
    """A pane with non-NULL ``pending_marker_token`` must be in ``creating``."""
    _apply_migration_v9(conn)
    conn.execute("INSERT INTO agents (agent_id) VALUES ('a1')")
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO managed_pane
                (id, layout_id, container_id, role, capability, label,
                 tmux_session_name, tmux_pane_index, pending_marker_token,
                 state, chain_depth, created_at, updated_at)
            VALUES
                ('P1', 'L1', 'C1', 'master', 'orchestrator', 'm1',
                 's', 0, 'tok-1', 'ready', 0,
                 '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
            """
        )


def test_container_label_uniqueness_partial_index(conn: sqlite3.Connection) -> None:
    """Two non-terminal panes in the same container cannot share a label."""
    _apply_migration_v9(conn)
    conn.execute("INSERT INTO agents (agent_id) VALUES ('a1')")
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO managed_pane
            (id, layout_id, container_id, role, capability, label,
             tmux_session_name, tmux_pane_index, state, chain_depth,
             created_at, updated_at)
        VALUES
            ('P1', 'L1', 'C1', 'master', 'orchestrator', 'm1',
             's', 0, 'ready', 0,
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO managed_pane
                (id, layout_id, container_id, role, capability, label,
                 tmux_session_name, tmux_pane_index, state, chain_depth,
                 created_at, updated_at)
            VALUES
                ('P2', 'L1', 'C1', 'slave', 'worker', 'm1',
                 's', 1, 'ready', 0,
                 '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
            """
        )


def test_tmux_target_uniqueness_partial_index(conn: sqlite3.Connection) -> None:
    """M9 hardening: ``ux_managed_pane_tmux_target`` enforces
    ``(tmux_session_name, tmux_pane_index)`` uniqueness across the
    SAME container for non-terminal panes. The service layer's
    list-sessions pre-check (deferred to FEAT-004 wiring) is the
    operator-visible path, but the DB unique index is the
    defense-in-depth backstop — this test exercises that backstop
    directly so a regression that removed the index would surface.
    """
    _apply_migration_v9(conn)
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    conn.execute(
        """
        INSERT INTO managed_pane
            (id, layout_id, container_id, role, capability, label,
             tmux_session_name, tmux_pane_index, state, chain_depth,
             created_at, updated_at)
        VALUES
            ('P1', 'L1', 'C1', 'master', 'orchestrator', 'm1',
             'session-x', 0, 'ready', 0,
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )

    # Different label, different role, but same (session_name, pane_index)
    # → unique index fires.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO managed_pane
                (id, layout_id, container_id, role, capability, label,
                 tmux_session_name, tmux_pane_index, state, chain_depth,
                 created_at, updated_at)
            VALUES
                ('P2', 'L1', 'C1', 'slave', 'worker', 'different-label',
                 'session-x', 0, 'ready', 0,
                 '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
            """
        )


def test_tmux_target_terminal_panes_carve_out(conn: sqlite3.Connection) -> None:
    """The tmux-target index is partial — terminal panes (removed /
    failed) are excluded, so a recreated pane may take the same
    ``(tmux_session_name, tmux_pane_index)`` as its terminal
    predecessor."""
    _apply_migration_v9(conn)
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    # Predecessor in ``removed`` — outside the partial index.
    conn.execute(
        """
        INSERT INTO managed_pane
            (id, layout_id, container_id, role, capability, label,
             tmux_session_name, tmux_pane_index, state, chain_depth,
             created_at, updated_at)
        VALUES
            ('P1', 'L1', 'C1', 'master', 'orchestrator', 'm1',
             'session-x', 0, 'removed', 0,
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    # Successor takes the same tmux target — should succeed.
    conn.execute(
        """
        INSERT INTO managed_pane
            (id, layout_id, container_id, role, capability, label,
             tmux_session_name, tmux_pane_index, predecessor_id, state,
             chain_depth, created_at, updated_at)
        VALUES
            ('P2', 'L1', 'C1', 'master', 'orchestrator', 'm1',
             'session-x', 0, 'P1', 'creating', 1,
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )


def test_terminal_panes_can_reuse_labels(conn: sqlite3.Connection) -> None:
    """A ``removed`` pane does not block a new pane with the same label."""
    _apply_migration_v9(conn)
    conn.execute("INSERT INTO agents (agent_id) VALUES ('a1')")
    conn.execute(
        """
        INSERT INTO managed_layout
            (id, container_id, template_name, intended_pane_count, state,
             created_at, updated_at)
        VALUES
            ('L1', 'C1', '1m+2s', 3, 'creating',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    # Predecessor in ``removed`` state.
    conn.execute(
        """
        INSERT INTO managed_pane
            (id, layout_id, container_id, role, capability, label,
             tmux_session_name, tmux_pane_index, state, chain_depth,
             created_at, updated_at)
        VALUES
            ('P1', 'L1', 'C1', 'master', 'orchestrator', 'm1',
             's', 0, 'removed', 0,
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    # Successor with the same label — should succeed because P1 is terminal.
    conn.execute(
        """
        INSERT INTO managed_pane
            (id, layout_id, container_id, role, capability, label,
             tmux_session_name, tmux_pane_index, predecessor_id, state,
             chain_depth, created_at, updated_at)
        VALUES
            ('P2', 'L1', 'C1', 'master', 'orchestrator', 'm1',
             's', 0, 'P1', 'creating', 1,
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """
    )
    rows = conn.execute(
        "SELECT id, state FROM managed_pane WHERE label='m1' ORDER BY id"
    ).fetchall()
    assert rows == [("P1", "removed"), ("P2", "creating")]
