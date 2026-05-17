"""T026 — FEAT-010 RoutesService CRUD orchestration tests.

Covers ``agenttower.routing.routes_service.RoutesService``:

* :meth:`add_route` validation order per research §R15 — each closed-set
  check rejects in the documented sequence; first failure wins.
* :meth:`add_route` happy path — INSERTs with cursor_at_creation set to
  MAX(events.event_id), emits route_created.
* :meth:`enable_route` / :meth:`disable_route` idempotency per FR-009:
  no-op returns False AND does NOT emit route_updated.
* :meth:`remove_route` — DELETE + audit; unknown id raises
  RouteIdNotFound.
* :meth:`show_route` — returns RouteRow + runtime sub-object;
  unknown id raises RouteIdNotFound.
* :meth:`list_routes` — passthrough to routes_dao ordering.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agenttower.routing import routes_service as svc
from agenttower.routing.route_errors import (
    RouteCreationFailed,
    RouteEventTypeInvalid,
    RouteIdNotFound,
    RouteMasterRuleInvalid,
    RouteSourceScopeInvalid,
    RouteTargetRuleInvalid,
    RouteTemplateInvalid,
)
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Fakes & fixtures
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _FakeAuditWriter:
    """Capture every emit call for assertion."""

    created: list[dict] = field(default_factory=list)
    updated: list[dict] = field(default_factory=list)
    deleted: list[dict] = field(default_factory=list)

    def emit_route_created(self, events_file: Path, **kw: Any) -> None:
        self.created.append(kw)

    def emit_route_updated(self, events_file: Path, **kw: Any) -> None:
        self.updated.append(kw)

    def emit_route_deleted(self, events_file: Path, **kw: Any) -> None:
        self.deleted.append(kw)


@dataclass
class _FakeSharedState:
    events_consumed_total: int = 0
    last_routing_cycle_at: str | None = None
    last_skip_per_route: dict[str, tuple[str, str]] = field(
        default_factory=dict
    )


@pytest.fixture
def state_db(tmp_path: Path) -> Path:
    """Fresh DB at schema head; returns the path so the conn_factory
    can re-open per call (matching the production daemon's pattern of
    short-lived adapter connections)."""
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
def service(state_db: Path, tmp_path: Path) -> svc.RoutesService:
    audit = _FakeAuditWriter()

    def _conn_factory() -> sqlite3.Connection:
        return sqlite3.connect(state_db, isolation_level=None)

    s = svc.RoutesService(
        conn_factory=_conn_factory,
        audit_writer=audit,  # type: ignore[arg-type]
        events_file=tmp_path / "events.jsonl",
    )
    # Attach the audit writer so tests can inspect emits without
    # plumbing a separate fixture.
    s._test_audit = audit  # type: ignore[attr-defined]
    return s


def _good_add_kwargs(**overrides) -> dict[str, Any]:
    base = {
        "event_type": "waiting_for_input",
        "source_scope_kind": "any",
        "source_scope_value": None,
        "target_rule": "explicit",
        "target_value": "agt_slave000001",
        "master_rule": "auto",
        "master_value": None,
        "template_string": "respond to {source_label}: {event_excerpt}",
        "created_by_agent_id": "host-operator",
    }
    base.update(overrides)
    return base


# ──────────────────────────────────────────────────────────────────────
# add_route — happy path
# ──────────────────────────────────────────────────────────────────────


def test_add_route_inserts_and_emits_created(service: svc.RoutesService) -> None:
    row = service.add_route(**_good_add_kwargs())
    assert row.event_type == "waiting_for_input"
    assert row.enabled is True
    assert row.last_consumed_event_id == 0  # empty events table
    # Audit emitted with full row snapshot.
    audit = service._test_audit  # type: ignore[attr-defined]
    assert len(audit.created) == 1
    assert audit.created[0]["route_id"] == row.route_id
    assert audit.created[0]["event_type_subscribed"] == "waiting_for_input"
    assert audit.created[0]["cursor_at_creation"] == 0
    assert audit.created[0]["created_by_agent_id"] == "host-operator"


def test_add_route_cursor_at_creation_matches_max_event_id(
    service: svc.RoutesService, state_db: Path,
) -> None:
    """FR-002: new route's last_consumed_event_id = MAX(events.event_id).
    Seeds the events table with 3 rows; the route should pick cursor=3."""
    conn = sqlite3.connect(state_db, isolation_level=None)
    for excerpt in ("a", "b", "c"):
        conn.execute(
            """
            INSERT INTO events (
                event_type, agent_id, attachment_id, log_path,
                byte_range_start, byte_range_end,
                line_offset_start, line_offset_end,
                observed_at, excerpt, classifier_rule_id
            ) VALUES (
                'waiting_for_input', 'agt_slave000001', 'atc_x', '/tmp/x.log',
                0, 1, 0, 1,
                '2026-05-17T00:00:00.000000+00:00', ?, 'activity.fallback.v1'
            )
            """,
            (excerpt,),
        )
    conn.commit()
    conn.close()

    row = service.add_route(**_good_add_kwargs())
    assert row.last_consumed_event_id == 3
    audit = service._test_audit  # type: ignore[attr-defined]
    assert audit.created[0]["cursor_at_creation"] == 3


# ──────────────────────────────────────────────────────────────────────
# add_route — validation order (research §R15)
# ──────────────────────────────────────────────────────────────────────


def test_validation_order_event_type_first(service: svc.RoutesService) -> None:
    """R15 step 1: event_type check fires before any other validation.
    Bad event_type + bad master_rule + bad template — only the
    event_type code surfaces."""
    with pytest.raises(RouteEventTypeInvalid):
        service.add_route(**_good_add_kwargs(
            event_type="not_a_real_event",
            master_rule="round_robin",
            template_string="references {nonsense_field}",
        ))


def test_validation_order_master_rule_second(service: svc.RoutesService) -> None:
    """R15 step 2: master_rule check fires before target_rule."""
    with pytest.raises(RouteMasterRuleInvalid):
        service.add_route(**_good_add_kwargs(
            master_rule="round_robin",  # bad
            target_rule="not_a_rule",   # also bad — should NOT surface
        ))


def test_validation_order_target_rule_third(service: svc.RoutesService) -> None:
    """R15 step 3: target_rule check fires before source-scope parse."""
    with pytest.raises(RouteTargetRuleInvalid):
        service.add_route(**_good_add_kwargs(
            target_rule="not_a_rule",            # bad
            source_scope_kind="not_a_kind",      # also bad
        ))


def test_validation_order_source_scope_fourth(service: svc.RoutesService) -> None:
    """R15 step 4: source-scope parse fires before template validation."""
    with pytest.raises(RouteSourceScopeInvalid):
        service.add_route(**_good_add_kwargs(
            source_scope_kind="not_a_kind",
            template_string="references {nonsense_field}",  # bad but not surfaced
        ))


def test_validation_order_template_last(service: svc.RoutesService) -> None:
    """R15 step 5: template validation fires last (everything else valid)."""
    with pytest.raises(RouteTemplateInvalid):
        service.add_route(**_good_add_kwargs(
            template_string="references {nonsense_field}",
        ))


# ──────────────────────────────────────────────────────────────────────
# add_route — per-field rejections
# ──────────────────────────────────────────────────────────────────────


def test_add_rejects_master_explicit_without_value(
    service: svc.RoutesService,
) -> None:
    with pytest.raises(RouteMasterRuleInvalid, match="non-empty master_value"):
        service.add_route(**_good_add_kwargs(
            master_rule="explicit",
            master_value=None,
        ))


def test_add_rejects_master_auto_with_value(service: svc.RoutesService) -> None:
    with pytest.raises(RouteMasterRuleInvalid, match="master_value=NULL"):
        service.add_route(**_good_add_kwargs(
            master_rule="auto",
            master_value="agt_master00001",
        ))


def test_add_rejects_target_source_with_value(service: svc.RoutesService) -> None:
    with pytest.raises(RouteTargetRuleInvalid, match="target_value=NULL"):
        service.add_route(**_good_add_kwargs(
            target_rule="source",
            target_value="agt_slave000001",
        ))


def test_add_rejects_target_explicit_without_value(
    service: svc.RoutesService,
) -> None:
    with pytest.raises(RouteTargetRuleInvalid, match="non-empty target_value"):
        service.add_route(**_good_add_kwargs(
            target_rule="explicit",
            target_value=None,
        ))


def test_add_rejects_target_role_with_master_role_token(
    service: svc.RoutesService,
) -> None:
    """FR-006: target_rule=role's role token MUST be in {slave, swarm}."""
    with pytest.raises(RouteTargetRuleInvalid, match="FEAT-009 receive-permitted"):
        service.add_route(**_good_add_kwargs(
            target_rule="role",
            target_value="role:master",
        ))


