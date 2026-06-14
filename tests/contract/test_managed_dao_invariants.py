"""FEAT-013 DAO storage-layer invariant guards (reviews P2#8 + P3#9).

``insert_pane`` enforces invariants the schema FKs cannot express:

* P2#8 — denormalized ``managed_pane.container_id`` MUST equal its parent
  ``managed_layout.container_id`` (the FK only checks ``layout_id``).
* P3#9 — a recreate successor MUST point at a terminal (removed/failed)
  predecessor. The companion ``chain_depth == predecessor.chain_depth + 1``
  rule is a SERVICE-layer invariant only and is intentionally NOT enforced
  at the DAO (a storage-level check would reject legitimate synthetic-depth
  fixtures); ``test_insert_pane_accepts_terminal_predecessor_at_any_depth``
  asserts the DAO accepts an arbitrary depth for a terminal predecessor.
* Existence (review P2) — both the parent layout and (when set) the
  predecessor MUST exist, rejected independent of ``PRAGMA foreign_keys``.

These are defense-in-depth: the service already enforces all of these for
every production write, so production never trips them. The tests drive the
DAO directly to prove the guard fires on a malformed insert.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
import uuid

import pytest

from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
)
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    _apply_migration_v9(c)
    return c


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _layout(conn: sqlite3.Connection, container_id: str) -> str:
    layout_id = str(uuid.uuid4())
    now = _now()
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id,
            container_id=container_id,
            template_name="1m+2s",
            intended_pane_count=1,
            state=ManagedState.READY,
            failed_stage=None,
            idempotency_key=None,
            created_at=now,
            updated_at=now,
        ),
    )
    return layout_id


def _pane_row(
    layout_id: str,
    container_id: str,
    *,
    pane_id: str | None = None,
    state: ManagedState = ManagedState.READY,
    predecessor_id: str | None = None,
    chain_depth: int = 0,
    tmux_pane_index: int = 0,
) -> ManagedPaneRow:
    now = _now()
    return ManagedPaneRow(
        id=pane_id or str(uuid.uuid4()),
        layout_id=layout_id,
        container_id=container_id,
        agent_id=None,
        role="master",
        capability="orchestrator",
        label=f"m{tmux_pane_index}",
        launch_command_ref=None,
        tmux_session_name="session-x",
        tmux_pane_index=tmux_pane_index,
        pending_marker_token=None,
        state=state,
        failed_stage=None,
        predecessor_id=predecessor_id,
        chain_depth=chain_depth,
        created_at=now,
        updated_at=now,
    )


# ─── P2#8: container_id must match parent layout ─────────────────────────


def test_insert_pane_rejects_container_id_drift_from_parent_layout(
    conn: sqlite3.Connection,
) -> None:
    layout_id = _layout(conn, "bench-alpha")
    with pytest.raises(ValueError, match="does not match parent layout"):
        insert_pane(conn, _pane_row(layout_id, "bench-beta"))


def test_insert_pane_accepts_matching_container_id(
    conn: sqlite3.Connection,
) -> None:
    layout_id = _layout(conn, "bench-alpha")
    insert_pane(conn, _pane_row(layout_id, "bench-alpha"))  # no raise


# ─── P3#9: recreate-chain invariants ─────────────────────────────────────


def test_insert_pane_rejects_successor_of_non_terminal_predecessor(
    conn: sqlite3.Connection,
) -> None:
    layout_id = _layout(conn, "bench-alpha")
    pred = _pane_row(layout_id, "bench-alpha", state=ManagedState.READY)
    insert_pane(conn, pred)
    successor = _pane_row(
        layout_id, "bench-alpha", predecessor_id=pred.id, chain_depth=1,
        tmux_pane_index=1,
    )
    with pytest.raises(ValueError, match="non-terminal state"):
        insert_pane(conn, successor)


def test_insert_pane_accepts_terminal_predecessor_at_any_depth(
    conn: sqlite3.Connection,
) -> None:
    """A terminal predecessor is accepted regardless of the successor's
    chain_depth — the strict ``depth == predecessor + 1`` rule is a
    service-layer invariant, deliberately NOT enforced at the DAO layer so
    synthetic-depth fixtures (and recovery seeds) remain insertable."""
    layout_id = _layout(conn, "bench-alpha")
    pred = _pane_row(layout_id, "bench-alpha", state=ManagedState.REMOVED)
    insert_pane(conn, pred)
    # chain_depth deliberately not predecessor.chain_depth + 1 — still OK.
    successor = _pane_row(
        layout_id, "bench-alpha", predecessor_id=pred.id, chain_depth=7,
        tmux_pane_index=1,
    )
    insert_pane(conn, successor)  # terminal predecessor → no raise
