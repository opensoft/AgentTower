"""T015 — FEAT-010 deterministic master arbitration tests.

Covers ``agenttower.routing.arbitration.pick_master``:

* ``master_rule='auto'`` with N ≥ 2 active masters picks lex-lowest
  ``agent_id`` (FR-017). Tested at N=2, N=3, N=5 + SC-002's 100%
  determinism threshold over N=100 simulated fires.
* ``master_rule='auto'`` with 0 active masters → MasterSkip(no_eligible_master).
* ``master_rule='explicit'`` + active match → MasterWon.
* ``master_rule='explicit'`` + registered-but-inactive → MasterSkip(master_inactive).
* ``master_rule='explicit'`` + no record in snapshot → MasterSkip(master_not_found).
* Unknown master_rule → RouteMasterRuleInvalid (caught at route-add time
  via the routes_service layer; pick_master defends in depth).
* T035 invariant: implementation uses ``sorted(...)[0]``, NOT ``min()``
  or streaming-min — verified via AST inspection.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass

import pytest

from agenttower.routing import arbitration as arb
from agenttower.routing.route_errors import RouteMasterRuleInvalid


# ──────────────────────────────────────────────────────────────────────
# Lightweight test double (Protocol-compatible with AgentRecord)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeAgent:
    agent_id: str
    role: str = "master"
    active: bool = True


# ──────────────────────────────────────────────────────────────────────
# master_rule='auto' — lex-lowest selection (FR-017 / SC-002)
# ──────────────────────────────────────────────────────────────────────


def test_auto_picks_lex_lowest_at_n_two() -> None:
    result = arb.pick_master(
        master_rule="auto",
        master_value=None,
        active_masters=[
            _FakeAgent("agt_bbbbbb222222"),
            _FakeAgent("agt_aaaaaa111111"),
        ],
    )
    assert isinstance(result, arb.MasterWon)
    assert result.agent.agent_id == "agt_aaaaaa111111"


def test_auto_picks_lex_lowest_at_n_three() -> None:
    result = arb.pick_master(
        master_rule="auto",
        master_value=None,
        active_masters=[
            _FakeAgent("agt_ccccccccccc1"),
            _FakeAgent("agt_aaaaaaaaaaa1"),
            _FakeAgent("agt_bbbbbbbbbbb1"),
        ],
    )
    assert isinstance(result, arb.MasterWon)
    assert result.agent.agent_id == "agt_aaaaaaaaaaa1"


def test_auto_picks_lex_lowest_at_n_five() -> None:
    candidates = [_FakeAgent(f"agt_{c}{'0' * 11}") for c in "edcba"]
    result = arb.pick_master(
        master_rule="auto",
        master_value=None,
        active_masters=candidates,
    )
    assert isinstance(result, arb.MasterWon)
    assert result.agent.agent_id == "agt_a00000000000"


def test_auto_is_deterministic_across_n_one_hundred_fires_sc002() -> None:
    """SC-002 acceptance: with N ≥ 2 active masters, 100/100 fires must
    pick the lex-lowest agent_id."""
    candidates = [
        _FakeAgent("agt_aaaaaa111111"),
        _FakeAgent("agt_bbbbbb222222"),
        _FakeAgent("agt_cccccc333333"),
    ]
    results = [
        arb.pick_master(
            master_rule="auto",
            master_value=None,
            active_masters=candidates,
        )
        for _ in range(100)
    ]
    assert all(isinstance(r, arb.MasterWon) for r in results)
    assert all(
        r.agent.agent_id == "agt_aaaaaa111111" for r in results
    ), "SC-002 violated — non-lex-lowest winner in 100-fire run"


def test_auto_ignores_non_master_role() -> None:
    """Defense-in-depth: the caller should pre-filter the snapshot to
    role='master', but pick_master re-checks."""
    result = arb.pick_master(
        master_rule="auto",
        master_value=None,
        active_masters=[
            _FakeAgent("agt_aaaaaa111111", role="slave"),
            _FakeAgent("agt_bbbbbb222222", role="master"),
        ],
    )
    assert isinstance(result, arb.MasterWon)
    assert result.agent.agent_id == "agt_bbbbbb222222"


def test_auto_ignores_inactive_master() -> None:
    """Defense-in-depth re-check of active=True."""
    result = arb.pick_master(
        master_rule="auto",
        master_value=None,
        active_masters=[
            _FakeAgent("agt_aaaaaa111111", active=False),
            _FakeAgent("agt_bbbbbb222222", active=True),
        ],
    )
    assert isinstance(result, arb.MasterWon)
    assert result.agent.agent_id == "agt_bbbbbb222222"


# ──────────────────────────────────────────────────────────────────────
# master_rule='auto' — empty snapshot (FR-018 + SC-003)
# ──────────────────────────────────────────────────────────────────────


def test_auto_with_zero_active_masters_skips_no_eligible_master() -> None:
    result = arb.pick_master(
        master_rule="auto",
        master_value=None,
        active_masters=[],
    )
    assert isinstance(result, arb.MasterSkip)
    assert result.reason == arb.NO_ELIGIBLE_MASTER


def test_auto_with_all_inactive_skips_no_eligible_master() -> None:
    result = arb.pick_master(
        master_rule="auto",
        master_value=None,
        active_masters=[
            _FakeAgent("agt_aaaaaa111111", active=False),
            _FakeAgent("agt_bbbbbb222222", active=False),
        ],
    )
    assert isinstance(result, arb.MasterSkip)
    assert result.reason == arb.NO_ELIGIBLE_MASTER


# ──────────────────────────────────────────────────────────────────────
# master_rule='explicit' — three branches (FR-016 + Story 3 #2/#3)
# ──────────────────────────────────────────────────────────────────────


def test_explicit_picks_named_master_when_active() -> None:
    result = arb.pick_master(
        master_rule="explicit",
        master_value="agt_bbbbbb222222",
        active_masters=[
            _FakeAgent("agt_aaaaaa111111"),
            _FakeAgent("agt_bbbbbb222222"),
            _FakeAgent("agt_cccccc333333"),
        ],
    )
    assert isinstance(result, arb.MasterWon)
    assert result.agent.agent_id == "agt_bbbbbb222222"


def test_explicit_skips_master_inactive_when_named_is_inactive() -> None:
    result = arb.pick_master(
        master_rule="explicit",
        master_value="agt_bbbbbb222222",
        active_masters=[
            _FakeAgent("agt_aaaaaa111111", active=True),
            _FakeAgent("agt_bbbbbb222222", active=False),
        ],
    )
    assert isinstance(result, arb.MasterSkip)
    assert result.reason == arb.MASTER_INACTIVE


def test_explicit_skips_master_not_found_when_named_is_absent() -> None:
    result = arb.pick_master(
        master_rule="explicit",
        master_value="agt_zzzzzz999999",
        active_masters=[
            _FakeAgent("agt_aaaaaa111111"),
            _FakeAgent("agt_bbbbbb222222"),
        ],
    )
    assert isinstance(result, arb.MasterSkip)
    assert result.reason == arb.MASTER_NOT_FOUND


def test_explicit_with_named_master_present_but_role_not_master() -> None:
    """If the named agent_id is in the snapshot but its role is not
    'master' (defensive — should be impossible if caller pre-filters),
    treat as ``master_inactive``."""
    result = arb.pick_master(
        master_rule="explicit",
        master_value="agt_bbbbbb222222",
        active_masters=[
            _FakeAgent("agt_bbbbbb222222", role="slave", active=True),
        ],
    )
    assert isinstance(result, arb.MasterSkip)
    assert result.reason == arb.MASTER_INACTIVE


# ──────────────────────────────────────────────────────────────────────
# Validation errors
# ──────────────────────────────────────────────────────────────────────


def test_unknown_master_rule_raises() -> None:
    with pytest.raises(RouteMasterRuleInvalid, match="not in"):
        arb.pick_master(
            master_rule="round_robin",
            master_value=None,
            active_masters=[],
        )


def test_explicit_without_master_value_raises() -> None:
    with pytest.raises(RouteMasterRuleInvalid, match="non-NULL master_value"):
        arb.pick_master(
            master_rule="explicit",
            master_value=None,
            active_masters=[],
        )


# ──────────────────────────────────────────────────────────────────────
# T035 invariant — sorted(...)[0] pattern, NOT min()
# ──────────────────────────────────────────────────────────────────────


def test_pick_auto_uses_sorted_not_min_per_t035_invariant() -> None:
    """tasks.md T035: confirm ``_pick_auto`` implements the lex-lowest
    selection as ``sorted(..., key=lambda a: a.agent_id)[0]`` and NOT
    ``min(...)``. The reason: ``sorted`` makes the determinism
    contract obvious at code-review time and removes any risk of a
    streaming-min edge case under unusual collection types.

    Implemented as an AST walk so a future refactor that switches to
    ``min`` would fail this test immediately.
    """
    source = inspect.getsource(arb._pick_auto)
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    func_names = {
        c.func.id for c in calls if isinstance(c.func, ast.Name)
    }
    assert "sorted" in func_names, (
        "T035 invariant: _pick_auto MUST use sorted(...) for the "
        "lex-lowest pick"
    )
    assert "min" not in func_names, (
        "T035 invariant: _pick_auto MUST NOT use min() — see docstring "
        "for rationale (sorted-then-[0] is the canonical pattern)"
    )
