"""T025 — FEAT-009 permissions matrix tests.

Covers the full FR-019 / FR-020 precedence (six steps, first-failing
wins) plus the FR-025 / R-006 three-step delivery-time re-check.

Each precedence step has its own happy-path + failure tests. A
precedence-order test exercises the case where multiple steps would
fail simultaneously and asserts only the earliest step's
``block_reason`` is returned.

The "send to self" Edge Case is covered indirectly: a master-to-master
attempt fails at step 4 (``target_role_not_permitted``) because master
is not in the permitted target role set.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agenttower.routing.permissions import (
    Decision,
    evaluate_enqueue_permissions,
    recheck_target_only,
)
from agenttower.state.agents import AgentRecord


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


def _make_agent(
    *,
    agent_id: str = "agt_aaaaaa111111",
    role: str = "master",
    label: str = "agent",
    active: bool = True,
    container_id: str = "c0123456789a",
    tmux_pane_id: str = "%0",
) -> AgentRecord:
    return AgentRecord(
        agent_id=agent_id,
        container_id=container_id,
        tmux_socket_path="/tmp/tmux-1000/default",
        tmux_session_name="agenttower",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id=tmux_pane_id,
        role=role,
        capability="plan",
        label=label,
        project_path="/workspace/proj",
        parent_agent_id=None,
        effective_permissions={},
        created_at="2026-05-12T00:00:00.000Z",
        last_registered_at="2026-05-12T00:00:00.000Z",
        last_seen_at="2026-05-12T00:00:00.000Z",
        active=active,
    )


_MASTER = _make_agent(agent_id="agt_aaaaaa111111", role="master", label="queen")
_SLAVE = _make_agent(agent_id="agt_bbbbbb222222", role="slave", label="worker-1")
_SWARM = _make_agent(agent_id="agt_cccccc333333", role="swarm", label="swarm-1")


# ──────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────


def test_evaluate_master_to_slave_all_checks_pass() -> None:
    d = evaluate_enqueue_permissions(
        _MASTER, _SLAVE,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d == Decision.allow()
    assert d.ok is True
    assert d.block_reason is None


def test_evaluate_master_to_swarm_all_checks_pass() -> None:
    """US1 #5: master → swarm is permitted with the same explicitness
    as master → slave."""
    d = evaluate_enqueue_permissions(
        _MASTER, _SWARM,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.ok is True


# ──────────────────────────────────────────────────────────────────────
# Step 1: routing flag
# ──────────────────────────────────────────────────────────────────────


def test_step_1_kill_switch_off_blocks_with_kill_switch_off() -> None:
    d = evaluate_enqueue_permissions(
        _MASTER, _SLAVE,
        routing_enabled=False,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.ok is False
    assert d.block_reason == "kill_switch_off"


# ──────────────────────────────────────────────────────────────────────
# Step 2: sender role + active
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_sender_role", ["slave", "swarm", "test-runner", "shell", "unknown"]
)
def test_step_2_non_master_sender_role_blocked(bad_sender_role: str) -> None:
    sender = replace(_MASTER, role=bad_sender_role)
    d = evaluate_enqueue_permissions(
        sender, _SLAVE,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "sender_role_not_permitted"


def test_step_2_inactive_master_sender_blocked_with_sender_role_not_permitted() -> None:
    """FR-023: an inactive sender is treated identically to an
    unprivileged sender — same ``block_reason``."""
    inactive_master = replace(_MASTER, active=False)
    d = evaluate_enqueue_permissions(
        inactive_master, _SLAVE,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "sender_role_not_permitted"


# ──────────────────────────────────────────────────────────────────────
# Step 3: target active
# ──────────────────────────────────────────────────────────────────────


def test_step_3_inactive_target_blocks_with_target_not_active() -> None:
    inactive_slave = replace(_SLAVE, active=False)
    d = evaluate_enqueue_permissions(
        _MASTER, inactive_slave,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_not_active"


# ──────────────────────────────────────────────────────────────────────
# Step 4: target role
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_target_role", ["master", "test-runner", "shell", "unknown"]
)
def test_step_4_non_slave_swarm_target_role_blocked(bad_target_role: str) -> None:
    target = replace(_SLAVE, role=bad_target_role)
    d = evaluate_enqueue_permissions(
        _MASTER, target,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_role_not_permitted"


def test_step_4_send_to_self_blocks_with_target_role_not_permitted() -> None:
    """Edge Case: a master targeting itself fails at step 4 because
    master is not in the permitted target role set."""
    self_target = _MASTER  # same record, role='master'
    d = evaluate_enqueue_permissions(
        _MASTER, self_target,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_role_not_permitted"


# ──────────────────────────────────────────────────────────────────────
# Step 5: container active
# ──────────────────────────────────────────────────────────────────────


def test_step_5_container_inactive_blocks_with_target_container_inactive() -> None:
    d = evaluate_enqueue_permissions(
        _MASTER, _SLAVE,
        routing_enabled=True,
        target_container_active=False,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_container_inactive"


# ──────────────────────────────────────────────────────────────────────
# Step 6: pane resolvable
# ──────────────────────────────────────────────────────────────────────


def test_step_6_pane_missing_blocks_with_target_pane_missing() -> None:
    d = evaluate_enqueue_permissions(
        _MASTER, _SLAVE,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=False,
    )
    assert d.block_reason == "target_pane_missing"


# ──────────────────────────────────────────────────────────────────────
# FR-020 precedence: first failing step wins
# ──────────────────────────────────────────────────────────────────────


def test_precedence_routing_wins_over_sender_role() -> None:
    """Routing disabled + non-master sender → routing wins (step 1
    fires before step 2)."""
    bad_sender = replace(_MASTER, role="unknown")
    d = evaluate_enqueue_permissions(
        bad_sender, _SLAVE,
        routing_enabled=False,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "kill_switch_off"


def test_precedence_sender_wins_over_target_inactive() -> None:
    """Non-master sender + inactive target → sender wins (step 2 before step 3)."""
    bad_sender = replace(_MASTER, role="slave")
    inactive_target = replace(_SLAVE, active=False)
    d = evaluate_enqueue_permissions(
        bad_sender, inactive_target,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "sender_role_not_permitted"


def test_precedence_target_inactive_wins_over_target_role() -> None:
    """Inactive target + wrong target role → target_not_active wins
    (step 3 before step 4). This is the Group-A walk H2 resolution:
    splitting the original FR-019 step 3 into two distinct ordered
    steps with deterministic precedence."""
    inactive_master_target = _make_agent(
        agent_id="agt_dddddd444444",
        role="master",  # wrong role for target
        label="rogue",
        active=False,  # AND inactive
    )
    d = evaluate_enqueue_permissions(
        _MASTER, inactive_master_target,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_not_active"


def test_precedence_target_role_wins_over_container() -> None:
    """Wrong target role + inactive container → target_role_not_permitted
    wins (step 4 before step 5)."""
    bad_target = replace(_SLAVE, role="master")
    d = evaluate_enqueue_permissions(
        _MASTER, bad_target,
        routing_enabled=True,
        target_container_active=False,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_role_not_permitted"


def test_precedence_container_wins_over_pane() -> None:
    """Inactive container + missing pane → container wins (step 5 before step 6)."""
    d = evaluate_enqueue_permissions(
        _MASTER, _SLAVE,
        routing_enabled=True,
        target_container_active=False,
        target_pane_resolvable=False,
    )
    assert d.block_reason == "target_container_inactive"


def test_precedence_all_six_failing_picks_routing() -> None:
    """All six conditions fail simultaneously → routing wins (step 1)."""
    bad_sender = replace(_MASTER, role="unknown", active=False)
    bad_target = replace(_SLAVE, role="master", active=False)
    d = evaluate_enqueue_permissions(
        bad_sender, bad_target,
        routing_enabled=False,
        target_container_active=False,
        target_pane_resolvable=False,
    )
    assert d.block_reason == "kill_switch_off"


# ──────────────────────────────────────────────────────────────────────
# FR-025 / R-006 delivery-time re-check
# ──────────────────────────────────────────────────────────────────────


def test_recheck_target_only_happy_path() -> None:
    d = recheck_target_only(
        _SLAVE,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.ok is True


def test_recheck_kill_switch_off() -> None:
    d = recheck_target_only(
        _SLAVE,
        routing_enabled=False,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "kill_switch_off"


def test_recheck_target_inactive() -> None:
    inactive = replace(_SLAVE, active=False)
    d = recheck_target_only(
        inactive,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_not_active"


def test_recheck_container_inactive() -> None:
    d = recheck_target_only(
        _SLAVE,
        routing_enabled=True,
        target_container_active=False,
        target_pane_resolvable=True,
    )
    assert d.block_reason == "target_container_inactive"


def test_recheck_pane_missing() -> None:
    d = recheck_target_only(
        _SLAVE,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=False,
    )
    assert d.block_reason == "target_pane_missing"


def test_recheck_does_not_check_sender_role_or_liveness() -> None:
    """FR-025 Assumption: authorization is locked at enqueue time. The
    re-check function doesn't take a sender, so role / active state of
    the original sender cannot affect the decision."""
    # By construction (function signature), recheck_target_only has
    # no `sender` parameter. This test pins the contract.
    import inspect
    sig = inspect.signature(recheck_target_only)
    assert "sender" not in sig.parameters
    # And: the four delivery-time conditions in order are routing,
    # target.active, container, pane.
    assert list(sig.parameters)[1:] == [
        "routing_enabled",
        "target_container_active",
        "target_pane_resolvable",
    ]


def test_recheck_does_not_check_target_role() -> None:
    """FR-025 / Edge Case: target role is re-checked according to the
    spec ('Target role demoted between enqueue and delivery' edge case).
    But the R-006 wording lists only target_active / container / pane —
    NOT target role. Test pins R-006: a target whose role flipped to
    'unknown' between enqueue and delivery is NOT re-blocked by the
    re-check (the spec leaves that as an Edge Case but the re-check
    function itself doesn't enforce it; the role re-check, if needed,
    happens elsewhere)."""
    role_flipped = replace(_SLAVE, role="unknown")
    d = recheck_target_only(
        role_flipped,
        routing_enabled=True,
        target_container_active=True,
        target_pane_resolvable=True,
    )
    # Per the strict R-006 contract, this passes.
    assert d.ok is True


def test_recheck_precedence_routing_wins() -> None:
    inactive = replace(_SLAVE, active=False)
    d = recheck_target_only(
        inactive,
        routing_enabled=False,
        target_container_active=False,
        target_pane_resolvable=False,
    )
    assert d.block_reason == "kill_switch_off"