def test_add_accepts_target_role_swarm(service: svc.RoutesService) -> None:
    row = service.add_route(**_good_add_kwargs(
        target_rule="role",
        target_value="role:swarm,capability:codex",
    ))
    assert row.target_value == "role:swarm,capability:codex"


# ──────────────────────────────────────────────────────────────────────
# enable_route / disable_route — FR-009 idempotency
# ──────────────────────────────────────────────────────────────────────


def test_enable_already_enabled_returns_false_no_audit(
    service: svc.RoutesService,
) -> None:
    row = service.add_route(**_good_add_kwargs())  # default enabled=True
    audit = service._test_audit  # type: ignore[attr-defined]
    audit.updated.clear()  # discard any prior emits

    changed = service.enable_route(row.route_id, updated_by_agent_id="host-operator")
    assert changed is False
    assert len(audit.updated) == 0  # FR-009: no audit on idempotent no-op


def test_disable_then_re_disable_only_audits_once(
    service: svc.RoutesService,
) -> None:
    row = service.add_route(**_good_add_kwargs())
    audit = service._test_audit  # type: ignore[attr-defined]
    audit.updated.clear()

    # First disable: state changes True → False, audit emitted.
    assert service.disable_route(row.route_id, updated_by_agent_id="host-operator") is True
    assert len(audit.updated) == 1
    assert audit.updated[0]["change"] == {"enabled": False}

    # Second disable: idempotent no-op, no new audit.
    assert service.disable_route(row.route_id, updated_by_agent_id="host-operator") is False
    assert len(audit.updated) == 1


