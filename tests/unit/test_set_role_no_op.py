"""Unit tests for FEAT-006 set_* no-op contract (T067 / FR-027).

Set-role / set-label / set-capability with the same value the agent
already has MUST succeed (exit 0) without error and MUST append no new
audit row. The result envelope reports ``audit_appended=False``.
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


def test_set_role_no_op_skips_audit(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    pre = len(read_events(service))
    result = service.set_role(
        {"agent_id": first["agent_id"], "role": "slave"},
        socket_peer_uid=1000,
    )
    assert result["audit_appended"] is False
    assert len(read_events(service)) == pre


def test_set_label_no_op(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave", label="orig"), socket_peer_uid=1000
    )
    result = service.set_label(
        {"agent_id": first["agent_id"], "label": "orig"},
        socket_peer_uid=1000,
    )
    assert result["audit_appended"] is False
    assert result["new_value"] == "orig"


def test_set_capability_no_op(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave", capability="codex"),
        socket_peer_uid=1000,
    )
    result = service.set_capability(
        {"agent_id": first["agent_id"], "capability": "codex"},
        socket_peer_uid=1000,
    )
    assert result["audit_appended"] is False
    assert result["new_value"] == "codex"
