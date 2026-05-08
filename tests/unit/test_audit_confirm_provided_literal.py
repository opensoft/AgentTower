"""Unit tests for FEAT-006 ``confirm_provided`` literal contract (T066 / Q5).

Clarifications session 2026-05-07-continued Q5: ``confirm_provided``
records the literal request value verbatim, never rewritten based on
whether ``--confirm`` was *required* by the transition.
"""

from __future__ import annotations

from pathlib import Path

from ._agent_test_helpers import (
    make_service,
    read_events,
    register_params,
    seed_container,
    seed_pane,
)


def test_demotion_with_redundant_confirm_logs_true(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    service.set_role(
        {"agent_id": first["agent_id"], "role": "master", "confirm": True},
        socket_peer_uid=1000,
    )
    # Demote with REDUNDANT --confirm (not required by FR-013).
    service.set_role(
        {"agent_id": first["agent_id"], "role": "slave", "confirm": True},
        socket_peer_uid=1000,
    )
    rows = read_events(service)
    # creation, master, demotion → 3 rows.
    assert len(rows) == 3
    assert rows[2]["payload"]["confirm_provided"] is True


def test_set_role_to_non_master_with_redundant_confirm_logs_true(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    service.set_role(
        {"agent_id": first["agent_id"], "role": "shell", "confirm": True},
        socket_peer_uid=1000,
    )
    rows = read_events(service)
    assert rows[-1]["payload"]["confirm_provided"] is True


def test_register_self_creation_logs_false(tmp_path: Path) -> None:
    """register-self never has a meaningful --confirm; always logs False."""
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    rows = read_events(service)
    assert rows[0]["payload"]["confirm_provided"] is False


def test_set_role_demotion_without_confirm_logs_false(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    service.set_role(
        {"agent_id": first["agent_id"], "role": "master", "confirm": True},
        socket_peer_uid=1000,
    )
    # Demote WITHOUT --confirm (not required).
    service.set_role(
        {"agent_id": first["agent_id"], "role": "slave"},
        socket_peer_uid=1000,
    )
    rows = read_events(service)
    assert rows[-1]["payload"]["confirm_provided"] is False
    assert rows[-1]["payload"]["prior_role"] == "master"
    assert rows[-1]["payload"]["new_role"] == "slave"
