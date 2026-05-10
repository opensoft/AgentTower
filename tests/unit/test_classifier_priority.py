"""T023 — classifier priority-order determinism.

Per FR-008: when a record matches multiple rules, the documented
priority order resolves the tie deterministically. Each row from
``contracts/classifier-catalogue.md`` §"Priority overlap fixtures"
becomes one assertion here.
"""

from __future__ import annotations

import pytest

from agenttower.events.classifier import classify
from agenttower.events.classifier_rules import RULES


# --------------------------------------------------------------------------
# Priority overlap fixtures (from contracts/classifier-catalogue.md)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record, expected_event_type, expected_rule_id",
    [
        # error.line.v1 (priority 30) precedes test_failed.generic.v1 (41)
        (
            "Error: pytest test_x failed in setup",
            "error",
            "error.line.v1",
        ),
        # error.traceback.v1 (30) — anchored beats error.line.v1 (31)
        # ("Traceback (most recent call last):" matches both anchored
        # patterns in principle but traceback is more specific.)
        (
            "Traceback (most recent call last):",
            "error",
            "error.traceback.v1",
        ),
        # manual_review.v1 (20) precedes error.line.v1 (31).
        (
            "MANUAL_REVIEW: Error: foo",
            "manual_review_needed",
            "manual_review.v1",
        ),
        # test_passed.pytest.v1 matches the pytest summary line shape.
        (
            "=== 12 passed in 1.34s ===",
            "test_passed",
            "test_passed.pytest.v1",
        ),
        # test_failed.pytest.v1 — note this STARTS WITH ``FAILED`` so
        # it would NOT match error.line.v1 (anchored on
        # ``Error|ERROR|Exception``).
        (
            "FAILED tests/test_x.py::test_y - assertion",
            "test_failed",
            "test_failed.pytest.v1",
        ),
        # swarm_member.v1 (10) — highest priority.
        (
            "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%2 "
            "label=foo capability=bar purpose=baz",
            "swarm_member_reported",
            "swarm_member.v1",
        ),
        # Malformed ``AGENTTOWER_SWARM_MEMBER`` — strict parse fails →
        # falls through to activity.fallback.v1 (FR-009). NOT
        # captured as ``swarm_member_reported``.
        (
            "AGENTTOWER_SWARM_MEMBER parent=agt_x",
            "activity",
            "activity.fallback.v1",
        ),
        # No domain rule matches.
        (
            "running tests…",
            "activity",
            "activity.fallback.v1",
        ),
        # Python REPL prompt.
        (
            ">>> ",
            "waiting_for_input",
            "waiting_for_input.v1",
        ),
        # Build succeeded → completed.v1
        (
            "Build succeeded",
            "completed",
            "completed.v1",
        ),
    ],
)
def test_priority_overlap_table(
    record: str, expected_event_type: str, expected_rule_id: str
) -> None:
    """Each row from the priority overlap table classifies to the
    documented (event_type, rule_id)."""
    out = classify(record)
    assert out.event_type == expected_event_type, (
        f"record {record!r}: got event_type={out.event_type!r}; "
        f"expected {expected_event_type!r} (rule_id={out.rule_id})"
    )
    assert out.rule_id == expected_rule_id, (
        f"record {record!r}: got rule_id={out.rule_id!r}; "
        f"expected {expected_rule_id!r}"
    )


# --------------------------------------------------------------------------
# Priority order is total: every rule_id in RULES has a unique,
# strictly-ordered priority value.
# --------------------------------------------------------------------------


def test_rules_priorities_are_unique_and_sorted() -> None:
    priorities = [r.priority for r in RULES]
    assert priorities == sorted(priorities)
    assert len(priorities) == len(set(priorities))


def test_activity_fallback_is_last_priority() -> None:
    """The catch-all MUST sort last so it can never preempt a
    domain rule."""
    assert RULES[-1].rule_id == "activity.fallback.v1"


def test_swarm_member_is_first_priority() -> None:
    """Highest-priority MVP rule per contracts/classifier-catalogue.md."""
    assert RULES[0].rule_id == "swarm_member.v1"


def test_priority_order_is_deterministic_across_repeated_classification() -> None:
    """Same record → same outcome on repeated calls (FR-010 purity)."""
    record = "Error: division by zero"
    out1 = classify(record)
    out2 = classify(record)
    out3 = classify(record)
    assert out1 == out2 == out3
