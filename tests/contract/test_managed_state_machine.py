"""FEAT-013 state-machine contract test (T018).

Covers FR-007 transitions (creating / ready / degraded / failed / removed),
the illegal-transition rejection set, FR-026 layout-state aggregation
from per-pane distributions, and the reserved ``promoted_from_adopted``
transition stub (FR-018).
"""

from __future__ import annotations

import pytest

from agenttower.managed_sessions.state_machine import (
    PROMOTE_FROM_ADOPTED,
    FailedStage,
    ManagedState,
    aggregate_layout_state,
    assert_allowed,
    is_allowed,
    is_terminal,
)


# ─── Allowed transitions (per contracts/state-machine.md §Pane transitions) ──


@pytest.mark.parametrize(
    "src, dst",
    [
        (ManagedState.CREATING, ManagedState.READY),
        (ManagedState.CREATING, ManagedState.DEGRADED),
        (ManagedState.CREATING, ManagedState.FAILED),
        (ManagedState.READY, ManagedState.DEGRADED),
        (ManagedState.READY, ManagedState.REMOVED),
        (ManagedState.DEGRADED, ManagedState.REMOVED),
        (ManagedState.DEGRADED, ManagedState.FAILED),
        (ManagedState.FAILED, ManagedState.REMOVED),
    ],
)
def test_allowed_transitions(src: ManagedState, dst: ManagedState) -> None:
    assert is_allowed(src, dst)


def test_self_transitions_are_allowed() -> None:
    """``X → X`` is allowed (idempotent observation)."""
    for state in ManagedState:
        assert is_allowed(state, state)


# ─── Disallowed transitions (must be rejected) ────────────────────────────


@pytest.mark.parametrize(
    "src, dst",
    [
        # Recovery from degraded/failed back to ready is forbidden;
        # recovery goes via recreate (FR-011 + research §R3).
        (ManagedState.DEGRADED, ManagedState.READY),
        (ManagedState.FAILED, ManagedState.READY),
        (ManagedState.READY, ManagedState.CREATING),
        # Terminal: REMOVED has no outgoing transitions.
        (ManagedState.REMOVED, ManagedState.READY),
        (ManagedState.REMOVED, ManagedState.CREATING),
        (ManagedState.REMOVED, ManagedState.DEGRADED),
        (ManagedState.REMOVED, ManagedState.FAILED),
    ],
)
def test_disallowed_transitions(src: ManagedState, dst: ManagedState) -> None:
    assert not is_allowed(src, dst)


def test_assert_allowed_raises_on_illegal_transition() -> None:
    with pytest.raises(ValueError, match="illegal managed_pane transition"):
        assert_allowed(ManagedState.REMOVED, ManagedState.READY)


def test_assert_allowed_silent_on_legal_transition() -> None:
    # Returns ``None``; no exception.
    assert assert_allowed(ManagedState.CREATING, ManagedState.READY) is None


# ─── Terminal-state check ─────────────────────────────────────────────────


def test_removed_is_terminal() -> None:
    assert is_terminal(ManagedState.REMOVED)


@pytest.mark.parametrize(
    "state",
    [
        ManagedState.CREATING,
        ManagedState.READY,
        ManagedState.DEGRADED,
        ManagedState.FAILED,
    ],
)
def test_non_removed_states_are_not_terminal(state: ManagedState) -> None:
    assert not is_terminal(state)


# ─── Layout state aggregation (FR-026 worst-child rule) ───────────────────


def test_aggregate_all_ready_is_ready() -> None:
    assert aggregate_layout_state(
        [ManagedState.READY, ManagedState.READY, ManagedState.READY]
    ) == ManagedState.READY


def test_aggregate_any_creating_is_creating() -> None:
    assert aggregate_layout_state(
        [ManagedState.READY, ManagedState.CREATING, ManagedState.READY]
    ) == ManagedState.CREATING


def test_aggregate_any_failed_dominates_degraded() -> None:
    """FR-026 worst-child rule: ``failed`` beats ``degraded``."""
    assert aggregate_layout_state(
        [ManagedState.DEGRADED, ManagedState.FAILED, ManagedState.READY]
    ) == ManagedState.FAILED


def test_aggregate_degraded_when_no_failed() -> None:
    assert aggregate_layout_state(
        [ManagedState.READY, ManagedState.DEGRADED, ManagedState.READY]
    ) == ManagedState.DEGRADED


def test_aggregate_all_removed_is_removed() -> None:
    assert aggregate_layout_state(
        [ManagedState.REMOVED, ManagedState.REMOVED]
    ) == ManagedState.REMOVED


def test_aggregate_ready_plus_removed_is_ready() -> None:
    """A layout with some panes removed but the rest ``ready`` is ``ready``."""
    assert aggregate_layout_state(
        [ManagedState.READY, ManagedState.REMOVED, ManagedState.READY]
    ) == ManagedState.READY


def test_aggregate_empty_raises() -> None:
    with pytest.raises(ValueError):
        aggregate_layout_state([])


# ─── Failed-stage closed enum (research §R7 / FR-013 amendment) ───────────


def test_failed_stage_enum_has_exact_six_members() -> None:
    expected = {
        "pane_create",
        "launch_command",
        "registration",
        "log_attach",
        "tmux_kill",
        "recovery_reattach",
    }
    actual = {member.value for member in FailedStage}
    assert actual == expected


# ─── Reserved promote_from_adopted transition (FR-018) ────────────────────


def test_promote_from_adopted_is_reserved_constant() -> None:
    """The constant exists but is not invokable in MVP — service returns
    ``not_implemented``."""
    assert PROMOTE_FROM_ADOPTED == "promoted_from_adopted"
