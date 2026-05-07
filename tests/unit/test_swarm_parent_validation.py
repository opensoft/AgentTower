"""Unit tests for FEAT-006 swarm parent validation (T082 / FR-015..FR-020).

Covers all five failure paths plus the success path:
* ``parent_not_found``    — parent agent_id does not exist.
* ``parent_inactive``     — parent agent is active=false.
* ``parent_role_invalid`` — parent role is not 'slave' (incl. nested swarm).
* ``parent_role_mismatch``— --parent supplied without --role swarm.
* ``swarm_parent_required`` — --role swarm without --parent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError

from ._agent_test_helpers import (
    CK_DEFAULT,
    CONTAINER_ID,
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def _seed_two_panes(service) -> None:
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")


def _ck1() -> tuple:
    return (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 1, "%1")


def test_swarm_success_path(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_panes(service)
    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    child = service.register_agent(
        register_params(_ck1(), role="swarm", parent_agent_id=parent["agent_id"]),
        socket_peer_uid=1000,
    )
    assert child["role"] == "swarm"
    assert child["parent_agent_id"] == parent["agent_id"]


def test_parent_not_found(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_panes(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(
                _ck1(), role="swarm", parent_agent_id="agt_aaaaaaaaaaaa"
            ),
            socket_peer_uid=1000,
        )
    assert info.value.code == "parent_not_found"


def test_parent_inactive(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_panes(service)
    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Force the parent inactive.
    conn = service.connection_factory()
    try:
        conn.execute(
            "UPDATE agents SET active = 0 WHERE agent_id = ?",
            (parent["agent_id"],),
        )
    finally:
        conn.close()
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(
                _ck1(), role="swarm", parent_agent_id=parent["agent_id"]
            ),
            socket_peer_uid=1000,
        )
    assert info.value.code == "parent_inactive"


@pytest.mark.parametrize("parent_role", ["master", "test-runner", "shell", "unknown"])
def test_parent_role_invalid_for_non_slave(
    tmp_path: Path, parent_role: str
) -> None:
    service = make_service(tmp_path)
    _seed_two_panes(service)
    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Promote/demote the parent to a non-slave role first.
    if parent_role == "master":
        service.set_role(
            {"agent_id": parent["agent_id"], "role": "master", "confirm": True},
            socket_peer_uid=1000,
        )
    else:
        service.set_role(
            {"agent_id": parent["agent_id"], "role": parent_role},
            socket_peer_uid=1000,
        )
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(
                _ck1(), role="swarm", parent_agent_id=parent["agent_id"]
            ),
            socket_peer_uid=1000,
        )
    assert info.value.code == "parent_role_invalid"


def test_nested_swarm_rejected(tmp_path: Path) -> None:
    """FR-020: a swarm cannot be a parent (parent must be role=slave)."""
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")
    seed_pane(service, tmux_pane_index=2, tmux_pane_id="%2")
    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    swarm = service.register_agent(
        register_params(_ck1(), role="swarm", parent_agent_id=parent["agent_id"]),
        socket_peer_uid=1000,
    )
    ck2 = (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 2, "%2")
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(ck2, role="swarm", parent_agent_id=swarm["agent_id"]),
            socket_peer_uid=1000,
        )
    assert info.value.code == "parent_role_invalid"


def test_parent_role_mismatch_when_role_not_swarm(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_panes(service)
    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(
                _ck1(), role="slave", parent_agent_id=parent["agent_id"]
            ),
            socket_peer_uid=1000,
        )
    assert info.value.code == "parent_role_mismatch"


def test_swarm_parent_required_when_role_swarm_without_parent(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_panes(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(_ck1(), role="swarm"),
            socket_peer_uid=1000,
        )
    assert info.value.code == "swarm_parent_required"
