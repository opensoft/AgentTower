"""T024 — strict ``AGENTTOWER_SWARM_MEMBER`` parser tests (FR-009).

Per FR-009 / spec.md edge case: malformed variants fall through to
``activity`` and MUST NOT produce a ``swarm_member_reported`` event.
"""

from __future__ import annotations

import pytest

from agenttower.events.classifier import classify
from agenttower.events.classifier_rules import parse_swarm_member


# --------------------------------------------------------------------------
# Positive: parse_swarm_member returns the documented dict.
# --------------------------------------------------------------------------


def test_parse_swarm_member_returns_named_groups() -> None:
    line = (
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%17 "
        "label=worker-2 capability=test purpose=run-tests"
    )
    parsed = parse_swarm_member(line)
    assert parsed == {
        "parent": "agt_a1b2c3d4e5f6",
        "pane": "%17",
        "label": "worker-2",
        "capability": "test",
        "purpose": "run-tests",
    }


def test_classify_swarm_member_emits_swarm_member_reported() -> None:
    line = (
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%17 "
        "label=worker-2 capability=test purpose=run-tests"
    )
    out = classify(line)
    assert out.event_type == "swarm_member_reported"
    assert out.rule_id == "swarm_member.v1"


def test_parse_swarm_member_purpose_long_string_under_cap() -> None:
    """The matcher caps purpose at 256 chars; a 200-char purpose works."""
    purpose = "a" * 200
    line = (
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%1 "
        f"label=foo capability=bar purpose={purpose}"
    )
    parsed = parse_swarm_member(line)
    assert parsed is not None
    assert parsed["purpose"] == purpose


# --------------------------------------------------------------------------
# Negative: malformed variants → None (and classify() returns activity).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed",
    [
        # missing required keys
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6",
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%2",
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%2 label=foo",
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%2 label=foo capability=bar",
        # invalid agent_id shape (not 12 hex)
        "AGENTTOWER_SWARM_MEMBER parent=agt_xx pane=%1 label=l capability=c purpose=p",
        "AGENTTOWER_SWARM_MEMBER parent=foo pane=%1 label=l capability=c purpose=p",
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5 pane=%1 label=l capability=c purpose=p",
        # invalid pane shape
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=2 label=l capability=c purpose=p",
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%abc label=l capability=c purpose=p",
        # whitespace-corrupted (extra spaces)
        "AGENTTOWER_SWARM_MEMBER  parent=agt_a1b2c3d4e5f6 pane=%1 label=l capability=c purpose=p",
        # missing the AGENTTOWER_SWARM_MEMBER prefix
        "parent=agt_a1b2c3d4e5f6 pane=%1 label=l capability=c purpose=p",
        # leading/trailing junk
        "junk AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%1 label=l capability=c purpose=p",
        # blank label / capability (\\S+ rejects empty)
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%1 label= capability=c purpose=p",
        # empty purpose ({1,256} requires at least 1 char)
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%1 label=l capability=c purpose=",
    ],
)
def test_malformed_swarm_member_returns_none(malformed: str) -> None:
    assert parse_swarm_member(malformed) is None


@pytest.mark.parametrize(
    "malformed",
    [
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6",
        "AGENTTOWER_SWARM_MEMBER parent=agt_xx pane=%1 label=l capability=c purpose=p",
        "AGENTTOWER_SWARM_MEMBER  parent=agt_a1b2c3d4e5f6 pane=%1 label=l capability=c purpose=p",
    ],
)
def test_malformed_swarm_member_classifies_as_activity(malformed: str) -> None:
    """FR-009: malformed → activity, NOT swarm_member_reported."""
    out = classify(malformed)
    assert out.event_type == "activity"
    assert out.rule_id == "activity.fallback.v1"


def test_parse_swarm_member_empty_string() -> None:
    assert parse_swarm_member("") is None
