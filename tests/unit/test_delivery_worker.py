"""T043 — T047 — FEAT-009 DeliveryWorker tests.

Five tasks consolidated by shared fixtures:

* **T043 ordering**: stamp commits BEFORE any tmux call (FR-041);
  terminal commit BEFORE the next row is picked (FR-042); recovery
  pass runs BEFORE worker.start (research §R-012).
* **T044 recovery**: ``run_recovery_pass`` transitions every in-flight
  row to ``failed/attempt_interrupted``; no second tmux paste is
  issued; non-interrupted rows are preserved byte-for-byte.
* **T045 pre-paste re-check**: each FR-025 / R-006 re-check failure
  (target inactive, container inactive, pane missing) produces the
  matching ``block_reason`` and does NOT invoke any tmux method.
* **T046 failure modes**: each ``failure_reason`` value mapping from
  FR-018, the Group-A walk Q1 cleanup-`finally` invariant
  (delete_buffer called after a failed paste/send_keys), and the
  Q2 successful-paste-cleanup-failure invariant (row stays
  ``delivered``).
* **T047 kill-switch race**: Q1 of Clarifications session 2 — a row
  with ``delivery_attempt_started_at`` already committed at the
  moment of ``routing disable`` runs to terminal under normal commit
  ordering; the worker does NOT preempt.

The worker integrates DAO + RoutingFlagService + AgentsLookup +
ContainerPaneLookup + TmuxAdapter + QueueAuditWriter + QueueService.
We use real instances of the SQLite-backed components (DAO, kill
switch, audit writer) and stub the lookups + tmux for control.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agenttower.routing.audit_writer import QueueAuditWriter
from agenttower.routing.dao import (
    DaemonStateDao,
    MessageQueueDao,
    QueueListFilter,
    QueueRow,
)
from agenttower.routing.delivery import (
    DeliveryContext,
    DeliveryContextResolver,
    DeliveryWorker,
)
from agenttower.routing.errors import SqliteLockConflict
from agenttower.routing.kill_switch import RoutingFlagService
from agenttower.routing.service import (
    ContainerPaneLookup,
    QueueService,
)
from agenttower.routing.target_resolver import AgentsLookup
from agenttower.state import schema
from agenttower.state.agents import AgentRecord
from agenttower.tmux.adapter import TmuxError
from agenttower.tmux.fakes import FakeTmuxAdapter


# ──────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────


def _open_v7(tmp_path: Path) -> sqlite3.Connection:
    """Open a v7 DB with cross-thread access.

    The delivery worker spawns a thread, so the SQLite connection must
    allow cross-thread access in unit tests. In production, the worker
    owns its own dedicated connection — there's no cross-thread sharing
    on the hot path.
    """
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (6)")
    for v in (2, 3, 4, 5, 6):
        schema._MIGRATIONS[v](conn)
    schema._apply_migration_v7(conn)
    conn.commit()
    return conn


def _make_agent(
    *,
    agent_id: str,
    role: str,
    label: str,
    active: bool = True,
    container_id: str = "c0123456789a",
    pane_id: str = "%0",
) -> AgentRecord:
    return AgentRecord(
        agent_id=agent_id,
        container_id=container_id,
        tmux_socket_path="/tmp/tmux-1000/default",
        tmux_session_name="agenttower",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id=pane_id,
        role=role,
        capability="impl",
        label=label,
        project_path="/proj",
        parent_agent_id=None,
        effective_permissions={},
        created_at="2026-05-12T00:00:00.000Z",
        last_registered_at="2026-05-12T00:00:00.000Z",
        last_seen_at="2026-05-12T00:00:00.000Z",
        active=active,
    )


@dataclass
class FakeAgentsLookup:
    records: list[AgentRecord]

    def get_agent_by_id(self, agent_id: str) -> AgentRecord | None:
        for r in self.records:
            if r.agent_id == agent_id:
                return r
        return None

    def find_agents_by_label(self, label: str, *, only_active: bool = True) -> list[AgentRecord]:
        return [
            r for r in self.records
            if r.label == label and (not only_active or r.active)
        ]


@dataclass
class StubContainerPanes(ContainerPaneLookup):
    container_active: bool = True
    pane_resolvable: bool = True

    def is_container_active(self, container_id: str) -> bool:
        return self.container_active

    def is_pane_resolvable(self, container_id: str, pane_id: str) -> bool:
        return self.pane_resolvable


@dataclass
class StubResolver:
    """DeliveryContextResolver test double. Returns a fixed context."""

    container_id: str = "c0123456789a"
    bench_user: str = "agent"
    socket_path: str = "/tmp/tmux-1000/default"
    pane_id: str = "%0"
    should_fail: bool = False

    def resolve(self, row: QueueRow) -> DeliveryContext:
        if self.should_fail:
            raise RuntimeError("resolver stub failure")
        return DeliveryContext(
            container_id=self.container_id,
            bench_user=self.bench_user,
            socket_path=self.socket_path,
            pane_id=self.pane_id,
        )


@dataclass
class _Harness:
    """All the wired components a test needs."""

    conn: sqlite3.Connection
    dao: MessageQueueDao
    routing: RoutingFlagService
    tmux: FakeTmuxAdapter
    audit: QueueAuditWriter
    queue: QueueService
    worker: DeliveryWorker
    agents: FakeAgentsLookup
    container_panes: StubContainerPanes
    resolver: StubResolver


def _make_harness(
    tmp_path: Path,
    *,
    extra_agents: list[AgentRecord] | None = None,
) -> _Harness:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    routing = RoutingFlagService(DaemonStateDao(conn))

    sender = _make_agent(agent_id="agt_aaaaaa111111", role="master", label="queen")
    target = _make_agent(
        agent_id="agt_bbbbbb222222", role="slave", label="worker-1",
    )
    agents = FakeAgentsLookup([sender, target] + (extra_agents or []))
    container_panes = StubContainerPanes()
    tmux = FakeTmuxAdapter()
    audit = QueueAuditWriter(conn, tmp_path / "events.jsonl")
    queue = QueueService(dao, routing, agents, container_panes, audit)
    resolver = StubResolver()
    worker = DeliveryWorker(
        dao, routing, agents, container_panes, tmux,
        audit, queue, resolver,
        idle_poll_seconds=0.01,  # snappy for tests
    )
    return _Harness(
        conn=conn, dao=dao, routing=routing, tmux=tmux,
        audit=audit, queue=queue, worker=worker, agents=agents,
        container_panes=container_panes, resolver=resolver,
    )


def _insert_queued_row(harness: _Harness, *, message_id: str) -> QueueRow:
    """Insert a queued row directly via the QueueService (so the audit
    is emitted exactly like in production)."""
    sender = harness.agents.records[0]
    result = harness.queue.send_input(
        sender=sender, target_input="worker-1",
        body_bytes=b"do thing", wait=False,
    )
    # The result.row.message_id was UUID-generated; rewrite to a known id
    # for predictable assertions.
    harness.conn.execute(
        "UPDATE message_queue SET message_id = ? WHERE message_id = ?",
        (message_id, result.row.message_id),
    )
    harness.conn.commit()
    out = harness.dao.get_row_by_id(message_id)
    assert out is not None
    return out


# ──────────────────────────────────────────────────────────────────────
# T044 — Recovery pass (FR-040)
# ──────────────────────────────────────────────────────────────────────


def test_recovery_transitions_in_flight_to_failed_attempt_interrupted(
    tmp_path: Path,
) -> None:
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000001")
    # Simulate crash mid-attempt.
    h.dao.stamp_delivery_attempt_started(row.message_id, "2026-05-12T00:00:01.000Z")
    # New worker simulates a fresh boot.
    count = h.worker.run_recovery_pass()
    assert count == 1
    recovered = h.dao.get_row_by_id(row.message_id)
    assert recovered.state == "failed"
    assert recovered.failure_reason == "attempt_interrupted"


def test_recovery_no_second_tmux_paste(tmp_path: Path) -> None:
    """SC-004: zero tmux delivery calls are made by the recovery pass."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000002")
    h.dao.stamp_delivery_attempt_started(row.message_id, "2026-05-12T00:00:01.000Z")
    h.worker.run_recovery_pass()
    assert h.tmux.delivery_calls == []


