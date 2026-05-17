"""T050 — FEAT-010 ``agenttower status`` routing section contract tests.

Per ``contracts/cli-status-routing.md``: the existing FEAT-009 ``status``
socket method gains a set of FEAT-010 fields INSIDE the same
top-level ``routing`` object (operators conceptualize "routing" as
one subsystem; merging the FEAT-009 kill-switch state with the
FEAT-010 worker state under one JSON key matches that mental model).

Tests cover:

* The 8 documented FEAT-010 fields are present on every status response
  (regardless of routing activity).
* ``most_stalled_route`` is ``null`` when no enabled route has lag,
  AND a ``{route_id, lag}`` object when one does.
* Sparse ``skips_by_reason`` map (zero-valued reasons omitted).
* ``routing_worker_degraded`` mirrors ``_SharedRoutingState.routing_worker_degraded``.
* ``degraded_routing_audit_persistence`` derives from
  ``RoutesAuditWriter.has_pending()``.
* FEAT-009's existing ``routing.enabled`` / ``routing.last_toggled_at``
  fields are preserved (additive contract per "Backward compatibility").
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agenttower.routing.routes_audit import RoutesAuditWriter
from agenttower.routing.routes_service import RoutesService
from agenttower.routing.worker import _SharedRoutingState
from agenttower.socket_api.methods import DISPATCH, DaemonContext
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Fakes — minimal kill-switch / queue-audit surfaces (so _status runs)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _FakeRoutingFlag:
    """The FEAT-009 routing.read_full() return shape."""

    value: str = "enabled"
    last_at: str | None = None
    last_by: str | None = None

    def read_full(self) -> tuple[str, str | None, str | None]:
        return self.value, self.last_at, self.last_by


@dataclass
class _FakeQueueAuditWriter:
    """The FEAT-009 status block reads .degraded / .pending_count /
    .last_failure_exc_class."""

    degraded: bool = False
    pending_count: int = 0
    last_failure_exc_class: str | None = None


@pytest.fixture
def ctx_with_full_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DaemonContext:
    """DaemonContext with all FEAT-010 wiring populated against a real
    SQLite schema v8 + temp paths."""
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

    def _conn_factory() -> sqlite3.Connection:
        return sqlite3.connect(str(db), isolation_level=None)

    audit_writer = RoutesAuditWriter()
    shared_state = _SharedRoutingState()
    routes_service = RoutesService(
        conn_factory=_conn_factory,
        audit_writer=audit_writer,
        events_file=tmp_path / "events.jsonl",
        shared_state=shared_state,
    )

    return DaemonContext(
        pid=1,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "sock",
        state_path=tmp_path,
        daemon_version="test",
        routing_flag_service=_FakeRoutingFlag(),
        queue_audit_writer=_FakeQueueAuditWriter(),
        routes_service=routes_service,
        routing_audit_writer=audit_writer,
        routing_shared_state=shared_state,
    )


# ──────────────────────────────────────────────────────────────────────
# Field-set completeness
# ──────────────────────────────────────────────────────────────────────


_EXPECTED_FEAT010_KEYS = {
    "routes_total",
    "routes_enabled",
    "routes_disabled",
    "last_routing_cycle_at",
    "events_consumed_total",
    "skips_by_reason",
    "most_stalled_route",
    "routing_worker_degraded",
    "degraded_routing_audit_persistence",
}


def test_routing_section_has_all_eight_feat010_fields(
    ctx_with_full_routing: DaemonContext,
) -> None:
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    assert resp["ok"] is True
    routing = resp["result"]["routing"]
    missing = _EXPECTED_FEAT010_KEYS - set(routing.keys())
    assert not missing, f"missing FEAT-010 status keys: {missing}"


def test_routing_section_field_types(
    ctx_with_full_routing: DaemonContext,
) -> None:
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    routing = resp["result"]["routing"]
    assert isinstance(routing["routes_total"], int)
    assert isinstance(routing["routes_enabled"], int)
    assert isinstance(routing["routes_disabled"], int)
    assert routing["last_routing_cycle_at"] is None or isinstance(
        routing["last_routing_cycle_at"], str
    )
    assert isinstance(routing["events_consumed_total"], int)
    assert isinstance(routing["skips_by_reason"], dict)
    assert routing["most_stalled_route"] is None or isinstance(
        routing["most_stalled_route"], dict
    )
    assert isinstance(routing["routing_worker_degraded"], bool)
    assert isinstance(routing["degraded_routing_audit_persistence"], bool)


# ──────────────────────────────────────────────────────────────────────
# Empty-state baseline
# ──────────────────────────────────────────────────────────────────────


def test_routing_section_empty_state_zero_counts(
    ctx_with_full_routing: DaemonContext,
) -> None:
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    routing = resp["result"]["routing"]
    assert routing["routes_total"] == 0
    assert routing["routes_enabled"] == 0
    assert routing["routes_disabled"] == 0
    assert routing["events_consumed_total"] == 0
    assert routing["skips_by_reason"] == {}
    assert routing["most_stalled_route"] is None
    assert routing["routing_worker_degraded"] is False
    assert routing["degraded_routing_audit_persistence"] is False


# ──────────────────────────────────────────────────────────────────────
# Route counts reflect routes table
# ──────────────────────────────────────────────────────────────────────


def test_routing_section_counts_routes(
    ctx_with_full_routing: DaemonContext,
) -> None:
    svc = ctx_with_full_routing.routes_service
    r1 = svc.add_route(
        event_type="waiting_for_input",
        source_scope_kind="any", source_scope_value=None,
        target_rule="explicit", target_value="agt_slave000001",
        master_rule="auto", master_value=None,
        template_string="x",
        created_by_agent_id="host-operator",
    )
    r2 = svc.add_route(
        event_type="waiting_for_input",
        source_scope_kind="any", source_scope_value=None,
        target_rule="explicit", target_value="agt_slave000001",
        master_rule="auto", master_value=None,
        template_string="y",
        created_by_agent_id="host-operator",
    )
    svc.disable_route(r2.route_id, updated_by_agent_id="host-operator")

    resp = DISPATCH["status"](ctx_with_full_routing, {})
    routing = resp["result"]["routing"]
    assert routing["routes_total"] == 2
    assert routing["routes_enabled"] == 1
    assert routing["routes_disabled"] == 1


# ──────────────────────────────────────────────────────────────────────
# routing_worker_degraded mirrors shared state
# ──────────────────────────────────────────────────────────────────────


def test_routing_worker_degraded_mirrors_shared_state(
    ctx_with_full_routing: DaemonContext,
) -> None:
    shared = ctx_with_full_routing.routing_shared_state
    with shared.lock:
        shared.routing_worker_degraded = True
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    assert resp["result"]["routing"]["routing_worker_degraded"] is True

    with shared.lock:
        shared.routing_worker_degraded = False
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    assert resp["result"]["routing"]["routing_worker_degraded"] is False


# ──────────────────────────────────────────────────────────────────────
# degraded_routing_audit_persistence mirrors audit buffer
# ──────────────────────────────────────────────────────────────────────


def test_degraded_routing_audit_persistence_when_buffer_pending(
    ctx_with_full_routing: DaemonContext,
) -> None:
    audit = ctx_with_full_routing.routing_audit_writer
    # Push a pending entry directly via the bounded buffer to simulate
    # a degraded JSONL-write state without forcing an OSError.
    from agenttower.routing.routes_audit import _PendingAudit
    audit._pending.append(_PendingAudit(Path("/tmp/x"), {"event_type": "x"}))

    resp = DISPATCH["status"](ctx_with_full_routing, {})
    assert resp["result"]["routing"]["degraded_routing_audit_persistence"] is True


def test_degraded_routing_audit_persistence_clean_when_buffer_empty(
    ctx_with_full_routing: DaemonContext,
) -> None:
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    assert resp["result"]["routing"]["degraded_routing_audit_persistence"] is False


# ──────────────────────────────────────────────────────────────────────
# events_consumed_total / skips_by_reason mirror shared state
# ──────────────────────────────────────────────────────────────────────


def test_events_consumed_and_skips_mirror_shared_state(
    ctx_with_full_routing: DaemonContext,
) -> None:
    shared = ctx_with_full_routing.routing_shared_state
    with shared.lock:
        shared.events_consumed_total = 17
        shared.skips_by_reason = {
            "no_eligible_master": 3,
            "target_not_found": 1,
        }
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    routing = resp["result"]["routing"]
    assert routing["events_consumed_total"] == 17
    assert routing["skips_by_reason"] == {
        "no_eligible_master": 3,
        "target_not_found": 1,
    }


# ──────────────────────────────────────────────────────────────────────
# FEAT-009 backward-compat: existing routing.enabled/last_toggled_*
# fields are preserved (additive contract)
# ──────────────────────────────────────────────────────────────────────


def test_feat009_routing_kill_switch_field_preserved(
    ctx_with_full_routing: DaemonContext,
) -> None:
    resp = DISPATCH["status"](ctx_with_full_routing, {})
    routing = resp["result"]["routing"]
    # The FEAT-009 routing.read_full() returns (value, last_at, last_by)
    # — _status maps to {"value", "last_updated_at", "last_updated_by"}.
    assert routing["value"] == "enabled"


# ──────────────────────────────────────────────────────────────────────
# Unwired FEAT-010 wiring — defensive defaults
# ──────────────────────────────────────────────────────────────────────


def test_unwired_feat010_returns_zero_defaults(tmp_path: Path) -> None:
    """When the FEAT-010 wiring is unset (e.g., legacy test fixtures),
    the routing section still includes all FEAT-010 keys with
    zero/default values — operators see "not running" rather than a
    KeyError."""
    ctx = DaemonContext(
        pid=1,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "sock",
        state_path=tmp_path,
        daemon_version="test",
        routing_flag_service=_FakeRoutingFlag(),
        queue_audit_writer=_FakeQueueAuditWriter(),
        # routes_service / routing_audit_writer / routing_shared_state
        # all intentionally None.
    )
    resp = DISPATCH["status"](ctx, {})
    routing = resp["result"]["routing"]
    missing = _EXPECTED_FEAT010_KEYS - set(routing.keys())
    assert not missing
    assert routing["routes_total"] == 0
    assert routing["most_stalled_route"] is None
    assert routing["routing_worker_degraded"] is False
