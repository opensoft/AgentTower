"""FEAT-009 audit writer with FR-046 dual-write.

:class:`QueueAuditWriter` writes every state transition to BOTH:

1. The FEAT-008 ``events`` SQLite table (source of truth per FR-048),
   using the column mapping declared in data-model.md §7.1. The
   :func:`agenttower.events.dao.insert_audit_event` helper NULL-fills
   the FEAT-008-specific columns.

2. The FEAT-008 ``events.jsonl`` stream (best-effort replica with a
   per-row ``jsonl_appended_at`` watermark; FR-029-style retry pattern).

Two callsite patterns:

* **Atomic (preferred)** — :meth:`insert_queue_transition_in_tx` /
  :meth:`insert_routing_toggled_in_tx` perform ONLY the SQLite step,
  inside the caller's already-open ``BEGIN IMMEDIATE`` transaction
  (the caller MUST also hold the shared ``tx_lock``). The DAO row
  INSERT/UPDATE and the audit row INSERT then commit together — if
  the audit INSERT raises, the state transition rolls back atomically.
  After the caller commits, it MUST invoke
  :meth:`append_jsonl_for_queue_transition` (or
  :meth:`append_jsonl_for_routing_toggled`) to perform the JSONL side
  of the dual-write. The :class:`MessageQueueDao` state-mutating
  methods accept an ``audit_callback`` parameter that drives this
  pattern from service/delivery callers.

* **Legacy** — :meth:`append_queue_transition` and
  :meth:`append_routing_toggled` perform the SQLite step in their own
  transaction and then append to JSONL. These remain as backward-
  compatible thin wrappers (some unit tests target them directly),
  but if the SQLite step succeeds and the caller's prior state
  transition is in a SEPARATE committed transaction, a SQLite audit
  failure CANNOT roll back the state transition. Prefer the atomic
  pattern for new callers.

Failure handling per Group-A walk Q6 (2026-05-12):

* SQLite INSERT failure (atomic pattern) → exception propagates;
  caller's surrounding transaction rolls back the state transition.
  SQLite is the source of truth.
* SQLite INSERT failure (legacy pattern) → exception propagates;
  the prior state transition is already committed and cannot be
  rolled back. Operator-visible state diverges from audit until ops
  intervenes; this is the gap the atomic pattern closes.
* JSONL write failure (either pattern) of ANY exception class → buffer
  the record in a bounded deque, capture the exception class for
  forensics, set ``degraded_queue_audit_persistence`` on ``agenttower
  status``. The SQLite row remains intact and the JSONL watermark
  stays NULL until a later drain succeeds.

Drain semantics: :meth:`drain_pending` is called by the delivery
worker at the top of every cycle (plan §"Delivery worker loop"). It
attempts to write each buffered record to JSONL in FIFO order;
successful writes back-fill ``jsonl_appended_at`` via
:func:`agenttower.events.dao.mark_jsonl_appended`. The first failure
in a drain pass stops the drain (preserves FIFO; retries on next cycle).

Per data-model.md §7.1.1 column mapping, ``agent_id`` for
``queue_message_*`` events is set to the target's ``agent_id`` so
``events --target <agent>`` surfaces queue activity to that agent.
Per data-model.md §7.1.2, ``agent_id`` for ``routing_toggled`` events
is the operator identity (``host-operator`` for host-only toggles);
the JSONL row uses the routing-toggle audit schema with
``previous_value`` / ``current_value`` rather than ``from_state`` /
``to_state`` (contracts/queue-audit-schema.md "Routing toggle audit
entry").
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agenttower.events.dao import insert_audit_event, mark_jsonl_appended
from agenttower.events.writer import append_event


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


@dataclass
class PendingJsonl:
    """One buffered audit record waiting for a successful JSONL write.

    Captured fields: the event_id (so we can back-fill
    ``jsonl_appended_at`` after the JSONL write succeeds), the JSONL
    record payload, the exception class of the original failure for
    forensics (visible through ``agenttower status``), and a flag
    tracking whether the JSONL append has already succeeded — the
    SQLite watermark update may still fail after JSONL succeeds, and
    we MUST NOT re-append the same payload on retry (would produce
    duplicate JSONL entries with the same ``event_id``).
    """

    event_id: int
    payload: dict
    failure_exc_class: str
    jsonl_appended: bool = False


class QueueAuditWriter:
    """FR-046 dual-write audit writer (SQLite + JSONL).

    Thread-safety: shares the ``tx_lock`` constructor argument with
    the DAOs that hold the same underlying SQLite connection (the
    daemon's ``worker_conn`` is the canonical case). The shared lock
    guarantees that the dispatcher thread + the delivery worker can't
    race on ``BEGIN IMMEDIATE`` against the same connection.

    When ``tx_lock`` is not supplied (unit tests that hold a private
    connection), the writer creates its own lock — harmless single-
    threaded overhead.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        events_jsonl_path: Path,
        *,
        max_pending: int = DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS,
        tx_lock: threading.Lock | None = None,
    ) -> None:
        self._conn = conn
        self._events_jsonl_path = events_jsonl_path
        self._max_pending = max_pending
        self._pending: deque[PendingJsonl] = deque(maxlen=max_pending)
        self._degraded_exc_class: str | None = None
        # Shared with the FEAT-009 DAOs holding the same connection;
        # see :class:`MessageQueueDao` docstring for the contract.
        self._tx_lock = tx_lock if tx_lock is not None else threading.Lock()
        # Dedicated lock guarding the degraded-buffer state
        # (``_pending`` + ``_degraded_exc_class``). Separate from
        # ``_tx_lock`` (which serializes SQLite transactions) because
        # the JSONL-buffer mutations don't touch SQLite — and we want
        # to avoid holding the SQLite tx lock while iterating /
        # decoding payloads. Reads of ``len(_pending)`` are safe via
        # CPython's GIL but compound operations (``self._pending[0]``
        # after another thread ``popleft``-ed it) are not — guard
        # those under this lock.
        self._buffer_lock = threading.Lock()

    # ─── State for `agenttower status` ────────────────────────────────

    @property
    def degraded(self) -> bool:
        """True iff at least one pending JSONL row hasn't been drained."""
        with self._buffer_lock:
            return len(self._pending) > 0

    @property
    def pending_count(self) -> int:
        with self._buffer_lock:
            return len(self._pending)

    @property
    def last_failure_exc_class(self) -> str | None:
        """Exception class name of the most-recent JSONL append failure.
        ``None`` if no failure has occurred (or after a successful drain
        clears the buffer)."""
        with self._buffer_lock:
            return self._degraded_exc_class

    # ─── Atomic (in-tx) append paths ──────────────────────────────────

    def insert_queue_transition_in_tx(
        self,
        conn: sqlite3.Connection,
        *,
        event_type: str,
        message_id: str,
        from_state: str | None,
        to_state: str,
        reason: str | None,
        operator: str | None,
        observed_at: str,
        sender: dict,
        target: dict,
        excerpt: str,
    ) -> tuple[int, dict]:
        """SQLite-step only: INSERT the audit row inside the caller's
        already-open ``BEGIN IMMEDIATE`` transaction.

        Caller MUST hold the shared ``tx_lock`` and have already issued
        ``BEGIN IMMEDIATE`` on ``conn``. Returns ``(event_id, payload)``
        so the caller can invoke
        :meth:`append_jsonl_for_queue_transition` AFTER its surrounding
        transaction commits. If this method raises (CHECK violation,
        disk I/O), the caller's outer transaction MUST roll back —
        the DAO state transition and the audit row commit or fail
        together (FR-046 atomicity).

        See :meth:`append_queue_transition` for the legacy non-atomic
        wrapper. See the module docstring for the dual-write contract.
        """
        # Defense-in-depth: the closed-set check guards against a
        # mis-named ``event_type`` slipping through and breaking the
        # R-008 disjointness invariant.
        if not event_type.startswith(_QUEUE_MESSAGE_EVENT_PREFIX):
            raise ValueError(
                f"event_type {event_type!r} must start with "
                f"{_QUEUE_MESSAGE_EVENT_PREFIX!r}"
            )
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
        event_id = insert_audit_event(
            conn,
            event_type=event_type,
            agent_id=target["agent_id"],
            observed_at=observed_at,
            excerpt=excerpt,
        )
        return event_id, payload

    def append_jsonl_for_queue_transition(
        self, event_id: int, payload: dict, *, watermark_ts: str,
    ) -> None:
        """JSONL-step only: append ``payload`` to ``events.jsonl`` and,
        on success, back-fill the ``jsonl_appended_at`` watermark.

        Caller invokes this AFTER its surrounding transaction commits
        (the audit row is already on disk via
        :meth:`insert_queue_transition_in_tx`). Failures are non-fatal:
        the payload is buffered in the bounded deque and the writer is
        marked degraded; :meth:`drain_pending` retries later.
        """
        self._append_jsonl_then_watermark(
            event_id, payload, watermark_ts=watermark_ts,
        )

    # ─── Legacy (own-tx) append paths ─────────────────────────────────

    def append_queue_transition(
        self,
        *,
        event_type: str,
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
        """Legacy non-atomic ``queue_message_*`` audit emit.

        Opens its OWN ``BEGIN IMMEDIATE`` for the SQLite step, then
        appends to JSONL. Used by unit tests and any caller that does
        not (or cannot) coordinate a shared transaction.

        Atomicity warning: if the caller's prior state transition is
        in a separate, already-committed transaction, a SQLite audit
        failure here CANNOT roll back the state transition — see the
        module docstring. Prefer :meth:`insert_queue_transition_in_tx`
        from new production callsites.

        ``event_type`` is the FEAT-009 closed-set transition verb
        (``queue_message_enqueued`` / ``_delivered`` / ``_blocked`` /
        ``_failed`` / ``_canceled`` / ``_approved`` / ``_delayed``).
        ``to_state`` is the resulting QUEUE STATE per
        ``contracts/queue-audit-schema.md`` (``queued|blocked|delivered
        |canceled|failed``). The two are intentionally decoupled:
        ``queue_message_approved`` ends in ``to_state='queued'``
        because the row is now eligible for the worker again;
        ``queue_message_delayed`` ends in ``to_state='blocked'`` with
        ``reason='operator_delayed'``.
        """
        # Step 1: SQLite insert in its own transaction (legacy path).
        with self._tx_lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                event_id, payload = self.insert_queue_transition_in_tx(
                    self._conn,
                    event_type=event_type,
                    message_id=message_id,
                    from_state=from_state,
                    to_state=to_state,
                    reason=reason,
                    operator=operator,
                    observed_at=observed_at,
                    sender=sender,
                    target=target,
                    excerpt=excerpt,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        # Step 2 + 3: JSONL append (best-effort).
        self.append_jsonl_for_queue_transition(
            event_id, payload, watermark_ts=observed_at,
        )
        return event_id

    def insert_routing_toggled_in_tx(
        self,
        conn: sqlite3.Connection,
        *,
        previous_value: str,
        current_value: str,
        operator: str,
        observed_at: str,
    ) -> tuple[int, dict]:
        """SQLite-step only for ``routing_toggled``. Caller MUST hold
        ``tx_lock`` and be in ``BEGIN IMMEDIATE`` on ``conn``. Returns
        ``(event_id, payload)``; caller invokes
        :meth:`append_jsonl_for_routing_toggled` after commit.
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
        event_id = insert_audit_event(
            conn,
            event_type=_ROUTING_TOGGLED_EVENT_TYPE,
            agent_id=operator,
            observed_at=observed_at,
            excerpt=excerpt,
        )
        return event_id, payload

    def append_jsonl_for_routing_toggled(
        self, event_id: int, payload: dict, *, watermark_ts: str,
    ) -> None:
        """JSONL-step only for ``routing_toggled``. Caller invokes this
        AFTER the surrounding transaction commits."""
        self._append_jsonl_then_watermark(
            event_id, payload, watermark_ts=watermark_ts,
        )

    def append_routing_toggled(
        self,
        *,
        previous_value: str,
        current_value: str,
        operator: str,
        observed_at: str,
    ) -> int:
        """Legacy non-atomic ``routing_toggled`` audit emit (FR-046 +
        Contracts §queue-audit-schema "Routing toggle audit entry").

        See :meth:`append_queue_transition` for the atomicity warning.
        Prefer :meth:`insert_routing_toggled_in_tx` from new callers
        that can coordinate a shared transaction.

        Per data-model.md §7.1.2: ``events.agent_id`` is the operator
        identity (``host-operator`` for host-only toggles); the
        ``excerpt`` is a fixed human summary string
        (``"routing <current> (was <previous>)"``) — short, contains
        no body content, satisfies FEAT-008's NOT NULL excerpt
        constraint.

        Idempotent ``changed=False`` toggles MUST NOT call this method
        (contracts/socket-routing.md "Success response"); the caller
        (kill switch dispatcher in :mod:`socket_api/methods.py`)
        enforces the gate.
        """
        # Step 1: SQLite insert in its own transaction (legacy path).
        with self._tx_lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                event_id, payload = self.insert_routing_toggled_in_tx(
                    self._conn,
                    previous_value=previous_value,
                    current_value=current_value,
                    operator=operator,
                    observed_at=observed_at,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        # Step 2 + 3: JSONL append.
        self.append_jsonl_for_routing_toggled(
            event_id, payload, watermark_ts=observed_at,
        )
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

        Concurrency: ``_pending`` and ``_degraded_exc_class`` are
        mutated from the delivery worker (drain) and the socket
        dispatcher (append-on-failure), so every read / mutation in
        this method holds ``_buffer_lock``. The SQLite watermark
        update is done OUTSIDE the buffer lock (it acquires the
        ``_tx_lock`` for the BEGIN IMMEDIATE block); deadlock avoided
        by never taking both locks in the opposite order.
        """
        drained = 0
        while True:
            with self._buffer_lock:
                if not self._pending:
                    break
                head = self._pending[0]
            # The JSONL write and the SQLite watermark update are
            # two independent failure points. We track which step
            # succeeded so a retry can skip the JSONL append if it
            # already landed (otherwise an intermittent watermark
            # failure would cause duplicate JSONL entries with the
            # same ``event_id``).
            if not head.jsonl_appended:
                try:
                    append_event(self._events_jsonl_path, head.payload)
                except Exception as exc:
                    with self._buffer_lock:
                        self._degraded_exc_class = type(exc).__name__
                        pending_now = len(self._pending)
                    _log.warning(
                        "drain_pending: JSONL append failed (%s); "
                        "%d records still pending",
                        type(exc).__name__, pending_now,
                    )
                    break
                # Mark the head as having reached JSONL; if the
                # watermark update fails below, the next drain pass
                # will skip the append step for this record.
                head.jsonl_appended = True
            # JSONL succeeded (now or earlier); back-fill the
            # watermark. Serialize with the rest of the FEAT-009 write
            # paths on this shared connection.
            try:
                with self._tx_lock:
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
                # will retry the watermark only (jsonl_appended=True
                # prevents a duplicate JSONL line).
                _log.error(
                    "drain_pending: mark_jsonl_appended failed for "
                    "event_id=%d: %s (jsonl already on disk; will retry "
                    "watermark on next drain)",
                    head.event_id, exc,
                )
                break
            with self._buffer_lock:
                # Defensive: confirm the head is still the same record
                # before popleft (another thread shouldn't be popping
                # from this deque — drain is single-caller — but
                # guarding makes the invariant explicit).
                if self._pending and self._pending[0] is head:
                    self._pending.popleft()
            drained += 1
        with self._buffer_lock:
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
            # is NOT rolled back. The buffer mutation runs under
            # ``_buffer_lock`` because :meth:`drain_pending` (running on
            # the delivery worker thread) may be reading the same deque.
            exc_name = type(exc).__name__
            with self._buffer_lock:
                self._degraded_exc_class = exc_name
                dropped_event_id: int | None = None
                if len(self._pending) == self._max_pending:
                    # Dropping the OLDEST buffered record to make room.
                    dropped_event_id = self._pending[0].event_id
                self._pending.append(PendingJsonl(
                    event_id=event_id,
                    payload=payload,
                    failure_exc_class=exc_name,
                ))
                pending_count = len(self._pending)
            if dropped_event_id is not None:
                _log.warning(
                    "audit buffer at cap (%d); dropping oldest event_id=%d",
                    self._max_pending, dropped_event_id,
                )
            _log.warning(
                "audit JSONL append failed (%s) for event_id=%d; buffered (pending=%d)",
                exc_name, event_id, pending_count,
            )
            return

        # JSONL succeeded; back-fill the watermark.
        with self._tx_lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                mark_jsonl_appended(self._conn, event_id, watermark_ts)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