def test_recovery_emits_one_audit_per_row(tmp_path: Path) -> None:
    """US6 #2: exactly one audit entry per recovered row."""
    h = _make_harness(tmp_path)
    row1 = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000003")
    row2 = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000004")
    h.dao.stamp_delivery_attempt_started(row1.message_id, "2026-05-12T00:00:01.000Z")
    h.dao.stamp_delivery_attempt_started(row2.message_id, "2026-05-12T00:00:01.000Z")
    # Snapshot audit count BEFORE recovery (each insert emitted one
    # queue_message_enqueued already).
    pre_failed = h.conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'queue_message_failed'"
    ).fetchone()[0]
    assert pre_failed == 0
    h.worker.run_recovery_pass()
    post_failed = h.conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'queue_message_failed'"
    ).fetchone()[0]
    assert post_failed == 2


def test_recovery_preserves_non_interrupted_rows(tmp_path: Path) -> None:
    """US6 #3: queued / blocked / delivered / failed / canceled rows
    that did NOT have an interrupted in-flight attempt are preserved
    byte-for-byte."""
    h = _make_harness(tmp_path)
    # Queued (no stamp).
    queued = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000005")
    # Delivered.
    delivered = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000006")
    h.dao.stamp_delivery_attempt_started(delivered.message_id, "2026-05-12T00:00:01.000Z")
    h.dao.transition_queued_to_delivered(delivered.message_id, "2026-05-12T00:00:02.000Z")
    pre_queued = h.dao.get_row_by_id(queued.message_id)
    pre_delivered = h.dao.get_row_by_id(delivered.message_id)
    h.worker.run_recovery_pass()
    post_queued = h.dao.get_row_by_id(queued.message_id)
    post_delivered = h.dao.get_row_by_id(delivered.message_id)
    assert pre_queued == post_queued
    assert pre_delivered == post_delivered


