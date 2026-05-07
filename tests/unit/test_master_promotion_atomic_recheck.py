"""Unit tests for FR-011 atomic master re-check (T063 / Clarifications Q3).

Covers the master-promotion atomic re-check inside BEGIN IMMEDIATE: if
the target agent OR its bound container becomes inactive between the
client request and the transaction commit, the daemon ROLLBACKs and
returns ``agent_inactive``. No role mutation, no
``effective_permissions`` recomputation, no JSONL audit row.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError

from ._agent_test_helpers import (
    make_service,
    read_events,
    register_params,
    seed_container,
    seed_pane,
)


def test_inactive_agent_rejects_promotion(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Force agent inactive (simulates FEAT-004 cascade).
    conn = service.connection_factory()
    try:
        conn.execute(
            "UPDATE agents SET active = 0 WHERE agent_id = ?",
            (first["agent_id"],),
        )
    finally:
        conn.close()

    pre_audit_count = len(read_events(service))
    with pytest.raises(RegistrationError) as info:
        service.set_role(
            {"agent_id": first["agent_id"], "role": "master", "confirm": True},
            socket_peer_uid=1000,
        )
    assert info.value.code == "agent_inactive"

    # Role unchanged; no audit row appended.
    conn = service.connection_factory()
    try:
        role = conn.execute(
            "SELECT role FROM agents WHERE agent_id = ?", (first["agent_id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert role == "slave"
    assert len(read_events(service)) == pre_audit_count


def test_inactive_container_rejects_promotion(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Mark the container inactive (simulates FEAT-003 reconciliation).
    conn = service.connection_factory()
    try:
        conn.execute(
            "UPDATE containers SET active = 0 WHERE container_id = ?",
            (first["container_id"],),
        )
    finally:
        conn.close()

    pre_audit_count = len(read_events(service))
    with pytest.raises(RegistrationError) as info:
        service.set_role(
            {"agent_id": first["agent_id"], "role": "master", "confirm": True},
            socket_peer_uid=1000,
        )
    assert info.value.code == "agent_inactive"

    conn = service.connection_factory()
    try:
        role = conn.execute(
            "SELECT role FROM agents WHERE agent_id = ?", (first["agent_id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert role == "slave"
    assert len(read_events(service)) == pre_audit_count
