"""FEAT-013 read-surface view models (T013).

Row shapes for ``managed.layout.list`` / ``managed.layout.detail`` and
``managed.pane.list`` / ``managed.pane.detail`` (contracts/managed-methods.md
§M2-M5). Surface ``origin = "managed"`` for FR-005 / FR-008 alignment
with adopted-agent view models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Optional

from .state_machine import FailedStage, ManagedState


# Constant used by the agent / route / queue / event view models that
# this feature shares with FEAT-006 / FEAT-008 / FEAT-009 / FEAT-010.
# When a row is sourced from FEAT-013 it carries this origin (FR-005).
ORIGIN_MANAGED: Final[str] = "managed"


@dataclass(frozen=True, slots=True)
class ManagedPaneView:
    """Row shape returned by ``managed.pane.list`` / ``managed.pane.detail``.

    Mirrors the ``managed_pane`` SQLite row plus the derived ``origin``
    field. Optional fields are ``None`` when the row is in a state that
    has not yet populated them (e.g., ``agent_id`` is ``None`` until
    FEAT-006 registration completes).
    """

    pane_id: str
    layout_id: str
    container_id: str
    role: str
    capability: str
    label: str
    state: ManagedState
    tmux_session_name: str
    tmux_pane_index: int
    chain_depth: int
    created_at: str
    updated_at: str
    agent_id: Optional[str] = None
    launch_command_ref: Optional[str] = None
    pending_marker_token: Optional[str] = None
    failed_stage: Optional[FailedStage] = None
    predecessor_id: Optional[str] = None
    log_attached: bool = False
    origin: str = ORIGIN_MANAGED


@dataclass(frozen=True, slots=True)
class ManagedLayoutView:
    """Row shape returned by ``managed.layout.list`` / ``managed.layout.detail``.

    Mirrors the ``managed_layout`` SQLite row. ``panes`` is populated by
    detail responses (M3); list responses (M2) omit it and instead surface
    a count summary derived by the handler.
    """

    layout_id: str
    container_id: str
    template_name: str
    intended_pane_count: int
    state: ManagedState
    created_at: str
    updated_at: str
    failed_stage: Optional[FailedStage] = None
    idempotency_key: Optional[str] = None
    panes: list[ManagedPaneView] = field(default_factory=list)
    origin: str = ORIGIN_MANAGED

    @property
    def ready_pane_count(self) -> int:
        """Number of panes in ``ready`` state (M2 list-row summary)."""
        return sum(1 for p in self.panes if p.state == ManagedState.READY)
