"""FEAT-009 audit writer with FR-046 dual-write.

:class:`QueueAuditWriter` writes every state transition to BOTH:

1. The FEAT-008 ``events`` SQLite table (source of truth per FR-048),
   using the column mapping declared in data-model.md §7.1. The
   :func:`agenttower.events.dao.insert_audit_event` helper NULL-fills
   the FEAT-008-specific columns.

2. The FEAT-008 ``events.jsonl`` stream (best-effort replica with a
   per-row ``jsonl_appended_at`` watermark; FR-029-style retry pattern).

Failure handling per Group-A walk Q6 (2026-05-12):

* SQLite INSERT failure → exception propagates; the caller (queue
  service / delivery worker) rolls back the state transition. The
  SQLite write is the source of truth.
* JSONL write failure of ANY exception class (not just ``OSError``) →
  buffer the record in a bounded deque, capture the exception class
  for forensics, set ``degraded_queue_audit_persistence`` on
  ``agenttower status``. The SQLite row remains intact and the JSONL
  watermark stays NULL until a later drain succeeds. The state
  transition is NOT rolled back.

Drain semantics: :meth:`drain_pending` is called by the delivery
worker at the top of every cycle (plan §"Delivery worker loop"). It
attempts to write each buffered record to JSONL in FIFO order;
successful writes back-fill ``jsonl_appended_at`` via
:func:`agenttower.events.dao.mark_jsonl_appended`. The first failure
in a drain pass stops the drain (preserves FIFO; retries on next cycle).

Two append methods:

* :meth:`append_queue_transition` — for the seven ``queue_message_*``
  event types. Per data-model.md §7.1.1 column mapping, ``agent_id``
  is set to the target's ``agent_id`` so ``events --target <agent>``
  surfaces queue activity to that agent.
* :meth:`append_routing_toggled` — for the ``routing_toggled`` event
  type. Per data-model.md §7.1.2, ``agent_id`` is the operator
  identity (``host-operator`` for host-only toggles); the JSONL row
  uses the routing-toggle audit schema with ``previous_value`` /
  ``current_value`` rather than ``from_state`` / ``to_state``
  (contracts/queue-audit-schema.md "Routing toggle audit entry").
"""

from __future__ import annotations

import logging
import sqlite3
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agenttower.events.dao import insert_audit_event, mark_jsonl_appended
from agenttower.events.writer import append_event
from agenttower.routing.dao import _conn_tx_lock


__all__ = [
    "DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS",
    "PendingJsonl",
    "QueueAuditWriter",
]


DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS: Final[int] = 1024
"""Default cap on the in-memory deque of pending-JSONL records
(plan.md §"Defaults locked", Group-A walk Q6). Sized at ≤ 1 minute of
sustained 10 events/s peak per the Scale/Scope budget; older entries
drop with a warning."""


_QUEUE_MESSAGE_EVENT_PREFIX = "queue_message_"
_ROUTING_TOGGLED_EVENT_TYPE = "routing_toggled"

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingJsonl:
    """One buffered audit record waiting for a successful JSONL write.

    Captured fields: the event_id (so we can back-fill
    ``jsonl_appended_at`` after the JSONL write succeeds), the JSONL
    record payload, and the exception class of the original failure
    for forensics (visible through ``agenttower status``).
    """

    event_id: int
    payload: dict
    failure_exc_class: str


