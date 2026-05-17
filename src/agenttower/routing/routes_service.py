"""FEAT-010 routes-catalog service (CRUD orchestration).

Sits between the socket dispatch layer and :mod:`routes_dao` /
:mod:`routes_audit`. Each public method does:

- input validation (FR-005..008 closed-set checks for
  :meth:`add_route`; FR-009 idempotency check for
  :meth:`enable_route` / :meth:`disable_route`)
- DAO call inside ``BEGIN IMMEDIATE``
- audit emit via :class:`RoutesAuditWriter` (only on actual state
  change per FR-009 — no-op invocations MUST NOT audit)

The service is the single integration point for the socket dispatch
layer; the routing worker imports :mod:`routes_dao` directly (not
this module) to avoid pulling in the audit-writer dependency on the
worker's hot path.

Validation order at :meth:`add_route` follows research §R15:

1. FR-005 — event_type in FEAT-008 closed vocabulary
2. FR-007 — master_rule in {auto, explicit}
3. FR-006 — target_rule in {explicit, source, role}
4. Clarifications Q1 — source-scope value parse
5. FR-008 — template field whitelist parse

First failure short-circuits; the CLI exit code reflects the first
failure category (single-error-per-call convention matching FEAT-009).
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from agenttower.routing import routes_dao, source_scope, template
from agenttower.routing.arbitration import MASTER_RULES
from agenttower.routing.dao import with_lock_retry
from agenttower.routing.route_errors import (
    RouteCreationFailed,
    RouteEventTypeInvalid,
    RouteIdNotFound,
    RouteMasterRuleInvalid,
    RouteSourceScopeInvalid,
    RouteTargetRuleInvalid,
    RouteTemplateInvalid,
)
from agenttower.routing.routes_audit import RoutesAuditWriter
from agenttower.routing.routes_dao import RouteRow
from agenttower.routing.timestamps import Clock, SystemClock, now_iso_ms_utc

_log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Closed-set vocabularies (mirror spec FRs)
# ──────────────────────────────────────────────────────────────────────


_ALLOWED_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "activity",
        "waiting_for_input",
        "completed",
        "error",
        "test_failed",
        "test_passed",
        "manual_review_needed",
        "long_running",
        "pane_exited",
        "swarm_member_reported",
    }
)
"""FR-005 closed set (matches FEAT-008 events.event_type CHECK)."""

_ALLOWED_TARGET_RULES: Final[frozenset[str]] = frozenset(
    {"explicit", "source", "role"}
)

# FR-006: target_rule=role's role token MUST be in {slave, swarm}
# (the FEAT-009 receive-permitted set). Source-scope role is
# unrestricted (a route may legitimately subscribe to master events).
_RECEIVE_PERMITTED_ROLES: Final[frozenset[str]] = frozenset({"slave", "swarm"})


# ──────────────────────────────────────────────────────────────────────
# Runtime sub-object (FR-047)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouteRuntime:
    """Runtime stats accompanying :meth:`RoutesService.show_route` per FR-047.

    Sourced from the in-memory ``_SharedRoutingState`` (resets on
    daemon restart per data-model.md §11).
    """

    last_routing_cycle_at: str | None
    events_consumed: int
    last_skip_reason: str | None
    last_skip_at: str | None


@dataclass(frozen=True)
class StalledRoute:
    """One enabled route's lag — emitted by :func:`compute_most_stalled`
    when at least one enabled route has unconsumed matching events.

    ``lag`` is the count of events ``WHERE event_id > cursor AND
    event_type = route.event_type`` for the route's selector. Higher
    is more-stalled.
    """

    route_id: str
    lag: int


def compute_most_stalled(conn) -> StalledRoute | None:
    """Per-enabled-route lag computation for the ``most_stalled_route``
    JSON field on ``agenttower status`` (FR-038 + contracts/cli-status-routing.md).

    Returns the enabled route with the largest lag, OR ``None`` when
    every enabled route's lag is 0 (no backlog anywhere). Disabled
    routes are EXCLUDED — a deliberately-paused route is not "stalled"
    per contracts/cli-status-routing.md "Lag-computation with disabled
    routes".

    Tie-break per contracts/cli-status-routing.md: ``(created_at,
    route_id)`` of the route row (matches the routing worker's
    FR-042 processing order).

    Complexity: one indexed scan per enabled route. At MVP scale
    (1000 routes, 100K events post-cursor) total cost ≈ 1000 ×
    O(log N + M) which is well under SC-006's 500 ms budget (per
    plan §Performance Addendum).
    """
    routes = routes_dao.list_routes(conn, enabled_only=True)
    if not routes:
        return None

    leader: StalledRoute | None = None
    for route in routes:
        # Routes are pre-sorted by (created_at ASC, route_id ASC),
        # so the FIRST route to claim a given lag wins the tie.
        cur = conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_id > ? AND event_type = ?",
            (int(route.last_consumed_event_id), route.event_type),
        )
        (count,) = cur.fetchone()
        lag = int(count or 0)
        if lag <= 0:
            continue
        if leader is None or lag > leader.lag:
            leader = StalledRoute(route_id=route.route_id, lag=lag)
    return leader


def compute_route_counts(conn) -> tuple[int, int, int]:
    """Return ``(total, enabled, disabled)`` for the routes table.
    Used by the ``agenttower status`` ``routing`` JSON section."""
    row = conn.execute(
        "SELECT "
        "  COUNT(*) AS total, "
        "  COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS enabled "
        "FROM routes"
    ).fetchone()
    total = int(row[0] or 0)
    enabled = int(row[1] or 0)
    return total, enabled, total - enabled


# ──────────────────────────────────────────────────────────────────────
# Shared-state Protocol (avoid hard import of worker module)
# ──────────────────────────────────────────────────────────────────────


class _SharedStateProtocol:
    """Minimal read surface of ``worker._SharedRoutingState`` used by
    :meth:`show_route`. Stays small so :class:`RoutesService` doesn't
    pull in the worker module."""

    events_consumed_total: int
    last_routing_cycle_at: str | None
    last_skip_per_route: dict[str, tuple[str, str]]


# ──────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────


class RoutesService:
    """Top-level CRUD orchestration for the ``routes`` table.

    Construction wires every dependency; methods are called from the
    socket dispatch layer (see ``socket_api/methods.py`` once T030
    lands).
    """

    def __init__(
        self,
        *,
        conn_factory: Callable[[], sqlite3.Connection],
        audit_writer: RoutesAuditWriter,
        events_file: Path,
        shared_state: _SharedStateProtocol | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._audit = audit_writer
        self._events_file = events_file
        self._shared_state = shared_state
        self._clock = clock if clock is not None else SystemClock()

    # ─── add_route (FR-001 / FR-002 / FR-005..008) ───────────────────

    def add_route(
        self,
        *,
        event_type: str,
        source_scope_kind: str,
        source_scope_value: str | None,
        target_rule: str,
        target_value: str | None,
        master_rule: str,
        master_value: str | None,
        template_string: str,
        created_by_agent_id: str | None,
    ) -> RouteRow:
        """Insert a new route after validating every closed-set field.

        Validation order per research §R15 (single-error-per-call):
        event_type → master_rule → target_rule → source_scope →
        target_value → template.

        Sets ``last_consumed_event_id`` to
        ``MAX(events.event_id) OR 0`` at insert time (FR-002 — new
        routes never replay history).

        Emits ``route_created`` on success per FR-035 +
        :class:`RoutesAuditWriter`.

        Returns:
            The persisted :class:`RouteRow`.

        Raises:
            RouteEventTypeInvalid: ``event_type`` not in FR-005 set.
            RouteMasterRuleInvalid: ``master_rule`` not in
                ``{auto, explicit}`` OR explicit with missing value.
            RouteTargetRuleInvalid: ``target_rule`` not in
                ``{explicit, source, role}`` OR conditional value
                mismatch.
            RouteSourceScopeInvalid: ``source_scope_*`` shape
                violation (Clarifications Q1).
            RouteTemplateInvalid: ``template`` references unknown
                fields (FR-008).
            RouteCreationFailed: SQLite INSERT failed (PK collision —
                vanishingly unlikely with UUIDv4, but defended).
        """
        # 1. event_type — FR-005
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise RouteEventTypeInvalid(
                f"event_type {event_type!r} not in FR-005 vocabulary "
                f"{sorted(_ALLOWED_EVENT_TYPES)}"
            )

        # 2. master_rule — FR-007
        if master_rule not in MASTER_RULES:
            raise RouteMasterRuleInvalid(
                f"master_rule {master_rule!r} not in "
                f"{sorted(MASTER_RULES)}"
            )
        if master_rule == "explicit" and not master_value:
            raise RouteMasterRuleInvalid(
                "master_rule='explicit' requires a non-empty master_value"
            )
        if master_rule == "auto" and master_value is not None:
            raise RouteMasterRuleInvalid(
                "master_rule='auto' requires master_value=NULL"
            )

        # 3. target_rule — FR-006
        if target_rule not in _ALLOWED_TARGET_RULES:
            raise RouteTargetRuleInvalid(
                f"target_rule {target_rule!r} not in "
                f"{sorted(_ALLOWED_TARGET_RULES)}"
            )
        if target_rule == "source" and target_value is not None:
            raise RouteTargetRuleInvalid(
                "target_rule='source' requires target_value=NULL"
            )
        if target_rule != "source" and not target_value:
            raise RouteTargetRuleInvalid(
                f"target_rule={target_rule!r} requires a non-empty target_value"
            )

        # 4. source_scope parse (Clarifications Q1) — uses
        # source_scope.parse_source_scope_value which raises
        # RouteSourceScopeInvalid on any bad shape.
        source_scope.parse_source_scope_value(
            source_scope_value, source_scope_kind,
        )

        # 5. target_value parse when target_rule=role — FR-006: role
        # MUST be in {slave, swarm}.
        if target_rule == "role":
            assert target_value is not None
            try:
                role, _capability = source_scope.parse_role_capability(
                    target_value,
                )
            except ValueError as exc:
                raise RouteTargetRuleInvalid(
                    f"target_value {target_value!r} (target_rule='role') is "
                    f"malformed: {exc}"
                ) from None
            if role not in _RECEIVE_PERMITTED_ROLES:
                raise RouteTargetRuleInvalid(
                    f"target_rule='role' value role={role!r} must be in "
                    f"{sorted(_RECEIVE_PERMITTED_ROLES)} "
                    f"(the FEAT-009 receive-permitted set per FR-006)"
                )

        # 6. template — FR-008 whitelist (raises RouteTemplateInvalid).
        template.validate_template_string(template_string)

        # ── All validations passed — proceed to INSERT.
        ts = now_iso_ms_utc(self._clock)
        route_id = str(uuid.uuid4())

        conn = self._conn_factory()
        try:
            cursor_at_creation = routes_dao.select_max_event_id(conn)
            row = RouteRow(
                route_id=route_id,
                event_type=event_type,
                source_scope_kind=source_scope_kind,
                source_scope_value=source_scope_value,
                target_rule=target_rule,
                target_value=target_value,
                master_rule=master_rule,
                master_value=master_value,
                template=template_string,
                enabled=True,
                last_consumed_event_id=cursor_at_creation,
                created_at=ts,
                updated_at=ts,
                created_by_agent_id=created_by_agent_id,
            )

            def _insert() -> None:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    routes_dao.insert_route(conn, row)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            try:
                with_lock_retry(_insert)
            except sqlite3.IntegrityError as exc:
                raise RouteCreationFailed(
                    f"routes INSERT failed: {exc}"
                ) from exc
        finally:
            conn.close()

        # Audit emit AFTER commit.
        self._audit.emit_route_created(
            self._events_file,
            route_id=route_id,
            event_type_subscribed=event_type,
            source_scope_kind=source_scope_kind,
            source_scope_value=source_scope_value,
            target_rule=target_rule,
            target_value=target_value,
            master_rule=master_rule,
            master_value=master_value,
            template=template_string,
            created_by_agent_id=created_by_agent_id,
            cursor_at_creation=cursor_at_creation,
        )
        return row

    # ─── remove_route (FR-003) ────────────────────────────────────────

    def remove_route(
        self, route_id: str, *, deleted_by_agent_id: str | None,
    ) -> None:
        """Hard-delete one route. Raises :class:`RouteIdNotFound` on miss.

        Queue rows with this ``route_id`` remain intact (orphan
        reference per FR-003).
        """
        conn = self._conn_factory()
        try:
            def _delete() -> bool:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    deleted = routes_dao.delete_route(conn, route_id)
                    conn.execute("COMMIT")
                    return deleted
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            deleted = with_lock_retry(_delete)
        finally:
            conn.close()

        if not deleted:
            raise RouteIdNotFound(f"no route with route_id={route_id!r}")

        self._audit.emit_route_deleted(
            self._events_file,
            route_id=route_id,
            deleted_by_agent_id=deleted_by_agent_id,
        )

    # ─── enable_route / disable_route (FR-009 idempotent) ─────────────

    def enable_route(
        self, route_id: str, *, updated_by_agent_id: str | None,
    ) -> bool:
        """Set ``enabled=true``. Returns ``True`` iff state changed.

        Idempotent per FR-009: re-enabling an already-enabled route
        is a no-op that returns ``False`` and does NOT emit
        ``route_updated``. The CLI / socket layer still returns
        ``operation='enabled'`` for both cases (no error).
        """
        return self._flip_enabled(
            route_id, enabled=True,
            updated_by_agent_id=updated_by_agent_id,
        )

    def disable_route(
        self, route_id: str, *, updated_by_agent_id: str | None,
    ) -> bool:
        """Set ``enabled=false``. Returns ``True`` iff state changed.
        Idempotent per FR-009 (mirror of :meth:`enable_route`)."""
        return self._flip_enabled(
            route_id, enabled=False,
            updated_by_agent_id=updated_by_agent_id,
        )

    def _flip_enabled(
        self,
        route_id: str,
        *,
        enabled: bool,
        updated_by_agent_id: str | None,
    ) -> bool:
        ts = now_iso_ms_utc(self._clock)
        conn = self._conn_factory()
        try:
            # Distinguish "not found" from "already in state" via a
            # pre-check; routes_dao.update_enabled returns False for
            # both cases, but the service layer's contract requires
            # raising RouteIdNotFound only when the route truly
            # doesn't exist.
            existing = routes_dao.select_route(conn, route_id)
            if existing is None:
                raise RouteIdNotFound(f"no route with route_id={route_id!r}")

            def _update() -> bool:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    changed = routes_dao.update_enabled(
                        conn, route_id,
                        enabled=enabled,
                        updated_at=ts,
                    )
                    conn.execute("COMMIT")
                    return changed
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            changed = with_lock_retry(_update)
        finally:
            conn.close()

        if changed:
            self._audit.emit_route_updated(
                self._events_file,
                route_id=route_id,
                change={"enabled": enabled},
                updated_by_agent_id=updated_by_agent_id,
            )
        return changed

    # ─── Reads (FR-046, FR-047) ───────────────────────────────────────

    def list_routes(self, *, enabled_only: bool = False) -> list[RouteRow]:
        """List every route ordered by ``(created_at ASC, route_id ASC)``
        per FR-042 / FR-046."""
        conn = self._conn_factory()
        try:
            return routes_dao.list_routes(conn, enabled_only=enabled_only)
        finally:
            conn.close()

    def show_route(self, route_id: str) -> tuple[RouteRow, RouteRuntime]:
        """Return the route row + runtime sub-object per FR-047.

        Raises:
            RouteIdNotFound: when no row matches.
        """
        conn = self._conn_factory()
        try:
            row = routes_dao.select_route(conn, route_id)
        finally:
            conn.close()
        if row is None:
            raise RouteIdNotFound(f"no route with route_id={route_id!r}")
        return row, self._build_runtime(route_id)

    def _build_runtime(self, route_id: str) -> RouteRuntime:
        """Derive the runtime sub-object from ``_SharedRoutingState``.

        Per data-model.md §11, the runtime fields are in-memory only
        (reset on daemon restart). When no shared state is wired
        (e.g., unit tests of the service in isolation), returns a
        zeroed runtime block — operators see "nothing has happened
        yet" rather than a crash.
        """
        if self._shared_state is None:
            return RouteRuntime(
                last_routing_cycle_at=None,
                events_consumed=0,
                last_skip_reason=None,
                last_skip_at=None,
            )

        last_skip = self._shared_state.last_skip_per_route.get(route_id)
        return RouteRuntime(
            last_routing_cycle_at=self._shared_state.last_routing_cycle_at,
            # Per data-model.md §11: events_consumed is an approximate
            # measure (current cursor minus 0). Cross-restart precision
            # is a forward-compat follow-up. For now we return the
            # process-wide total — operators interpret it as "events
            # the worker has processed since daemon start".
            events_consumed=self._shared_state.events_consumed_total,
            last_skip_reason=(last_skip[0] if last_skip else None),
            last_skip_at=(last_skip[1] if last_skip else None),
        )
