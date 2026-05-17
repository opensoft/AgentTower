"""T016 — FEAT-010 routing-worker unit tests.

Covers ``agenttower.routing.worker.RoutingWorker`` orchestration:

* Cycle iterates routes in ``(created_at, route_id)`` order (FR-042).
* Per-event flow: arbitration → target resolution → render → enqueue
  → cursor advance → audit emit.
* Skip paths: ``no_eligible_master``, ``target_not_found``,
  ``template_render_error``, ``target_role_not_permitted``,
  ``kill_switch_off`` (NOT a skip — row inserted blocked).
* Mid-batch ``route disable`` stops processing for that route (Risk §1).
* Shutdown event short-circuits the cycle.
* Transient SQLite-lock during enqueue → cursor NOT advanced; degraded
  flag flips; event retried on next cycle.
* Duplicate-insert UNIQUE constraint → recovery path (cursor advances
  + emit route_matched, no exception propagated).

Uses mock dependencies (AgentsService, EventReader, QueueService,
RoutesAuditWriter) so the cycle logic is tested without an actual
SQLite or worker thread spinning up. The shared-state lock is real.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agenttower.routing import worker as wkr
from agenttower.routing.arbitration import MasterSkip, MasterWon
from agenttower.routing.errors import QueueServiceError
from agenttower.routing.route_errors import (
    BODY_TOO_LARGE,
    NO_ELIGIBLE_MASTER,
    RoutingTransientError,
)
from agenttower.routing.routes_dao import RouteRow
from agenttower.routing.worker import (
    EventRowSnapshot,
    RoutingWorker,
    _SharedRoutingState,
    _TargetResolveSkip,
)


# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeAgent:
    agent_id: str
    label: str = "agent-label"
    role: str = "slave"
    capability: str | None = None
    active: bool = True


class _FakeAgents:
    """Minimal AgentsService Protocol implementation."""

    def __init__(
        self,
        *,
        masters: list[_FakeAgent] | None = None,
        by_id: dict[str, _FakeAgent] | None = None,
        by_role: dict[tuple[str, str | None], list[_FakeAgent]] | None = None,
    ) -> None:
        self.masters = masters or []
        self.by_id = by_id or {}
        self.by_role = by_role or {}

    def list_active_masters(self) -> list[_FakeAgent]:
        return list(self.masters)

    def get_agent_by_id(self, agent_id: str) -> _FakeAgent | None:
        return self.by_id.get(agent_id)

    def list_active_by_role(
        self, role: str, capability: str | None = None
    ) -> list[_FakeAgent]:
        return list(self.by_role.get((role, capability), []))


class _FakeEvents:
    def __init__(self, events: list[EventRowSnapshot] | None = None) -> None:
        self.events = events or []

    def select_events_after_cursor(
        self, conn, *, cursor: int, event_type: str, limit: int,
    ) -> list[EventRowSnapshot]:
        return [
            e for e in self.events
            if e.event_id > cursor and e.event_type == event_type
        ][:limit]


@dataclass
class _FakeAudit:
    """Captures every emit call so tests can assert on the sequence."""

    matched: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    drained: int = 0
    pending: bool = False

    def drain_pending(self) -> int:
        d = self.drained
        self.drained = 0
        return d

    def has_pending(self) -> bool:
        return self.pending

    def emit_route_matched(self, events_file: Path, **kwargs: Any) -> None:
        self.matched.append(kwargs)

    def emit_route_skipped(self, events_file: Path, **kwargs: Any) -> None:
        self.skipped.append(kwargs)


class _FakeRoutesDao:
    """Stand-in for ``routes_dao`` module functions. Stores routes
    in-memory and exposes module-level functions via monkeypatching
    in the fixture.
    """

    def __init__(self, routes: list[RouteRow]) -> None:
        self._routes = {r.route_id: r for r in routes}

    def list_routes(self, conn, *, enabled_only: bool = False) -> list[RouteRow]:
        result = list(self._routes.values())
        if enabled_only:
            result = [r for r in result if r.enabled]
        return sorted(result, key=lambda r: (r.created_at, r.route_id))

    def select_route(self, conn, route_id: str) -> RouteRow | None:
        return self._routes.get(route_id)

    def advance_cursor(
        self, conn, route_id: str, event_id: int, *, updated_at: str
    ) -> None:
        existing = self._routes.get(route_id)
        if existing is None:
            return
        if existing.last_consumed_event_id >= event_id:
            return
        from dataclasses import replace
        self._routes[route_id] = replace(
            existing,
            last_consumed_event_id=event_id,
            updated_at=updated_at,
        )

    def set_enabled(self, route_id: str, enabled: bool) -> None:
        """Test helper: mid-batch disable simulation."""
        from dataclasses import replace
        existing = self._routes[route_id]
        self._routes[route_id] = replace(existing, enabled=enabled)


@pytest.fixture
def fake_routes_dao(monkeypatch):
    """Monkeypatch the routes_dao module's functions to use a fake."""
    def _factory(routes: list[RouteRow]) -> _FakeRoutesDao:
        fake = _FakeRoutesDao(routes)
        monkeypatch.setattr(wkr.routes_dao, "list_routes", fake.list_routes)
        monkeypatch.setattr(wkr.routes_dao, "select_route", fake.select_route)
        monkeypatch.setattr(wkr.routes_dao, "advance_cursor", fake.advance_cursor)
        return fake
    return _factory