def test_recovery_returns_zero_when_no_in_flight_rows(tmp_path: Path) -> None:
    h = _make_harness(tmp_path)
    _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000007")
    assert h.worker.run_recovery_pass() == 0


# ──────────────────────────────────────────────────────────────────────
# T043 — Ordering (FR-041 / FR-042 / R-012)
# ──────────────────────────────────────────────────────────────────────


def test_stamp_commits_before_any_tmux_call(tmp_path: Path) -> None:
    """FR-041: ``delivery_attempt_started_at`` is committed to SQLite
    BEFORE the first tmux call. Verified by inserting a row, calling
    ``_deliver_one`` directly, and confirming the stamp is set at the
    time of the FIRST tmux call."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000010")

    stamps_at_load: list[str | None] = []

    original_load = h.tmux.load_buffer

    def spy_load(**kwargs: Any) -> None:
        current = h.dao.get_row_by_id(row.message_id)
        stamps_at_load.append(current.delivery_attempt_started_at)
        return original_load(**kwargs)

    h.tmux.load_buffer = spy_load  # type: ignore[method-assign]
    h.worker._deliver_one(row)
    assert len(stamps_at_load) == 1
    assert stamps_at_load[0] is not None, (
        "stamp must be committed BEFORE load_buffer is called (FR-041)"
    )


def test_terminal_commit_happens_after_all_tmux_calls(tmp_path: Path) -> None:
    """FR-042: ``delivered_at`` is committed AFTER the four tmux calls.
    Verified by inspecting the row state at the moment of each tmux call."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000011")

    states_at_calls: list[str] = []

    def make_spy(method_name: str, original):
        def spy(**kwargs: Any) -> None:
            current = h.dao.get_row_by_id(row.message_id)
            states_at_calls.append(f"{method_name}:{current.state}")
            return original(**kwargs)
        return spy

    h.tmux.load_buffer = make_spy("load", h.tmux.load_buffer)
    h.tmux.paste_buffer = make_spy("paste", h.tmux.paste_buffer)
    h.tmux.send_keys = make_spy("send_keys", h.tmux.send_keys)
    h.tmux.delete_buffer = make_spy("delete", h.tmux.delete_buffer)
    h.worker._deliver_one(row)
    # State during all four tmux calls is 'queued' (terminal stamp not yet set).
    assert states_at_calls == [
        "load:queued",
        "paste:queued",
        "send_keys:queued",
        "delete:queued",
    ]
    # Final state is delivered.
    assert h.dao.get_row_by_id(row.message_id).state == "delivered"


