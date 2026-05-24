"""FEAT-014 T003 — Unit tests for the PaneState bucket aggregator.

Exercises ``agenttower.app_contract.dashboard._compute_pane_state_buckets``.

Maps to:

* FR-001 / FR-002 — every v1.1 PaneState key present.
* FR-003 — empty buckets emit integer ``0``, not omitted or ``null``.
* FR-019 — panes cross-check (sum == total) + Research §PR carve-out
  (partially_configured agents still register their pane).
* FR-025 — aggregator-failure path returns all-zero, never raises.
* Research §PB — bucket priority (degraded > stale > registered > unmanaged).
* US1 acceptance scenario #1 — 1 registered + 2 unadopted → {dau:2, dar:1, ios:0, dd:0}.

Every assertion is ``@pytest.mark.v1_1`` per tasks.md §Notes 'v1.1 marker rule'.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dashboard import (
    PANE_STATE_KEYS,
    _compute_pane_state_buckets,
)
from agenttower.state.schema import open_registry

from ._v11_fixture_helpers import seed_agent, seed_container, seed_pane


@pytest.fixture
def db_ctx(tmp_path: Path) -> SimpleNamespace:
    """Minimal ctx-shaped object: only ``state_conn`` is read by the helper."""
    state_db = tmp_path / "registry.db"
    conn, _status = open_registry(state_db, namespace_root=tmp_path)
    return SimpleNamespace(state_conn=conn)


# ─── FR-002 / FR-003 — keys present, integer-typed ─────────────────────────


@pytest.mark.v1_1
def test_all_four_keys_present_when_empty(db_ctx: SimpleNamespace) -> None:
    """FR-002 / FR-003: every PaneState key present with integer ``0`` on empty DB."""
    result = _compute_pane_state_buckets(db_ctx)
    assert set(result.keys()) == set(PANE_STATE_KEYS)
    for key in PANE_STATE_KEYS:
        assert isinstance(result[key], int), f"{key} value is not int"
        assert result[key] == 0, f"{key} should be 0 on empty DB, got {result[key]}"


# ─── FR-025 — aggregator-failure fallback ─────────────────────────────────


@pytest.mark.v1_1
def test_fr025_fallback_no_state_conn() -> None:
    """FR-025: ctx without ``state_conn`` → all-zero, no exception."""
    result = _compute_pane_state_buckets(SimpleNamespace())
    assert result == {k: 0 for k in PANE_STATE_KEYS}


@pytest.mark.v1_1
def test_fr025_fallback_accessor_raises() -> None:
    """FR-025: if the SQLite accessor raises (e.g., missing tables), return all-zero."""

    class BrokenConn:
        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("simulated FEAT-003 service-layer outage")

    result = _compute_pane_state_buckets(SimpleNamespace(state_conn=BrokenConn()))
    assert result == {k: 0 for k in PANE_STATE_KEYS}


# ─── US1 acceptance scenario #1 ────────────────────────────────────────────


@pytest.mark.v1_1
def test_us1_acceptance_one_registered_two_unadopted(db_ctx: SimpleNamespace) -> None:
    """US1 acceptance #1: 1 registered + 2 unadopted panes on an active container
    → ``{dau: 2, dar: 1, ios: 0, dd: 0}``."""
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=2)
    seed_agent(db_ctx.state_conn, agent_id="a1", container_id="c1", pane_index=0)

    result = _compute_pane_state_buckets(db_ctx)
    assert result == {
        "discovered-and-unmanaged": 2,
        "discovered-and-registered": 1,
        "inactive-or-stale": 0,
        "discovery-degraded": 0,
    }


# ─── FR-019 — panes cross-check (sum == total) ─────────────────────────────


@pytest.mark.v1_1
def test_fr019_cross_check_sum_equals_total_panes(db_ctx: SimpleNamespace) -> None:
    """FR-019: sum of all four buckets == total panes (no double-counting)."""
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    for i in range(5):
        seed_pane(db_ctx.state_conn, container_id="c1", pane_index=i)
    result = _compute_pane_state_buckets(db_ctx)
    assert sum(result.values()) == 5


# ─── Research §PB — bucket priority ────────────────────────────────────────


@pytest.mark.v1_1
def test_research_pb_priority_inactive_container_wins_over_unmanaged(
    db_ctx: SimpleNamespace,
) -> None:
    """Research §PB: a pane on an inactive container goes to ``inactive-or-stale``,
    NOT ``discovered-and-unmanaged`` (priority: stale > unmanaged)."""
    seed_container(db_ctx.state_conn, container_id="c-act", active=1)
    seed_container(db_ctx.state_conn, container_id="c-ina", active=0)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=0)
    seed_pane(db_ctx.state_conn, container_id="c-ina", pane_index=0)

    result = _compute_pane_state_buckets(db_ctx)
    assert result["inactive-or-stale"] == 1, "pane on inactive container should be in ios"
    assert result["discovered-and-unmanaged"] == 1, "pane on active container w/o agent → dau"
    assert result["discovered-and-registered"] == 0
    assert result["discovery-degraded"] == 0


# ─── Research §PR — partially_configured agent still registers pane ────────


@pytest.mark.v1_1
def test_research_pr_partially_configured_agent_still_registers_pane(
    db_ctx: SimpleNamespace,
) -> None:
    """Research §PR / FR-019 carve-out: an agent with role='unknown' (a
    ``partially_configured`` AgentState bucket per Clarifications Q2) still
    puts its pane in ``discovered-and-registered``. The pane bucket is
    determined by ``agents.active = 1``, NOT agent configuration completeness.
    """
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a1",
        container_id="c1",
        pane_index=0,
        # Partially-configured: role='unknown' triggers it per Clarifications Q2.
        role="unknown",
    )

    result = _compute_pane_state_buckets(db_ctx)
    assert result["discovered-and-registered"] == 1, (
        "partially_configured agent should still register its pane (FR-019 carve-out)"
    )
    assert result["discovered-and-unmanaged"] == 0