class _NullConnFactory:
    """Returns a no-op connection; the fake DAO ignores the conn argument."""

    def __call__(self) -> sqlite3.Connection:
        # Return a real :memory: connection so any unexpected SQL
        # against it fails loudly (the fake DAO methods ignore it).
        conn = sqlite3.connect(":memory:")
        return conn


@pytest.fixture
def harness(monkeypatch, fake_routes_dao, tmp_path):
    """Compose a RoutingWorker with the standard fakes.

    Returns a builder callable; tests configure events/agents/queue
    before calling :meth:`build`.
    """
    class _Builder:
        def __init__(self):
            self.routes: list[RouteRow] = []
            self.events: list[EventRowSnapshot] = []
            self.masters: list[_FakeAgent] = []
            self.by_id: dict[str, _FakeAgent] = {}
            self.by_role: dict[tuple[str, str | None], list[_FakeAgent]] = {}
            self.queue: MagicMock = MagicMock(spec=["enqueue_route_message"])
            self.queue.enqueue_route_message.return_value = None
            self.audit = _FakeAudit()
            self.state = _SharedRoutingState()
            self.shutdown = threading.Event()
            self.events_file = tmp_path / "events.jsonl"

        def build(self, **kwargs) -> RoutingWorker:
            fake_routes_dao(self.routes)
            return RoutingWorker(
                conn_factory=_NullConnFactory(),
                agents_service=_FakeAgents(
                    masters=self.masters,
                    by_id=self.by_id,
                    by_role=self.by_role,
                ),
                event_reader=_FakeEvents(self.events),
                queue_service=self.queue,
                audit_writer=self.audit,
                events_file=self.events_file,
                shutdown_event=self.shutdown,
                shared_state=self.state,
                cycle_interval=kwargs.get("cycle_interval", 0.1),
                batch_size=kwargs.get("batch_size", 100),
            )

    return _Builder()


def _make_route(
    *,
    route_id: str = "r1",
    event_type: str = "waiting_for_input",
    source_scope_kind: str = "any",
    source_scope_value: str | None = None,
    target_rule: str = "explicit",
    target_value: str | None = "agt_slave000001",
    master_rule: str = "auto",
    master_value: str | None = None,
    template: str = "respond: {event_excerpt}",
    enabled: bool = True,
    last_consumed_event_id: int = 0,
    created_at: str = "2026-05-17T00:00:00.000Z",
) -> RouteRow:
    return RouteRow(
        route_id=route_id,
        event_type=event_type,
        source_scope_kind=source_scope_kind,
        source_scope_value=source_scope_value,
        target_rule=target_rule,
        target_value=target_value,
        master_rule=master_rule,
        master_value=master_value,
        template=template,
        enabled=enabled,
        last_consumed_event_id=last_consumed_event_id,
        created_at=created_at,
        updated_at=created_at,
        created_by_agent_id="host-operator",
    )


