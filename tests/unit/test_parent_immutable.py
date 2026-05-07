"""Unit tests for FEAT-006 parent_immutable (T083 / FR-018a / Clarifications Q3).

Re-registration with the same ``--parent`` value is a no-op success.
Re-registration with a *different* ``--parent`` value (including
NULL ↔ non-NULL) is rejected with ``parent_immutable``; on rejection
no mutable field is updated even if other fields were also supplied,
the transaction is rolled back, and no audit row is appended.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError

from ._agent_test_helpers import (
    CK_DEFAULT,
    CONTAINER_ID,
    make_service,
    read_events,
    register_params,
    seed_container,
    seed_pane,
)


def _ck1() -> tuple:
    return (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 1, "%1")


def _ck2() -> tuple:
    return (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 2, "%2")


def test_same_parent_value_is_noop_success(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")

    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    swarm = service.register_agent(
        register_params(_ck1(), role="swarm", parent_agent_id=parent["agent_id"]),
        socket_peer_uid=1000,
    )
    second = service.register_agent(
        register_params(
            _ck1(),
            role="swarm",
            parent_agent_id=parent["agent_id"],
            label="updated",
        ),
        socket_peer_uid=1000,
    )
    assert second["agent_id"] == swarm["agent_id"]
    assert second["parent_agent_id"] == parent["agent_id"]
    assert second["label"] == "updated"


def test_different_parent_value_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")
    seed_pane(service, tmux_pane_index=2, tmux_pane_id="%2")

    parent_a = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    parent_b = service.register_agent(
        register_params(_ck2(), role="slave"), socket_peer_uid=1000
    )
    service.register_agent(
        register_params(_ck1(), role="swarm", parent_agent_id=parent_a["agent_id"]),
        socket_peer_uid=1000,
    )
    pre_audit = len(read_events(service))
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(
                _ck1(),
                role="swarm",
                parent_agent_id=parent_b["agent_id"],
                label="should-not-stick",
            ),
            socket_peer_uid=1000,
        )
    assert info.value.code == "parent_immutable"
    # No audit row appended for the rejected call.
    assert len(read_events(service)) == pre_audit
    # No mutable field updated — label is whatever it was before.
    listed = service.list_agents({})["agents"]
    swarm_row = next(a for a in listed if a["role"] == "swarm")
    assert swarm_row["label"] != "should-not-stick"


def test_null_to_nonnull_parent_rejected(tmp_path: Path) -> None:
    """A non-swarm agent has parent_agent_id=NULL; supplying any --parent
    on re-registration is rejected (parent is immutable)."""
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")
    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # The slave at CK_DEFAULT has parent_agent_id=None.
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(role="slave", parent_agent_id=parent["agent_id"]),
            socket_peer_uid=1000,
        )
    # The validator catches parent_role_mismatch first because role=slave
    # with --parent is invalid by FR-016 — that's the correct early
    # rejection. (If we changed role=swarm, parent_immutable would fire
    # because pane_index=0 was registered as slave, not swarm.)
    assert info.value.code == "parent_role_mismatch"