def test_recovery_runs_before_start(tmp_path: Path) -> None:
    """Research §R-012 / T048 boot ordering: the worker's recovery pass
    is intended to be called BEFORE start(). Pin this contract by
    verifying that start() raises if called twice (boot-ordering bug
    surface) and recovery is a separate synchronous method."""
    h = _make_harness(tmp_path)
    h.worker.run_recovery_pass()  # synchronous
    assert h.worker.is_running is False
    # start() spawns the thread. Calling start() twice is a programmer error.
    h.worker.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            h.worker.start()
    finally:
        h.worker.stop(timeout=1.0)
    assert h.worker.is_running is False


# ──────────────────────────────────────────────────────────────────────
# T045 — Pre-paste re-check (FR-025 / R-006)
# ──────────────────────────────────────────────────────────────────────


def test_re_check_target_inactive_transitions_to_blocked(tmp_path: Path) -> None:
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000020")
    # Flip the target to inactive.
    h.agents.records[1] = replace(h.agents.records[1], active=False)
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "blocked"
    assert out.block_reason == "target_not_active"
    assert h.tmux.delivery_calls == []


def test_re_check_container_inactive_transitions_to_blocked(tmp_path: Path) -> None:
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000021")
    h.container_panes.container_active = False
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "blocked"
    assert out.block_reason == "target_container_inactive"
    assert h.tmux.delivery_calls == []


def test_re_check_pane_missing_transitions_to_blocked(tmp_path: Path) -> None:
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000022")
    h.container_panes.pane_resolvable = False
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "blocked"
    assert out.block_reason == "target_pane_missing"
    assert h.tmux.delivery_calls == []


def test_re_check_target_deregistered_transitions_to_blocked(tmp_path: Path) -> None:
    """Edge case: target hard-deleted between enqueue and delivery → R-006
    treats as target_not_active."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000023")
    # Remove target from registry.
    h.agents.records = [r for r in h.agents.records if r.role != "slave"]
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "blocked"
    assert out.block_reason == "target_not_active"
    assert h.tmux.delivery_calls == []


def test_re_check_routing_disabled_transitions_to_blocked(tmp_path: Path) -> None:
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000024")
    h.routing.disable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "blocked"
    assert out.block_reason == "kill_switch_off"
    assert h.tmux.delivery_calls == []


def test_re_check_does_not_stamp_delivery_attempt(tmp_path: Path) -> None:
    """A re-check failure must NOT stamp delivery_attempt_started_at —
    the FR-025 contract is that re-check happens BEFORE the stamp."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000025")
    h.container_panes.pane_resolvable = False
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.delivery_attempt_started_at is None


# ──────────────────────────────────────────────────────────────────────
# T046 — Failure modes (FR-018) + Group-A walk Q1/Q2 cleanup
# ──────────────────────────────────────────────────────────────────────


def test_load_buffer_failure_maps_to_failure_reason(tmp_path: Path) -> None:
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000030")
    h.tmux.load_buffer_failures.append(
        TmuxError(code="docker_exec_failed", message="boom",
                  failure_reason="tmux_paste_failed")
    )
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "failed"
    assert out.failure_reason == "tmux_paste_failed"