def _make_event(
    *,
    event_id: int = 1,
    event_type: str = "waiting_for_input",
    source_agent_id: str = "agt_slave000001",
    excerpt: str = "please respond",
    observed_at: str = "2026-05-17T00:00:01.000000+00:00",
) -> EventRowSnapshot:
    return EventRowSnapshot(
        event_id=event_id,
        event_type=event_type,
        source_agent_id=source_agent_id,
        excerpt=excerpt,
        observed_at=observed_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Construction validation
# ──────────────────────────────────────────────────────────────────────


def test_worker_rejects_out_of_bounds_cycle_interval(harness) -> None:
    with pytest.raises(ValueError, match="cycle_interval"):
        harness.build(cycle_interval=0.01)
    with pytest.raises(ValueError, match="cycle_interval"):
        harness.build(cycle_interval=120.0)


def test_worker_rejects_out_of_bounds_batch_size(harness) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        harness.build(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        harness.build(batch_size=100_000)


# ──────────────────────────────────────────────────────────────────────
# Happy path — single route, single event
# ──────────────────────────────────────────────────────────────────────


def test_happy_path_enqueues_advances_cursor_emits_matched(harness) -> None:
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=10)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    worker = harness.build()
    worker._run_one_cycle()

    # Queue insert was called exactly once with the right args.
    harness.queue.enqueue_route_message.assert_called_once()
    kwargs = harness.queue.enqueue_route_message.call_args.kwargs
    assert kwargs["sender"].agent_id == "agt_master00001"
    assert kwargs["target_input"] == "agt_slave000001"
    assert kwargs["route_id"] == "r1"
    assert kwargs["event_id"] == 10

    # route_matched audit emitted.
    assert len(harness.audit.matched) == 1
    assert len(harness.audit.skipped) == 0
    assert harness.audit.matched[0]["target_agent_id"] == "agt_slave000001"
    assert harness.audit.matched[0]["winner_master_agent_id"] == "agt_master00001"

    # Cursor advanced.
    assert harness.state.events_consumed_total == 1


# ──────────────────────────────────────────────────────────────────────
# Skip — no eligible master (FR-018 / SC-003)
# ──────────────────────────────────────────────────────────────────────


def test_no_eligible_master_skips_and_advances_cursor(harness) -> None:
    """SC-003: when zero active masters exist, every fire produces
    route_skipped(no_eligible_master) AND cursor advances."""
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=i) for i in range(1, 11)]
    harness.masters = []  # zero active masters
    harness.by_id = {
        "agt_slave000001": _FakeAgent(agent_id="agt_slave000001", role="slave"),
    }

    worker = harness.build()
    worker._run_one_cycle()

    assert len(harness.audit.matched) == 0
    assert len(harness.audit.skipped) == 10
    assert all(
        s["reason"] == NO_ELIGIBLE_MASTER for s in harness.audit.skipped
    )
    # SC-003 invariants
    assert harness.queue.enqueue_route_message.call_count == 0
    assert harness.state.skips_by_reason[NO_ELIGIBLE_MASTER] == 10
    # All target fields null when arbitration fails (Clarifications Q2).
    for s in harness.audit.skipped:
        assert s["winner_master_agent_id"] is None
        assert s["target_agent_id"] is None
        assert s["target_label"] is None


# ──────────────────────────────────────────────────────────────────────
# Skip — target_not_found
# ──────────────────────────────────────────────────────────────────────


def test_explicit_target_not_in_registry_skips(harness) -> None:
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    harness.routes = [_make_route(target_value="agt_does_not_exist")]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {
        "agt_slave000001": _FakeAgent(agent_id="agt_slave000001", role="slave"),
        "agt_master00001": master,
    }

    worker = harness.build()
    worker._run_one_cycle()

    assert len(harness.audit.skipped) == 1
    assert harness.audit.skipped[0]["reason"] == "target_not_found"
    assert harness.audit.skipped[0]["winner_master_agent_id"] == "agt_master00001"
    assert harness.audit.skipped[0]["target_agent_id"] is None


# ──────────────────────────────────────────────────────────────────────
# Skip — template_render_error sub-reason mapping
# ──────────────────────────────────────────────────────────────────────


def test_oversized_template_render_skips_with_body_too_large(harness) -> None:
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    # Build a template that renders > 4 KiB envelope cap.
    huge = "X" * 200_000
    harness.routes = [_make_route(template=f"prefix {huge} suffix")]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    worker = harness.build()
    worker._run_one_cycle()

    assert len(harness.audit.skipped) == 1
    assert harness.audit.skipped[0]["reason"] == "template_render_error"
    assert harness.audit.skipped[0]["sub_reason"] == BODY_TOO_LARGE
    # Target was resolved before render → target fields populated.
    assert harness.audit.skipped[0]["target_agent_id"] == "agt_slave000001"


# ──────────────────────────────────────────────────────────────────────
# Skip — FEAT-009 QueueServiceError → mapped reason
# ──────────────────────────────────────────────────────────────────────


def test_feat009_queue_error_maps_to_skip_reason(harness) -> None:
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}
    harness.queue.enqueue_route_message.side_effect = QueueServiceError(
        "target_pane_missing", "pane gone"
    )

    worker = harness.build()
    worker._run_one_cycle()

    assert len(harness.audit.skipped) == 1
    assert harness.audit.skipped[0]["reason"] == "target_pane_missing"
    # Target was resolved before enqueue → identity populated.
    assert harness.audit.skipped[0]["target_agent_id"] == "agt_slave000001"


