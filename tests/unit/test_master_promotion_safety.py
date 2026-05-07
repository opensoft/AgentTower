"""Unit tests for FEAT-006 master safety boundary (T062 / FR-010 / FR-011 / FR-012 / FR-013).

Covers the four pillars of the master safety contract:
* ``register-self --role master`` rejected regardless of ``--confirm``.
* ``set-role --role master`` without ``--confirm`` rejected.
* ``set-role --role swarm`` rejected (swarm is register-only).
* Demotion (master → slave / shell / unknown / etc.) does NOT require ``--confirm``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError

from ._agent_test_helpers import (
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def test_register_self_rejects_master_no_confirm(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(role="master"), socket_peer_uid=1000
        )
    assert info.value.code == "master_via_register_self_rejected"


def test_register_self_rejects_master_with_confirm(tmp_path: Path) -> None:
    """FR-010: --confirm MUST NOT bypass the register-self master rejection."""
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(role="master", confirm=True), socket_peer_uid=1000
        )
    assert info.value.code == "master_via_register_self_rejected"


def test_set_role_master_without_confirm_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    with pytest.raises(RegistrationError) as info:
        service.set_role(
            {"agent_id": first["agent_id"], "role": "master"},
            socket_peer_uid=1000,
        )
    assert info.value.code == "master_confirm_required"


def test_set_role_master_with_confirm_succeeds(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    result = service.set_role(
        {"agent_id": first["agent_id"], "role": "master", "confirm": True},
        socket_peer_uid=1000,
    )
    assert result["new_value"] == "master"
    assert result["effective_permissions"]["can_send_to_roles"] == ["slave", "swarm"]
    assert result["audit_appended"] is True


def test_set_role_swarm_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    with pytest.raises(RegistrationError) as info:
        service.set_role(
            {"agent_id": first["agent_id"], "role": "swarm"},
            socket_peer_uid=1000,
        )
    assert info.value.code == "swarm_role_via_set_role_rejected"


def test_demotion_from_master_does_not_require_confirm(tmp_path: Path) -> None:
    """FR-013: master → any other role does NOT need --confirm."""
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
    result = service.set_role(
        {"agent_id": first["agent_id"], "role": "slave"},
        socket_peer_uid=1000,
    )
    assert result["prior_value"] == "master"
    assert result["new_value"] == "slave"
