"""FEAT-013 T040: promote_from_adopted stub (M8) contract test.

Covers FR-018 / state-machine.md §Promotion stub:
- `promote_from_adopted(agent_id)` always returns `not_implemented`
  with `details.reserved_since = "FEAT-013"`.
- The state-machine module exposes the `PROMOTE_FROM_ADOPTED` constant
  so test fixtures + a later feature's transition table can reference
  the reserved name, but the transition itself is gated off in MVP.
"""

from __future__ import annotations

from agenttower.managed_sessions.service import (
    PromoteFromAdoptedStubResult,
    promote_from_adopted,
)
from agenttower.managed_sessions.state_machine import PROMOTE_FROM_ADOPTED


def test_promote_returns_not_implemented_with_reserved_since() -> None:
    """FR-018: MVP returns ``not_implemented`` with ``details.reserved_since
    = "FEAT-013"``. Operator-facing semantics: "this is reserved for a
    later feature; M8 is the placeholder so the contract surface is
    complete."""
    result = promote_from_adopted("agent-some-id")
    assert isinstance(result, PromoteFromAdoptedStubResult)
    assert result.error_code == "not_implemented"
    assert result.details == {"reserved_since": "FEAT-013"}


def test_promote_state_machine_constant_exists_but_gated() -> None:
    """state-machine.md §Promotion stub: the reserved transition name
    is exposed for tests but the service entry point itself returns
    ``not_implemented``. The constant value matches the canonical
    transition name from the spec."""
    assert PROMOTE_FROM_ADOPTED == "promoted_from_adopted"


def test_promote_is_pure_function_no_side_effects() -> None:
    """The stub doesn't touch SQLite or emit events — purely a function
    that returns a discriminated result type. Calling it repeatedly
    yields identical results."""
    a = promote_from_adopted("agent-A")
    b = promote_from_adopted("agent-B")
    # Different agent_ids produce identical stub outputs because the
    # stub never looks at the input.
    assert a.error_code == b.error_code == "not_implemented"
    assert a.details == b.details == {"reserved_since": "FEAT-013"}
