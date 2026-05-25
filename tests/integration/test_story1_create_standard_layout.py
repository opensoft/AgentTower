"""FEAT-013 US1 integration test (T021).

End-to-end coverage of the three US1 acceptance scenarios:

1. Given the daemon is healthy and a bench container is running, when
   the operator creates a "1 master + 2 slaves" layout, AgentTower
   creates the required panes, launches the configured agent commands,
   registers the panes, and shows them in the agent surfaces.
2. Same as (1) but with the "2 masters + 2 slaves" layout — 4 panes
   created, all routable/monitorable through the existing control
   surfaces.
3. Given a template creation request is in progress, when one pane or
   command launch fails, AgentTower reports which part failed and
   leaves a recoverable lifecycle state instead of silently presenting
   a complete layout (FR-013 + FR-026).

These tests integrate the T022 service.create_layout entry point with
the FEAT-002 socket dispatcher and FEAT-011 app_contract dispatcher
(T023/T024 handlers + T025 registration). They use the same synthetic
NDJSON Unix-socket client pattern as FEAT-011's contract tests.

All test bodies are pending T022-T025 (Phase 3b).
"""

from __future__ import annotations

import pytest


# All US1 integration scenarios need the **background spawn pipeline**
# (FEAT-004 docker-exec + FEAT-006 register-self + FEAT-007 log attach).
# T022 (synchronous create_layout) landed in Phase 3b (commit `83285b8`);
# T023/T024/T025 (handlers + dispatcher registration) landed in Phase 3c
# (commit `1b85389`); the remaining gate is Phase 4 (T029/T030 spawn
# pipeline + T034 FEAT-004 scan update).
pytestmark = pytest.mark.skip(
    reason="US1 end-to-end needs T029/T030 spawn pipeline (Phase 4)"
)


# ─── AS-1: 1 master + 2 slaves ─────────────────────────────────────────


def test_us1_acceptance_1m_2s_healthy_path() -> None:
    """AS-1: daemon healthy, container running, template ``1m+2s``.

    Assertions (per quickstart §US1 step 2):
    * Response shape: ``{ok: true, result: {layout_id, state: 'creating',
      intended_pane_count: 3, panes: [3 entries]}}``.
    * After polling ``app.managed_layout_detail`` until ``state == 'ready'``:
      every pane has ``state: 'ready'``, ``agent_id`` set,
      ``log_attached: true``, ``origin: 'managed'``.
    * Tmux session ``session-quickstart`` exists in the bench container
      with 3 panes whose titles match the resolved labels (``m1``,
      ``s1``, ``s2``) — no ``@MANAGED:`` prefix remaining.
    """
    pytest.fail("US1 AS-1 integration test body pending Phase 3b")


# ─── AS-2: 2 masters + 2 slaves ────────────────────────────────────────


def test_us1_acceptance_2m_2s_healthy_path() -> None:
    """AS-2: same shape as AS-1 but 4 panes (2 master + 2 slave)."""
    pytest.fail("US1 AS-2 integration test body pending Phase 3b")


# ─── AS-3: partial failure leaves recoverable state ───────────────────


def test_us1_acceptance_partial_failure_leaves_recoverable_state() -> None:
    """AS-3: one pane's launch command exits within 1s → that pane
    transitions to ``degraded`` (``failed_stage = launch_command``);
    sibling panes complete normally; layout aggregates to ``degraded``;
    the FR-013 diagnostic surfaces the failed pane + failed stage.
    """
    pytest.fail("US1 AS-3 partial-failure integration test pending Phase 3b")


# ─── Cross-FEAT integration (FR-008) ──────────────────────────────────


def test_managed_panes_appear_in_app_agent_list() -> None:
    """After create_layout completes, each managed pane appears in
    ``app.agent.list`` with ``origin = 'managed'`` (FR-005 / FR-008
    parity with adopted agents)."""
    pytest.fail("Cross-FEAT app.agent.list parity test pending Phase 3b")
