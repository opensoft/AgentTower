"""FEAT-008 classifier (FR-007 / FR-010 / FR-011 / FR-012).

Pure function: same input bytes plus same prior reader-state inputs
yields same output type. No I/O, no clock reads, no dependency on
mutable global state beyond :data:`classifier_rules.RULES`. Tests can
exercise this surface in isolation without spinning up a daemon.

The reader does NOT call this module for ``pane_exited`` /
``long_running`` events — those are synthesized by the reader at
cycle entry (Plan §R11). For every other complete record the reader
calls :func:`classify` once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import (
    EXCERPT_TRUNCATION_MARKER,
    PER_EVENT_EXCERPT_CAP_BYTES,
)
from . import classifier_rules as rules_module
from ..logs.redaction import redact_one_line


@dataclass(frozen=True)
class ClassifierOutcome:
    """Result of classifying one complete record.

    ``rule_id`` is the matching rule's stable identifier (or one of
    the two synthetic rule ids when the reader synthesizes a
    ``pane_exited`` / ``long_running`` event — but those are NOT
    produced by :func:`classify`).
    """

    event_type: str
    rule_id: str
    excerpt: str  # already redacted and truncated
    redacted_record: str  # full redacted record, pre-truncation


def truncate_excerpt(
    redacted_record: str,
    *,
    cap_bytes: int = PER_EVENT_EXCERPT_CAP_BYTES,
    marker: str = EXCERPT_TRUNCATION_MARKER,
) -> str:
    """Truncate a redacted record to ``cap_bytes``, appending ``marker``.

    The cap is the OUTER bound: the returned string's UTF-8 byte
    length is at most ``cap_bytes``. The marker fits within the cap
    (the prefix is shortened to make room).

    The slicing is byte-aware: we never split a UTF-8 multibyte
    sequence in the middle. Pure function; no globals.
    """
    if cap_bytes <= 0:
        raise ValueError(f"cap_bytes must be > 0; got {cap_bytes}")
    encoded = redacted_record.encode("utf-8")
    if len(encoded) <= cap_bytes:
        return redacted_record

    marker_bytes = marker.encode("utf-8")
    if len(marker_bytes) >= cap_bytes:
        # Marker alone exceeds cap — fall back to byte-safe truncation
        # of the marker. (Edge case; defensive only.)
        return marker_bytes[:cap_bytes].decode("utf-8", errors="ignore")

    available = cap_bytes - len(marker_bytes)
    # Find the largest UTF-8-safe prefix of ``encoded`` not exceeding
    # ``available``. The decode-with-errors='ignore' approach drops
    # any partial multibyte sequence at the boundary.
    safe_prefix = encoded[:available].decode("utf-8", errors="ignore")
    return safe_prefix + marker


def classify(
    record: str,
    *,
    prior_event_type: Optional[str] = None,  # noqa: ARG001 (reserved; FR-013)
    cap_bytes: int = PER_EVENT_EXCERPT_CAP_BYTES,
) -> ClassifierOutcome:
    """Classify one complete record into the FR-008 closed set.

    Order of operations (FR-012, Edge Cases):

    1. ``redact_one_line(record)`` — FEAT-007 redaction utility runs
       FIRST so secret patterns split across the truncation boundary
       remain redacted.
    2. Walk :data:`classifier_rules.RULES` in priority order; the
       first match wins (FR-008). The catch-all
       ``activity.fallback.v1`` matches any non-empty record
       (FR-011 conservative default).
    3. Truncate the redacted excerpt to ``cap_bytes`` with the
       documented marker (Edge Cases).

    ``prior_event_type`` is reserved for FR-013 ``long_running``
    eligibility checks — but ``long_running`` is SYNTHESIZED by the
    reader, not produced here. The argument exists for symmetry with
    future rule additions that depend on prior state; currently
    unused.

    The function is pure: same ``record`` (and same ``cap_bytes``)
    yields the same outcome every call.
    """
    redacted = redact_one_line(record)

    # The catch-all matches non-empty records. Empty strings would
    # never be passed (FR-005 splits on ``\n`` and partial-line
    # carryover keeps the reader honest), but defensive default is
    # still ``activity`` per FR-011.
    matched_rule = None
    for rule in rules_module.RULES:
        if rule.matcher.search(redacted):
            matched_rule = rule
            break

    if matched_rule is None:
        # Empty record. Fall back to ``activity`` per FR-011 default.
        excerpt = truncate_excerpt(redacted, cap_bytes=cap_bytes)
        return ClassifierOutcome(
            event_type="activity",
            rule_id="activity.fallback.v1",
            excerpt=excerpt,
            redacted_record=redacted,
        )

    excerpt = truncate_excerpt(redacted, cap_bytes=cap_bytes)
    return ClassifierOutcome(
        event_type=matched_rule.event_type,
        rule_id=matched_rule.rule_id,
        excerpt=excerpt,
        redacted_record=redacted,
    )
