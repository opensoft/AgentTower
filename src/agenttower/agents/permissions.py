"""Pure ``effective_permissions`` derivation for FEAT-006 (FR-021).

Closed-set output shape ``{can_send, can_receive, can_send_to_roles}``
materialized on every agent row from the role. Recomputed by the
service layer on every write that mutates ``role`` (FR-021). FEAT-006
does NOT consume this for any decision; FEAT-009 / FEAT-010 will.
"""

from __future__ import annotations

import json
from typing import Final, TypedDict


class EffectivePermissions(TypedDict):
    can_send: bool
    can_receive: bool
    can_send_to_roles: list[str]


# Closed-set derivation table per FR-021 / data-model.md §4.3.
_TABLE: Final[dict[str, EffectivePermissions]] = {
    "master":      {"can_send": True,  "can_receive": False, "can_send_to_roles": ["slave", "swarm"]},
    "slave":       {"can_send": False, "can_receive": True,  "can_send_to_roles": []},
    "swarm":       {"can_send": False, "can_receive": True,  "can_send_to_roles": []},
    "test-runner": {"can_send": False, "can_receive": False, "can_send_to_roles": []},
    "shell":       {"can_send": False, "can_receive": False, "can_send_to_roles": []},
    "unknown":     {"can_send": False, "can_receive": False, "can_send_to_roles": []},
}


def effective_permissions(role: str) -> EffectivePermissions:
    """Return the FR-021 derivation for *role*.

    Raises ``KeyError`` if *role* is not one of the FR-004 closed set.
    Callers MUST validate ``role`` against the closed set before calling
    (the validator in :mod:`agenttower.agents.validation` does so).
    """
    perms = _TABLE[role]
    # Defensive copy of the list so callers cannot mutate the table.
    return {
        "can_send": perms["can_send"],
        "can_receive": perms["can_receive"],
        "can_send_to_roles": list(perms["can_send_to_roles"]),
    }


def serialize_effective_permissions(role: str) -> str:
    """Return the JSON column value with stable key ordering.

    Key order is locked as ``[can_send, can_receive, can_send_to_roles]``
    (research R-008) so the on-disk JSON column shape stays stable.
    """
    perms = effective_permissions(role)
    # Build an ordered dict explicitly so json.dumps preserves insertion order.
    ordered: dict[str, object] = {
        "can_send": perms["can_send"],
        "can_receive": perms["can_receive"],
        "can_send_to_roles": perms["can_send_to_roles"],
    }
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False)
