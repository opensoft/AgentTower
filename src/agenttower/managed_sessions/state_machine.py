"""FEAT-013 lifecycle state machine (T006).

Closed-set state graph for managed_pane (and, by aggregation, managed_layout):

    creating ─► ready ─► degraded ─► removed
       │           │         │
       │           ▼         ▼
       ▼        removed    failed ─► removed
    degraded ────┐
       │         │
       ▼         ▼
    failed ──► removed   (terminal)

See ``specs/013-managed-session-lifecycle/contracts/state-machine.md``
for the authoritative transition table; this module enforces it.

The disallowed transitions (rejected with ``managed_pane_illegal_transition``):

* ``ready → creating``
* ``degraded → ready`` (recovery is via recreate)
* ``failed → ready`` (same)
* ``removed → *``
* ``* → promoted_from_adopted`` (reserved; returns ``not_implemented``)
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class ManagedState(str, Enum):
    """managed_pane / managed_layout lifecycle states (FR-007)."""

    CREATING = "creating"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    REMOVED = "removed"


class FailedStage(str, Enum):
    """Closed-set ``failed_stage`` values (FR-013 amendment, research §R7)."""

    PANE_CREATE = "pane_create"
    LAUNCH_COMMAND = "launch_command"
    REGISTRATION = "registration"
    LOG_ATTACH = "log_attach"
    TMUX_KILL = "tmux_kill"
    RECOVERY_REATTACH = "recovery_reattach"


# Reserved transition name; not invokable in MVP (FR-018 / state-machine.md).
PROMOTE_FROM_ADOPTED: Final[str] = "promoted_from_adopted"


# Allowed transitions per contracts/state-machine.md §Pane transitions.
# Mapping: (from_state, to_state) → True.
_ALLOWED: Final[frozenset[tuple[ManagedState, ManagedState]]] = frozenset(
    {
        (ManagedState.CREATING, ManagedState.READY),
        (ManagedState.CREATING, ManagedState.DEGRADED),
        (ManagedState.CREATING, ManagedState.FAILED),
        (ManagedState.READY, ManagedState.DEGRADED),
        (ManagedState.READY, ManagedState.REMOVED),
        (ManagedState.DEGRADED, ManagedState.REMOVED),
        (ManagedState.DEGRADED, ManagedState.FAILED),
        (ManagedState.FAILED, ManagedState.REMOVED),
    }
)


# Terminal states have no outbound transitions.
_TERMINAL: Final[frozenset[ManagedState]] = frozenset({ManagedState.REMOVED})


def is_allowed(from_state: ManagedState, to_state: ManagedState) -> bool:
    """Return True iff ``from_state → to_state`` is an allowed transition.

    Self-transitions (``X → X``) are allowed (idempotent observation;
    callers usually skip them before invoking).
    """
    if from_state == to_state:
        return True
    return (from_state, to_state) in _ALLOWED


def is_terminal(state: ManagedState) -> bool:
    """Return True iff ``state`` is terminal (no outgoing transitions)."""
    return state in _TERMINAL


def assert_allowed(from_state: ManagedState, to_state: ManagedState) -> None:
    """Raise ``ValueError`` if the transition is not allowed.

    Service entry points should translate this into a closed-set
    ``managed_pane_illegal_transition`` error via the handler layer.
    """
    if not is_allowed(from_state, to_state):
        raise ValueError(
            f"illegal managed_pane transition: {from_state.value} → {to_state.value}"
        )


def aggregate_layout_state(pane_states: list[ManagedState]) -> ManagedState:
    """Derive layout-level state from the per-pane state distribution (FR-026).

    Aggregation rules per data-model.md §ManagedLayout lifecycle:

    * Any pane ``creating`` → layout ``creating``
    * Else any pane ``failed`` → layout ``failed`` (FR-026: worst child wins)
    * Else any pane ``degraded`` → layout ``degraded``
    * Else all panes ``ready`` → layout ``ready``
    * Else all panes ``removed`` → layout ``removed``

    Empty input raises ``ValueError`` — a layout with zero panes is
    structurally invalid (template-defined pane count is always ≥1).
    """
    if not pane_states:
        raise ValueError("aggregate_layout_state requires at least one pane state")
    state_set = set(pane_states)
    if ManagedState.CREATING in state_set:
        return ManagedState.CREATING
    if ManagedState.FAILED in state_set:
        return ManagedState.FAILED
    if ManagedState.DEGRADED in state_set:
        return ManagedState.DEGRADED
    if state_set == {ManagedState.REMOVED}:
        return ManagedState.REMOVED
    # All remaining panes are READY (possibly mixed with REMOVED — the
    # layout is ``ready`` once every non-removed pane is ready).
    return ManagedState.READY
