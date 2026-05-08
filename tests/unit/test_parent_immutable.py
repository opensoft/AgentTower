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


def test_role_slave_with_parent_caught_by_pre_flight(tmp_path: Path) -> None:
    """FR-016 pre-flight catches role=slave + --parent BEFORE the locked
    section runs.  The validator order matters: with role=slave the
    static pre-flight rejects the request before the per-pane lock is
    even taken, so the user gets the most actionable error
    (parent_role_mismatch — "use --role swarm") instead of
    parent_immutable.
    """
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
    assert info.value.code == "parent_role_mismatch"


def test_null_to_nonnull_parent_rejected_as_parent_immutable(
    tmp_path: Path,
) -> None:
    """Review-pass-6 N22: actually exercise the FR-018a parent_immutable
    branch for a NULL→non-NULL transition.

    To hit the locked-section parent_immutable check, the request must
    pass the FR-016 pre-flight (so role MUST be swarm).  An existing
    slave at CK_DEFAULT has ``parent_agent_id=None``; re-registering
    that pane with role=swarm + parent=X is the path where the
    pre-flight does not fire and the in-tx
    ``parent_in != existing.parent_agent_id`` check triggers
    parent_immutable.  Previously this test asserted on
    ``parent_role_mismatch`` (the static pre-flight outcome of the
    role=slave variant) — which passes for the wrong reason and
    leaves the parent_immutable path completely untested.
    """
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")
    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # The slave at CK_DEFAULT has parent_agent_id=None. Re-registering
    # the SAME pane with role=swarm + parent=X passes FR-016 pre-flight
    # (role IS swarm), reaches the locked section, and fails the
    # parent_immutable check because existing.parent_agent_id is None.
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(role="swarm", parent_agent_id=parent["agent_id"]),
            socket_peer_uid=1000,
        )
    assert info.value.code == "parent_immutable"


def test_existing_swarm_cannot_reregister_to_non_swarm_while_parent_retained(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")

    parent = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    service.register_agent(
        register_params(_ck1(), role="swarm", parent_agent_id=parent["agent_id"]),
        socket_peer_uid=1000,
    )

    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(_ck1(), role="slave"),
            socket_peer_uid=1000,
        )

    assert info.value.code == "parent_role_mismatch"
