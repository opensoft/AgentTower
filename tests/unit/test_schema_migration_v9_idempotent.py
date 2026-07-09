"""FEAT-013 review P3#10: migration v9 must not repeat destructive DDL.

``_apply_migration_v9`` runs on every current-version open (via
``_ensure_current_schema``). It previously did an unconditional
``DROP INDEX ... ux_managed_pane_tmux_target`` + recreate, so every daemon
boot dropped and rebuilt the index — wasted DDL that momentarily voided the
uniqueness guarantee. The drop is now conditional on the OLD pre-release
index shape being present.
"""

from __future__ import annotations

import sqlite3

import pytest

from agenttower.state.schema import _apply_migration_v9


def _tmux_target_columns(conn: sqlite3.Connection) -> list[str]:
    return [
        r[2]
        for r in conn.execute(
            "PRAGMA index_info(ux_managed_pane_tmux_target)"
        ).fetchall()
    ]


def _fresh() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    _apply_migration_v9(c)
    return c


def test_v9_creates_three_column_tmux_target_index() -> None:
    conn = _fresh()
    assert _tmux_target_columns(conn) == [
        "container_id",
        "tmux_session_name",
        "tmux_pane_index",
    ]


def test_v9_rerun_on_current_shape_does_not_drop_the_index() -> None:
    """A second v9 pass on an already-correct DB must NOT issue a
    DROP INDEX for the tmux-target index (steady-state open is non-destructive)."""
    conn = _fresh()

    traced: list[str] = []
    conn.set_trace_callback(traced.append)
    _apply_migration_v9(conn)
    conn.set_trace_callback(None)

    drops = [
        s for s in traced
        if "DROP INDEX" in s.upper() and "ux_managed_pane_tmux_target" in s
    ]
    assert drops == [], f"v9 rerun dropped the index: {drops}"
    # And the index is still present + correct.
    assert _tmux_target_columns(conn) == [
        "container_id",
        "tmux_session_name",
        "tmux_pane_index",
    ]


def test_v9_migrates_old_two_column_index_to_three_column() -> None:
    """A pre-release DB carrying the OLD 2-column index shape IS migrated:
    v9 drops the stale index and recreates the corrected 3-column one."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    _apply_migration_v9(conn)
    # Simulate the stale shape: drop the correct index and install the old
    # 2-column one.
    conn.execute("DROP INDEX ux_managed_pane_tmux_target")
    conn.execute(
        """
        CREATE UNIQUE INDEX ux_managed_pane_tmux_target
            ON managed_pane(tmux_session_name, tmux_pane_index)
            WHERE state IN ('creating','ready','degraded')
        """
    )
    assert _tmux_target_columns(conn) == ["tmux_session_name", "tmux_pane_index"]

    # Re-running v9 must correct it to the 3-column shape.
    _apply_migration_v9(conn)
    assert _tmux_target_columns(conn) == [
        "container_id",
        "tmux_session_name",
        "tmux_pane_index",
    ]
