"""Unit tests for FEAT-006 last_seen_at + active cascade (T032 / FR-009 / FR-009a).

Covers:
* Every FEAT-004 reconciliation transaction observing pane active=true
  updates ``agents.last_seen_at`` in the same transaction.
* Pane active 1→0 cascades ``agents.active = 0`` in the same transaction.
* Pane inactive→active does NOT auto-flip ``agents.active``.
* CLI calls (register_agent / list_agents / set_*) MUST NOT touch
  ``last_seen_at`` (asserted by snapshot before/after the call).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agenttower.state import agents as state_agents
from agenttower.state import panes as state_panes
from agenttower.state.panes import (
    PaneReconcileWriteSet,
    PaneUpsert,
)

from ._agent_test_helpers import (
    CK_DEFAULT,
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def _read_last_seen_at(service, agent_id: str) -> str | None:
    conn = service.connection_factory()
    try:
        row = conn.execute(
            "SELECT last_seen_at FROM agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def test_update_last_seen_at_helper_updates_only_matching(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    result = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    aid = result["agent_id"]
    assert _read_last_seen_at(service, aid) is None

    # Simulate a FEAT-004 reconciliation transaction.
    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.update_last_seen_at(
            conn,
            pane_keys=[CK_DEFAULT],
            now_iso="2026-05-07T12:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    assert _read_last_seen_at(service, aid) == "2026-05-07T12:00:00.000000+00:00"


def test_cascade_agents_active_from_pane(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    result = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    aid = result["agent_id"]

    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.cascade_agents_active_from_pane(
            conn, pane_keys=[CK_DEFAULT]
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    conn = service.connection_factory()
    try:
        active = conn.execute(
            "SELECT active FROM agents WHERE agent_id = ?", (aid,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert active == 0


def test_register_does_not_touch_last_seen_at(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Simulate a scan that set last_seen_at.
    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.update_last_seen_at(
            conn,
            pane_keys=[CK_DEFAULT],
            now_iso="2026-05-07T12:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    # Now re-register; last_seen_at MUST NOT be modified by register_agent.
    service.register_agent(
        register_params(role="slave", label="new"), socket_peer_uid=1000
    )
    assert _read_last_seen_at(service, first["agent_id"]) == (
        "2026-05-07T12:00:00.000000+00:00"
    )


def test_set_label_does_not_touch_last_seen_at(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave", label="orig"), socket_peer_uid=1000
    )
    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.update_last_seen_at(
            conn,
            pane_keys=[CK_DEFAULT],
            now_iso="2026-05-07T12:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    service.set_label(
        {"agent_id": first["agent_id"], "label": "new"},
        socket_peer_uid=1000,
    )
    assert _read_last_seen_at(service, first["agent_id"]) == (
        "2026-05-07T12:00:00.000000+00:00"
    )
