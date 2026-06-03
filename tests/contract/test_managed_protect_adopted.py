"""FEAT-013 T037: adopted-pane protection contract test.

Covers FR-012 + T044: a pane_id that does NOT have a managed_pane row
is treated as adopted (or non-existent — same operator-actionable
answer) and the destructive lifecycle entry points (`remove_pane`,
`recreate_pane`) refuse to act on it via
`managed_pane_protected_adopted`.

Adopted-pane protection is a "missing-row probe": the managed_sessions
service doesn't directly inspect the FEAT-006 `agents` table (it's
oblivious to whether the pane was registered through adoption vs created
by FEAT-013). The protection is structural — if `managed_pane` doesn't
have it, the service refuses to touch it.
"""

from __future__ import annotations

import sqlite3

import pytest

from agenttower.managed_sessions.errors import (
    MANAGED_PANE_PROTECTED_ADOPTED,
    ManagedSessionsError,
)
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    create_layout,
    recreate_pane,
    remove_pane,
)
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY, origin TEXT)")
    _apply_migration_v9(c)
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


# ─── remove_pane refuses adopted (= no managed_pane row) ────────────────


def test_remove_pane_refuses_adopted_id(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Seed an adopted agent in the FEAT-006 agents table but NOT in
    managed_pane. `remove_pane` returns `managed_pane_protected_adopted`
    because there's no managed_pane row for this agent_id."""
    conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-ADOPTED-MASTER", "adopted"),
    )
    conn.commit()

    with pytest.raises(ManagedSessionsError) as exc_info:
        remove_pane(
            conn=conn, serializer=serializer,
            pane_id="01HZ-ADOPTED-MASTER",
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_PROTECTED_ADOPTED
    assert exc.details == {"agent_id": "01HZ-ADOPTED-MASTER", "is_adopted": True}


def test_remove_pane_refuses_adopted_pane_unaffected_after_attempt(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-012 + SC-005: the adopted agent's row is unchanged by the
    refused remove attempt."""
    conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-ADOPTED-WORKER", "adopted"),
    )
    conn.commit()
    row_before = conn.execute(
        "SELECT * FROM agents WHERE agent_id = ?",
        ("01HZ-ADOPTED-WORKER",),
    ).fetchone()

    with pytest.raises(ManagedSessionsError):
        remove_pane(
            conn=conn, serializer=serializer,
            pane_id="01HZ-ADOPTED-WORKER",
        )

    row_after = conn.execute(
        "SELECT * FROM agents WHERE agent_id = ?",
        ("01HZ-ADOPTED-WORKER",),
    ).fetchone()
    assert row_before == row_after  # adopted row byte-for-byte unchanged


# ─── recreate_pane refuses adopted ──────────────────────────────────────


def test_recreate_pane_refuses_adopted_id(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """T044 protection extends to recreate_pane: predecessor_pane_id
    pointing at an adopted-only id returns `managed_pane_protected_adopted`."""
    conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-ADOPTED-ONLY", "adopted"),
    )
    conn.commit()
    with pytest.raises(ManagedSessionsError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id="01HZ-ADOPTED-ONLY",
        )
    exc = exc_info.value
    assert exc.code == MANAGED_PANE_PROTECTED_ADOPTED


# ─── Managed remove + adopted-pane coexistence don't interfere ──────────


def test_managed_remove_leaves_adopted_row_untouched(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-009 + SC-005: removing a managed pane does NOT delete or
    modify any adopted-agent row that happens to share the container."""
    conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("01HZ-COEXISTING-ADOPTED", "adopted"),
    )
    conn.commit()

    # Create + remove a managed pane in the same container.
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="coexist",
    )
    # The pane is in 'creating' — to remove it we first need it to leave
    # creating. The simplest test path is to bypass the spawn pipeline
    # and UPDATE the row to 'ready' directly. (Production would let the
    # bg pipeline transition it.)
    target_pane_id = result.panes[0].pane_id
    conn.execute(
        "UPDATE managed_pane SET state='ready', pending_marker_token=NULL "
        "WHERE id=?",
        (target_pane_id,),
    )
    conn.commit()

    # Remove the managed pane.
    remove_pane(
        conn=conn, serializer=serializer, pane_id=target_pane_id,
        tmux_kill_fn=lambda p: {"ok": True},
    )

    # Adopted row unchanged.
    adopted_count = conn.execute(
        "SELECT COUNT(*) FROM agents WHERE agent_id = ?",
        ("01HZ-COEXISTING-ADOPTED",),
    ).fetchone()[0]
    assert adopted_count == 1
