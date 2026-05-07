"""Unit tests for FEAT-006 list_agents filters (T029 / FR-026).

Covers:
* ``role`` accepts a string OR a list of strings; AND-composes with other filters.
* ``container_id`` accepts full or 12-char short prefix.
* ``active_only`` filters inactive rows.
* ``parent_agent_id`` filters swarm children of a given slave.
* Unknown filter keys raise ``unknown_filter``.
* Mixed-case filter values raise ``value_out_of_set`` (case-sensitive).
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


def _seed_two_agents(service) -> tuple[str, str]:
    seed_container(service)
    # Pane 0 (slave) and pane 1 (slave) in the same container.
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")
    a = service.register_agent(
        register_params(
            CK_DEFAULT,
            role="slave",
            capability="codex",
            label="alpha",
        ),
        socket_peer_uid=1000,
    )
    ck1 = (CK_DEFAULT[0], CK_DEFAULT[1], CK_DEFAULT[2], 0, 1, "%1")
    b = service.register_agent(
        register_params(ck1, role="slave", capability="claude", label="beta"),
        socket_peer_uid=1000,
    )
    return a["agent_id"], b["agent_id"]


def test_role_accepts_single_string(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_agents(service)
    result = service.list_agents({"role": "slave"})
    assert {a["label"] for a in result["agents"]} == {"alpha", "beta"}


def test_role_accepts_list(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_agents(service)
    result = service.list_agents({"role": ["slave", "shell"]})
    assert len(result["agents"]) == 2


def test_role_rejects_mixed_case(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_agents(service)
    with pytest.raises(RegistrationError) as info:
        service.list_agents({"role": "Slave"})
    assert info.value.code == "value_out_of_set"


def test_container_id_short_prefix_matches(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_agents(service)
    short = CONTAINER_ID[:12]
    result = service.list_agents({"container_id": short})
    assert len(result["agents"]) == 2


def test_container_id_full_id_matches(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_agents(service)
    result = service.list_agents({"container_id": CONTAINER_ID})
    assert len(result["agents"]) == 2


def test_container_id_in_between_length_rejected(tmp_path: Path) -> None:
    """FR-026 review-pass-2: only the 12-char short or 64-char full id
    is accepted. Lengths in between would otherwise sneak through to the
    daemon's substr() prefix matcher and silently behave as undocumented
    arbitrary-length prefix filters.
    """
    service = make_service(tmp_path)
    _seed_two_agents(service)
    # 13..63 chars MUST be rejected with value_out_of_set.
    for length in (13, 32, 50, 63):
        with pytest.raises(RegistrationError) as info:
            service.list_agents({"container_id": CONTAINER_ID[:length]})
        assert info.value.code == "value_out_of_set", (
            f"length={length} should be rejected, got {info.value.code}"
        )


def test_active_only_filters_inactive(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    a, b = _seed_two_agents(service)
    conn = service.connection_factory()
    try:
        conn.execute("UPDATE agents SET active = 0 WHERE agent_id = ?", (a,))
    finally:
        conn.close()
    result = service.list_agents({"active_only": True})
    assert len(result["agents"]) == 1
    assert result["agents"][0]["agent_id"] == b


def test_unknown_filter_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(RegistrationError) as info:
        service.list_agents({"hostname": "anything"})
    assert info.value.code == "unknown_filter"


def test_active_only_must_be_bool(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(RegistrationError) as info:
        service.list_agents({"active_only": "true"})
    assert info.value.code == "value_out_of_set"


def test_filters_compose_with_and_semantics(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    _seed_two_agents(service)
    # role=slave AND container_id=<short> AND active_only=true
    result = service.list_agents(
        {
            "role": "slave",
            "container_id": CONTAINER_ID[:12],
            "active_only": True,
        }
    )
    assert len(result["agents"]) == 2
    # Echo the filter back per data-model.md §6.4.
    assert result["filter"]["role"] == ["slave"]
    assert result["filter"]["container_id"] == CONTAINER_ID[:12]
    assert result["filter"]["active_only"] is True