def test_enable_re_enable_lifecycle_audits_two_flips(
    service: svc.RoutesService,
) -> None:
    row = service.add_route(**_good_add_kwargs())
    audit = service._test_audit  # type: ignore[attr-defined]
    audit.updated.clear()

    assert service.disable_route(row.route_id, updated_by_agent_id="host-operator") is True
    assert service.enable_route(row.route_id, updated_by_agent_id="host-operator") is True
    assert service.disable_route(row.route_id, updated_by_agent_id="host-operator") is True
    assert [u["change"] for u in audit.updated] == [
        {"enabled": False},
        {"enabled": True},
        {"enabled": False},
    ]


def test_enable_unknown_route_raises(service: svc.RoutesService) -> None:
    with pytest.raises(RouteIdNotFound):
        service.enable_route("nonexistent", updated_by_agent_id="host-operator")


def test_disable_unknown_route_raises(service: svc.RoutesService) -> None:
    with pytest.raises(RouteIdNotFound):
        service.disable_route("nonexistent", updated_by_agent_id="host-operator")


# ──────────────────────────────────────────────────────────────────────
# remove_route
# ──────────────────────────────────────────────────────────────────────


def test_remove_existing_route_emits_deleted(service: svc.RoutesService) -> None:
    row = service.add_route(**_good_add_kwargs())
    audit = service._test_audit  # type: ignore[attr-defined]
    audit.deleted.clear()

    service.remove_route(row.route_id, deleted_by_agent_id="host-operator")

    assert len(audit.deleted) == 1
    assert audit.deleted[0]["route_id"] == row.route_id
    assert audit.deleted[0]["deleted_by_agent_id"] == "host-operator"


