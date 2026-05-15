"""FEAT-009 QueueService façade.

Orchestrates the ``send-input`` and operator-action paths consumed by
``socket_api/methods.py``. Each method routes:

  envelope render → permission gate → DAO insert/transition → audit emit

The façade is intentionally thin — every step is in a dedicated module
(envelope, permissions, target_resolver, dao, audit_writer, kill_switch).
This module composes them and is the single integration point for the
socket dispatch layer.

Caller-context responsibilities (NOT in this module):

* Host-vs-bench-container origin gating (Clarifications session 2 Q2
  for routing toggle; Q3 for ``send-input``). Enforced at the socket
  dispatch boundary (T049).
* Pane → agent resolution for the sender / operator. The caller passes
  resolved :class:`AgentRecord` instances; this module trusts them.
* Operator-pane liveness check (Group-A walk Q8). The dispatch layer
  raises ``OperatorPaneInactive`` BEFORE invoking the service for
  bench-container callers whose pane resolved to an inactive agent.

Wait semantics for :meth:`send_input` (FR-009):

* ``wait=True`` (default): block until the row reaches a terminal
  state OR ``wait_timeout`` elapses. Returns the row's current state.
* ``wait=False`` (``--no-wait``): return immediately after enqueue.

The wait is implemented with a per-``message_id`` :class:`Condition`
registered before the row is inserted (plan §"In-memory state"). The
delivery worker notifies the condition after every terminal transition.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from agenttower.routing.audit_writer import QueueAuditWriter
from agenttower.routing.dao import (
    MessageQueueDao,
    QueueListFilter,
    QueueRow,
)
from agenttower.routing.envelope import (
    DEFAULT_ENVELOPE_BODY_MAX_BYTES,
    EnvelopeIdentity,
    serialize_and_check_size,
)
from agenttower.routing.errors import (
    APPROVAL_NOT_APPLICABLE,
    KILL_SWITCH_OFF,
    QueueServiceError,
)
from agenttower.routing.excerpt import render_excerpt
from agenttower.routing.kill_switch import RoutingFlagService
from agenttower.routing.permissions import (
    Decision,
    evaluate_enqueue_permissions,
)
from agenttower.routing.target_resolver import AgentsLookup, resolve_target
from agenttower.routing.timestamps import Clock, SystemClock, now_iso_ms_utc
from agenttower.state.agents import AgentRecord


__all__ = [
    "DEFAULT_SEND_INPUT_WAIT_SECONDS",
    "QueueService",
    "SendInputResult",
]


DEFAULT_SEND_INPUT_WAIT_SECONDS: Final[float] = 10.0
"""FR-009 default ``send-input`` wait timeout. Overridable via the
``[routing]`` section of ``config.toml`` (plan §"Defaults locked")."""


@dataclass(frozen=True)
class SendInputResult:
    """Wrapped :class:`QueueRow` plus a flag indicating whether the
    caller waited for a terminal state.

    ``waited_to_terminal`` is False under ``--no-wait`` OR when
    ``wait_timeout`` elapsed before the row reached terminal. The CLI
    translates the latter to closed-set ``delivery_wait_timeout``.
    """

    row: QueueRow
    waited_to_terminal: bool


# ──────────────────────────────────────────────────────────────────────
# ContainerPaneLookup Protocol — minimal surface for FR-019 step 5/6
# ──────────────────────────────────────────────────────────────────────


class ContainerPaneLookup:
    """Minimal surface the QueueService needs from FEAT-003 (container
    service) and FEAT-004 (pane discovery).

    Real implementations wrap the existing FEAT-003 / FEAT-004 services;
    tests pass a small stub.
    """

    def is_container_active(self, container_id: str) -> bool:
        """Return True iff ``container_id`` is in the daemon's active
        container set (FEAT-003 ``containers/list``)."""
        raise NotImplementedError

    def is_pane_resolvable(self, container_id: str, pane_id: str) -> bool:
        """Return True iff the pane is still discoverable by FEAT-004
        in ``container_id`` (FR-019 step 6, FR-025 re-check)."""
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────
# QueueService
# ──────────────────────────────────────────────────────────────────────


_log = logging.getLogger(__name__)


class QueueService:
    """FEAT-009 service façade consumed by ``socket_api/methods.py``."""

    def __init__(
        self,
        dao: MessageQueueDao,
        routing_flag: RoutingFlagService,
        agents_lookup: AgentsLookup,
        container_pane_lookup: ContainerPaneLookup,
        audit_writer: QueueAuditWriter,
        *,
        clock: Clock | None = None,
        envelope_max_bytes: int = DEFAULT_ENVELOPE_BODY_MAX_BYTES,
        default_wait_seconds: float = DEFAULT_SEND_INPUT_WAIT_SECONDS,
    ) -> None:
        self._dao = dao
        self._routing_flag = routing_flag
        self._agents = agents_lookup
        self._container_panes = container_pane_lookup
        self._audit = audit_writer
        self._clock: Clock = clock or SystemClock()
        self._envelope_max_bytes = envelope_max_bytes
        self._default_wait_seconds = default_wait_seconds
        # Per-message wait registry: message_id → Condition + state-holder.
        self._wait_lock = threading.Lock()
        self._wait_observers: dict[str, _WaitObserver] = {}

    # ─── send-input (FR-006 — FR-011, FR-019/020, FR-046 audit) ───────

    def send_input(
        self,
        *,
        sender: AgentRecord,
        target_input: str,
        body_bytes: bytes,
        wait: bool = True,
        wait_timeout: float | None = None,
    ) -> SendInputResult:
        """Enqueue one ``send-input`` row and (optionally) wait for terminal.

        Args:
            sender: The resolved sender agent (the socket dispatch layer
                enforces ``sender_not_in_pane`` for host-origin callers
                BEFORE invoking the service).
            target_input: Verbatim ``--target`` argument; resolved via
                :func:`routing.target_resolver.resolve_target`.
            body_bytes: Raw envelope body (decoded from the socket's
                base64 transport at the dispatch layer).
            wait: ``True`` (default) to block until terminal or timeout;
                ``False`` (``--no-wait``) to return immediately.
            wait_timeout: Override the default 10 s timeout (FR-009).

        Returns:
            :class:`SendInputResult` wrapping the row and a flag for
            whether the caller waited to terminal.
        """
        # Step 1: resolve target (raises TargetResolveError on miss /
        # ambiguity).
        resolved_target = resolve_target(target_input, self._agents)

        # Step 2: assemble envelope identities + render + size check.
        sender_identity = EnvelopeIdentity(
            agent_id=sender.agent_id, label=sender.label,
            role=sender.role, capability=sender.capability,
        )
        target_identity = EnvelopeIdentity(
            agent_id=resolved_target.agent_id, label=resolved_target.label,
            role=resolved_target.role, capability=resolved_target.capability,
        )
        message_id = str(uuid.uuid4())
        # Two distinct payloads (data-model.md §5):
        # * ``envelope_body`` BLOB column = the BODY bytes only (what the
        #   delivery worker pastes byte-for-byte into the target pane
        #   per FR-005). Headers from FR-001 are NOT included in this
        #   column.
        # * ``envelope_size_bytes`` INTEGER column = the SERIALIZED
        #   envelope size (headers + body) — used for FR-004 cap
        #   accounting + observability via ``agenttower queue --json``.
        # * ``envelope_body_sha256`` TEXT column = SHA-256 of the BODY
        #   bytes (matches the BLOB column, not the rendered size).
        rendered = serialize_and_check_size(
            message_id, sender_identity, target_identity, body_bytes,
            max_bytes=self._envelope_max_bytes,
        )
        envelope_size_bytes = len(rendered)  # full envelope (FR-004 cap)
        envelope_body_sha256 = _sha256_hex(body_bytes)  # body only

        # Step 3: permission gate (FR-019 / FR-020 six-step precedence).
        routing_enabled = self._routing_flag.is_enabled()
        container_active = self._container_panes.is_container_active(
            resolved_target.container_id
        )
        pane_resolvable = self._container_panes.is_pane_resolvable(
            resolved_target.container_id, resolved_target.tmux_pane_id
        )
        decision = evaluate_enqueue_permissions(
            sender, resolved_target,
            routing_enabled=routing_enabled,
            target_container_active=container_active,
            target_pane_resolvable=pane_resolvable,
        )
        ts = now_iso_ms_utc(self._clock)

        # Step 4: DAO insert (queued or blocked) — atomic with the
        # FR-046 audit row INSERT via the ``audit_callback`` plumbing
        # (see audit_writer.py module docstring). The DAO opens
        # BEGIN IMMEDIATE, INSERTs the message_queue row, runs the
        # callback (which INSERTs the events row), then COMMITs. If
        # the audit INSERT raises, the queue row INSERT rolls back —
        # state transition and audit row commit/fail together.
        sender_dict = _identity_to_dict(sender_identity)
        target_dict = _identity_to_dict(target_identity, container=resolved_target)
        excerpt_str = render_excerpt(body_bytes)
        if decision.ok:
            def _audit_enqueue_queued(conn: sqlite3.Connection) -> tuple[int, dict]:
                # Audit queue_message_enqueued: event_type is the
                # transition verb; to_state is the resulting queue
                # state (``queued``, permission gate passed).
                return self._audit.insert_queue_transition_in_tx(
                    conn,
                    event_type="queue_message_enqueued",
                    message_id=message_id,
                    from_state=None,
                    to_state="queued",
                    reason=None,
                    operator=None,
                    observed_at=ts,
                    sender=sender_dict,
                    target=target_dict,
                    excerpt=excerpt_str,
                )
            audit_event_id, audit_payload = self._dao.insert_queued(
                message_id=message_id,
                sender=sender_dict,
                target=target_dict,
                envelope_body=body_bytes,
                envelope_body_sha256=envelope_body_sha256,
                envelope_size_bytes=envelope_size_bytes,
                enqueued_at=ts,
                audit_callback=_audit_enqueue_queued,
            )
        else:
            assert decision.block_reason is not None
            block_reason_val = decision.block_reason
            def _audit_enqueue_blocked(conn: sqlite3.Connection) -> tuple[int, dict]:
                # Per the audit schema, an at-enqueue blocked landing
                # is still a queue_message_enqueued event (it's the
                # first event for this message_id). The
                # ``to_state='blocked'`` + ``reason=<block_reason>``
                # distinguishes it from a ``queue_message_blocked``
                # mid-flight transition (which the worker emits when
                # the pre-paste re-check fails).
                return self._audit.insert_queue_transition_in_tx(
                    conn,
                    event_type="queue_message_enqueued",
                    message_id=message_id,
                    from_state=None,
                    to_state="blocked",
                    reason=block_reason_val,
                    operator=None,
                    observed_at=ts,
                    sender=sender_dict,
                    target=target_dict,
                    excerpt=excerpt_str,
                )
            audit_event_id, audit_payload = self._dao.insert_blocked(
                message_id=message_id,
                sender=sender_dict,
                target=target_dict,
                envelope_body=body_bytes,
                envelope_body_sha256=envelope_body_sha256,
                envelope_size_bytes=envelope_size_bytes,
                enqueued_at=ts,
                block_reason=decision.block_reason,
                audit_callback=_audit_enqueue_blocked,
            )

        # Step 4b: JSONL append (best-effort; runs AFTER the atomic
        # SQLite commit). Failures buffer + mark degraded; the worker
        # drains on its next cycle.
        self._audit.append_jsonl_for_queue_transition(
            audit_event_id, audit_payload, watermark_ts=ts,
        )

        # Step 5: read back the row (so the response carries the canonical
        # SQLite state, not the in-memory assumption).
        row = self._dao.get_row_by_id(message_id)
        assert row is not None, "row vanished after insert — invariant broken"

        # Step 6: wait if requested AND the row is non-end-of-wait.
        # ``blocked`` is an end-of-wait state for send-input — a
        # blocked-at-enqueue outcome (e.g. kill_switch_off,
        # target_not_active) returns immediately with the block_reason
        # rather than sleeping until the wait timeout elapses
        # (cli-send-input.md). ``waited_to_terminal`` still tracks only
        # the strictly-terminal states.
        if not wait or row.state in _END_OF_WAIT_STATES:
            return SendInputResult(row=row, waited_to_terminal=row.state in _TERMINAL_STATES)
        timeout = wait_timeout if wait_timeout is not None else self._default_wait_seconds
        terminal = self._wait_for_terminal(message_id, timeout)
        # Re-read; the worker may have transitioned the row.
        row = self._dao.get_row_by_id(message_id)
        assert row is not None
        return SendInputResult(row=row, waited_to_terminal=terminal)

    # ─── Operator actions (FR-031 — FR-036) ────────────────────────────

    def approve(self, message_id: str, *, operator: str) -> QueueRow:
        """Operator ``approve``: ``blocked → queued`` (FR-033).

        Checks the block_reason for operator-resolvability. The
        operator-pane liveness check (Group-A walk Q8) is done at the
        dispatch layer BEFORE this method is called.
        """
        row = self._dao.get_row_by_id(message_id)
        if row is None:
            raise QueueServiceError(
                "message_id_not_found", f"unknown message_id {message_id!r}",
            )
        # FR-033: check if block_reason is operator-resolvable.
        if row.state == "blocked":
            self._check_approve_applicable(row)
        # If state != 'blocked', the DAO will raise approval_not_applicable.
        ts = now_iso_ms_utc(self._clock)
        # Capture identity + block_reason from the pre-transition row.
        # After the transition commits, block_reason is cleared on the
        # row (FR-033), so we must read it BEFORE the DAO call. The
        # audit_callback runs inside the DAO's transaction, so it sees
        # these values via closure.
        sender_dict = _row_sender_dict(row)
        target_dict = _row_target_dict(row)
        prior_block_reason = row.block_reason

        def _audit_approve(conn: sqlite3.Connection) -> tuple[int, dict]:
            # event_type is the action verb; to_state is the RESULTING
            # queue state (queued, since approve takes blocked →
            # queued). reason carries the resolved block_reason per the
            # audit contract (e.g. operator_delayed / target_not_active).
            return self._audit.insert_queue_transition_in_tx(
                conn,
                event_type="queue_message_approved",
                message_id=message_id,
                from_state="blocked",
                to_state="queued",
                reason=prior_block_reason,
                operator=operator,
                observed_at=ts,
                sender=sender_dict,
                target=target_dict,
                excerpt="",  # operator action has no body context
            )
        audit_event_id, audit_payload = self._dao.transition_blocked_to_queued_approve(
            message_id, operator=operator, ts=ts,
            audit_callback=_audit_approve,
        )
        self._audit.append_jsonl_for_queue_transition(
            audit_event_id, audit_payload, watermark_ts=ts,
        )
        row = self._dao.get_row_by_id(message_id)
        assert row is not None
        self._notify_terminal(message_id)
        return row

    def delay(self, message_id: str, *, operator: str) -> QueueRow:
        """Operator ``delay``: ``queued → blocked operator_delayed`` (FR-034)."""
        # Capture identity from the pre-transition row so the
        # audit_callback (running inside the DAO transaction) doesn't
        # have to re-read the row after the UPDATE.
        pre_row = self._dao.get_row_by_id(message_id)
        if pre_row is None:
            raise QueueServiceError(
                "message_id_not_found", f"unknown message_id {message_id!r}",
            )
        sender_dict = _row_sender_dict(pre_row)
        target_dict = _row_target_dict(pre_row)
        ts = now_iso_ms_utc(self._clock)

        def _audit_delay(conn: sqlite3.Connection) -> tuple[int, dict]:
            # event_type is the action verb; to_state is the RESULTING
            # queue state (blocked, since delay takes queued → blocked).
            return self._audit.insert_queue_transition_in_tx(
                conn,
                event_type="queue_message_delayed",
                message_id=message_id,
                from_state="queued",
                to_state="blocked",
                reason="operator_delayed",
                operator=operator,
                observed_at=ts,
                sender=sender_dict,
                target=target_dict,
                excerpt="",
            )
        audit_event_id, audit_payload = self._dao.transition_queued_to_blocked_delay(
            message_id, operator=operator, ts=ts,
            audit_callback=_audit_delay,
        )
        self._audit.append_jsonl_for_queue_transition(
            audit_event_id, audit_payload, watermark_ts=ts,
        )
        # Wake any send-input waiter — ``blocked`` is end-of-wait per
        # ``_END_OF_WAIT_STATES`` / cli-send-input.md, so an operator
        # delay must return the sender immediately with the row's new
        # block_reason rather than letting it sleep until timeout.
        # (Same pattern as ``cancel()`` and the delivery worker's
        # queued→blocked re-check transition.)
        #
        # This is the ONLY ``_notify_terminal`` invocation on the
        # ``delay`` path. The DAO and audit_callback paths above are
        # pure storage writes — neither dispatches to waiters. A
        # second notify after the post-transition ``get_row_by_id``
        # would be redundant; we don't add one.
        self._notify_terminal(message_id)
        row = self._dao.get_row_by_id(message_id)
        assert row is not None
        self._notify_terminal(message_id)
        return row

    def cancel(self, message_id: str, *, operator: str) -> QueueRow:
        """Operator ``cancel``: ``queued | blocked → canceled`` (FR-035)."""
        # Capture the pre-transition state for the audit row; once the
        # DAO commits the transition the row's `state` becomes
        # ``canceled`` and we lose the queued-vs-blocked distinction.
        pre_row = self._dao.get_row_by_id(message_id)
        pre_state = pre_row.state if pre_row is not None else None
        sender_dict = _row_sender_dict(pre_row) if pre_row is not None else {}
        target_dict = _row_target_dict(pre_row) if pre_row is not None else {}
        ts = now_iso_ms_utc(self._clock)

        def _audit_cancel(conn: sqlite3.Connection) -> tuple[int, dict]:
            return self._audit.insert_queue_transition_in_tx(
                conn,
                event_type="queue_message_canceled",
                message_id=message_id,
                from_state=pre_state,
                to_state="canceled",
                reason=None,
                operator=operator,
                observed_at=ts,
                sender=sender_dict,
                target=target_dict,
                excerpt="",
            )
        audit_event_id, audit_payload = self._dao.transition_to_canceled(
            message_id, operator=operator, ts=ts,
            audit_callback=_audit_cancel,
        )
        self._audit.append_jsonl_for_queue_transition(
            audit_event_id, audit_payload, watermark_ts=ts,
        )
        row = self._dao.get_row_by_id(message_id)
        assert row is not None
        # Notify any waiter (cancel produces a terminal state).
        self._notify_terminal(message_id)
        return row

    # ─── Listing (FR-031) ─────────────────────────────────────────────

    def list_rows(self, filters: QueueListFilter) -> list[QueueRow]:
        """Pass-through to the DAO; filters resolved per FR-031."""
        return self._dao.list_rows(filters)

    # ─── Public helpers for the socket dispatch layer ────────────────
    #
    # The dispatcher used to reach into ``_agents`` / ``_dao`` directly.
    # These methods give it a stable, narrowly-scoped surface so the
    # service's internal layout can evolve without breaking callers.

    def resolve_target_agent_id(self, target_input: str) -> str:
        """Resolve a ``--target`` argument (agent_id OR label) to an
        agent_id. Raises :class:`TargetResolveError` with
        ``agent_not_found`` / ``target_label_ambiguous`` on miss /
        ambiguous match — same closed-set semantics as
        :meth:`send_input`."""
        return resolve_target(target_input, self._agents).agent_id

    def read_envelope_excerpt(self, message_id: str) -> str:
        """Read the persisted body BLOB and return the FR-047b excerpt.
        Returns an empty string if the row is missing or the body can't
        be read — callers should treat the excerpt as best-effort.
        """
        try:
            body = self._dao.read_envelope_bytes(message_id)
        except Exception:
            return ""
        return render_excerpt(body)

    # ─── Worker notification hook ─────────────────────────────────────

    def notify_worker_transition(self, message_id: str, terminal: bool) -> None:
        """Called by the delivery worker after every state transition.

        If ``terminal=True``, wakes up any ``send-input`` caller waiting
        on this message_id so its wait loop can re-check the DB state.
        No-op otherwise — pre-terminal transitions (the worker's stamp
        path) don't need to wake the waiter.

        Note: the parameter name predates the addition of ``blocked``
        to ``_END_OF_WAIT_STATES``. The worker passes ``terminal=True``
        for the queued→blocked re-check transition too, because that
        transition is end-of-wait for send-input (CLI contract: a
        re-check blocked outcome returns immediately with
        ``block_reason``). The wait loop itself re-reads the row state
        and decides whether to exit, so this remains correct.
        """
        if terminal:
            self._notify_terminal(message_id)

    # ─── Internal helpers ─────────────────────────────────────────────

    def _check_approve_applicable(self, row: QueueRow) -> None:
        """FR-033: ``approve`` is valid only when ``block_reason`` is
        operator-resolvable. The ``kill_switch_off`` case has a wrinkle —
        approve is only valid IF the switch is currently enabled."""
        operator_resolvable = {
            "operator_delayed",
            "target_not_active",
            "target_pane_missing",
            "target_container_inactive",
        }
        if row.block_reason in operator_resolvable:
            return
        if row.block_reason == KILL_SWITCH_OFF:
            if self._routing_flag.is_enabled():
                # Switch flipped back on → approve is allowed.
                return
            raise QueueServiceError(
                APPROVAL_NOT_APPLICABLE,
                "cannot approve kill_switch_off rows while routing is disabled",
            )
        # Intrinsic block_reason — not operator-resolvable.
        raise QueueServiceError(
            APPROVAL_NOT_APPLICABLE,
            f"block_reason={row.block_reason!r} is not operator-resolvable",
        )

    def _wait_for_terminal(self, message_id: str, timeout: float) -> bool:
        """Block up to ``timeout`` seconds for the row to settle.

        ``settle`` means either a strictly-terminal state
        (``_TERMINAL_STATES``) or ``blocked`` — see ``_END_OF_WAIT_STATES``
        above for why ``send-input`` returns immediately on a blocked
        outcome. The boolean return value still reflects only the
        strictly-terminal cases: ``True`` iff the row reached
        ``delivered`` / ``failed`` / ``canceled``; ``False`` on timeout
        OR on a settle-via-blocked exit.

        ``threading.Condition.wait`` can return ``True`` on spurious
        wakeups without an actual notification, so we re-check the
        SQLite row's state after every wakeup. The loop budget is the
        original ``timeout``; subsequent waits use the remaining slack
        so spurious wakeups don't compound.

        Time accounting goes through ``self._clock.monotonic`` (not
        :mod:`time` directly) so :class:`FakeClock` can drive the
        deadline deterministically in tests.
        """
        observer = _WaitObserver()
        with self._wait_lock:
            self._wait_observers[message_id] = observer
        try:
            deadline = self._clock.monotonic() + timeout
            with observer.condition:
                while True:
                    # Re-check the DB before each sleep so a settle
                    # transition that landed between our service-level
                    # read and the wait registration (OR between two
                    # wakeups) is observed immediately.
                    row = self._dao.get_row_by_id(message_id)
                    if row is not None and row.state in _END_OF_WAIT_STATES:
                        return row.state in _TERMINAL_STATES
                    remaining = deadline - self._clock.monotonic()
                    if remaining <= 0:
                        return False
                    observer.condition.wait(timeout=remaining)
        finally:
            with self._wait_lock:
                self._wait_observers.pop(message_id, None)

    def _notify_terminal(self, message_id: str) -> None:
        with self._wait_lock:
            observer = self._wait_observers.get(message_id)
        if observer is None:
            return
        with observer.condition:
            observer.condition.notify_all()


_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {"delivered", "failed", "canceled"}
)

# End-of-wait states for ``send-input`` waiters: terminal states plus
# ``blocked``. The CLI contract (FR-010, cli-send-input.md) says a
# blocked-at-enqueue or worker-re-check blocked outcome MUST return
# the row + ``block_reason`` immediately rather than sleeping until
# the wait timeout elapses. ``waited_to_terminal`` in
# :class:`SendInputResult` still reflects only ``_TERMINAL_STATES``;
# a ``blocked`` exit is reported as ``waited_to_terminal=False``.
_END_OF_WAIT_STATES: Final[frozenset[str]] = _TERMINAL_STATES | {"blocked"}


@dataclass
class _WaitObserver:
    """Wraps a :class:`threading.Condition` so we can pass it by reference
    through the registry without exposing the Lock directly."""

    condition: threading.Condition = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.condition is None:
            self.condition = threading.Condition()


# ──────────────────────────────────────────────────────────────────────
# Tiny pure helpers
# ──────────────────────────────────────────────────────────────────────


def _sha256_hex(body: bytes) -> str:
    import hashlib
    return hashlib.sha256(body).hexdigest()


def _identity_to_dict(
    identity: EnvelopeIdentity,
    *,
    container: AgentRecord | None = None,
) -> dict:
    """Pack an :class:`EnvelopeIdentity` into the dict shape the DAO
    expects. When ``container`` is supplied (target side), include
    container_id + pane_id."""
    d = {
        "agent_id": identity.agent_id,
        "label": identity.label,
        "role": identity.role,
        "capability": identity.capability,
    }
    if container is not None:
        d["container_id"] = container.container_id
        d["pane_id"] = container.tmux_pane_id
    return d


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