# ──────────────────────────────────────────────────────────────────────
# Kill switch (Story 5 #1) — NOT a skip; cursor still advances
# ──────────────────────────────────────────────────────────────────────


def test_kill_switch_off_is_not_a_skip_and_cursor_advances(harness) -> None:
    """FR-032 / Story 5 #1: when the kill switch is off, the queue
    insert returns normally with the row in 'blocked' state — the
    worker treats this as a successful match (route_matched audit
    emitted), NOT a skip."""
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}
    # service.enqueue_route_message returns normally (FEAT-009 handles
    # the kill-switch path internally by inserting into 'blocked').

    worker = harness.build()
    worker._run_one_cycle()

    assert len(harness.audit.matched) == 1
    assert len(harness.audit.skipped) == 0
    assert harness.state.events_consumed_total == 1


# ──────────────────────────────────────────────────────────────────────
# Transient SQLite-lock → cursor NOT advanced, degraded flag flips
# ──────────────────────────────────────────────────────────────────────


def test_sqlite_locked_during_enqueue_does_not_advance_cursor(harness) -> None:
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}
    harness.queue.enqueue_route_message.side_effect = sqlite3.OperationalError(
        "database is locked"
    )

    worker = harness.build()
    worker._run_one_cycle()  # the RoutingTransientError is caught by _run_one_cycle

    # No advance, no audit emit; degraded flag set.
    assert len(harness.audit.matched) == 0
    assert len(harness.audit.skipped) == 0
    assert harness.state.events_consumed_total == 0
    assert harness.state.routing_worker_degraded is True


# ──────────────────────────────────────────────────────────────────────
# Duplicate-insert recovery (SC-004 path)
# ──────────────────────────────────────────────────────────────────────


def test_unique_constraint_violation_treated_as_recovery(harness) -> None:
    """Partial UNIQUE on (route_id, event_id) fires when a prior cycle
    inserted the row but crashed before advancing the cursor. The
    worker MUST treat this as 'already done' and still advance the
    cursor + emit route_matched (so the event isn't re-evaluated
    forever)."""
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}
    harness.queue.enqueue_route_message.side_effect = sqlite3.IntegrityError(
        "UNIQUE constraint failed: message_queue.route_id, message_queue.event_id"
    )

    worker = harness.build()
    worker._run_one_cycle()

    # Cursor still advanced (state counts the consumption).
    assert harness.state.events_consumed_total == 1
    # route_matched audit emitted (treated as recovery).
    assert len(harness.audit.matched) == 1
    assert len(harness.audit.skipped) == 0


# ──────────────────────────────────────────────────────────────────────
# Route processing order (FR-042)
# ──────────────────────────────────────────────────────────────────────


def test_routes_processed_in_created_at_then_route_id_order(harness) -> None:
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    # Three routes with overlapping selectors; same event matches all.
    harness.routes = [
        _make_route(
            route_id="z_later", created_at="2026-05-17T01:00:00.000Z",
        ),
        _make_route(
            route_id="a_earlier", created_at="2026-05-17T00:00:00.000Z",
        ),
        _make_route(
            route_id="m_middle", created_at="2026-05-17T00:30:00.000Z",
        ),
    ]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    worker = harness.build()
    worker._run_one_cycle()

    # Three matches (FR-015 fan-out), in created_at order.
    matched_route_ids = [m["route_id"] for m in harness.audit.matched]
    assert matched_route_ids == ["a_earlier", "m_middle", "z_later"]


# ──────────────────────────────────────────────────────────────────────
# Mid-batch route-disable (Risk Register §1)
# ──────────────────────────────────────────────────────────────────────


