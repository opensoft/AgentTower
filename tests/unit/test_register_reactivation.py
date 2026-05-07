"""Unit tests for FEAT-006 re-activation of inactive agents (T028 / FR-008).

Covers FR-008: re-registering at a composite key whose existing agent
is ``active=false`` re-activates it, preserving ``agent_id``,
``created_at``, ``parent_agent_id``; the FR-007 mutable-field semantics
still apply.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ._agent_test_helpers import (
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def _force_inactive(service, agent_id: str) -> None:
    conn = service.connection_factory()
    try:
        conn.execute("UPDATE agents SET active = 0 WHERE agent_id = ?", (agent_id,))
    finally:
        conn.close()


def test_reactivation_preserves_agent_id_and_created_at(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    _force_inactive(service, first["agent_id"])

    second = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )

    assert second["agent_id"] == first["agent_id"]
    assert second["created_at"] == first["created_at"]
    assert second["created_or_reactivated"] == "reactivated"
    assert second["active"] is True


def test_reactivation_with_mutable_field_changes(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    first = service.register_agent(
        register_params(role="slave", capability="codex", label="old"),
        socket_peer_uid=1000,
    )
    _force_inactive(service, first["agent_id"])

    second = service.register_agent(
        register_params(label="new"), socket_peer_uid=1000
    )
    assert second["label"] == "new"
    # Role, capability NOT supplied — stored values preserved.
    assert second["role"] == "slave"
    assert second["capability"] == "codex"
    assert second["active"] is True
