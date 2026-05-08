"""Unit tests for FEAT-006 agent_id generation and shape validation (T012 / FR-001).

Covers:

* ``generate_agent_id`` returns ``agt_<12-hex>`` strings (16 chars).
* ``validate_agent_id_shape`` accepts valid forms.
* ``validate_agent_id_shape`` rejects mixed-case (``AGT_abc...``,
  ``agt_ABC...``) without normalization (Clarifications session
  2026-05-07-continued Q2).
* The collision-retry contract is exercised at the service layer
  (``test_register_idempotency.py``); this file pins only the ID-shape
  contract.
"""

from __future__ import annotations

import re

import pytest

from agenttower.agents.errors import RegistrationError
from agenttower.agents.identifiers import (
    AGENT_ID_RE,
    generate_agent_id,
    validate_agent_id_shape,
)


def test_generate_agent_id_shape() -> None:
    for _ in range(200):
        agent_id = generate_agent_id()
        assert len(agent_id) == 16
        assert AGENT_ID_RE.match(agent_id)
        assert agent_id.startswith("agt_")
        assert re.fullmatch(r"[0-9a-f]{12}", agent_id[4:])


def test_generate_agent_id_uniqueness_in_bulk() -> None:
    """48 bits of entropy makes accidental dup vanishingly unlikely at MVP scale.

    Birthday-bound first expected collision is at ~2^24 ≈ 16M unique
    ids; 2,000 draws stay well clear of any plausible collision.
    """
    ids = {generate_agent_id() for _ in range(2_000)}
    assert len(ids) == 2_000


def test_validate_agent_id_shape_accepts_canonical() -> None:
    assert validate_agent_id_shape("agt_abc123def456") == "agt_abc123def456"
    assert validate_agent_id_shape("agt_000000000000") == "agt_000000000000"
    assert validate_agent_id_shape("agt_ffffffffffff") == "agt_ffffffffffff"


@pytest.mark.parametrize(
    "bad",
    [
        "AGT_abc123def456",       # mixed-case prefix
        "agt_ABC123DEF456",       # mixed-case hex
        "agt_abc123def4567",      # too long
        "agt_abc123def45",        # too short
        "agt_abc123def4XY",       # non-hex chars
        "agtabc123def456",        # missing underscore
        "abc123def456",           # missing prefix
        "",                       # empty
    ],
)
def test_validate_agent_id_shape_rejects(bad: str) -> None:
    with pytest.raises(RegistrationError) as info:
        validate_agent_id_shape(bad)
    assert info.value.code == "value_out_of_set"


def test_validate_agent_id_shape_rejects_non_string() -> None:
    with pytest.raises(RegistrationError) as info:
        validate_agent_id_shape(12345)  # type: ignore[arg-type]
    assert info.value.code == "value_out_of_set"
