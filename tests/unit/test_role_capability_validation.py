"""Unit tests for FEAT-006 closed-set role / capability validation (T013).

Covers FR-004 / FR-005:
* Every closed-set value is accepted.
* Out-of-set values are rejected with closed-set code ``value_out_of_set``.
* Mixed-case (``Slave``, ``MASTER``, ``Codex``) is rejected without
  normalization (Clarifications session 2026-05-07-continued Q2).
"""

from __future__ import annotations

import pytest

from agenttower.agents.errors import RegistrationError
from agenttower.agents.validation import (
    VALID_CAPABILITIES,
    VALID_ROLES,
    validate_capability,
    validate_role,
)


@pytest.mark.parametrize("role", VALID_ROLES)
def test_role_accepts_canonical_lowercase(role: str) -> None:
    assert validate_role(role) == role


@pytest.mark.parametrize("cap", VALID_CAPABILITIES)
def test_capability_accepts_canonical_lowercase(cap: str) -> None:
    assert validate_capability(cap) == cap


@pytest.mark.parametrize("bad", ["Slave", "MASTER", "Test-Runner", "shell ", "", "robot", 42])
def test_role_rejects_mixed_case_or_unknown(bad: object) -> None:
    with pytest.raises(RegistrationError) as info:
        validate_role(bad)
    assert info.value.code == "value_out_of_set"
    # Actionable message lists the canonical lowercase tokens.
    for token in VALID_ROLES:
        assert token in info.value.message


@pytest.mark.parametrize("bad", ["Claude", "CODEX", "Gemini", "openCode", "", "vim", None])
def test_capability_rejects_mixed_case_or_unknown(bad: object) -> None:
    with pytest.raises(RegistrationError) as info:
        validate_capability(bad)
    assert info.value.code == "value_out_of_set"
    for token in VALID_CAPABILITIES:
        assert token in info.value.message