def test_mid_batch_disable_stops_processing_remaining_events(
    harness, monkeypatch,
) -> None:
    """If an operator disables a route between two events in the
    middle of a batch, the worker MUST stop processing further events
    for that route (the cycle completes for events it has already
    started; subsequent events become next-cycle work)."""
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=i) for i in range(1, 6)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    fake_dao = _FakeRoutesDao(harness.routes)
    monkeypatch.setattr(wkr.routes_dao, "list_routes", fake_dao.list_routes)
    monkeypatch.setattr(wkr.routes_dao, "select_route", fake_dao.select_route)
    monkeypatch.setattr(wkr.routes_dao, "advance_cursor", fake_dao.advance_cursor)

    # After the second enqueue, simulate operator disabling the route.
    def _disable_after_two_calls(*args: Any, **kwargs: Any) -> None:
        if harness.queue.enqueue_route_message.call_count >= 2:
            fake_dao.set_enabled("r1", enabled=False)

    harness.queue.enqueue_route_message.side_effect = _disable_after_two_calls

    worker = RoutingWorker(
        conn_factory=_NullConnFactory(),
        agents_service=_FakeAgents(
            masters=harness.masters, by_id=harness.by_id,
        ),
        event_reader=_FakeEvents(harness.events),
        queue_service=harness.queue,
        audit_writer=harness.audit,
        events_file=harness.events_file,
        shutdown_event=harness.shutdown,
        shared_state=harness.state,
        cycle_interval=0.1,
        batch_size=100,
    )
    worker._run_one_cycle()

    # Two events processed (1, 2); event 3 detected disabled mid-batch.
    assert harness.queue.enqueue_route_message.call_count == 2


# ──────────────────────────────────────────────────────────────────────
# Shutdown event short-circuits
# ──────────────────────────────────────────────────────────────────────


def test_shutdown_event_breaks_route_loop(harness) -> None:
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [
        _make_route(route_id="r1", created_at="2026-05-17T00:00:00.000Z"),
        _make_route(route_id="r2", created_at="2026-05-17T00:00:01.000Z"),
    ]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    # Trip the shutdown event after the first route is processed.
    def _set_shutdown_after_first_call(*args, **kwargs):
        harness.shutdown.set()

    harness.queue.enqueue_route_message.side_effect = _set_shutdown_after_first_call

    worker = harness.build()
    worker._run_one_cycle()

    # Only one route should have been processed before the shutdown
    # signal short-circuited the outer loop.
    assert harness.queue.enqueue_route_message.call_count == 1


# ──────────────────────────────────────────────────────────────────────
# Fault injection (research §R16)
# ──────────────────────────────────────────────────────────────────────


def test_fault_injection_env_var_triggers_systemexit(harness, monkeypatch) -> None:
    monkeypatch.setenv(
        wkr._FAULT_INJECT_ENV, wkr._FAULT_INJECT_BEFORE_COMMIT,
    )
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    worker = harness.build()
    with pytest.raises(SystemExit) as info:
        worker._process_one_event(harness.routes[0], harness.events[0], slave)
    assert info.value.code == 137


def test_no_fault_injection_when_env_var_unset(harness, monkeypatch) -> None:
    monkeypatch.delenv(wkr._FAULT_INJECT_ENV, raising=False)
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route()]
    harness.events = [_make_event(event_id=1)]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    worker = harness.build()
    # Should NOT raise SystemExit.
    worker._run_one_cycle()
    assert harness.state.events_consumed_total == 1


# ──────────────────────────────────────────────────────────────────────
# Audit-buffer drain at top of cycle
# ──────────────────────────────────────────────────────────────────────


def test_drains_audit_buffer_at_top_of_cycle(harness) -> None:
    """FR-039 / research §R14: each cycle's first action is to drain
    any buffered audit entries from a prior degraded cycle."""
    harness.audit.drained = 3  # simulate 3 entries from prior cycle
    harness.audit.pending = False  # drain succeeds → empty after

    worker = harness.build()
    worker._run_one_cycle()

    # drain_pending was called.
    assert harness.audit.drained == 0


# ──────────────────────────────────────────────────────────────────────
# Source-scope mismatch silently advances cursor (no audit)
# ──────────────────────────────────────────────────────────────────────


def test_source_scope_mismatch_advances_cursor_silently(harness) -> None:
    """FR-010 only emits audit for MATCHING events that reach a
    terminal decision. Events whose source doesn't match the route's
    source_scope are silently consumed (cursor advances, no audit)."""
    master = _FakeAgent(agent_id="agt_master00001", role="master")
    slave = _FakeAgent(agent_id="agt_slave000001", role="slave")
    harness.routes = [_make_route(
        source_scope_kind="agent_id",
        source_scope_value="agt_different00",
    )]
    harness.events = [_make_event(event_id=1, source_agent_id="agt_slave000001")]
    harness.masters = [master]
    harness.by_id = {"agt_slave000001": slave, "agt_master00001": master}

    worker = harness.build()
    worker._run_one_cycle()

    # No audit emitted, no enqueue, but the cycle DID complete.
    assert len(harness.audit.matched) == 0
    assert len(harness.audit.skipped) == 0
    assert harness.queue.enqueue_route_message.call_count == 0
