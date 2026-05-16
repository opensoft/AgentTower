"""T016 — FEAT-009 HOST_OPERATOR_SENTINEL reservation tests.

Research §R-004 requires the literal ``host-operator`` string to be
reserved as an agent_id so it cannot collide with any registered FEAT-006
agent. The reservation is two-layered (defense in depth):

1. The :data:`AGENT_ID_RE` regex (``^agt_[0-9a-f]{12}$``) does not match
   ``host-operator``.
2. :func:`validate_agent_id_shape` rejects the literal sentinel BEFORE
   the regex check, so a future shape regex change that accidentally
   matched the sentinel would still bar registration.

This file pins both defenses.
"""

from __future__ import annotations

import re

import pytest

from agenttower.agents import HOST_OPERATOR_SENTINEL
from agenttower.agents.errors import RegistrationError
from agenttower.agents.identifiers import (
    AGENT_ID_RE,
    generate_agent_id,
    validate_agent_id_shape,
)


def test_sentinel_value_is_host_operator() -> None:
    """The sentinel string is exactly ``host-operator`` (no leading/
    trailing whitespace, no case variation). FEAT-009 audit consumers
    (queue listings, JSONL, the FEAT-008 events.agent_id column)
    branch on this literal."""
    assert HOST_OPERATOR_SENTINEL == "host-operator"


def test_sentinel_does_not_match_agent_id_regex() -> None:
    """Layer 1: AGENT_ID_RE does not match the sentinel.

    The agent_id shape is ``agt_<12-hex>``; ``host-operator`` contains
    a hyphen which the hex class doesn't match. If a future shape change
    weakened the regex, this assertion would catch it.
    """
    assert AGENT_ID_RE.match(HOST_OPERATOR_SENTINEL) is None


def test_validate_agent_id_shape_rejects_sentinel_literal() -> None:
    """Layer 2: validate_agent_id_shape rejects the sentinel literal."""
    with pytest.raises(RegistrationError) as info:
        validate_agent_id_shape(HOST_OPERATOR_SENTINEL)
    assert info.value.code == "value_out_of_set"
    assert HOST_OPERATOR_SENTINEL in str(info.value.message)


def test_validate_agent_id_shape_sentinel_check_runs_before_regex() -> None:
    """The sentinel rejection MUST fire even if a future regex would
    erroneously accept it. The error message names the sentinel
    explicitly, distinguishing it from the generic shape error.
    """
    # The sentinel-specific error message says "reserved sentinel"; the
    # generic shape error says "must match agt_<12-hex-lowercase>".
    with pytest.raises(RegistrationError) as info:
        validate_agent_id_shape(HOST_OPERATOR_SENTINEL)
    assert "reserved sentinel" in info.value.message


def test_validate_agent_id_shape_still_accepts_valid_agent_ids() -> None:
    """The sentinel reservation must NOT break the happy path."""
    valid = "agt_a1b2c3d4e5f6"
    assert validate_agent_id_shape(valid) == valid


def test_validate_agent_id_shape_still_rejects_invalid_shape() -> None:
    """The sentinel reservation must NOT shadow the existing shape rules."""
    with pytest.raises(RegistrationError) as info:
        validate_agent_id_shape("agt_BADCASE12345")  # uppercase
    assert info.value.code == "value_out_of_set"
    # Generic shape error, not sentinel error.
    assert "reserved sentinel" not in info.value.message


def test_generate_agent_id_cannot_produce_sentinel() -> None:
    """``generate_agent_id`` returns ``agt_<12-hex>``; the sentinel does
    not start with ``agt_`` so collisions are impossible by construction.

    Smoke-test: 1,000 generated ids do not match the sentinel and all
    match the agent_id regex.
    """
    for _ in range(1000):
        gen = generate_agent_id()
        assert gen != HOST_OPERATOR_SENTINEL
        assert AGENT_ID_RE.match(gen) is not None


def test_sentinel_is_disjoint_from_agent_id_namespace() -> None:
    """Final invariant: the sentinel cannot match the agent_id namespace.

    This guards against a future refactor that re-shapes both the
    sentinel and the regex.
    """
    # Sentinel has a hyphen; agent_id namespace is [0-9a-f] in the hex part.
    assert "-" in HOST_OPERATOR_SENTINEL
    assert not re.match(r"^[a-z_]+_[0-9a-f]{12}$", HOST_OPERATOR_SENTINEL)