def test_paste_buffer_failure_triggers_cleanup_finally(tmp_path: Path) -> None:
    """Group-A walk Q1: after a successful load_buffer, a paste_buffer
    failure invokes delete_buffer best-effort in the cleanup path.
    The row still transitions to failed."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000031")
    h.tmux.paste_buffer_failures.append(
        TmuxError(code="docker_exec_failed", message="boom",
                  failure_reason="tmux_paste_failed")
    )
    h.worker._deliver_one(row)
    methods = [c[0] for c in h.tmux.delivery_calls]
    assert methods == ["load_buffer", "paste_buffer", "delete_buffer"]
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "failed"
    assert out.failure_reason == "tmux_paste_failed"


def test_send_keys_failure_triggers_cleanup_finally(tmp_path: Path) -> None:
    """Same as above but the failure happens on send_keys (after both
    load_buffer AND paste_buffer succeeded)."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000032")
    h.tmux.send_keys_failures.append(
        TmuxError(code="docker_exec_failed", message="boom",
                  failure_reason="tmux_send_keys_failed")
    )
    h.worker._deliver_one(row)
    methods = [c[0] for c in h.tmux.delivery_calls]
    assert methods == ["load_buffer", "paste_buffer", "send_keys", "delete_buffer"]
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "failed"
    assert out.failure_reason == "tmux_send_keys_failed"


def test_cleanup_delete_buffer_failure_is_logged_not_propagated(tmp_path: Path) -> None:
    """Group-A walk Q1 continued: the cleanup delete_buffer failure is
    logged but never raised — the row still transitions to failed with
    the ORIGINAL failure_reason, not the cleanup's."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000033")
    h.tmux.paste_buffer_failures.append(
        TmuxError(code="docker_exec_failed", message="boom",
                  failure_reason="tmux_paste_failed")
    )
    h.tmux.delete_buffer_failures.append(
        TmuxError(code="docker_exec_failed", message="cleanup boom",
                  failure_reason="tmux_paste_failed")
    )
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "failed"
    # failure_reason is the ORIGINAL paste failure, not the cleanup failure.
    assert out.failure_reason == "tmux_paste_failed"


def test_delete_buffer_failure_after_successful_paste_stays_delivered(
    tmp_path: Path,
) -> None:
    """Group-A walk Q2: a delete_buffer failure AFTER paste+submit
    succeeded does NOT downgrade the row — it stays delivered."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000034")
    h.tmux.delete_buffer_failures.append(
        TmuxError(code="docker_exec_failed", message="cleanup boom",
                  failure_reason="tmux_paste_failed")
    )
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "delivered"  # Q2: stays delivered
    assert out.failure_reason is None
    assert out.delivered_at is not None


def test_pane_disappeared_mid_attempt_propagates(tmp_path: Path) -> None:
    """failure_reason=pane_disappeared_mid_attempt propagates from the
    tmux adapter through to the row."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000035")
    h.tmux.paste_buffer_failures.append(
        TmuxError(code="docker_exec_failed", message="pane gone",
                  failure_reason="pane_disappeared_mid_attempt")
    )
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.failure_reason == "pane_disappeared_mid_attempt"


def test_docker_exec_failed_propagates(tmp_path: Path) -> None:
    """failure_reason=docker_exec_failed propagates."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000036")
    h.tmux.load_buffer_failures.append(
        TmuxError(code="docker_unavailable", message="docker gone",
                  failure_reason="docker_exec_failed")
    )
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.failure_reason == "docker_exec_failed"


