"""FEAT-009 delivery worker (FR-040 — FR-045, plan §"Delivery worker loop").

Single host-side thread that:

1. Runs the FR-040 crash-recovery pass synchronously at boot, BEFORE
   :meth:`DeliveryWorker.start` is called (research §R-012). Recovery
   transitions every interrupted row (``delivery_attempt_started_at``
   set, terminal stamps unset) to ``failed`` with
   ``failure_reason='attempt_interrupted'`` and emits one JSONL audit
   row each.

2. Loops:

   * Drain buffered audits (FR-048 degraded-JSONL retry).
   * Check routing flag — if disabled, sleep and continue (no pickup).
   * Pick next ready row in ``(enqueued_at, message_id)`` order.
   * Pre-paste re-check (FR-025) — if blocked, transition queued→blocked
     and audit. NO stamp, NO tmux call.
   * Stamp ``delivery_attempt_started_at`` (FR-041) BEFORE any tmux call.
   * tmux load-buffer → paste-buffer → send-keys → delete-buffer.
   * Transition ``delivered`` and audit (FR-042).

Failure handling per Group-A walk (2026-05-12):

* **Q1**: any ``TmuxError`` raised AFTER a successful ``load_buffer``
  invokes ``delete_buffer`` best-effort in a ``finally`` block; cleanup
  errors are logged but never raised; the row still transitions to
  ``failed`` with the original ``failure_reason``.
* **Q2**: a ``delete_buffer`` failure AFTER a successful paste+submit
  does NOT downgrade the row — it stays ``delivered``; the orphaned
  buffer is logged and surfaced through ``agenttower status``.
* **Q4**: on :meth:`DeliveryWorker.stop`, the worker signals ``_stop``
  and exits at the next loop check WITHOUT draining the in-flight
  row; the next daemon boot's FR-040 recovery handles cleanup.
* **Q5 / Q7**: every in-transition SQLite call is wrapped in the
  bounded retry helper (T028 DAO). On
  :class:`SqliteLockConflict`, the worker transitions the row to
  ``failed`` with ``failure_reason='sqlite_lock_conflict'``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from typing import Final, Protocol

from agenttower.routing.audit_writer import QueueAuditWriter
from agenttower.routing.dao import MessageQueueDao, QueueRow
from agenttower.routing.errors import SqliteLockConflict
from agenttower.routing.excerpt import render_excerpt
from agenttower.routing.kill_switch import RoutingFlagService
from agenttower.routing.permissions import recheck_target_only
from agenttower.routing.service import ContainerPaneLookup, QueueService
from agenttower.routing.target_resolver import AgentsLookup
from agenttower.routing.timestamps import Clock, SystemClock, now_iso_ms_utc
from agenttower.state.agents import AgentRecord
from agenttower.tmux.adapter import TmuxAdapter, TmuxError


__all__ = [
    "DEFAULT_DELIVERY_WORKER_IDLE_POLL_SECONDS",
    "DeliveryContext",
    "DeliveryContextResolver",
    "DeliveryWorker",
]


DEFAULT_DELIVERY_WORKER_IDLE_POLL_SECONDS: Final[float] = 0.1
"""Empty-queue wakeup granularity (plan §"Defaults locked")."""


@dataclass(frozen=True)
class DeliveryContext:
    """Resolved tmux call arguments for one delivery attempt.

    Returned by :class:`DeliveryContextResolver` and passed to the
    tmux adapter's four delivery methods. Decouples the worker from
    the FEAT-005 / FEAT-006 bench-user resolution and FEAT-004 socket
    path discovery.
    """

    container_id: str
    bench_user: str
    socket_path: str
    pane_id: str


class DeliveryContextResolver(Protocol):
    """Resolve a queue row's ``target_container_id`` + ``target_pane_id``
    into the full tmux call argument tuple.

    Production implementation wraps the FEAT-006 agent registry +
    FEAT-005 bench-user resolution; tests pass a small stub.
    """

    def resolve(self, row: QueueRow) -> DeliveryContext: ...


_log = logging.getLogger(__name__)


class DeliveryWorker:
    """FEAT-009 delivery worker thread (FR-040 — FR-045)."""

    # Closed-set ``failure_reason`` for delete_buffer cleanup-on-success
    # — only logged, never surfaces as a row state change.
    _ORPHAN_BUFFER_LOG_TAG: Final[str] = "tmux_buffer_leaked_after_delivered"

    def __init__(
        self,
        dao: MessageQueueDao,
        routing_flag: RoutingFlagService,
        agents_lookup: AgentsLookup,
        container_panes: ContainerPaneLookup,
        tmux: TmuxAdapter,
        audit_writer: QueueAuditWriter,
        queue_service: QueueService,
        delivery_context_resolver: DeliveryContextResolver,
        *,
        clock: Clock | None = None,
        idle_poll_seconds: float = DEFAULT_DELIVERY_WORKER_IDLE_POLL_SECONDS,
    ) -> None:
        self._dao = dao
        self._routing_flag = routing_flag
        self._agents = agents_lookup
        self._container_panes = container_panes
        self._tmux = tmux
        self._audit = audit_writer
        self._queue_service = queue_service
        self._resolver = delivery_context_resolver
        self._clock: Clock = clock or SystemClock()
        self._idle_poll_seconds = idle_poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ─── Boot recovery (FR-040, research §R-012) ──────────────────────

    def run_recovery_pass(self) -> int:
        """Synchronous FR-040 recovery — MUST run BEFORE :meth:`start`.

        Transitions every in-flight row (``delivery_attempt_started_at``
        set, all terminal stamps unset) to ``failed`` with
        ``failure_reason='attempt_interrupted'``. Emits one JSONL audit
        row per affected row. Returns the count.

        Lock-conflict handling: a :class:`SqliteLockConflict` here is
        fatal — the daemon refuses to serve (spec §Assumptions "SQLite
        lock-conflict retry policy"). Propagates the exception to the
        boot wiring.
        """
        ts = now_iso_ms_utc(self._clock)
        # Snapshot interrupted rows BEFORE updating, so we have their
        # identities for the audit emit. Use the partial index implicitly.
        # (Cheap — the recovery path runs once at boot.)
        cur = self._dao._conn.execute(  # noqa: SLF001 — internal use
            "SELECT message_id, sender_agent_id, sender_label, sender_role, sender_capability, "
            "       target_agent_id, target_label, target_role, target_capability "
            "FROM message_queue "
            "WHERE delivery_attempt_started_at IS NOT NULL "
            "  AND delivered_at IS NULL "
            "  AND failed_at IS NULL "
            "  AND canceled_at IS NULL"
        )
        rows = cur.fetchall()
        if not rows:
            return 0

        # Recover + audit atomically: the DAO's UPDATE and the per-row
        # audit INSERTs commit together. After the tx commits we replay
        # the JSONL writes (best-effort).
        pending_jsonl: list[tuple[int, dict]] = []

        def _audit_recovered(conn: sqlite3.Connection, _count: int) -> None:
            for r in rows:
                eid, payload = self._audit.insert_queue_transition_in_tx(
                    conn,
                    event_type="queue_message_failed",
                    message_id=r[0],
                    from_state="queued",
                    to_state="failed",
                    reason="attempt_interrupted",
                    operator=None,
                    observed_at=ts,
                    sender={
                        "agent_id": r[1], "label": r[2], "role": r[3],
                        "capability": r[4],
                    },
                    target={
                        "agent_id": r[5], "label": r[6], "role": r[7],
                        "capability": r[8],
                    },
                    excerpt="",  # excerpt isn't meaningful for recovery
                )
                pending_jsonl.append((eid, payload))

        count = self._dao.recover_in_flight_rows(ts, audit_callback=_audit_recovered)
        # JSONL append after the atomic tx commits (best-effort).
        for eid, payload in pending_jsonl:
            self._audit.append_jsonl_for_queue_transition(
                eid, payload, watermark_ts=ts,
            )
        return count

    # ─── Thread lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the worker thread. Must be called AFTER
        :meth:`run_recovery_pass` per research §R-012."""
        if self._thread is not None:
            raise RuntimeError("DeliveryWorker.start: already started")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="agenttower-routing-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float | None = None) -> None:
        """Signal the worker to exit (Group-A walk Q4: abort, not drain).

        Returns after the worker thread has exited or ``timeout`` elapsed.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ─── Main loop ────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Worker thread body."""
        while not self._stop.is_set():
            try:
                self._audit.drain_pending()
            except Exception:
                _log.exception("DeliveryWorker: drain_pending raised")
            if not self._routing_flag.is_enabled():
                # Routing disabled → don't pick up new rows. Wait for the
                # next idle-poll wakeup (the stop event is checked at the
                # top of every iteration).
                self._stop.wait(self._idle_poll_seconds)
                continue
            try:
                row = self._dao.pick_next_ready_row()
            except SqliteLockConflict:
                # Lock conflict reading the queue; back off and retry.
                _log.warning("DeliveryWorker: pick_next_ready_row lock conflict")
                self._stop.wait(self._idle_poll_seconds)
                continue
            except Exception:
                _log.exception("DeliveryWorker: pick_next_ready_row raised")
                self._stop.wait(self._idle_poll_seconds)
                continue
            if row is None:
                self._stop.wait(self._idle_poll_seconds)
                continue
            try:
                self._deliver_one(row)
            except Exception:
                # Defensive: never let a per-row exception kill the worker.
                _log.exception(
                    "DeliveryWorker: _deliver_one raised for %s", row.message_id,
                )

    # ─── Per-row delivery ─────────────────────────────────────────────

    def _deliver_one(self, row: QueueRow) -> None:
        """Process one ``queued`` row through the full delivery sequence.

        Group-A walk semantics encoded inline; see module docstring.
        """
        ts_before_recheck = now_iso_ms_utc(self._clock)

        # ─── Pre-paste re-check (FR-025) ──────────────────────────────
        # Read the target's current state from the registry; check
        # container + pane state.
        target = self._agents.get_agent_by_id(row.target_agent_id)
        if target is None:
            # Target deregistered between enqueue and delivery — surface
            # as target_not_active per the spec's edge case ("Queue row
            # references a hard-deleted agent" + R-006).
            self._transition_to_blocked_re_check(
                row, "target_not_active", ts_before_recheck,
            )
            return
        container_active = self._container_panes.is_container_active(
            row.target_container_id
        )
        pane_resolvable = self._container_panes.is_pane_resolvable(
            row.target_container_id, row.target_pane_id,
        )
        try:
            decision = recheck_target_only(
                target,
                routing_enabled=self._routing_flag.is_enabled(),
                target_container_active=container_active,
                target_pane_resolvable=pane_resolvable,
            )
        except SqliteLockConflict:
            self._transition_to_failed(
                row, "sqlite_lock_conflict", ts_before_recheck,
            )
            return
        if not decision.ok:
            assert decision.block_reason is not None
            self._transition_to_blocked_re_check(
                row, decision.block_reason, ts_before_recheck,
            )
            return

        # ─── Resolve delivery context (container/socket/user/pane) ────
        try:
            ctx = self._resolver.resolve(row)
        except Exception as exc:
            # Resolver failure is rare but possible (e.g., the agent
            # is hard-deleted between the re-check and the resolver).
            # Treat as target_pane_missing — re-check semantics.
            _log.warning(
                "DeliveryWorker: resolver failed for %s: %s; "
                "transitioning blocked", row.message_id, exc,
            )
            self._transition_to_blocked_re_check(
                row, "target_pane_missing", ts_before_recheck,
            )
            return

        # ─── FR-041 stamp BEFORE any tmux call ────────────────────────
        ts_stamp = now_iso_ms_utc(self._clock)
        try:
            self._dao.stamp_delivery_attempt_started(row.message_id, ts_stamp)
        except SqliteLockConflict:
            # Couldn't stamp — try again on next cycle (no audit emit;
            # no state change).
            return

        # ─── tmux delivery + cleanup ──────────────────────────────────
        buffer_name = f"agenttower-{row.message_id}"
        body = self._dao.read_envelope_bytes(row.message_id)
        load_succeeded = False
        try:
            self._tmux.load_buffer(
                container_id=ctx.container_id,
                bench_user=ctx.bench_user,
                socket_path=ctx.socket_path,
                buffer_name=buffer_name,
                body=body,
            )
            load_succeeded = True
            self._tmux.paste_buffer(
                container_id=ctx.container_id,
                bench_user=ctx.bench_user,
                socket_path=ctx.socket_path,
                pane_id=ctx.pane_id,
                buffer_name=buffer_name,
            )
            self._tmux.send_keys(
                container_id=ctx.container_id,
                bench_user=ctx.bench_user,
                socket_path=ctx.socket_path,
                pane_id=ctx.pane_id,
                key="Enter",
            )
        except TmuxError as exc:
            # Group-A walk Q1: best-effort delete_buffer cleanup if
            # load_buffer already succeeded.
            if load_succeeded:
                try:
                    self._tmux.delete_buffer(
                        container_id=ctx.container_id,
                        bench_user=ctx.bench_user,
                        socket_path=ctx.socket_path,
                        buffer_name=buffer_name,
                    )
                except TmuxError as cleanup_exc:
                    _log.warning(
                        "DeliveryWorker: delete_buffer cleanup failed "
                        "for %s after %s: %s",
                        row.message_id, exc.failure_reason, cleanup_exc,
                    )
            failure_reason = exc.failure_reason or "tmux_paste_failed"
            self._transition_to_failed(row, failure_reason, now_iso_ms_utc(self._clock))
            return

        # ─── Paste+submit succeeded ───────────────────────────────────
        # Group-A walk Q2: delete_buffer failure here does NOT downgrade
        # the row's terminal state. The body has already reached the
        # target pane.
        try:
            self._tmux.delete_buffer(
                container_id=ctx.container_id,
                bench_user=ctx.bench_user,
                socket_path=ctx.socket_path,
                buffer_name=buffer_name,
            )
        except TmuxError as exc:
            _log.warning(
                "%s: orphaned tmux buffer %s after successful delivery: %s",
                self._ORPHAN_BUFFER_LOG_TAG, buffer_name, exc,
            )

        # ─── FR-042 commit delivered BEFORE picking next row ──────────
        ts_delivered = now_iso_ms_utc(self._clock)
        excerpt_str = render_excerpt(body)
        sender_dict = _row_sender_dict(row)
        target_dict = _row_target_dict(row)

        def _audit_delivered(conn: sqlite3.Connection) -> tuple[int, dict]:
            return self._audit.insert_queue_transition_in_tx(
                conn,
                event_type="queue_message_delivered",
                message_id=row.message_id,
                from_state="queued",
                to_state="delivered",
                reason=None,
                operator=None,
                observed_at=ts_delivered,
                sender=sender_dict,
                target=target_dict,
                excerpt=excerpt_str,
            )
        try:
            audit_event_id, audit_payload = self._dao.transition_queued_to_delivered(
                row.message_id, ts_delivered,
                audit_callback=_audit_delivered,
            )
        except SqliteLockConflict:
            # The paste already reached the slave pane, but the DB
            # commit for ``delivered`` lost every retry of the lock
            # contest. Don't leave the row half-stamped — the recovery
            # pass would mis-classify it as ``failed/attempt_interrupted``
            # at the next boot, hiding what really happened. Instead,
            # mark the row failed with ``failure_reason='sqlite_lock_conflict'``
            # per the module docstring (Group-A walk Q5/Q7). Operators
            # see a terminal row with an actionable failure_reason and
            # can investigate the underlying SQLite contention.
            _log.error(
                "DeliveryWorker: could not commit delivered for %s; "
                "transitioning to failed/sqlite_lock_conflict "
                "(paste already reached pane)",
                row.message_id,
            )
            self._transition_to_failed(
                row, "sqlite_lock_conflict", now_iso_ms_utc(self._clock),
            )
            return
        # JSONL append after atomic SQLite commit; notify waiters.
        self._audit.append_jsonl_for_queue_transition(
            audit_event_id, audit_payload, watermark_ts=ts_delivered,
        )
        self._queue_service.notify_worker_transition(row.message_id, terminal=True)

    # ─── Transition helpers ───────────────────────────────────────────

    def _transition_to_blocked_re_check(
        self, row: QueueRow, block_reason: str, ts: str,
    ) -> None:
        sender_dict = _row_sender_dict(row)
        target_dict = _row_target_dict(row)

        def _audit_blocked(conn: sqlite3.Connection) -> tuple[int, dict]:
            return self._audit.insert_queue_transition_in_tx(
                conn,
                event_type="queue_message_blocked",
                message_id=row.message_id,
                from_state="queued",
                to_state="blocked",
                reason=block_reason,
                operator=None,
                observed_at=ts,
                sender=sender_dict,
                target=target_dict,
                excerpt="",
            )
        try:
            audit_event_id, audit_payload = self._dao.transition_queued_to_blocked_re_check(
                row.message_id, block_reason, ts,
                audit_callback=_audit_blocked,
            )
        except SqliteLockConflict:
            _log.error(
                "DeliveryWorker: could not commit re-check blocked for %s; "
                "will retry on next cycle", row.message_id,
            )
            return
        self._audit.append_jsonl_for_queue_transition(
            audit_event_id, audit_payload, watermark_ts=ts,
        )
        # Wake any send-input waiter — ``blocked`` is end-of-wait per
        # cli-send-input.md so the waiter must return immediately with
        # the block_reason rather than sleeping until timeout.
        self._queue_service.notify_worker_transition(row.message_id, terminal=True)

    def _transition_to_failed(
        self, row: QueueRow, failure_reason: str, ts: str,
    ) -> None:
        sender_dict = _row_sender_dict(row)
        target_dict = _row_target_dict(row)

        def _audit_failed(conn: sqlite3.Connection) -> tuple[int, dict]:
            return self._audit.insert_queue_transition_in_tx(
                conn,
                event_type="queue_message_failed",
                message_id=row.message_id,
                from_state="queued",
                to_state="failed",
                reason=failure_reason,
                operator=None,
                observed_at=ts,
                sender=sender_dict,
                target=target_dict,
                excerpt="",
            )
        try:
            audit_event_id, audit_payload = self._dao.transition_queued_to_failed(
                row.message_id, failure_reason, ts,
                audit_callback=_audit_failed,
            )
        except SqliteLockConflict:
            _log.error(
                "DeliveryWorker: could not commit failed for %s "
                "(failure_reason=%s); deferred to next-boot recovery",
                row.message_id, failure_reason,
            )
            return
        self._audit.append_jsonl_for_queue_transition(
            audit_event_id, audit_payload, watermark_ts=ts,
        )
        # Notify any send-input waiter — failed is terminal.
        self._queue_service.notify_worker_transition(row.message_id, terminal=True)


# ──────────────────────────────────────────────────────────────────────
# Helpers (duplicated from service.py to keep the import direction safe)
# ──────────────────────────────────────────────────────────────────────


def _row_sender_dict(row: QueueRow) -> dict:
    return {
        "agent_id": row.sender_agent_id,
        "label": row.sender_label,
        "role": row.sender_role,
        "capability": row.sender_capability,
    }


def _row_target_dict(row: QueueRow) -> dict:
    return {
        "agent_id": row.target_agent_id,
        "label": row.target_label,
        "role": row.target_role,
        "capability": row.target_capability,
    }
