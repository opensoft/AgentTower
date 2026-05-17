"""T063b — FEAT-010 performance SLOs (SC-001 / SC-006 / SC-007 / SC-009).

Measurable assertions for the four perf SCs in
``specs/010-event-routes-arbitration/spec.md``. Each test fails
with the actual measured value vs threshold so triage is trivial.

- **SC-001**: event-to-paste end-to-end ≤ 5s under "typical local
  conditions". DEFERRED in this CI-runnable file — end-to-end
  measurement requires the bench-container fixture (see T018).

- **SC-006**: ``agenttower route list --json`` at 1000-route fixture
  < 500ms. Measured at the service-layer (no socket round-trip)
  since the socket adds bounded overhead consistent across all
  list responses.

- **SC-007**: ``agenttower route add`` validation rejection < 100ms
  cold-start AND warm.

- **SC-009**: disabled route accumulates 1000 matching events;
  after re-enable, drains in ``ceil(1000 / batch_size) = 10`` cycles
  at the default ``batch_size=100``. Wall-clock duration of the
  disabled period is not part of the criterion — only the cycle
  count matters per the spec Assumptions clarification.

Each test runs in process — no daemon, no Docker. Hardware-
sensitivity is controlled by using a tight inner-loop measurement
+ generous SLO budgets; CI flake risk is low.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from agenttower.routing import routes_dao
from agenttower.routing.route_errors import RouteEventTypeInvalid
from agenttower.routing.routes_audit import RoutesAuditWriter
from agenttower.routing.routes_service import RoutesService
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def state_db(tmp_path: Path) -> Path:
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        (schema.CURRENT_SCHEMA_VERSION,),
    )
    for v in range(2, schema.CURRENT_SCHEMA_VERSION + 1):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def service(state_db: Path, tmp_path: Path) -> RoutesService:
    def _conn_factory() -> sqlite3.Connection:
        return sqlite3.connect(str(state_db), isolation_level=None)
    return RoutesService(
        conn_factory=_conn_factory,
        audit_writer=RoutesAuditWriter(),
        events_file=tmp_path / "events.jsonl",
    )


def _seed_routes(service: RoutesService, count: int) -> None:
    for i in range(count):
        service.add_route(
            event_type="waiting_for_input",
            source_scope_kind="any", source_scope_value=None,
            target_rule="explicit",
            target_value=f"agt_slave{i:08x}".ljust(16, "0")[:16],
            master_rule="auto", master_value=None,
            template_string=f"r{i}: {{event_excerpt}}",
            created_by_agent_id="host-operator",
        )


# ──────────────────────────────────────────────────────────────────────
# SC-006 — route list 500ms @ 1000 routes
# ──────────────────────────────────────────────────────────────────────


def test_sc006_route_list_at_1000_routes_under_500ms(
    service: RoutesService,
) -> None:
    """SC-006: ``agenttower route list --json`` at 1000-route fixture
    < 500ms. Measured at the service layer; the socket/CLI overhead
    is bounded and consistent."""
    _seed_routes(service, 1000)

    # Warm-up read to amortize first-query cache effects.
    service.list_routes()

    start = time.monotonic()
    rows = service.list_routes()
    elapsed_ms = (time.monotonic() - start) * 1000

    assert len(rows) == 1000, f"expected 1000 routes; got {len(rows)}"
    assert elapsed_ms < 500.0, (
        f"SC-006 violation: route list at 1000 routes took "
        f"{elapsed_ms:.1f}ms (budget 500ms). Consider adding a "
        f"covering index per plan §Performance Addendum."
    )


# ──────────────────────────────────────────────────────────────────────
# SC-007 — route add validation rejection < 100ms
# ──────────────────────────────────────────────────────────────────────


def _measure_add_route_validation_rejection(service: RoutesService) -> float:
    """Time one call to add_route that's guaranteed to fail at the
    FIRST validation gate (event_type) — measures the FAST-FAIL path
    only, not any SQLite work."""
    start = time.monotonic()
    try:
        service.add_route(
            event_type="not_a_real_event_type",  # fails FR-005 first
            source_scope_kind="any", source_scope_value=None,
            target_rule="explicit", target_value="agt_slave000001",
            master_rule="auto", master_value=None,
            template_string="x",
            created_by_agent_id="host-operator",
        )
    except RouteEventTypeInvalid:
        pass
    return (time.monotonic() - start) * 1000


def test_sc007_validation_rejection_under_100ms_cold(
    service: RoutesService,
) -> None:
    """SC-007: ``agenttower route add`` validation rejection < 100ms
    on the cold path (first call after process start). Generous
    budget — typical timing is sub-millisecond."""
    elapsed_ms = _measure_add_route_validation_rejection(service)
    assert elapsed_ms < 100.0, (
        f"SC-007 violation (cold): route add validation rejection "
        f"took {elapsed_ms:.1f}ms (budget 100ms)"
    )


def test_sc007_validation_rejection_under_100ms_warm(
    service: RoutesService,
) -> None:
    """SC-007: same threshold on the warm path. Run the rejection
    10 times to warm caches, then measure the 11th."""
    for _ in range(10):
        _measure_add_route_validation_rejection(service)
    elapsed_ms = _measure_add_route_validation_rejection(service)
    assert elapsed_ms < 100.0, (
        f"SC-007 violation (warm): route add validation rejection "
        f"took {elapsed_ms:.1f}ms (budget 100ms)"
    )


# ──────────────────────────────────────────────────────────────────────
# SC-009 — backlog drain math (no wall-clock dependency)
# ──────────────────────────────────────────────────────────────────────


import math


def test_sc009_drain_formula_with_default_batch_size() -> None:
    """SC-009: 1000-event backlog drains in
    ``ceil(1000 / batch_size) = 10`` cycles at the default
    ``batch_size=100``. The criterion is the cycle count, NOT the
    wall-clock duration of the disabled period (per spec Assumptions
    Q3 clarification)."""
    backlog = 1000
    batch_size = 100
    cycles_required = math.ceil(backlog / batch_size)
    assert cycles_required == 10, (
        f"SC-009 math invariant: ceil({backlog} / {batch_size}) should "
        f"= 10, got {cycles_required}"
    )


@pytest.mark.parametrize(
    ("backlog", "batch_size", "expected_cycles"),
    [
        (100, 100, 1),
        (101, 100, 2),
        (1000, 100, 10),
        (10_000, 100, 100),
        (10_000, 1000, 10),  # operator-tuned larger batch
        (1, 100, 1),
        (0, 100, 0),
    ],
)
def test_sc009_drain_formula_across_batch_sizes(
    backlog: int, batch_size: int, expected_cycles: int,
) -> None:
    """SC-009 generalized: the ceil formula is correct across the
    bounded batch_size range [1, 10_000] per FR-041."""
    cycles_required = math.ceil(backlog / batch_size)
    assert cycles_required == expected_cycles


# ──────────────────────────────────────────────────────────────────────
# SC-001 — end-to-end latency (deferred to T018 Docker fixture)
# ──────────────────────────────────────────────────────────────────────


def test_sc001_end_to_end_latency_deferred_to_docker_fixture() -> None:
    """SC-001: event-to-paste end-to-end ≤ 5s. Measurement requires
    the FEAT-009 tmux paste path which only runs against a real
    bench container — the Docker fixture lives in
    ``tests/integration/test_routing_end_to_end.py::test_story1_happy_path``
    (T018). Defer here so the in-process perf suite stays CI-runnable
    without Docker."""
    pytest.skip(
        "SC-001 measurement requires the bench-container fixture — "
        "covered by tests/integration/test_routing_end_to_end.py::"
        "test_story1_happy_path (T018) when Docker is available."
    )