class QueueAuditWriter:
    """FR-046 dual-write audit writer (SQLite + JSONL).

    Thread-safety: each mutating method acquires the per-connection
    transaction-serializer lock (``_conn_tx_lock``) before issuing
    ``BEGIN IMMEDIATE`` so the dispatcher thread and the delivery worker
    — both sharing the daemon's ``worker_conn`` — cannot race on the
    same connection. In MVP there is only one delivery worker
    (Clarifications session 2 Q5); the lock is cheap and forward-safe
    if parallel workers are introduced later.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        events_jsonl_path: Path,
        *,
        max_pending: int = DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS,
    ) -> None:
        self._conn = conn
        self._events_jsonl_path = events_jsonl_path
        self._max_pending = max_pending
        self._pending: deque[PendingJsonl] = deque(maxlen=max_pending)
        self._degraded_exc_class: str | None = None

    # ─── State for `agenttower status` ────────────────────────────────

    @property
    def degraded(self) -> bool:
        """True iff at least one pending JSONL row hasn't been drained."""
        return len(self._pending) > 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def last_failure_exc_class(self) -> str | None:
        """Exception class name of the most-recent JSONL append failure.
        ``None`` if no failure has occurred (or after a successful drain
        clears the buffer)."""
        return self._degraded_exc_class

    # ─── Append paths ─────────────────────────────────────────────────

    def append_queue_transition(
        self,
        *,
        message_id: str,
        from_state: str | None,
        to_state: str,
        reason: str | None,
        operator: str | None,
        observed_at: str,
        sender: dict,
        target: dict,
        excerpt: str,
    ) -> int:
        """Emit one ``queue_message_*`` audit record (FR-046).

        Returns the SQLite ``event_id``. The dual-write order is:
        1. INSERT into ``events`` (source of truth; propagates exceptions).
        2. Append to ``events.jsonl`` (best-effort; failures buffered).
        3. If JSONL succeeded, ``mark_jsonl_appended`` updates the watermark.

        Per data-model.md §7.1.1, ``events.agent_id`` is set to the
        target's ``agent_id`` so a subsequent ``events --target <agent>``
        surfaces this row.
        """
        event_type = _QUEUE_MESSAGE_EVENT_PREFIX + to_state
        payload = {
            "schema_version": 1,
            "event_type": event_type,
            "message_id": message_id,
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            "operator": operator,
            "observed_at": observed_at,
            "sender": sender,
            "target": target,
            "excerpt": excerpt,
        }
        # Step 1: SQLite insert (must succeed; propagates exceptions).
        # Serialize with the DAO via the per-connection lock
        # (Slice 16 — multi-threaded daemon would otherwise race BEGIN
        # IMMEDIATE against the worker/dispatcher DAOs sharing this conn).
        with _conn_tx_lock(self._conn):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                event_id = insert_audit_event(
                    self._conn,
                    event_type=event_type,
                    agent_id=target["agent_id"],
                    observed_at=observed_at,
                    excerpt=excerpt,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        # Step 2 + 3: JSONL append (best-effort).
        self._append_jsonl_then_watermark(event_id, payload, watermark_ts=observed_at)
        return event_id

    def append_routing_toggled(
        self,
        *,
        previous_value: str,
        current_value: str,
        operator: str,
        observed_at: str,
    ) -> int:
        """Emit one ``routing_toggled`` audit record (FR-046 + Contracts
        §queue-audit-schema "Routing toggle audit entry").

        Per data-model.md §7.1.2: ``events.agent_id`` is the operator
        identity (``host-operator`` for host-only toggles); the
        ``excerpt`` is a fixed human summary string
        (``"routing <current> (was <previous>)"``) — short, contains
        no body content, satisfies FEAT-008's NOT NULL excerpt constraint.

        Idempotent ``changed=False`` toggles MUST NOT call this method
        (contracts/socket-routing.md "Success response"); the caller
        (kill switch dispatcher in :mod:`socket_api/methods.py`)
        enforces the gate.
        """
        excerpt = f"routing {current_value} (was {previous_value})"
        payload = {
            "schema_version": 1,
            "event_type": _ROUTING_TOGGLED_EVENT_TYPE,
            "previous_value": previous_value,
            "current_value": current_value,
            "observed_at": observed_at,
            "operator": operator,
        }
        # Step 1: SQLite insert.
        with _conn_tx_lock(self._conn):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                event_id = insert_audit_event(
                    self._conn,
                    event_type=_ROUTING_TOGGLED_EVENT_TYPE,
                    agent_id=operator,
                    observed_at=observed_at,
                    excerpt=excerpt,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        # Step 2 + 3: JSONL append.
        self._append_jsonl_then_watermark(event_id, payload, watermark_ts=observed_at)
        return event_id

    # ─── Drain / degraded-buffer helpers ──────────────────────────────

    def drain_pending(self) -> int:
        """Attempt to write each buffered JSONL record in FIFO order.

        Called by the delivery worker at the top of every cycle
        (plan §"Delivery worker loop"). Returns the number of records
        successfully drained. Stops at the first failure (FIFO order
        preserved; the failed record stays at the head of the deque).

        On success, back-fills ``jsonl_appended_at`` for each drained
        event_id and clears ``_degraded_exc_class`` if the deque
        becomes empty.
        """
        drained = 0
        while self._pending:
            head = self._pending[0]
            try:
                append_event(self._events_jsonl_path, head.payload)
            except Exception as exc:
                self._degraded_exc_class = type(exc).__name__
                _log.warning(
                    "drain_pending: JSONL append failed (%s); %d records still pending",
                    type(exc).__name__, len(self._pending),
                )
                break
            # JSONL succeeded; back-fill the watermark and drop the head.
            # Serialize with the rest of the FEAT-009 write paths on this
            # shared connection (the dispatcher thread + worker thread
            # both write through here — without the lock the same
            # multi-thread BEGIN-within-transaction race we fixed in
            # ``_append_jsonl_then_watermark`` would reappear here).
            try:
                with _conn_tx_lock(self._conn):
                    self._conn.execute("BEGIN IMMEDIATE")
                    try:
                        mark_jsonl_appended(
                            self._conn, head.event_id,
                            head.payload["observed_at"],
                        )
                        self._conn.execute("COMMIT")
                    except Exception:
                        self._conn.execute("ROLLBACK")
                        raise
            except Exception as exc:
                # Catastrophic — the SQLite write that owns the watermark
                # failed during drain. Log + bail; next drain attempt
                # will retry.
                _log.error(
                    "drain_pending: mark_jsonl_appended failed for event_id=%d: %s",
                    head.event_id, exc,
                )
                break
            self._pending.popleft()
            drained += 1
        if not self._pending:
            self._degraded_exc_class = None
        return drained

    # ─── Internal: JSONL append-then-watermark with degraded fallback ─

    def _append_jsonl_then_watermark(
        self,
        event_id: int,
        payload: dict,
        *,
        watermark_ts: str,
    ) -> None:
        try:
            append_event(self._events_jsonl_path, payload)
        except Exception as exc:
            # Group-A walk Q6: catch ANY exception (not just OSError).
            # The SQLite row is already committed; we buffer the JSONL
            # record and surface the degraded state. State transition
            # is NOT rolled back.
            self._degraded_exc_class = type(exc).__name__
            if len(self._pending) == self._max_pending:
                # Dropping the OLDEST buffered record to make room.
                dropped = self._pending[0]
                _log.warning(
                    "audit buffer at cap (%d); dropping oldest event_id=%d",
                    self._max_pending, dropped.event_id,
                )
            self._pending.append(PendingJsonl(
                event_id=event_id,
                payload=payload,
                failure_exc_class=type(exc).__name__,
            ))
            _log.warning(
                "audit JSONL append failed (%s) for event_id=%d; buffered (pending=%d)",
                type(exc).__name__, event_id, len(self._pending),
            )
            return

        # JSONL succeeded; back-fill the watermark.
        with _conn_tx_lock(self._conn):
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                mark_jsonl_appended(self._conn, event_id, watermark_ts)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
