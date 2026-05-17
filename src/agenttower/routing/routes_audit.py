"""FEAT-010 routes-audit writer (spec §FR-035 + §FR-039a).

Emits six JSONL audit event types to the FEAT-008 ``events.jsonl``
stream:

* ``route_matched`` — route fired, master arbitrated, queue row inserted
* ``route_skipped`` — route matched but no queue row (closed-set reason)
* ``route_created`` — operator added a route
* ``route_updated`` — operator flipped enabled (idempotent no-op DOES
  NOT emit; see :meth:`emit_route_updated` for the contract)
* ``route_deleted`` — operator removed a route
* ``routing_worker_heartbeat`` — periodic liveness signal (FR-039a)

Each emit function builds the JSONL envelope per
``contracts/routes-audit-schema.md`` and hands off to the FEAT-008
:func:`agenttower.events.writer.append_event` helper. On OSError
(disk full, permissions, etc.) the failed payload is pushed onto a
bounded ``collections.deque`` (``maxlen=10_000`` per research §R14)
for the routing worker to retry on the next cycle. When the deque
rolls over (a new entry forces the oldest one out), an
``audit_buffer_overflow`` warning line is written to the daemon log
and the ``audit_buffer_dropped`` counter on
:class:`_SharedRoutingState` is incremented (status-visible).

The writer also exposes :meth:`has_pending` so the ``agenttower
status`` socket handler can compute the
``degraded_routing_audit_persistence`` flag without coupling status
to the audit-buffer internals (data-model.md §4-§5).

Thread safety: every emit + retry path is serialized by an internal
``threading.Lock`` so concurrent ``route_*`` emissions from different
worker code paths don't interleave with the heartbeat thread's
emissions or with retry-buffer draining.
"""

from __future__ import annotations

import collections
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping

from agenttower.events.writer import append_event
from agenttower.routing.timestamps import now_iso_ms_utc

_log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Closed sets (mirror routes-audit-schema.md)
# ──────────────────────────────────────────────────────────────────────


_ROUTE_MATCHED: Final[str] = "route_matched"
_ROUTE_SKIPPED: Final[str] = "route_skipped"
_ROUTE_CREATED: Final[str] = "route_created"
_ROUTE_UPDATED: Final[str] = "route_updated"
_ROUTE_DELETED: Final[str] = "route_deleted"
_ROUTING_WORKER_HEARTBEAT: Final[str] = "routing_worker_heartbeat"

# Maximum entries held in the in-memory retry buffer when the JSONL
# stream is briefly unwritable. At ~1 KiB per entry, max RAM is ~10 MiB.
# When this cap is reached, FIFO eviction protects RAM at the cost of
# dropping the oldest unflushed entry (operator-visible via the
# ``audit_buffer_dropped`` counter on _SharedRoutingState).
DEFAULT_AUDIT_BUFFER_MAX_ROWS: Final[int] = 10_000


# ──────────────────────────────────────────────────────────────────────
# Pending-entry record
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _PendingAudit:
    """One audit entry that failed to write and is buffered for retry."""

    events_file: Path
    payload: Mapping[str, Any]


# ──────────────────────────────────────────────────────────────────────
# RoutesAuditWriter
# ──────────────────────────────────────────────────────────────────────


