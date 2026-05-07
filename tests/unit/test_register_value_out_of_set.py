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
