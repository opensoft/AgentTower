"""FEAT-009 ``message_queue`` and ``daemon_state`` DAO.

Implements all CRUD + state-transition methods for the FEAT-009 queue
schema declared in ``specs/009-safe-prompt-queue/data-model.md`` §2.

Every state-mutating method runs under ``BEGIN IMMEDIATE`` and is
wrapped in the bounded SQLite-lock retry helper from Group-A walk Q5:
3 attempts at 10 ms / 50 ms / 250 ms exponential backoff. If the
retry budget is exhausted the helper raises :class:`SqliteLockConflict`
which the delivery worker maps to ``failure_reason='sqlite_lock_conflict'``.

This module is the sole production-side writer for ``message_queue``
and ``daemon_state`` rows; only the queue service, delivery worker,
and kill-switch service call into it.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Final

from agenttower.routing.errors import (
    APPROVAL_NOT_APPLICABLE,
    DELAY_NOT_APPLICABLE,
    DELIVERY_IN_PROGRESS,
    MESSAGE_ID_NOT_FOUND,
    TERMINAL_STATE_CANNOT_CHANGE,
    QueueServiceError,
    SqliteLockConflict,
)


__all__ = [
    "DaemonStateDao",
    "MessageQueueDao",
    "QueueRow",
    "QueueListFilter",
    "with_lock_retry",
]


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Group-A walk Q5: bounded retry on SQLite ``BEGIN IMMEDIATE`` lock conflict.
_LOCK_RETRY_DELAYS_S: Final[tuple[float, ...]] = (0.010, 0.050, 0.250)
"""Three retry attempts at 10 / 50 / 250 ms exponential backoff. Total ≤ 310 ms."""


# Closed-set states + terminal subset (data-model §3).
_TERMINAL_STATES: Final[frozenset[str]] = frozenset({"delivered", "failed", "canceled"})


# ──────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueueRow:
    """One ``message_queue`` row, as read by the DAO and consumed by the
    queue service / delivery worker.

    Mirrors the SQLite schema (data-model.md §2). Identity fields are
    frozen snapshots from enqueue time (data-model.md §5).
    """

    message_id: str
    state: str
    block_reason: str | None
    failure_reason: str | None
    sender_agent_id: str
    sender_label: str
    sender_role: str
    sender_capability: str | None
    target_agent_id: str
    target_label: str
    target_role: str
    target_capability: str | None
    target_container_id: str
    target_pane_id: str
    envelope_body_sha256: str
    envelope_size_bytes: int
    enqueued_at: str
    delivery_attempt_started_at: str | None
    delivered_at: str | None
    failed_at: str | None
    canceled_at: str | None
    last_updated_at: str
    operator_action: str | None
    operator_action_at: str | None
    operator_action_by: str | None


@dataclass(frozen=True)
class QueueListFilter:
    """Filters for :meth:`MessageQueueDao.list_rows` (FR-031)."""

    state: str | None = None
    target_agent_id: str | None = None
    sender_agent_id: str | None = None
    since: str | None = None  # canonical ISO 8601 ms UTC (FR-012b)
    limit: int | None = 100  # default 100, max 1000


# ──────────────────────────────────────────────────────────────────────
# SQLite lock-conflict retry helper (Group-A walk Q5)
# ──────────────────────────────────────────────────────────────────────


def with_lock_retry(
    operation,
    *,
    retries: tuple[float, ...] | None = None,
    lock: threading.Lock | None = None,
):
    """Run ``operation()`` with bounded retry on SQLite lock conflict.

    On ``sqlite3.OperationalError`` whose message contains "database is
    locked" or "database is busy", sleep for the next delay in
    ``retries`` and try again. After the last delay is exhausted,
    raise :class:`SqliteLockConflict`.

    Other ``OperationalError`` types (e.g., disk I/O errors, integrity
    violations) propagate immediately — they're not retryable.

    Group-A walk Q5: ``len(retries) + 1`` total attempts, with each
    ``retries[i]`` being the sleep between attempt ``i`` and attempt
    ``i+1``. Default ``_LOCK_RETRY_DELAYS_S = (0.010, 0.050, 0.250)``
    gives 4 attempts separated by 3 sleeps; total worst-case wait
    ≤ 310 ms (comfortably inside SC-001's 3 s budget).

    When ``lock`` is supplied, the entire retry loop runs inside it
    so multi-threaded callers (the dispatcher thread + the delivery
    worker, sharing the daemon's ``worker_conn``) can't race on
    ``BEGIN IMMEDIATE``. The lock is created and OWNED by the calling
    DAO / audit writer (one lock per shared connection), not looked
    up via a process-global dict — that earlier design leaked memory
    in test suites that create many short-lived connections, and could
    mis-associate locks when Python reused object ids after GC.
    """
    delays = retries if retries is not None else _LOCK_RETRY_DELAYS_S

    def _attempt_chain() -> object:
        last_exc: sqlite3.OperationalError | None = None
        for attempt_index in range(len(delays) + 1):
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                # SQLite surfaces lock contention as either "database is
                # locked" (SQLITE_LOCKED) or "database is busy"
                # (SQLITE_BUSY) depending on the contention path and
                # platform / build options. Retry on both; let every
                # other ``OperationalError`` propagate immediately.
                msg = str(exc).lower()
                if "database is locked" not in msg and "database is busy" not in msg:
                    raise
                last_exc = exc
                if attempt_index < len(delays):
                    time.sleep(delays[attempt_index])
        raise SqliteLockConflict(
            f"BEGIN IMMEDIATE failed after {len(delays) + 1} attempts: {last_exc}"
        )

    if lock is None:
        return _attempt_chain()
    with lock:
        return _attempt_chain()


# ──────────────────────────────────────────────────────────────────────
# Row decoder
# ──────────────────────────────────────────────────────────────────────


_QUEUE_COLUMNS = (
    "message_id, state, block_reason, failure_reason, "
    "sender_agent_id, sender_label, sender_role, sender_capability, "
    "target_agent_id, target_label, target_role, target_capability, "
    "target_container_id, target_pane_id, "
    "envelope_body_sha256, envelope_size_bytes, "
    "enqueued_at, delivery_attempt_started_at, "
    "delivered_at, failed_at, canceled_at, "
    "last_updated_at, "
    "operator_action, operator_action_at, operator_action_by"
)


def _row_to_queue_row(row: tuple) -> QueueRow:
    return QueueRow(
        message_id=row[0],
        state=row[1],
        block_reason=row[2],
        failure_reason=row[3],
        sender_agent_id=row[4],
        sender_label=row[5],
        sender_role=row[6],
        sender_capability=row[7],
        target_agent_id=row[8],
        target_label=row[9],
        target_role=row[10],
        target_capability=row[11],
        target_container_id=row[12],
        target_pane_id=row[13],
        envelope_body_sha256=row[14],
        envelope_size_bytes=int(row[15]),
        enqueued_at=row[16],
        delivery_attempt_started_at=row[17],
        delivered_at=row[18],
        failed_at=row[19],
        canceled_at=row[20],
        last_updated_at=row[21],
        operator_action=row[22],
        operator_action_at=row[23],
        operator_action_by=row[24],
    )


# ──────────────────────────────────────────────────────────────────────
# MessageQueueDao
# ──────────────────────────────────────────────────────────────────────


class MessageQueueDao:
    """SQLite DAO for the ``message_queue`` table.

    Every state-mutating method wraps the ``BEGIN IMMEDIATE`` block in
    :func:`with_lock_retry`. Read-only methods do NOT need the retry
    helper (WAL allows concurrent readers).

    Preconditions are enforced at the SQL layer via the from-state
    predicate in each ``UPDATE`` (rows count = 0 → raise the matching
    closed-set error). This prevents TOCTOU races between a service-
    layer check and the transition write.

    Concurrency: the optional ``tx_lock`` constructor argument is a
    :class:`threading.Lock` that serializes every ``BEGIN IMMEDIATE``
    block AND every read against ``self._conn``. When multiple DAOs
    + the audit writer share a single connection (the daemon's
    ``worker_conn`` is the prototypical case), they MUST share the
    SAME lock — otherwise two threads can race on ``BEGIN IMMEDIATE``
    and SQLite surfaces ``cannot start a transaction within a
    transaction``. When ``tx_lock`` is not supplied (e.g., unit tests
    that hold a private connection), the DAO creates its own lock —
    that lock is harmless overhead for the single-threaded test path.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        tx_lock: threading.Lock | None = None,
    ) -> None:
        self._conn = conn
        # Owned per-DAO when no shared lock is passed in. The daemon
        # boot path passes one shared lock to the DAOs + audit writer
        # so every transactional write serializes against the same
        # lock.
        self._tx_lock = tx_lock if tx_lock is not None else threading.Lock()

    # ─── Insert paths (FR-019 / FR-020) ───────────────────────────────

    def insert_queued(
        self,
        *,
        message_id: str,
        sender: dict,
        target: dict,
        envelope_body: bytes,
        envelope_body_sha256: str,
        envelope_size_bytes: int,
        enqueued_at: str,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Insert a new row in state ``queued`` (FR-019 happy path).

        ``audit_callback`` (if supplied) runs inside the same
        ``BEGIN IMMEDIATE`` transaction, AFTER the INSERT and BEFORE
        the COMMIT — driving the FR-046 dual-write atomicity contract
        (see :mod:`agenttower.routing.audit_writer`). The callback's
        return value is returned to the caller; if it raises, the
        INSERT is rolled back.
        """

        def _op() -> Any:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # Plain string (not f-string): every value is bound via
                # parameter markers below. Some scanners flag any
                # ``f"""..."""`` near an INSERT as potential injection
                # even when there are no interpolations — using a
                # regular triple-quoted string removes the false
                # positive without changing behavior.
                self._conn.execute(
                    """
                    INSERT INTO message_queue (
                        message_id, state,
                        sender_agent_id, sender_label, sender_role, sender_capability,
                        target_agent_id, target_label, target_role, target_capability,
                        target_container_id, target_pane_id,
                        envelope_body, envelope_body_sha256, envelope_size_bytes,
                        enqueued_at, last_updated_at
                    ) VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        sender["agent_id"], sender["label"], sender["role"],
                        sender.get("capability"),
                        target["agent_id"], target["label"], target["role"],
                        target.get("capability"),
                        target["container_id"], target["pane_id"],
                        envelope_body, envelope_body_sha256, envelope_size_bytes,
                        enqueued_at, enqueued_at,
                    ),
                )
                result = audit_callback(self._conn) if audit_callback else None
                self._conn.execute("COMMIT")
                return result
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)

    def insert_blocked(
        self,
        *,
        message_id: str,
        sender: dict,
        target: dict,
        envelope_body: bytes,
        envelope_body_sha256: str,
        envelope_size_bytes: int,
        enqueued_at: str,
        block_reason: str,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Insert a new row in state ``blocked`` (FR-020) with the
        FR-019 first-failing-step ``block_reason``.

        ``audit_callback`` runs in the same transaction as the INSERT
        (see :meth:`insert_queued` for the FR-046 atomicity contract).
        """

        def _op() -> Any:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # Plain string (not f-string): see insert_queued above
                # for the rationale — every value is parameter-bound.
                self._conn.execute(
                    """
                    INSERT INTO message_queue (
                        message_id, state, block_reason,
                        sender_agent_id, sender_label, sender_role, sender_capability,
                        target_agent_id, target_label, target_role, target_capability,
                        target_container_id, target_pane_id,
                        envelope_body, envelope_body_sha256, envelope_size_bytes,
                        enqueued_at, last_updated_at
                    ) VALUES (?, 'blocked', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id, block_reason,
                        sender["agent_id"], sender["label"], sender["role"],
                        sender.get("capability"),
                        target["agent_id"], target["label"], target["role"],
                        target.get("capability"),
                        target["container_id"], target["pane_id"],
                        envelope_body, envelope_body_sha256, envelope_size_bytes,
                        enqueued_at, enqueued_at,
                    ),
                )
                result = audit_callback(self._conn) if audit_callback else None
                self._conn.execute("COMMIT")
                return result
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)

    # ─── Worker-side transitions (FR-041 / FR-042 / FR-043) ───────────

    def pick_next_ready_row(self) -> QueueRow | None:
        """Return the oldest ``queued`` row that the live worker may claim
        (FR-031 ordering: ``enqueued_at`` ASC, ``message_id`` ASC
        tie-break), or ``None`` if no row is ready.

        Read-only — but still acquires the per-connection transaction
        lock because the same sqlite3.Connection is shared with the
        socket dispatcher thread, and a concurrent ``BEGIN IMMEDIATE``
        write must not race a read on the same connection
        (``check_same_thread=False`` removes the safety net but the
        connection itself isn't thread-safe).

        Half-stamped rows (``delivery_attempt_started_at IS NOT NULL``
        with the terminal stamps still unset) are EXCLUDED here. Those
        rows are owned by the recovery pass at the next daemon boot
        (FR-040 / data-model §3.1 / Research §R-012); picking them up
        again from the live worker would crash-loop on the next
        ``stamp_delivery_attempt_started`` call (which rejects a row
        whose stamp is already set). The recovery pass transitions such
        rows to ``failed`` with ``failure_reason='attempt_interrupted'``
        on boot.
        """
        with self._tx_lock:
            cur = self._conn.execute(
                f"SELECT {_QUEUE_COLUMNS} FROM message_queue "
                "WHERE state = 'queued' "
                "AND delivery_attempt_started_at IS NULL "
                "ORDER BY enqueued_at ASC, message_id ASC LIMIT 1"
            )
            row = cur.fetchone()
        return _row_to_queue_row(row) if row else None

    def stamp_delivery_attempt_started(self, message_id: str, ts: str) -> None:
        """FR-041: stamp ``delivery_attempt_started_at`` BEFORE any tmux call.

        Only valid when the row is in state ``queued`` and the stamp is
        not already set. Raises :class:`QueueServiceError` with
        ``DELIVERY_IN_PROGRESS`` if the stamp was already committed.
        """

        def _op() -> None:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    "UPDATE message_queue "
                    "SET delivery_attempt_started_at = ?, last_updated_at = ? "
                    "WHERE message_id = ? AND state = 'queued' "
                    "AND delivery_attempt_started_at IS NULL",
                    (ts, ts, message_id),
                )
                if cur.rowcount == 0:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        DELIVERY_IN_PROGRESS,
                        f"message {message_id} not in queued+unstamped state",
                    )
                self._conn.execute("COMMIT")
            except QueueServiceError:
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        with_lock_retry(_op, lock=self._tx_lock)

    def transition_queued_to_delivered(
        self,
        message_id: str,
        ts: str,
        *,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """FR-042: commit ``delivered`` (terminal) after a successful paste+submit.

        ``audit_callback`` runs in the same transaction (FR-046 atomicity).
        """
        return self._terminal_transition_from_in_flight(
            message_id, new_state="delivered", stamp_column="delivered_at",
            ts=ts, reason_column=None, reason_value=None,
            audit_callback=audit_callback,
        )

    def transition_queued_to_failed(
        self,
        message_id: str,
        failure_reason: str,
        ts: str,
        *,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """FR-043: transition to ``failed`` with a closed-set ``failure_reason``.

        ``audit_callback`` runs in the same transaction (FR-046 atomicity).
        """
        return self._terminal_transition_from_in_flight(
            message_id, new_state="failed", stamp_column="failed_at",
            ts=ts, reason_column="failure_reason", reason_value=failure_reason,
            audit_callback=audit_callback,
        )

    def _terminal_transition_from_in_flight(
        self,
        message_id: str,
        *,
        new_state: str,
        stamp_column: str,
        ts: str,
        reason_column: str | None,
        reason_value: str | None,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Shared body for ``queued`` (in-flight) → terminal transitions.

        Precondition: row is in state ``queued``, ``delivery_attempt_started_at``
        is set, and no terminal stamp is set. Violations raise
        :class:`QueueServiceError` with ``MESSAGE_ID_NOT_FOUND``.
        """
        set_clauses = [
            "state = ?",
            f"{stamp_column} = ?",
            "last_updated_at = ?",
        ]
        params: list = [new_state, ts, ts]
        if reason_column is not None:
            set_clauses.append(f"{reason_column} = ?")
            params.append(reason_value)
        params.append(message_id)
        update_sql = (
            f"UPDATE message_queue SET {', '.join(set_clauses)} "
            f"WHERE message_id = ? AND state = 'queued' "
            f"AND delivery_attempt_started_at IS NOT NULL "
            f"AND delivered_at IS NULL AND failed_at IS NULL "
            f"AND canceled_at IS NULL"
        )

        def _op() -> Any:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(update_sql, params)
                if cur.rowcount == 0:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        MESSAGE_ID_NOT_FOUND,
                        f"message {message_id} not in in-flight state",
                    )
                result = audit_callback(self._conn) if audit_callback else None
                self._conn.execute("COMMIT")
                return result
            except QueueServiceError:
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)

    def transition_queued_to_blocked_re_check(
        self,
        message_id: str,
        block_reason: str,
        ts: str,
        *,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """FR-025: pre-paste re-check failure transitions ``queued → blocked``.

        Called BEFORE ``stamp_delivery_attempt_started`` — the row's
        ``delivery_attempt_started_at`` is still NULL.

        ``audit_callback`` runs in the same transaction (FR-046 atomicity).
        """

        def _op() -> Any:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    "UPDATE message_queue "
                    "SET state = 'blocked', block_reason = ?, last_updated_at = ? "
                    "WHERE message_id = ? AND state = 'queued' "
                    "AND delivery_attempt_started_at IS NULL",
                    (block_reason, ts, message_id),
                )
                if cur.rowcount == 0:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        MESSAGE_ID_NOT_FOUND,
                        f"message {message_id} not in queued+unstamped state",
                    )
                result = audit_callback(self._conn) if audit_callback else None
                self._conn.execute("COMMIT")
                return result
            except QueueServiceError:
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)

    # ─── Operator-driven transitions (FR-031 — FR-036) ────────────────

    def transition_blocked_to_queued_approve(
        self,
        message_id: str,
        operator: str,
        ts: str,
        *,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Operator ``approve``: ``blocked → queued`` (FR-033).

        Caller (service layer) is responsible for the FR-033 closed-set
        check (block_reason must be operator-resolvable); this DAO
        method only enforces the from-state transition.

        ``audit_callback`` runs in the same transaction (FR-046 atomicity).
        """
        return self._operator_transition(
            message_id, operator=operator, ts=ts,
            from_state="blocked", to_state="queued",
            operator_action="approved",
            block_reason_new=None, stamp_column=None,
            audit_callback=audit_callback,
        )

    def transition_queued_to_blocked_delay(
        self,
        message_id: str,
        operator: str,
        ts: str,
        *,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Operator ``delay``: ``queued → blocked`` with
        ``block_reason='operator_delayed'`` (FR-034).

        ``audit_callback`` runs in the same transaction (FR-046 atomicity).
        """
        return self._operator_transition(
            message_id, operator=operator, ts=ts,
            from_state="queued", to_state="blocked",
            operator_action="delayed",
            block_reason_new="operator_delayed",
            stamp_column=None,
            audit_callback=audit_callback,
        )

    def transition_to_canceled(
        self,
        message_id: str,
        operator: str,
        ts: str,
        *,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Operator ``cancel``: ``queued | blocked → canceled`` (FR-035).

        ``audit_callback`` runs in the same transaction (FR-046 atomicity).
        """
        # Operator cancel works from either non-terminal state, so we
        # need a slightly different precondition (state IN ('queued', 'blocked')).
        def _op() -> Any:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # First check the current state to give the operator a
                # precise error if the row is terminal or in-flight.
                cur = self._conn.execute(
                    "SELECT state, delivery_attempt_started_at, delivered_at, "
                    "failed_at, canceled_at "
                    "FROM message_queue WHERE message_id = ?",
                    (message_id,),
                )
                row = cur.fetchone()
                if row is None:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        MESSAGE_ID_NOT_FOUND, f"unknown message_id {message_id!r}",
                    )
                state, attempt_started, delivered_at, failed_at, canceled_at = row
                if state in _TERMINAL_STATES:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        TERMINAL_STATE_CANNOT_CHANGE,
                        f"row in terminal state {state!r}",
                    )
                # FR-036: an in-flight row (attempt_started set, no terminal stamp)
                # is unsafe to cancel — race with the worker.
                if (
                    attempt_started is not None
                    and delivered_at is None
                    and failed_at is None
                    and canceled_at is None
                ):
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        DELIVERY_IN_PROGRESS,
                        f"message {message_id} is mid-delivery",
                    )
                # Clear block_reason on transition out of 'blocked' to
                # satisfy the reason-state coherence CHECK constraint
                # (block_reason IS NULL OR state = 'blocked').
                cur = self._conn.execute(
                    "UPDATE message_queue "
                    "SET state = 'canceled', "
                    "    canceled_at = ?, "
                    "    last_updated_at = ?, "
                    "    block_reason = NULL, "
                    "    operator_action = 'canceled', "
                    "    operator_action_at = ?, "
                    "    operator_action_by = ? "
                    "WHERE message_id = ? AND state IN ('queued', 'blocked')",
                    (ts, ts, ts, operator, message_id),
                )
                if cur.rowcount == 0:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        MESSAGE_ID_NOT_FOUND,
                        f"message {message_id} state changed mid-cancel",
                    )
                result = audit_callback(self._conn) if audit_callback else None
                self._conn.execute("COMMIT")
                return result
            except QueueServiceError:
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)

    def _operator_transition(
        self,
        message_id: str,
        *,
        operator: str,
        ts: str,
        from_state: str,
        to_state: str,
        operator_action: str,
        block_reason_new: str | None,
        stamp_column: str | None,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Shared body for approve / delay (FR-033 / FR-034)."""

        def _op() -> Any:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                # Check row exists first → precise error.
                cur = self._conn.execute(
                    "SELECT state, delivery_attempt_started_at, delivered_at, "
                    "failed_at, canceled_at "
                    "FROM message_queue WHERE message_id = ?",
                    (message_id,),
                )
                row = cur.fetchone()
                if row is None:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        MESSAGE_ID_NOT_FOUND, f"unknown message_id {message_id!r}",
                    )
                state, attempt_started, delivered_at, failed_at, canceled_at = row
                if state in _TERMINAL_STATES:
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        TERMINAL_STATE_CANNOT_CHANGE,
                        f"row in terminal state {state!r}",
                    )
                if (
                    attempt_started is not None
                    and delivered_at is None
                    and failed_at is None
                    and canceled_at is None
                ):
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(
                        DELIVERY_IN_PROGRESS,
                        f"message {message_id} is mid-delivery",
                    )
                if state != from_state:
                    # The operator's intended action isn't applicable in
                    # the row's current state. The service-layer
                    # caller distinguishes approve / delay-specific
                    # mappings; pick a reasonable default here.
                    if operator_action == "approved":
                        code = APPROVAL_NOT_APPLICABLE
                        msg = f"approve requires state='blocked'; got {state!r}"
                    elif operator_action == "delayed":
                        code = DELAY_NOT_APPLICABLE
                        msg = f"delay requires state='queued'; got {state!r}"
                    else:
                        code = TERMINAL_STATE_CANNOT_CHANGE
                        msg = f"transition not applicable from {state!r}"
                    self._conn.execute("ROLLBACK")
                    raise QueueServiceError(code, msg)
                # Issue the UPDATE.
                set_clauses = [
                    "state = ?",
                    "last_updated_at = ?",
                    "operator_action = ?",
                    "operator_action_at = ?",
                    "operator_action_by = ?",
                ]
                params: list = [to_state, ts, operator_action, ts, operator]
                # Clear block_reason when leaving 'blocked' → 'queued'.
                if from_state == "blocked" and to_state == "queued":
                    set_clauses.append("block_reason = NULL")
                if block_reason_new is not None:
                    set_clauses.append("block_reason = ?")
                    params.append(block_reason_new)
                params.append(message_id)
                params.append(from_state)
                cur = self._conn.execute(
                    "UPDATE message_queue SET "
                    + ", ".join(set_clauses)
                    + " WHERE message_id = ? AND state = ?",
                    params,
                )
                if cur.rowcount == 0:
                    # The row's state changed between our SELECT and
                    # the UPDATE (another writer raced us). Without
                    # this check the COMMIT would silently land a
                    # zero-row update and the service layer would
                    # assume success. Surface the same closed-set
                    # code the equivalent service-layer pre-check
                    # would have raised.
                    self._conn.execute("ROLLBACK")
                    if operator_action == "approved":
                        code = APPROVAL_NOT_APPLICABLE
                        msg = (
                            f"approve race-aborted: row state changed during "
                            f"transition (expected {from_state!r})"
                        )
                    elif operator_action == "delayed":
                        code = DELAY_NOT_APPLICABLE
                        msg = (
                            f"delay race-aborted: row state changed during "
                            f"transition (expected {from_state!r})"
                        )
                    else:
                        code = TERMINAL_STATE_CANNOT_CHANGE
                        msg = (
                            f"operator transition race-aborted: row state "
                            f"changed during transition (expected {from_state!r})"
                        )
                    raise QueueServiceError(code, msg)
                result = audit_callback(self._conn) if audit_callback else None
                self._conn.execute("COMMIT")
                return result
            except QueueServiceError:
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)

    # ─── FR-040 recovery ──────────────────────────────────────────────

    def snapshot_in_flight_identities(self) -> list[tuple]:
        """Return ``(message_id, sender_agent_id, sender_label, sender_role,
        sender_capability, target_agent_id, target_label, target_role,
        target_capability)`` for every row currently in flight
        (``delivery_attempt_started_at`` set, no terminal stamps).

        Used by the delivery worker's :meth:`run_recovery_pass` at boot
        to emit one audit row per row about to be recovered to
        ``failed/attempt_interrupted``. Acquires ``self._tx_lock`` so
        the snapshot doesn't race the worker's writes — callers should
        prefer this over reaching into the private ``_conn``.
        """
        with self._tx_lock:
            cur = self._conn.execute(
                "SELECT message_id, sender_agent_id, sender_label, sender_role, "
                "       sender_capability, "
                "       target_agent_id, target_label, target_role, target_capability "
                "FROM message_queue "
                "WHERE delivery_attempt_started_at IS NOT NULL "
                "  AND delivered_at IS NULL "
                "  AND failed_at IS NULL "
                "  AND canceled_at IS NULL"
            )
            return list(cur.fetchall())

    def recover_in_flight_rows(
        self,
        ts: str,
        *,
        audit_callback: Callable[[sqlite3.Connection, int], Any] | None = None,
    ) -> int:
        """FR-040: transition every row whose ``delivery_attempt_started_at``
        is set but whose terminal stamps are all unset → ``failed`` with
        ``failure_reason='attempt_interrupted'``.

        Returns the number of rows affected. Called synchronously at
        boot BEFORE the delivery worker thread starts (research §R-012,
        T048 boot wiring).

        ``audit_callback`` (if supplied) runs in the same transaction
        as the UPDATE; it receives ``(conn, recovered_count)`` and lets
        the caller emit per-row audit INSERTs atomically with the
        recovery UPDATE (FR-046 atomicity for FR-040 recovery).
        """

        def _op() -> int:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    "UPDATE message_queue "
                    "SET state = 'failed', "
                    "    failure_reason = 'attempt_interrupted', "
                    "    failed_at = ?, "
                    "    last_updated_at = ? "
                    "WHERE delivery_attempt_started_at IS NOT NULL "
                    "  AND delivered_at IS NULL "
                    "  AND failed_at IS NULL "
                    "  AND canceled_at IS NULL",
                    (ts, ts),
                )
                count = cur.rowcount
                if audit_callback is not None:
                    audit_callback(self._conn, count)
                self._conn.execute("COMMIT")
                return count
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)

    # ─── Reads (serialized with writes on the shared connection) ─────
    #
    # Every read below acquires the per-connection transaction lock.
    # The same sqlite3.Connection is shared across the worker thread +
    # the socket dispatcher threads (ThreadingUnixStreamServer); the
    # ``check_same_thread=False`` flag we pass at construction removes
    # the safety check but does NOT make the underlying connection
    # thread-safe. Serializing reads under the same lock as the
    # ``BEGIN IMMEDIATE`` writes prevents concurrent cursor access
    # corruption.

    def read_envelope_bytes(self, message_id: str) -> bytes:
        """Return the raw ``envelope_body`` BLOB for a row.

        Used by the delivery worker (FR-012a: read from persisted state,
        not transient memory). Raises :class:`QueueServiceError` with
        ``MESSAGE_ID_NOT_FOUND`` if the row doesn't exist.
        """
        with self._tx_lock:
            cur = self._conn.execute(
                "SELECT envelope_body FROM message_queue WHERE message_id = ?",
                (message_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise QueueServiceError(
                MESSAGE_ID_NOT_FOUND, f"unknown message_id {message_id!r}",
            )
        body = row[0]
        # SQLite returns BLOB as bytes; defensive cast for clarity.
        return bytes(body)

    def get_row_by_id(self, message_id: str) -> QueueRow | None:
        with self._tx_lock:
            cur = self._conn.execute(
                f"SELECT {_QUEUE_COLUMNS} FROM message_queue WHERE message_id = ?",
                (message_id,),
            )
            row = cur.fetchone()
        return _row_to_queue_row(row) if row else None

    def list_rows(self, filters: QueueListFilter) -> list[QueueRow]:
        """List rows matching ``filters`` (FR-031).

        Filters are AND-combined. Ordering is ``enqueued_at`` ASC,
        ``message_id`` ASC. Default limit is 100; max is 1000 (per
        contracts/cli-queue.md).
        """
        clauses: list[str] = []
        params: list = []
        if filters.state is not None:
            clauses.append("state = ?")
            params.append(filters.state)
        if filters.target_agent_id is not None:
            clauses.append("target_agent_id = ?")
            params.append(filters.target_agent_id)
        if filters.sender_agent_id is not None:
            clauses.append("sender_agent_id = ?")
            params.append(filters.sender_agent_id)
        if filters.since is not None:
            clauses.append("enqueued_at >= ?")
            params.append(filters.since)
        where = " AND ".join(clauses) if clauses else "1=1"
        limit = filters.limit if filters.limit is not None else 100
        limit = max(1, min(limit, 1000))
        params.append(limit)
        with self._tx_lock:
            cur = self._conn.execute(
                f"SELECT {_QUEUE_COLUMNS} FROM message_queue "
                f"WHERE {where} "
                "ORDER BY enqueued_at ASC, message_id ASC LIMIT ?",
                params,
            )
            return [_row_to_queue_row(r) for r in cur.fetchall()]


# ──────────────────────────────────────────────────────────────────────
# DaemonStateDao (routing flag — FR-026)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RoutingFlag:
    """One row of ``daemon_state`` for the routing kill switch."""

    value: str  # 'enabled' | 'disabled'
    last_updated_at: str
    last_updated_by: str


class DaemonStateDao:
    """SQLite DAO for the ``daemon_state`` key/value table.

    MVP supports exactly one key (``routing_enabled``); the table's
    CHECK constraint enforces this.
    """

    _ROUTING_KEY: Final[str] = "routing_enabled"

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        tx_lock: threading.Lock | None = None,
    ) -> None:
        self._conn = conn
        # Same lock contract as :class:`MessageQueueDao` — the daemon
        # boot path passes a single shared lock to all three FEAT-009
        # services that hold the worker_conn.
        self._tx_lock = tx_lock if tx_lock is not None else threading.Lock()

    def read_routing_flag(self) -> RoutingFlag:
        """Read the current routing flag row. Raises ``RuntimeError``
        if the seed row is missing (the migration guarantees it exists).

        Acquires the per-connection transaction lock for the same
        reason :meth:`MessageQueueDao.get_row_by_id` does — the
        connection is shared across threads.
        """
        with self._tx_lock:
            cur = self._conn.execute(
                "SELECT value, last_updated_at, last_updated_by "
                "FROM daemon_state WHERE key = ?",
                (self._ROUTING_KEY,),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                "daemon_state routing_enabled seed row missing — "
                "migration v7 was not applied"
            )
        return RoutingFlag(value=row[0], last_updated_at=row[1], last_updated_by=row[2])

    def write_routing_flag(
        self,
        value: str,
        *,
        ts: str,
        updated_by: str,
        audit_callback: Callable[[sqlite3.Connection], Any] | None = None,
    ) -> Any:
        """Set the routing flag to ``value`` (must be ``enabled`` or
        ``disabled``; CHECK constraint enforces this).

        Wrapped in the lock-retry helper. The caller (kill switch
        service) computes whether ``changed=True`` BEFORE calling — the
        DAO doesn't compute idempotency.

        ``audit_callback`` (if supplied) runs inside the same
        ``BEGIN IMMEDIATE`` transaction, AFTER the UPDATE and BEFORE
        the COMMIT — the FR-046 ``routing_toggled`` audit row commits
        atomically with the flag write.
        """
        if value not in ("enabled", "disabled"):
            raise ValueError(f"routing flag value must be 'enabled' or 'disabled', got {value!r}")

        def _op() -> Any:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "UPDATE daemon_state "
                    "SET value = ?, last_updated_at = ?, last_updated_by = ? "
                    "WHERE key = ?",
                    (value, ts, updated_by, self._ROUTING_KEY),
                )
                result = audit_callback(self._conn) if audit_callback else None
                self._conn.execute("COMMIT")
                return result
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return with_lock_retry(_op, lock=self._tx_lock)
