"""FEAT-014 T004 — Unit tests for the AgentState bucket aggregator.

Exercises ``agenttower.app_contract.dashboard._compute_agent_state_buckets``.

Maps to:

* FR-004 / FR-005 — every v1.1 AgentState key present.
* FR-003 — empty buckets emit integer ``0``, not omitted or ``null``.
* FR-006 — orthogonality: log-attached / log-detached independent of
  active / inactive / partially_configured.
* FR-020 — strict configuration partition:
  ``active + inactive + partially_configured == total agents``.
* Clarifications Q2 — ``partially_configured`` triggers on
  ``role='unknown'`` OR ``capability='unknown'`` OR ``label=''``.
* Clarifications Q5 — ``partially_configured`` mutually exclusive with
  ``active``/``inactive``.
* FR-025 — aggregator-failure fallback returns all-zero.

Every assertion is ``@pytest.mark.v1_1`` per tasks.md §Notes 'v1.1 marker rule'.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dashboard import (
    AGENT_STATE_KEYS,
    _compute_agent_state_buckets,
)
from agenttower.state.schema import open_registry

from ._v11_fixture_helpers import (
    seed_agent,
    seed_container,
    seed_log_attachment,
    seed_pane,
)


@pytest.fixture
def db_ctx(tmp_path: Path) -> SimpleNamespace:
    state_db = tmp_path / "registry.db"
    conn, _status = open_registry(state_db, namespace_root=tmp_path)
    return SimpleNamespace(state_conn=conn)


# ─── FR-005 / FR-003 — keys present, integer-typed ─────────────────────────


@pytest.mark.v1_1
def test_all_five_keys_present_when_empty(db_ctx: SimpleNamespace) -> None:
    result = _compute_agent_state_buckets(db_ctx)
    assert set(result.keys()) == set(AGENT_STATE_KEYS)
    for key in AGENT_STATE_KEYS:
        assert isinstance(result[key], int)
        assert result[key] == 0


# ─── FR-025 — aggregator-failure fallback ─────────────────────────────────


@pytest.mark.v1_1
def test_fr025_fallback_no_state_conn() -> None:
    result = _compute_agent_state_buckets(SimpleNamespace())
    assert result == {k: 0 for k in AGENT_STATE_KEYS}


@pytest.mark.v1_1
def test_fr025_fallback_accessor_raises() -> None:
    class BrokenConn:
        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("simulated service-layer outage")

    result = _compute_agent_state_buckets(SimpleNamespace(state_conn=BrokenConn()))
    assert result == {k: 0 for k in AGENT_STATE_KEYS}


# ─── FR-020 — strict configuration partition ───────────────────────────────


@pytest.mark.v1_1
def test_fr020_strict_configuration_partition(db_ctx: SimpleNamespace) -> None:
    """FR-020: active + inactive + partially_configured == total agents (strict)."""
    seed_container(db_ctx.state_conn, container_id="c-act", active=1)
    seed_container(db_ctx.state_conn, container_id="c-ina", active=0)
    # 2 active (fully configured, on active container)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=0)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=1)
    seed_agent(db_ctx.state_conn, agent_id="a-act-1", container_id="c-act", pane_index=0)
    seed_agent(db_ctx.state_conn, agent_id="a-act-2", container_id="c-act", pane_index=1)
    # 1 inactive (fully configured, on inactive container)
    seed_pane(db_ctx.state_conn, container_id="c-ina", pane_index=0)
    seed_agent(db_ctx.state_conn, agent_id="a-ina", container_id="c-ina", pane_index=0)
    # 2 partially_configured (role='unknown' on c-act; capability='unknown' on c-ina)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=2)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a-pc-1",
        container_id="c-act",
        pane_index=2,
        role="unknown",
    )
    seed_pane(db_ctx.state_conn, container_id="c-ina", pane_index=1)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a-pc-2",
        container_id="c-ina",
        pane_index=1,
        capability="unknown",
    )

    result = _compute_agent_state_buckets(db_ctx)
    assert result["active"] == 2
    assert result["inactive"] == 1
    assert result["partially_configured"] == 2
    # Strict partition sums to total agents (5)
    total = result["active"] + result["inactive"] + result["partially_configured"]
    assert total == 5, f"FR-020 partition violated: {result}"


# ─── Clarifications Q2 — partially_configured definition ───────────────────


@pytest.mark.v1_1
def test_clarifications_q2_partially_configured_definition(
    db_ctx: SimpleNamespace,
) -> None:
    """Clarifications Q2: ``partially_configured`` triggers when ANY of
    ``role``, ``capability``, ``label`` is missing/empty/``unknown``."""
    seed_container(db_ctx.state_conn, container_id="c1", active=1)

    # Each of these should trigger partially_configured.
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a-unknown-role",
        container_id="c1",
        pane_index=0,
        role="unknown",
    )

    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=1)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a-unknown-cap",
        container_id="c1",
        pane_index=1,
        capability="unknown",
    )

    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=2)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a-empty-label",
        container_id="c1",
        pane_index=2,
        label="",  # empty label (the only DB-allowed empty field of the three)
    )

    # Fully configured (none of the three trigger it).
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=3)
    seed_agent(db_ctx.state_conn, agent_id="a-ok", container_id="c1", pane_index=3)

    result = _compute_agent_state_buckets(db_ctx)
    assert result["partially_configured"] == 3, (
        "role='unknown', capability='unknown', and label='' should each trigger partially_configured"
    )
    assert result["active"] == 1
    assert result["inactive"] == 0


# ─── Clarifications Q5 — mutual exclusivity ────────────────────────────────


@pytest.mark.v1_1
def test_clarifications_q5_partial_config_mutually_exclusive_with_active(
    db_ctx: SimpleNamespace,
) -> None:
    """Clarifications Q5: a ``partially_configured`` agent is NOT counted in
    ``active`` or ``inactive`` — strict mutual exclusivity even on an active container."""
    seed_container(db_ctx.state_conn, container_id="c-act", active=1)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=0)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a-pc",
        container_id="c-act",
        pane_index=0,
        role="unknown",  # partially_configured trigger
    )

    result = _compute_agent_state_buckets(db_ctx)
    assert result["partially_configured"] == 1
    assert result["active"] == 0, (
        "partially_configured agents must not double-count into active (Clarifications Q5)"
    )
    assert result["inactive"] == 0


# ─── FR-006 — log-state partition orthogonality ────────────────────────────


@pytest.mark.v1_1
def test_fr006_log_state_orthogonal_to_config_partition(
    db_ctx: SimpleNamespace,
) -> None:
    """FR-006: ``log-attached`` + ``log-detached`` == total agents
    (independent of the configuration partition). Sum of all 5 keys MAY
    exceed total (documented overlap)."""
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=2)
    seed_agent(db_ctx.state_conn, agent_id="a1", container_id="c1", pane_index=0)
    seed_agent(db_ctx.state_conn, agent_id="a2", container_id="c1", pane_index=1)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a3",
        container_id="c1",
        pane_index=2,
        role="unknown",  # partially_configured, still gets log-state classification
    )
    # a1 has an active log attachment; a2 + a3 do not.
    seed_log_attachment(
        db_ctx.state_conn,
        attachment_id="la1",
        agent_id="a1",
        container_id="c1",
        pane_index=0,
        status="active",
    )

    result = _compute_agent_state_buckets(db_ctx)
    # Log partition is independent and complete: 1 attached + 2 detached = 3 total.
    assert result["log-attached"] == 1
    assert result["log-detached"] == 2
    assert result["log-attached"] + result["log-detached"] == 3
    # FR-006 documented overlap: sum of all 5 keys MAY exceed total (3).
    # Config partition: 2 active + 0 inactive + 1 pc = 3.
    # Log partition: 1 attached + 2 detached = 3.
    # Total = 6 > 3 agents.
    assert sum(result.values()) == 6