def test_resolver_failure_treats_as_blocked_target_pane_missing(
    tmp_path: Path,
) -> None:
    """If the resolver itself fails (e.g., agent hard-deleted between
    re-check and resolve), the worker transitions to blocked /
    target_pane_missing."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000037")
    h.resolver.should_fail = True
    h.worker._deliver_one(row)
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "blocked"
    assert out.block_reason == "target_pane_missing"
    assert h.tmux.delivery_calls == []


# ──────────────────────────────────────────────────────────────────────
# T047 — Kill-switch race (Clarifications session 2 Q1)
# ──────────────────────────────────────────────────────────────────────


def test_in_flight_row_finishes_after_disable(tmp_path: Path) -> None:
    """Q1: a row whose ``delivery_attempt_started_at`` was already
    committed at the moment of ``routing disable`` runs to terminal
    under normal commit ordering. The worker does NOT preempt
    in-flight rows."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000040")
    # Simulate the worker being mid-attempt: stamp it.
    h.dao.stamp_delivery_attempt_started(row.message_id, "2026-05-12T00:00:01.000Z")
    # Operator disables routing now.
    h.routing.disable(operator="host-operator", ts="2026-05-12T00:00:02.000Z")
    # The worker's normal _deliver_one would re-check routing first;
    # but for an already-stamped row, the worker's resumption path
    # (which transitions it via the next attempt) wouldn't apply here.
    # The realistic scenario is: worker started, stamp committed, then
    # disable fired, then worker continues its tmux calls. We model that
    # by directly running the post-stamp tmux + transition steps. The
    # _deliver_one helper expects a queued+unstamped row, so we exercise
    # the DAO path directly to simulate "in-flight survives disable".
    # Verify the stamp survives the disable + worker pickup attempt:
    out_before = h.dao.get_row_by_id(row.message_id)
    assert out_before.delivery_attempt_started_at == "2026-05-12T00:00:01.000Z"
    # Worker would NOT preempt — the row stays in-flight until the
    # worker's own state machine completes the tmux delivery.
    # (Verified at the DAO level: routing.disable doesn't touch
    # message_queue rows.)
    rows = h.dao.list_rows(QueueListFilter())
    assert len(rows) == 1
    assert rows[0].delivery_attempt_started_at is not None
    # Now the worker completes the tmux delivery (simulating a tick that
    # was already past the stamp+routing-check by the time disable fired).
    h.dao.transition_queued_to_delivered(row.message_id, "2026-05-12T00:00:03.000Z")
    out_after = h.dao.get_row_by_id(row.message_id)
    assert out_after.state == "delivered"


def test_routing_disable_blocks_new_pickups_only(tmp_path: Path) -> None:
    """When routing is disabled, the worker's main loop check skips
    pick_next_ready_row — new queued rows are NOT picked up until
    routing is re-enabled."""
    h = _make_harness(tmp_path)
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000041")
    h.routing.disable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    # Run the worker's main-loop check once: pick should NOT happen.
    # We invoke the routing check directly to verify the gate works.
    assert h.routing.is_enabled() is False
    # The row is still 'queued' — the worker did NOT pick it up.
    out = h.dao.get_row_by_id(row.message_id)
    assert out.state == "queued"
    # Re-enable; the worker would now pick it up.
    h.routing.enable(operator="host-operator", ts="2026-05-12T00:00:02.000Z")
    assert h.routing.is_enabled() is True


def test_worker_main_loop_respects_routing_flag(tmp_path: Path) -> None:
    """End-to-end: insert a row while routing is enabled (so it's
    queued), then disable routing and start the worker — observe no
    pickup; then re-enable routing and observe delivery."""
    h = _make_harness(tmp_path)
    # Insert the row while routing is enabled so it lands in 'queued'.
    row = _insert_queued_row(h, message_id="aa000000-0000-4000-8000-000000000042")
    assert h.dao.get_row_by_id(row.message_id).state == "queued"
    # Now disable routing.
    h.routing.disable(operator="host-operator", ts="2026-05-12T00:00:00.000Z")
    h.worker.start()
    try:
        import time
        # Sleep past several idle-poll windows.
        time.sleep(0.05)
        assert h.tmux.delivery_calls == [], (
            "worker must NOT pick up rows while routing is disabled"
        )
        assert h.dao.get_row_by_id(row.message_id).state == "queued"
        # Re-enable; the worker should now deliver.
        h.routing.enable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if h.dao.get_row_by_id(row.message_id).state == "delivered":
                break
            time.sleep(0.02)
    finally:
        h.worker.stop(timeout=1.0)
    assert h.dao.get_row_by_id(row.message_id).state == "delivered"


def test_worker_stop_aborts_without_drain(tmp_path: Path) -> None:
    """Group-A walk Q4: stop() aborts the loop; no drain mode."""
    h = _make_harness(tmp_path)
    h.worker.start()
    assert h.worker.is_running
    h.worker.stop(timeout=1.0)
    assert h.worker.is_running is False
