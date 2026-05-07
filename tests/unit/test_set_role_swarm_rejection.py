"""Unit tests for FEAT-006 set-role swarm rejection (T068 / FR-012).

``set-role --role swarm`` is rejected with closed-set
``swarm_role_via_set_role_rejected`` and an actionable message that
points the operator at ``register-self --role swarm --parent <id>``.
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


def test_set_role_swarm_rejected_actionable_message(tmp_path: Path) -> None:
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
    assert "register-self" in info.value.message
    assert "--role swarm --parent" in info.value.message