class RoutesAuditWriter:
    """Stateful writer holding the bounded retry buffer for FEAT-010
    audit emissions.

    Instantiated once per daemon process (daemon adapter wiring per
    plan §1). The routing worker calls :meth:`drain_pending` at the
    top of every cycle; the operator-facing status handler calls
    :meth:`has_pending` to compute
    ``degraded_routing_audit_persistence``.

    Optional ``on_buffer_drop`` callback fires once per overflow event
    so the daemon can increment ``_SharedRoutingState.audit_buffer_dropped``.
    """

    def __init__(
        self,
        *,
        max_buffer_rows: int = DEFAULT_AUDIT_BUFFER_MAX_ROWS,
        on_buffer_drop: callable | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._pending: collections.deque[_PendingAudit] = collections.deque(
            maxlen=max_buffer_rows,
        )
        self._on_buffer_drop = on_buffer_drop

    # ─── Public read API (consumed by status handler) ─────────────────

    def has_pending(self) -> bool:
        """Return ``True`` iff at least one audit entry is buffered
        awaiting retry. Used by the ``agenttower status`` handler to
        compute the ``degraded_routing_audit_persistence`` JSON field
        per data-model.md §5."""
        with self._lock:
            return len(self._pending) > 0

    def pending_count(self) -> int:
        """Return the current buffer depth (for diagnostics)."""
        with self._lock:
            return len(self._pending)

    # ─── Drain (consumed by worker at cycle start) ────────────────────

    def drain_pending(self) -> int:
        """Retry every buffered entry. Returns the count of successful
        retries. Failed retries stay in the buffer for the next call.

        The routing worker calls this at the top of every cycle BEFORE
        processing routes, so that the audit stream catches up before
        new entries are emitted.
        """
        drained = 0
        with self._lock:
            # Take a snapshot of the pending queue so we don't hold the
            # lock while doing JSONL I/O. Drop entries that succeed;
            # leave failures in place for the next drain.
            snapshot = list(self._pending)
            self._pending.clear()

        survivors: list[_PendingAudit] = []
        for entry in snapshot:
            try:
                append_event(entry.events_file, entry.payload)
                drained += 1
            except OSError:
                survivors.append(entry)

        if survivors:
            with self._lock:
                # Re-buffer the failures, preserving order.
                for entry in survivors:
                    self._enqueue_pending_locked(entry)
        return drained

    # ─── Emit methods (one per audit event type) ──────────────────────

    def emit_route_matched(
        self,
        events_file: Path,
        *,
        event_id: int,
        route_id: str,
        winner_master_agent_id: str,
        target_agent_id: str,
        target_label: str,
        event_excerpt: str,
    ) -> None:
        """Per FR-035 / contracts/routes-audit-schema.md §1: route fired,
        master arbitrated, queue row inserted (possibly into ``blocked``
        per Story 5 #1 — kill-switched inserts still emit
        ``route_matched``, NOT ``route_skipped``)."""
        self._emit(
            events_file,
            {
                "event_type": _ROUTE_MATCHED,
                "emitted_at": now_iso_ms_utc(),
                "event_id": int(event_id),
                "route_id": route_id,
                "winner_master_agent_id": winner_master_agent_id,
                "target_agent_id": target_agent_id,
                "target_label": target_label,
                "reason": None,  # always null on matched, for shape uniformity
                "event_excerpt": event_excerpt,
            },
        )

    def emit_route_skipped(
        self,
        events_file: Path,
        *,
        event_id: int,
        route_id: str,
        winner_master_agent_id: str | None,
        target_agent_id: str | None,
        target_label: str | None,
        reason: str,
        sub_reason: str | None,
        event_excerpt: str,
    ) -> None:
        """Per FR-035 / contracts/routes-audit-schema.md §2: route matched
        but no queue row created.

        ``winner_master_agent_id`` / ``target_agent_id`` / ``target_label``
        are ``None`` for arbitration-failure reasons (``no_eligible_master``,
        ``no_eligible_target``) per Clarifications Q2. ``sub_reason`` is
        non-None ONLY when ``reason == 'template_render_error'``.
        """
        self._emit(
            events_file,
            {
                "event_type": _ROUTE_SKIPPED,
                "emitted_at": now_iso_ms_utc(),
                "event_id": int(event_id),
                "route_id": route_id,
                "winner_master_agent_id": winner_master_agent_id,
                "target_agent_id": target_agent_id,
                "target_label": target_label,
                "reason": reason,
                "sub_reason": sub_reason,
                "event_excerpt": event_excerpt,
            },
        )

    def emit_route_created(
        self,
        events_file: Path,
        *,
        route_id: str,
        event_type_subscribed: str,
        source_scope_kind: str,
        source_scope_value: str | None,
        target_rule: str,
        target_value: str | None,
        master_rule: str,
        master_value: str | None,
        template: str,
        created_by_agent_id: str | None,
        cursor_at_creation: int,
    ) -> None:
        """Per FR-035 / contracts/routes-audit-schema.md §3: operator added
        a route via ``routes.add``."""
        self._emit(
            events_file,
            {
                "event_type": _ROUTE_CREATED,
                "emitted_at": now_iso_ms_utc(),
                "route_id": route_id,
                # NOTE: spelled ``event_type_subscribed`` to avoid colliding
                # with the audit envelope's own ``event_type`` discriminator
                # field (per contracts §3 explicit-naming rationale).
                "event_type_subscribed": event_type_subscribed,
                "source_scope_kind": source_scope_kind,
                "source_scope_value": source_scope_value,
                "target_rule": target_rule,
                "target_value": target_value,
                "master_rule": master_rule,
                "master_value": master_value,
                "template": template,
                "created_by_agent_id": created_by_agent_id,
                "cursor_at_creation": int(cursor_at_creation),
            },
        )

    def emit_route_updated(
        self,
        events_file: Path,
        *,
        route_id: str,
        change: Mapping[str, Any],
        updated_by_agent_id: str | None,
    ) -> None:
        """Per FR-035 / contracts/routes-audit-schema.md §4: operator
        flipped a route's ``enabled`` flag.

        CALLER CONTRACT (FR-009 idempotency): this method MUST NOT be
        called when the state did not actually change. The
        ``routes_dao.update_enabled`` helper returns ``False`` on no-op
        precisely so the service layer can skip this emit.
        """
        self._emit(
            events_file,
            {
                "event_type": _ROUTE_UPDATED,
                "emitted_at": now_iso_ms_utc(),
                "route_id": route_id,
                "change": dict(change),
                "updated_by_agent_id": updated_by_agent_id,
            },
        )

    def emit_route_deleted(
        self,
        events_file: Path,
        *,
        route_id: str,
        deleted_by_agent_id: str | None,
    ) -> None:
        """Per FR-035 / contracts/routes-audit-schema.md §5: operator
        removed a route via ``routes.remove``. Historical
        ``route_matched`` / ``route_skipped`` / ``queue_message_*``
        entries for this route remain intact (orphan reference per
        FR-003)."""
        self._emit(
            events_file,
            {
                "event_type": _ROUTE_DELETED,
                "emitted_at": now_iso_ms_utc(),
                "route_id": route_id,
                "deleted_by_agent_id": deleted_by_agent_id,
            },
        )

    def emit_routing_worker_heartbeat(
        self,
        events_file: Path,
        *,
        interval_seconds: int,
        cycles_since_last_heartbeat: int,
        events_consumed_since_last_heartbeat: int,
        skips_since_last_heartbeat: int,
        degraded: bool,
    ) -> None:
        """Per FR-039a / contracts/routes-audit-schema.md §6: periodic
        liveness signal from the heartbeat thread. Emitted regardless
        of routing-cycle activity; counters reset at every emission."""
        self._emit(
            events_file,
            {
                "event_type": _ROUTING_WORKER_HEARTBEAT,
                "emitted_at": now_iso_ms_utc(),
                "interval_seconds": int(interval_seconds),
                "cycles_since_last_heartbeat": int(cycles_since_last_heartbeat),
                "events_consumed_since_last_heartbeat": int(
                    events_consumed_since_last_heartbeat
                ),
                "skips_since_last_heartbeat": int(skips_since_last_heartbeat),
                "degraded": bool(degraded),
            },
        )

    # ─── Internals ────────────────────────────────────────────────────

    def _emit(self, events_file: Path, payload: Mapping[str, Any]) -> None:
        """Best-effort JSONL append; on failure, buffer for retry.

        Holds ``self._lock`` ONLY around the buffer mutation, NOT
        around the I/O call, so a slow/blocked filesystem cannot stall
        other emit calls (the FEAT-008 writer itself serializes via
        its own internal lock per ``events/writer.py``).
        """
        try:
            append_event(events_file, payload)
            return
        except OSError as exc:
            _log.warning(
                "routes audit append failed; buffering for retry (%s): %s",
                payload.get("event_type", "?"), exc,
            )
            with self._lock:
                self._enqueue_pending_locked(_PendingAudit(events_file, payload))

    def _enqueue_pending_locked(self, entry: _PendingAudit) -> None:
        """Push ``entry`` onto the bounded buffer. MUST be called with
        ``self._lock`` held. Fires the overflow callback if the deque
        was already full (a new entry pushed the oldest out).
        """
        was_full = len(self._pending) >= (self._pending.maxlen or 0)
        self._pending.append(entry)
        if was_full:
            _log.error(
                "routes audit buffer overflow (maxlen=%d); oldest entry dropped",
                self._pending.maxlen or 0,
            )
            if self._on_buffer_drop is not None:
                try:
                    self._on_buffer_drop()
                except Exception:  # pragma: no cover — callback failure is non-fatal
                    _log.exception("routes audit on_buffer_drop callback raised")
