"""T086 — JSONL namespace disjointness across FEAT-007 / FEAT-008 / FEAT-009.

Research §R-008: each FEAT's audit / event surface carries its own
closed-set ``event_type`` (or lifecycle ``event``) token. The three
namespaces MUST be pairwise disjoint so an operator reading
``events.jsonl`` or the lifecycle log can immediately attribute a row
to one feature without ambiguity.

This test imports each FEAT's closed set and asserts:

1. FEAT-007 lifecycle events ∩ FEAT-008 classifier event types = ∅.
2. FEAT-007 lifecycle events ∩ FEAT-009 queue audit types = ∅.
3. FEAT-007 lifecycle events ∩ FEAT-009 routing audit types = ∅.
4. FEAT-008 classifier types ∩ FEAT-009 queue audit types = ∅.
5. FEAT-008 classifier types ∩ FEAT-009 routing audit types = ∅.
6. FEAT-009 queue audit types ∩ FEAT-009 routing audit types = ∅.

If a future feature adds a new namespace, extend this test with the
new closed set and re-run the pairwise check.
"""

from __future__ import annotations

import itertools

import pytest

from agenttower.events.dao import _EVENT_TYPES as FEAT008_EVENT_TYPES
from agenttower.routing import (
    _QUEUE_AUDIT_EVENT_TYPES,
    _ROUTING_AUDIT_EVENT_TYPES,
)
from agenttower.socket_api.lifecycle import LIFECYCLE_EVENTS


_NAMESPACES: dict[str, frozenset[str]] = {
    "FEAT-007 lifecycle events": LIFECYCLE_EVENTS,
    "FEAT-008 classifier event types": frozenset(FEAT008_EVENT_TYPES),
    "FEAT-009 queue audit event types": _QUEUE_AUDIT_EVENT_TYPES,
    "FEAT-009 routing audit event types": _ROUTING_AUDIT_EVENT_TYPES,
}


def test_every_namespace_is_nonempty() -> None:
    """Sanity: every namespace was imported as a non-empty frozenset.
    Catches accidental import-rename or empty-export regressions."""
    for name, ns in _NAMESPACES.items():
        assert len(ns) > 0, f"namespace {name!r} is empty"


@pytest.mark.parametrize(
    "left_name, right_name",
    list(itertools.combinations(_NAMESPACES.keys(), 2)),
)
def test_pairwise_disjointness(left_name: str, right_name: str) -> None:
    """Every pair of namespaces MUST have an empty intersection
    (Research §R-008)."""
    left = _NAMESPACES[left_name]
    right = _NAMESPACES[right_name]
    overlap = left & right
    assert overlap == set(), (
        f"namespace overlap detected between {left_name} and {right_name}: "
        f"{sorted(overlap)}"
    )


def test_feat009_queue_namespace_has_seven_types() -> None:
    """FEAT-009 declares exactly seven queue_message_* audit types
    (one per state transition + the enqueue event). If this number
    changes, the data-model.md §7 inventory MUST be updated in lockstep."""
    assert len(_QUEUE_AUDIT_EVENT_TYPES) == 7
    # All tokens start with the queue_message_ prefix.
    for token in _QUEUE_AUDIT_EVENT_TYPES:
        assert token.startswith("queue_message_"), token


def test_feat009_routing_namespace_is_singleton() -> None:
    """FEAT-009 declares exactly one routing audit type
    (``routing_toggled``)."""
    assert _ROUTING_AUDIT_EVENT_TYPES == frozenset({"routing_toggled"})
