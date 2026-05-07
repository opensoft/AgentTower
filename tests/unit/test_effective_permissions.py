"""Unit tests for FEAT-006 effective_permissions derivation (T015 / FR-021).

Covers:
* All six roles produce the closed-set table from data-model.md §4.3.
* JSON column key ordering is locked as
  ``[can_send, can_receive, can_send_to_roles]`` (research R-008).
* ``can_send_to_roles`` is always a list (incl. empty ``[]``).
* The function does not return an aliased mutable view of an internal table
  (callers can't mutate the source of truth).
"""

from __future__ import annotations

import json

import pytest

from agenttower.agents.permissions import (
    effective_permissions,
    serialize_effective_permissions,
)


_EXPECTED = {
    "master":      {"can_send": True,  "can_receive": False, "can_send_to_roles": ["slave", "swarm"]},
    "slave":       {"can_send": False, "can_receive": True,  "can_send_to_roles": []},
    "swarm":       {"can_send": False, "can_receive": True,  "can_send_to_roles": []},
    "test-runner": {"can_send": False, "can_receive": False, "can_send_to_roles": []},
    "shell":       {"can_send": False, "can_receive": False, "can_send_to_roles": []},
    "unknown":     {"can_send": False, "can_receive": False, "can_send_to_roles": []},
}


@pytest.mark.parametrize("role,expected", list(_EXPECTED.items()))
def test_effective_permissions_table(role: str, expected: dict) -> None:
    assert effective_permissions(role) == expected


def test_effective_permissions_can_send_to_roles_is_list() -> None:
    for role in _EXPECTED:
        perms = effective_permissions(role)
        assert isinstance(perms["can_send_to_roles"], list)


def test_serialize_key_ordering_is_stable() -> None:
    """The JSON serialization MUST emit keys in
    [can_send, can_receive, can_send_to_roles] order (research R-008)."""
    text = serialize_effective_permissions("master")
    # Locate first occurrence of each key.
    can_send_pos = text.index('"can_send"')
    can_receive_pos = text.index('"can_receive"')
    can_send_to_pos = text.index('"can_send_to_roles"')
    assert can_send_pos < can_receive_pos < can_send_to_pos


def test_serialize_round_trip() -> None:
    for role, expected in _EXPECTED.items():
        text = serialize_effective_permissions(role)
        assert json.loads(text) == expected


def test_callers_cannot_mutate_internal_table() -> None:
    """Mutating the returned dict MUST NOT affect later calls."""
    perms = effective_permissions("master")
    perms["can_send_to_roles"].append("master")
    second = effective_permissions("master")
    assert second["can_send_to_roles"] == ["slave", "swarm"]


def test_unknown_role_raises_key_error() -> None:
    """Validators are responsible for rejecting unknown roles before this
    helper is called; raising KeyError documents the contract."""
    with pytest.raises(KeyError):
        effective_permissions("admin")
