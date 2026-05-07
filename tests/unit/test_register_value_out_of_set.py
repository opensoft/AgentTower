"""Unit tests for FEAT-006 closed-set rejection at register time (T035).

Covers FR-004 / FR-005 / Clarifications Q2: out-of-set role / capability
/ parent_agent_id rejected with ``value_out_of_set``; mixed-case values
rejected without normalization; actionable message lists canonical
lowercase tokens.
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "Slave"),
        ("role", "MASTER"),
        ("role", "robot"),
        ("capability", "Claude"),
        ("capability", "vim"),
        ("parent_agent_id", "AGT_abc123def456"),
        ("parent_agent_id", "agt_ABC123def456"),
        ("parent_agent_id", "agt_xyz123def456"),
    ],
)
def test_invalid_values_rejected(tmp_path: Path, field: str, value: str) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    params = register_params(**{field: value})
    # Some combinations also need a valid role to reach the parent check.
    if field == "parent_agent_id":
        params["role"] = "swarm"
    with pytest.raises(RegistrationError) as info:
        service.register_agent(params, socket_peer_uid=1000)
    assert info.value.code == "value_out_of_set"


def test_unknown_role_message_lists_canonical_tokens(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(role="robot"),
            socket_peer_uid=1000,
        )
    msg = info.value.message.lower()
    for tok in ("master", "slave", "swarm", "test-runner", "shell", "unknown"):
        assert tok in msg


def test_register_agent_rejects_unknown_keys(tmp_path: Path) -> None:
    """Review-pass-3: unknown params keys MUST fail with bad_request.

    Mirrors the FR-026 ``unknown_filter`` gate ``list_agents`` enforces.
    Without this, a stale CLI sending an obsolete or typo'd field would
    silently see its registration succeed with that field ignored —
    making forward-compat issues look like "it just worked".
    """
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    params = register_params(role="slave")
    params["typo_label"] = "oops"
    with pytest.raises(RegistrationError) as info:
        service.register_agent(params, socket_peer_uid=1000)
    assert info.value.code == "bad_request"
    assert "typo_label" in info.value.message


def test_register_agent_rejects_attempted_socket_peer_uid_spoof(
    tmp_path: Path,
) -> None:
    """A client cannot smuggle ``socket_peer_uid`` via the request body.

    The dispatcher already sources ``peer_uid`` out-of-band from
    SO_PEERCRED (review-pass-1), but layered defence: the unknown-keys
    gate refuses the request entirely so the audit trail is unambiguous.
    """
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    params = register_params(role="slave")
    params["socket_peer_uid"] = 9999
    with pytest.raises(RegistrationError) as info:
        service.register_agent(params, socket_peer_uid=1000)
    assert info.value.code == "bad_request"
    assert "socket_peer_uid" in info.value.message
