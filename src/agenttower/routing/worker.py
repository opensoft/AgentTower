"""FEAT-010 routing worker (spec §FR-010..014, §FR-040..044).

Single-threaded sequential routing cycle per Clarifications Q4 +
research §R1. The worker:

1. Drains any buffered audit entries (recovery from prior degraded
   state per FR-039).
2. Lists every ``enabled=1`` route in ``(created_at, route_id)`` order
   (FR-042).
3. For each route, processes up to ``batch_size`` matching events
   from ``event_id > last_consumed_event_id`` in ``event_id`` ascending
   order (FR-011 / FR-041).
4. For each event:
   - Snapshot active masters and arbitrate (FR-017 / FR-020).
   - Resolve target per ``target_rule`` (FR-021..023).
   - Render the template with FEAT-007 redaction on
     ``{event_excerpt}`` (FR-025 / FR-026).
   - Enqueue via :meth:`QueueService.enqueue_route_message` — same
     validation / permission / kill-switch / per-target FIFO path as
     direct sends (FR-024 / FR-032 / FR-055).
   - Advance the per-route cursor (FR-012).
   - Emit ``route_matched`` or ``route_skipped`` to JSONL.
5. Sleep until the next cycle boundary; wake immediately on
   shutdown_event signal.

Failure-mode mapping (contracts/error-codes.md §5 + Plan §R11):
- FEAT-009 ``KillSwitchOff`` → NOT a skip; row inserted with
  ``block_reason='kill_switch_off'``; cursor still advances (Story 5 #1).
- FEAT-009 target / body exceptions → ``route_skipped(reason=...)``
  with the matching closed-set reason; cursor advances.
- Transient SQLite-lock / ``RoutingDegraded`` → cursor does NOT
  advance; ``routing_worker_degraded`` flag flips; event retried
  next cycle (FR-013).
- Defense-in-depth: UNIQUE constraint on ``(route_id, event_id)``
  → ``RoutingDuplicateInsert`` (FR-030); cursor MUST still advance
  (the row was inserted in a prior cycle that crashed before
  advance — recovery path per SC-004).

Per research §R16, the worker reads
``_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT`` at construction time
and exits with ``SystemExit(137)`` at the specified hook point;
production builds with the env var unset are zero-cost.

Concurrency: this module spawns NO threads of its own. The daemon
adapter wires a single :meth:`RoutingWorker.run` thread + the
heartbeat thread (separate module).

All shared state lives on the supplied
:class:`_SharedRoutingState`; the lock there serializes mutation +
heartbeat snapshots.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

from agenttower.routing import (
    arbitration,
    routes_dao,
    source_scope,
    target_resolver,
    template,
)
from agenttower.routing.errors import (
    QueueServiceError,
    SqliteLockConflict,
    TargetResolveError,
)
from agenttower.routing.route_errors import (
    NO_ELIGIBLE_TARGET,
    ROUTING_INTERNAL_RENDER_FAILURE,
    ROUTING_SQLITE_LOCKED,
    RouteTemplateRenderError,
    RoutingTransientError,
)
from agenttower.routing.routes_audit import RoutesAuditWriter
from agenttower.routing.routes_dao import RouteRow
from agenttower.routing.service import QueueService
from agenttower.routing.timestamps import Clock, SystemClock, now_iso_ms_utc
from agenttower.state.agents import AgentRecord

_log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Shared state (data-model.md §4)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _SharedRoutingState:
    """Per-process in-memory state shared by the worker, the heartbeat
    thread, and the ``agenttower status`` handler (data-model.md §4).

    The ``lock`` serializes every mutation; the heartbeat thread
    reads-and-resets the ``*_since_last_heartbeat`` counters under
    the same lock at every emission. The ``agenttower status``
    handler reads the remaining fields under the same lock to compute
    the routing JSON object.
    """

    cycles_since_last_heartbeat: int = 0
    events_consumed_since_last_heartbeat: int = 0
    skips_since_last_heartbeat: int = 0
    events_consumed_total: int = 0
    skips_by_reason: dict[str, int] = field(default_factory=dict)
    last_routing_cycle_at: str | None = None
    routing_worker_degraded: bool = False
    audit_buffer_dropped: int = 0
    last_skip_per_route: dict[str, tuple[str, str]] = field(
        default_factory=dict
    )  # route_id -> (reason, timestamp)
    lock: threading.Lock = field(default_factory=threading.Lock)


# ──────────────────────────────────────────────────────────────────────
# Bounds (data-model.md §7)
# ──────────────────────────────────────────────────────────────────────


DEFAULT_CYCLE_INTERVAL_S: Final[float] = 1.0
DEFAULT_BATCH_SIZE: Final[int] = 100

_CYCLE_INTERVAL_BOUNDS: Final[tuple[float, float]] = (0.1, 60.0)
_BATCH_SIZE_BOUNDS: Final[tuple[int, int]] = (1, 10_000)


# ──────────────────────────────────────────────────────────────────────
# Fault-injection contract (research §R16)
# ──────────────────────────────────────────────────────────────────────


_FAULT_INJECT_ENV: Final[str] = "_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT"
_FAULT_INJECT_BEFORE_COMMIT: Final[str] = "before_commit"
_FAULT_INJECT_AFTER_COMMIT: Final[str] = "after_commit"


# ──────────────────────────────────────────────────────────────────────
# Protocol-typed dependencies (testable via mocks)
# ──────────────────────────────────────────────────────────────────────


class AgentsService(Protocol):
    """Read-only registry surface consumed by the routing worker.

    Defined as a Protocol so tests can pass a thin in-memory mock
    without spinning up the full FEAT-006 AgentsService stack.

    Structurally compatible with
    :class:`agenttower.routing.target_resolver.AgentsLookup` so the
    worker can delegate ``target_rule='explicit'`` resolution to the
    shared :func:`target_resolver.resolve_target` helper (FR-021).
    """

    def list_active_masters(self) -> list[AgentRecord]:
        """Snapshot of currently-active agents with ``role='master'``,
        in stable but unspecified order. The arbitration picker
        applies its own deterministic sort per FR-017."""

    def get_agent_by_id(self, agent_id: str) -> AgentRecord | None:
        """Lookup one agent by id (any role, any active state).
        Returns ``None`` on miss. Used for ``target_rule='source'``
        and ``target_rule='explicit'`` resolution."""

    def find_agents_by_label(
        self, label: str, *, only_active: bool = True,
    ) -> list[AgentRecord]:
        """Return every :class:`AgentRecord` whose ``label`` equals
        ``label``. With ``only_active=True``, deregistered or inactive
        agents are filtered out. Used by the FR-021 label-fallback
        path inside ``target_rule='explicit'`` resolution."""

    def list_active_by_role(
        self, role: str, capability: str | None = None
    ) -> list[AgentRecord]:
        """Snapshot of currently-active agents matching ``role`` (and
        ``capability`` when supplied), in stable but unspecified
        order. Used for ``target_rule='role'`` resolution; the worker
        applies its own lex-lowest sort per FR-023."""


class EventReader(Protocol):
    """Worker-tailored event-scan surface.

    The FEAT-008 ``events.dao.select_events`` is paginated for the
    CLI; the worker needs a simpler ``WHERE event_id > cursor AND
    event_type = ? ORDER BY event_id LIMIT batch`` query. This
    Protocol isolates the dependency.
    """

    def select_events_after_cursor(
        self,
        conn: sqlite3.Connection,
        *,
        cursor: int,
        event_type: str,
        limit: int,
    ) -> list["EventRowSnapshot"]:
        """Return events with ``event_id > cursor AND event_type = ?``
        ordered by ``event_id`` ascending, capped at ``limit``."""


@dataclass(frozen=True)
class EventRowSnapshot:
    """Subset of FEAT-008 EventRow that the worker actually consumes.

    Kept separate from the full ``events.dao.EventRow`` so the worker
    can construct test fixtures with minimal boilerplate.
    """

    event_id: int
    event_type: str
    source_agent_id: str  # FEAT-008 events.agent_id
    excerpt: str
    observed_at: str


# ──────────────────────────────────────────────────────────────────────
# RoutingWorker
# ──────────────────────────────────────────────────────────────────────


class RoutingWorker:
    """Single-threaded sequential routing cycle (plan §1).

    Construction wires every dependency; :meth:`run` is the loop body
    invoked on a daemon thread by ``daemon_adapters.start_daemon``.
    """

    def __init__(
        self,
        *,
        conn_factory: Callable[[], sqlite3.Connection],
        agents_service: AgentsService,
        event_reader: EventReader,
        queue_service: QueueService,
        audit_writer: RoutesAuditWriter,
        events_file: Path,
        shutdown_event: threading.Event,
        shared_state: _SharedRoutingState,
        clock: Clock | None = None,
        cycle_interval: float = DEFAULT_CYCLE_INTERVAL_S,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not (
            _CYCLE_INTERVAL_BOUNDS[0]
            <= cycle_interval
            <= _CYCLE_INTERVAL_BOUNDS[1]
        ):
            raise ValueError(
                f"cycle_interval {cycle_interval} out of bounds "
                f"{_CYCLE_INTERVAL_BOUNDS}"
            )
        if not (_BATCH_SIZE_BOUNDS[0] <= batch_size <= _BATCH_SIZE_BOUNDS[1]):
            raise ValueError(
                f"batch_size {batch_size} out of bounds {_BATCH_SIZE_BOUNDS}"
            )
        self._conn_factory = conn_factory
        self._agents = agents_service
        self._events = event_reader
        self._queue = queue_service
        self._audit = audit_writer
        self._events_file = events_file
        self._shutdown_event = shutdown_event
        self._state = shared_state
        self._clock = clock if clock is not None else SystemClock()
        self._cycle_interval = float(cycle_interval)
        self._batch_size = int(batch_size)
        self._fault_inject_at = os.environ.get(_FAULT_INJECT_ENV, "")

    # ─── Run loop (plan §1 / FR-014 / FR-040) ─────────────────────────

    def run(self) -> None:
        """Loop until ``shutdown_event`` is set; one cycle per tick.

        ``threading.Event.wait`` returns immediately when the event is
        set, so shutdown latency is bounded by the in-flight cycle's
        remaining work (FR-043).
        """
        while not self._shutdown_event.is_set():
            cycle_start = self._clock.monotonic()
            try:
                self._run_one_cycle()
            except Exception:  # pragma: no cover — defensive
                _log.exception("routing worker cycle raised unexpectedly")
                with self._state.lock:
                    self._state.routing_worker_degraded = True
            elapsed = self._clock.monotonic() - cycle_start
            remaining = self._cycle_interval - elapsed
            if remaining > 0:
                # event.wait(timeout) returns True iff the event was set
                # — exits the loop early on shutdown.
                self._shutdown_event.wait(remaining)

    # ─── Cycle body ───────────────────────────────────────────────────

    def _run_one_cycle(self) -> None:
        """One pass: drain audit buffer, list routes, process each."""
        # Step 1: drain any pending audit entries from a prior degraded
        # cycle (per FR-039 / research §R14). If anything stays
        # buffered, the `degraded` flag persists.
        self._audit.drain_pending()

        # Step 2: list every enabled route in deterministic order
        # (FR-042). The list is a snapshot — operator catalog changes
        # mid-cycle only take effect on the NEXT cycle (plan Risk
        # Register §1).
        conn = self._conn_factory()
        try:
            routes = routes_dao.list_routes(conn, enabled_only=True)
        finally:
            conn.close()

        cycle_had_any_advance = False
        cycle_had_any_failure = False

        for route in routes:
            if self._shutdown_event.is_set():
                break
            try:
                advanced = self._process_route_batch(route)
                cycle_had_any_advance = cycle_had_any_advance or advanced
            except RoutingTransientError as exc:
                _log.warning(
                    "routing worker transient error on route %s: %s",
                    route.route_id, exc,
                )
                cycle_had_any_failure = True
            except Exception:  # pragma: no cover — defensive
                _log.exception(
                    "routing worker unexpected error on route %s",
                    route.route_id,
                )
                cycle_had_any_failure = True

        # Step 3: cycle bookkeeping. Always count the cycle; clear
        # degraded if this cycle had no failures AND the audit buffer
        # is empty (per data-model.md §10 entry/exit rules).
        with self._state.lock:
            self._state.cycles_since_last_heartbeat += 1
            self._state.last_routing_cycle_at = now_iso_ms_utc(self._clock)
            audit_clean = not self._audit.has_pending()
            if cycle_had_any_failure or not audit_clean:
                self._state.routing_worker_degraded = True
            else:
                self._state.routing_worker_degraded = False

    # ─── Per-route batch ──────────────────────────────────────────────

    def _process_route_batch(self, route: RouteRow) -> bool:
        """Process up to ``batch_size`` matching events for ``route``.

        Returns ``True`` iff at least one event advanced the cursor.

        Re-fetches the route row between events (Risk Register §1) so
        a mid-batch ``route disable`` takes effect for the next event.
        """
        parsed_scope = source_scope.parse_source_scope_value(
            route.source_scope_value, route.source_scope_kind,
        )
        conn = self._conn_factory()
        try:
            candidates = self._events.select_events_after_cursor(
                conn,
                cursor=route.last_consumed_event_id,
                event_type=route.event_type,
                limit=self._batch_size,
            )
        finally:
            conn.close()

        any_advanced = False
        for ev in candidates:
            if self._shutdown_event.is_set():
                break
            # Re-fetch route to detect mid-batch disable (Risk §1).
            conn = self._conn_factory()
            try:
                refreshed = routes_dao.select_route(conn, route.route_id)
            finally:
                conn.close()
            if refreshed is None or not refreshed.enabled:
                break

            # Source-scope match (FR-010): pull the source agent's
            # role/capability for the scope match. None ↔ "missing
            # agent record"; treat as non-match (event will be skipped
            # by the cursor moving past it on a later cycle if needed,
            # but for now we simply advance + emit no audit).
            source_agent = self._agents.get_agent_by_id(ev.source_agent_id)
            if source_agent is None:
                self._advance_cursor_only(route.route_id, ev.event_id)
                any_advanced = True
                continue
            if not source_scope.matches(
                parsed_scope,
                event_source_agent_id=ev.source_agent_id,
                event_source_role=source_agent.role,
                event_source_capability=source_agent.capability,
            ):
                # Source doesn't match — silently advance cursor; not
                # an audit event (FR-010 only triggers audit for
                # MATCHING events that reach a terminal decision).
                self._advance_cursor_only(route.route_id, ev.event_id)
                any_advanced = True
                continue

            self._process_one_event(route, ev, source_agent)
            any_advanced = True

        return any_advanced

    # ─── Per-event ────────────────────────────────────────────────────

    def _process_one_event(
        self,
        route: RouteRow,
        ev: EventRowSnapshot,
        source_agent: AgentRecord,
    ) -> None:
        """One terminal decision: enqueue OR skip with closed-set reason.

        The cursor advances unconditionally on every terminal decision
        per FR-012; transient errors raise :class:`RoutingTransientError`
        which the caller catches WITHOUT advancing the cursor.
        """
        # Step 1: arbitrate master.
        active_masters = self._agents.list_active_masters()
        arb_result = arbitration.pick_master(
            master_rule=route.master_rule,
            master_value=route.master_value,
            active_masters=active_masters,
        )

        if isinstance(arb_result, arbitration.MasterSkip):
            self._skip(
                route, ev,
                winner=None, target=None,
                reason=arb_result.reason, sub_reason=None,
            )
            return

        assert isinstance(arb_result, arbitration.MasterWon)
        winner = arb_result.agent

        # Step 2: resolve target.
        try:
            target = self._resolve_target(route, ev, source_agent)
        except _TargetResolveSkip as exc:
            self._skip(
                route, ev,
                winner=winner, target=None,
                reason=exc.reason, sub_reason=None,
            )
            return

        # Step 3: render template.
        try:
            body_bytes = template.render_template(
                route.template,
                fields=self._build_template_fields(ev, source_agent),
                raw_event_excerpt=ev.excerpt,
            )
        except RouteTemplateRenderError as exc:
            self._skip(
                route, ev,
                winner=winner, target=target,
                reason="template_render_error", sub_reason=exc.sub_reason,
            )
            return
        except Exception as exc:  # pragma: no cover — defensive
            _log.exception(
                "unexpected render failure on route %s event %d",
                route.route_id, ev.event_id,
            )
            raise RoutingTransientError(
                ROUTING_INTERNAL_RENDER_FAILURE,
                f"template render raised {type(exc).__name__}",
            ) from exc

        # Step 4: enqueue via the FEAT-009 single-insert-path.
        # KillSwitchOff lands as a blocked row (NOT a skip per Story
        # 5 #1). Target-related QueueServiceErrors map to closed-set
        # skip reasons per contracts/error-codes.md §5.
        try:
            self._fault_inject(_FAULT_INJECT_BEFORE_COMMIT)
            self._queue.enqueue_route_message(
                sender=winner,
                target_input=target.agent_id,
                body_bytes=body_bytes,
                route_id=route.route_id,
                event_id=ev.event_id,
            )
            self._fault_inject(_FAULT_INJECT_AFTER_COMMIT)
        except QueueServiceError as exc:
            # Map FEAT-009 closed-set code → FEAT-010 skip reason. The
            # one exception: kill_switch_off does NOT raise — the
            # row is inserted with state='blocked' and the call
            # returns normally (FR-032 + Story 5 #1).
            self._skip(
                route, ev,
                winner=winner, target=target,
                reason=exc.code, sub_reason=None,
            )
            return
        except sqlite3.IntegrityError as exc:
            # Partial UNIQUE (route_id, event_id) fired — a prior
            # cycle inserted this row before its cursor advance got
            # COMMITted (crash recovery path per SC-004). Treat as
            # "already done": advance cursor + emit route_matched.
            _log.warning(
                "routing duplicate-insert recovery on route %s event %d: %s",
                route.route_id, ev.event_id, exc,
            )
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc).lower():
                raise RoutingTransientError(
                    ROUTING_SQLITE_LOCKED,
                    f"sqlite locked during enqueue: {exc}",
                ) from exc
            raise

        # Step 5: advance cursor (FR-012). Note: per Plan §R2's strict
        # reading, this MUST be in the same SQLite transaction as the
        # insert. The current implementation uses two sequential
        # transactions guarded by the FR-030 partial UNIQUE index —
        # see the module docstring "Implementation Deviation" note.
        self._advance_cursor_only(route.route_id, ev.event_id)

        # Step 6: emit route_matched audit (after commit).
        self._audit.emit_route_matched(
            self._events_file,
            event_id=ev.event_id,
            route_id=route.route_id,
            winner_master_agent_id=winner.agent_id,
            target_agent_id=target.agent_id,
            target_label=target.label,
            event_excerpt=ev.excerpt[:240],
        )
        with self._state.lock:
            self._state.events_consumed_total += 1
            self._state.events_consumed_since_last_heartbeat += 1

    # ─── Target resolution ────────────────────────────────────────────

    def _resolve_target(
        self,
        route: RouteRow,
        ev: EventRowSnapshot,
        source_agent: AgentRecord,
    ) -> AgentRecord:
        """Three branches per FR-021..023; raises :class:`_TargetResolveSkip`
        with a closed-set reason on failure."""
        rule = route.target_rule
        value = route.target_value

        if rule == "explicit":
            assert value is not None
            # FR-021: resolve as agent_id first, then as label. Reuses
            # the FEAT-009 :func:`target_resolver.resolve_target` so
            # ``send-input`` and the routing worker share one
            # resolution policy (id-shaped → id lookup; otherwise →
            # label lookup, with ``only_active=True`` so a
            # deregistered agent can't shadow the current owner).
            # Ambiguous labels (multiple active matches) also fold
            # into ``target_not_found`` — the routing-worker closed
            # set has no separate ``target_label_ambiguous`` reason.
            try:
                return target_resolver.resolve_target(value, self._agents)
            except TargetResolveError as exc:
                _log.warning(
                    "route %s target_value=%r resolution failed: %s",
                    route.route_id, value, exc,
                )
                raise _TargetResolveSkip("target_not_found") from exc

        if rule == "source":
            # FR-022: source agent is the target.
            if not source_agent.active:
                raise _TargetResolveSkip("target_not_active")
            return source_agent

        if rule == "role":
            # FR-023: lex-lowest active matching role+capability.
            assert value is not None
            role, capability = source_scope.parse_role_capability(value)
            matches = self._agents.list_active_by_role(role, capability)
            if not matches:
                raise _TargetResolveSkip(NO_ELIGIBLE_TARGET)
            return sorted(matches, key=lambda a: a.agent_id)[0]

        raise _TargetResolveSkip("target_not_found")  # unknown rule

    # ─── Template field assembly ──────────────────────────────────────

    def _build_template_fields(
        self, ev: EventRowSnapshot, source_agent: AgentRecord,
    ) -> dict[str, object]:
        """Build the substitution mapping for non-``event_excerpt`` fields.

        ``event_excerpt`` is supplied separately (and redacted) by
        :func:`template.render_template`.
        """
        return {
            "event_id": ev.event_id,
            "event_type": ev.event_type,
            "source_agent_id": ev.source_agent_id,
            "source_label": source_agent.label,
            "source_role": source_agent.role,
            "source_capability": source_agent.capability or "",
            "observed_at": ev.observed_at,
        }

    # ─── Skip path ────────────────────────────────────────────────────

    def _skip(
        self,
        route: RouteRow,
        ev: EventRowSnapshot,
        *,
        winner: AgentRecord | None,
        target: AgentRecord | None,
        reason: str,
        sub_reason: str | None,
    ) -> None:
        """Advance cursor + emit ``route_skipped`` + update counters."""
        self._advance_cursor_only(route.route_id, ev.event_id)
        self._audit.emit_route_skipped(
            self._events_file,
            event_id=ev.event_id,
            route_id=route.route_id,
            winner_master_agent_id=(winner.agent_id if winner else None),
            target_agent_id=(target.agent_id if target else None),
            target_label=(target.label if target else None),
            reason=reason,
            sub_reason=sub_reason,
            event_excerpt=ev.excerpt[:240],
        )
        ts = now_iso_ms_utc(self._clock)
        with self._state.lock:
            self._state.skips_since_last_heartbeat += 1
            self._state.skips_by_reason[reason] = (
                self._state.skips_by_reason.get(reason, 0) + 1
            )
            self._state.last_skip_per_route[route.route_id] = (reason, ts)

    # ─── Cursor advance ───────────────────────────────────────────────

    def _advance_cursor_only(self, route_id: str, event_id: int) -> None:
        """BEGIN IMMEDIATE + advance cursor + COMMIT, with lock retry."""
        ts = now_iso_ms_utc(self._clock)
        conn = self._conn_factory()
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
                routes_dao.advance_cursor(conn, route_id, event_id, updated_at=ts)
                conn.execute("COMMIT")
            except sqlite3.OperationalError as exc:
                conn.execute("ROLLBACK")
                if "database is locked" in str(exc).lower():
                    raise RoutingTransientError(
                        ROUTING_SQLITE_LOCKED,
                        f"sqlite locked during cursor advance: {exc}",
                    ) from exc
                raise
        finally:
            conn.close()

    # ─── Fault injection (research §R16) ──────────────────────────────

    def _fault_inject(self, point: str) -> None:
        """If the env var matches ``point``, raise SystemExit(137).

        Production builds with the env var unset are zero-cost (a
        single string compare per event).
        """
        if self._fault_inject_at == point:
            raise SystemExit(137)


# ──────────────────────────────────────────────────────────────────────
# Internal control-flow exception
# ──────────────────────────────────────────────────────────────────────


class _TargetResolveSkip(Exception):
    """Raised by :meth:`RoutingWorker._resolve_target` to short-circuit
    the per-event flow into the skip path. Carries one of the
    target-resolution skip reasons from
    :data:`agenttower.routing.route_errors.SKIP_REASONS`.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
