"""T089 — synthesized event-type contract tests.

``long_running`` and ``pane_exited`` are NOT regex-matched (FR-016).
They are synthesized by the reader at cycle entry (Plan §R11) when
the FEAT-004 pane state and last-output-at clocks satisfy the
documented eligibility rules.

The synthesis itself is implemented in T079 / T089 / T090 of the
reader. This test file pins the contract-level invariants the
catalogue exposes so the synthesis path can be wired in confidently:

- the rule-id constants are stable (`pane_exited.synth.v1`,
  `long_running.synth.v1`);
- synthetic ids are NOT in the matcher tuple (so a regex never
  classifies a record as ``pane_exited`` or ``long_running``);
- the synthetic ids match the JSON schema's classifier_rule_id
  pattern;
- the FR-008 closed set is exhaustively covered by matchers +
  synthesized types.
"""

from __future__ import annotations

import re

from agenttower.events.classifier import classify
from agenttower.events.classifier_rules import (
    LONG_RUNNING_SYNTH_RULE_ID,
    PANE_EXITED_SYNTH_RULE_ID,
    RULES,
    SYNTHETIC_RULE_IDS,
    _EVENT_TYPES,
)


def test_synthetic_rule_id_constants_are_stable() -> None:
    assert PANE_EXITED_SYNTH_RULE_ID == "pane_exited.synth.v1"
    assert LONG_RUNNING_SYNTH_RULE_ID == "long_running.synth.v1"
    assert set(SYNTHETIC_RULE_IDS) == {
        PANE_EXITED_SYNTH_RULE_ID, LONG_RUNNING_SYNTH_RULE_ID,
    }


def test_synthetic_rule_ids_match_the_classifier_rule_id_pattern() -> None:
    """The JSON schema's classifier_rule_id pattern accepts the
    synthetic ids (so a synthesized event row passes schema
    validation)."""
    pattern = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)?\.v[0-9]+$")
    for sid in SYNTHETIC_RULE_IDS:
        assert pattern.match(sid), f"synthetic {sid!r} doesn't match schema pattern"


def test_synthetic_types_are_not_in_matcher_tuple() -> None:
    """A regex matcher MUST NEVER produce ``pane_exited`` or
    ``long_running`` (FR-016)."""
    matcher_types = {r.event_type for r in RULES}
    assert "pane_exited" not in matcher_types
    assert "long_running" not in matcher_types


def test_event_type_closed_set_is_covered_by_matchers_plus_synthesized() -> None:
    matcher_types = {r.event_type for r in RULES}
    synthesized = {"pane_exited", "long_running"}
    assert set(_EVENT_TYPES) == matcher_types | synthesized


def test_classify_never_returns_long_running_or_pane_exited() -> None:
    """FR-016: pane_exited MUST NOT be inferred from log text alone.
    FR-013: long_running is synthesized — not classified."""
    candidates = [
        "pane exited unexpectedly",
        "process is long_running",
        "pane_exited at 12:00",
        "long-running task in progress",
    ]
    for record in candidates:
        out = classify(record)
        assert out.event_type not in ("pane_exited", "long_running"), (
            f"record {record!r} classified as {out.event_type!r}; "
            "synthesized types must NEVER come from a regex match"
        )