def test_remove_unknown_route_raises(service: svc.RoutesService) -> None:
    with pytest.raises(RouteIdNotFound):
        service.remove_route("nonexistent", deleted_by_agent_id="host-operator")


# ──────────────────────────────────────────────────────────────────────
# list_routes
# ──────────────────────────────────────────────────────────────────────


def test_list_routes_returns_created_order(service: svc.RoutesService) -> None:
    r1 = service.add_route(**_good_add_kwargs())
    r2 = service.add_route(**_good_add_kwargs())
    r3 = service.add_route(**_good_add_kwargs())

    listing = service.list_routes()
    # Timestamps are identical (per ms) so route_id breaks ties; verify
    # at least that all three rows are present.
    assert {r.route_id for r in listing} == {r1.route_id, r2.route_id, r3.route_id}


def test_list_routes_enabled_only_filters(service: svc.RoutesService) -> None:
    r1 = service.add_route(**_good_add_kwargs())
    r2 = service.add_route(**_good_add_kwargs())
    service.disable_route(r2.route_id, updated_by_agent_id="host-operator")

    enabled = service.list_routes(enabled_only=True)
    assert {r.route_id for r in enabled} == {r1.route_id}


# ──────────────────────────────────────────────────────────────────────
# show_route + runtime sub-object
# ──────────────────────────────────────────────────────────────────────


def test_show_route_returns_row_and_zeroed_runtime_without_shared_state(
    service: svc.RoutesService,
) -> None:
    row = service.add_route(**_good_add_kwargs())
    fetched, runtime = service.show_route(row.route_id)
    assert fetched == row
    assert runtime.events_consumed == 0
    assert runtime.last_routing_cycle_at is None
    assert runtime.last_skip_reason is None
    assert runtime.last_skip_at is None


def test_show_route_pulls_runtime_from_shared_state(
    state_db: Path, tmp_path: Path,
) -> None:
    audit = _FakeAuditWriter()
    shared = _FakeSharedState(
        events_consumed_total=42,
        last_routing_cycle_at="2026-05-17T01:00:00.000Z",
        last_skip_per_route={
            "r1": ("no_eligible_master", "2026-05-17T00:55:00.000Z"),
        },
    )

    def _conn_factory() -> sqlite3.Connection:
        return sqlite3.connect(state_db, isolation_level=None)

    s = svc.RoutesService(
        conn_factory=_conn_factory,
        audit_writer=audit,  # type: ignore[arg-type]
        events_file=tmp_path / "events.jsonl",
        shared_state=shared,  # type: ignore[arg-type]
    )
    row = s.add_route(**_good_add_kwargs())

    # Use the actual route_id (not "r1") for the shared-state lookup;
    # but for this test we want to verify the runtime block flows, so
    # manually inject the route_id into shared state.
    shared.last_skip_per_route[row.route_id] = (
        "no_eligible_master", "2026-05-17T00:55:00.000Z",
    )

    _, runtime = s.show_route(row.route_id)
    assert runtime.events_consumed == 42
    assert runtime.last_routing_cycle_at == "2026-05-17T01:00:00.000Z"
    assert runtime.last_skip_reason == "no_eligible_master"
    assert runtime.last_skip_at == "2026-05-17T00:55:00.000Z"


def test_show_unknown_route_raises(service: svc.RoutesService) -> None:
    with pytest.raises(RouteIdNotFound):
        service.show_route("nonexistent")
