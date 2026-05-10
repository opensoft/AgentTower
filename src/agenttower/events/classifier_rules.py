"""FEAT-008 classifier rule catalogue (FR-007 / FR-008).

The MVP catalogue is **closed**: adding a rule is a per-feature change.
Each rule is a frozen :class:`ClassifierRule` dataclass; the module-level
:data:`RULES` tuple is sorted by ``priority`` ascending. The classifier
walks the tuple in order and returns the first match
(``contracts/classifier-catalogue.md``).

The two synthesized event types ``pane_exited`` and ``long_running``
do NOT appear in :data:`RULES` — they are produced by the reader at
cycle entry (Plan §R11). Their synthetic rule ids are still exported
here for completeness so the daemon's ``events.classifier_rules``
diagnostic surface can return one canonical list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Pattern


_EVENT_TYPES: Final[tuple[str, ...]] = (
    "activity",
    "waiting_for_input",
    "completed",
    "error",
    "test_failed",
    "test_passed",
    "manual_review_needed",
    "long_running",
    "pane_exited",
    "swarm_member_reported",
)


@dataclass(frozen=True)
class ClassifierRule:
    """One matcher rule.

    Walked in priority order (lower wins). The matcher is evaluated
    against ONE complete record (post-redaction), with no
    ``MULTILINE`` semantics — FR-005 splits on ``\\n`` upstream so a
    record IS a single logical line in MVP.
    """

    rule_id: str
    event_type: str
    matcher: Pattern[str]
    priority: int


# --------------------------------------------------------------------------
# Rule definitions — `contracts/classifier-catalogue.md` §"Catalogue"
# --------------------------------------------------------------------------

# FR-009 — strict parse for ``AGENTTOWER_SWARM_MEMBER`` line shape.
# ``re.ASCII`` ensures ``\s``, ``\w``, etc. match only ASCII (closed-set
# vocabulary by spec). Malformed variants fall through to the
# ``activity.fallback.v1`` catch-all.
_SWARM_MEMBER_RE: Pattern[str] = re.compile(
    r"^AGENTTOWER_SWARM_MEMBER "
    r"parent=(?P<parent>agt_[0-9a-f]{12}) "
    r"pane=(?P<pane>%[0-9]+) "
    r"label=(?P<label>\S+) "
    r"capability=(?P<capability>\S+) "
    r"purpose=(?P<purpose>.{1,256})$",
    flags=re.ASCII,
)


def parse_swarm_member(record: str) -> dict[str, str] | None:
    """Return the parsed key/value dict iff *record* is a valid
    swarm-member line; ``None`` on any malformed variant.

    Used by the ``swarm_member.v1`` rule and exposed for tests
    (FR-009). Empty string also returns ``None``.
    """
    if not record:
        return None
    m = _SWARM_MEMBER_RE.match(record)
    if m is None:
        return None
    return {
        "parent": m.group("parent"),
        "pane": m.group("pane"),
        "label": m.group("label"),
        "capability": m.group("capability"),
        "purpose": m.group("purpose"),
    }


_RULES_UNORDERED: tuple[ClassifierRule, ...] = (
    ClassifierRule(
        rule_id="swarm_member.v1",
        event_type="swarm_member_reported",
        matcher=_SWARM_MEMBER_RE,
        priority=10,
    ),
    ClassifierRule(
        rule_id="manual_review.v1",
        event_type="manual_review_needed",
        # Note: ``TODO(human)`` ends with ``)`` which is not a word
        # character, so ``\b`` doesn't apply. Split the alternation
        # so we apply ``\b`` only to the underscore/dash forms.
        matcher=re.compile(
            r"(?:^|\s)(?:(?:MANUAL[_-]REVIEW|REVIEW[_-]REQUIRED)\b|TODO\(human\))"
        ),
        priority=20,
    ),
    ClassifierRule(
        rule_id="error.traceback.v1",
        event_type="error",
        matcher=re.compile(r"^Traceback \(most recent call last\):"),
        priority=30,
    ),
    ClassifierRule(
        rule_id="error.line.v1",
        event_type="error",
        matcher=re.compile(r"^(?:Error|ERROR|Exception)[: ]"),
        priority=31,
    ),
    ClassifierRule(
        rule_id="test_failed.pytest.v1",
        event_type="test_failed",
        # Pytest verbose summary line: "FAILED <path>::<name> [- ...]"
        # or "ERROR <path>::<name> [- ...]". Anchored at line start.
        matcher=re.compile(r"^(?:FAILED|ERROR) \S+::\S+"),
        priority=40,
    ),
    ClassifierRule(
        rule_id="test_failed.generic.v1",
        event_type="test_failed",
        matcher=re.compile(r"\b(?:test failed|tests failed|FAIL)\b"),
        priority=41,
    ),
    ClassifierRule(
        rule_id="test_passed.pytest.v1",
        event_type="test_passed",
        matcher=re.compile(r"^=+ \d+ passed(?: in [\d.]+s)? =+$"),
        priority=50,
    ),
    ClassifierRule(
        rule_id="test_passed.generic.v1",
        event_type="test_passed",
        matcher=re.compile(r"\b(?:all tests passed|tests passed)\b"),
        priority=51,
    ),
    ClassifierRule(
        rule_id="completed.v1",
        event_type="completed",
        # Case-insensitive — ``Build succeeded`` and ``build succeeded``
        # both classify as ``completed``. ``DONE`` is conventionally
        # uppercase but a case-insensitive match here is harmless and
        # consistent with the other phrases.
        matcher=re.compile(
            r"(?:^|\s)(?:DONE|completed successfully|task completed|build succeeded)\b",
            flags=re.IGNORECASE,
        ),
        priority=60,
    ),
    ClassifierRule(
        rule_id="waiting_for_input.v1",
        event_type="waiting_for_input",
        # Common interactive-prompt shapes. Single-line records (FR-005).
        matcher=re.compile(
            r"(?:.*\?\s*$"
            r"|.* \[Y/n\]\s*$"
            r"|.* \(yes/no\)\s*$"
            r"|>>>\s*$"
            r"|>\s+$"
            r"|Continue\?\s*$)"
        ),
        priority=70,
    ),
    ClassifierRule(
        rule_id="activity.fallback.v1",
        event_type="activity",
        matcher=re.compile(r".+"),  # non-empty record (FR-011 default)
        priority=999,
    ),
)


#: Authoritative ordered tuple. Sorted by priority ascending.
RULES: Final[tuple[ClassifierRule, ...]] = tuple(
    sorted(_RULES_UNORDERED, key=lambda r: r.priority)
)


# --------------------------------------------------------------------------
# Synthetic rule ids — emitted by the reader, NOT in :data:`RULES`.
# (Plan §R11 — `pane_exited` and `long_running` are time-driven, not
# regex-driven.)
# --------------------------------------------------------------------------

PANE_EXITED_SYNTH_RULE_ID: Final[str] = "pane_exited.synth.v1"
LONG_RUNNING_SYNTH_RULE_ID: Final[str] = "long_running.synth.v1"

SYNTHETIC_RULE_IDS: Final[tuple[str, ...]] = (
    PANE_EXITED_SYNTH_RULE_ID,
    LONG_RUNNING_SYNTH_RULE_ID,
)


# --------------------------------------------------------------------------
# Module-level invariants (asserted at import for early failure)
# --------------------------------------------------------------------------

# Every event_type in the FR-008 closed set is either covered by at
# least one matcher rule OR by a synthetic rule. Catches dropped rules
# during refactors. ``activity`` is covered by the catch-all.
_MATCHER_TYPES = {r.event_type for r in RULES}
_SYNTHESIZED_TYPES = {"pane_exited", "long_running"}
assert set(_EVENT_TYPES) == (_MATCHER_TYPES | _SYNTHESIZED_TYPES), (
    f"FR-008 event_type coverage mismatch: matchers={sorted(_MATCHER_TYPES)}, "
    f"synthesized={sorted(_SYNTHESIZED_TYPES)}, "
    f"declared={sorted(_EVENT_TYPES)}"
)

# Priority values must be unique so the priority order is total.
_PRIORITIES = [r.priority for r in RULES]
assert len(_PRIORITIES) == len(set(_PRIORITIES)), (
    f"classifier rule priorities must be unique; got {_PRIORITIES}"
)

# rule_id format pattern. Accepts both the 2-segment form
# (``swarm_member.v1``) and the 3-segment form
# (``error.traceback.v1``) that the catalogue uses; the JSON schema's
# ``classifier_rule_id`` constraint in ``contracts/event-schema.md``
# accepts the same set.
_RULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)?\.v[0-9]+$")
for _r in RULES:
    assert _RULE_ID_RE.match(_r.rule_id), (
        f"rule_id {_r.rule_id!r} does not match the documented pattern"
    )
for _id in SYNTHETIC_RULE_IDS:
    assert _RULE_ID_RE.match(_id), (
        f"synthetic rule_id {_id!r} does not match the documented pattern"
    )


__all__ = [
    "ClassifierRule",
    "RULES",
    "SYNTHETIC_RULE_IDS",
    "PANE_EXITED_SYNTH_RULE_ID",
    "LONG_RUNNING_SYNTH_RULE_ID",
    "parse_swarm_member",
]
