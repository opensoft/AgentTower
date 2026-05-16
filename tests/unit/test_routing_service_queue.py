from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from agenttower.agents.permissions import serialize_effective_permissions
from agenttower.events.dao import select_event_by_id
from agenttower.routing.audit_writer import QueueAuditWriter
from agenttower.routing.dao import DaemonStateDao, MessageQueueDao, QueueListFilter
from agenttower.routing.kill_switch import RoutingFlagService
from agenttower.routing.service import ContainerPaneLookup, QueueService
from agenttower.state import schema
from agenttower.state.agents import AgentRecord, insert_agent


class _AgentsLookup:
    def __init__(self, records: list[AgentRecord]) -> None:
        self._by_id = {record.agent_id: record for record in records}
        self._by_label: dict[str, list[AgentRecord]] = {}
        for record in records:
            self._by_label.setdefault(record.label, []).append(record)

    def get_agent_by_id(self, agent_id: str) -> AgentRecord | None:
        return self._by_id.get(agent_id)

    def find_agents_by_label(
        self, label: str, *, only_active: bool = True
    ) -> list[AgentRecord]:
        rows = list(self._by_label.get(label, []))
        if only_active:
            rows = [row for row in rows if row.active]
        return rows


class _ContainerPaneLookup(ContainerPaneLookup):
    def is_container_active(self, container_id: str) -> bool:
        return True

    def is_pane_resolvable(self, container_id: str, pane_id: str) -> bool:
        return True


def _open_registry(tmp_path: Path) -> sqlite3.Connection:
    state_db = tmp_path / "agenttower.sqlite3"
    conn, _ = schema.open_registry(state_db)
    conn.close()
    conn = sqlite3.connect(
        str(state_db),
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _insert_agent_record(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    role: str,
    label: str,
    container_id: str,
    pane_id: str,
) -> AgentRecord:
    now = "2026-05-15T12:00:00.000Z"
    pane_key = (container_id, "/tmp/tmux.sock", "s", 0, 0, pane_id)
    insert_agent(
        conn,
        agent_id=agent_id,
        pane_key=pane_key,
        role=role,
        capability="codex",
        label=label,
        project_path="/workspace",
        parent_agent_id=None,
        effective_permissions_json=serialize_effective_permissions(role),
        created_at=now,
        last_registered_at=now,
        active=True,
    )
    conn.commit()
    return AgentRecord(
        agent_id=agent_id,
        container_id=container_id,
        tmux_socket_path="/tmp/tmux.sock",
        tmux_session_name="s",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id=pane_id,
        role=role,
        capability="codex",
        label=label,
        project_path="/workspace",
        parent_agent_id=None,
        effective_permissions={"can_send": role == "master", "can_receive": role in {"slave", "swarm"}, "can_send_to_roles": ["slave", "swarm"] if role == "master" else []},
        created_at=now,
        last_registered_at=now,
        last_seen_at=None,
        active=True,
    )


def _build_service(
    tmp_path: Path,
) -> tuple[sqlite3.Connection, QueueService, MessageQueueDao, QueueAuditWriter, AgentRecord, AgentRecord]:
    conn = _open_registry(tmp_path)
    sender = _insert_agent_record(
        conn,
        agent_id="agt_aaaaaaaaaaaa",
        role="master",
        label="master-a",
        container_id="c" * 64,
        pane_id="%1",
    )
    target = _insert_agent_record(
        conn,
        agent_id="agt_bbbbbbbbbbbb",
        role="slave",
        label="slave-1",
        container_id="c" * 64,
        pane_id="%2",
    )
    # Share ONE tx_lock across every writer that holds ``conn`` —
    # MessageQueueDao, DaemonStateDao, and QueueAuditWriter all
    # serialize their ``BEGIN IMMEDIATE`` blocks on this lock. Without
    # the shared lock each writer would create its own
    # ``threading.Lock`` by default, and the threaded send-input /
    # operator-action tests below can race two BEGIN IMMEDIATE blocks
    # against the same sqlite3.Connection — SQLite then raises
    # "cannot start a transaction within a transaction" intermittently.
    # This mirrors the production wiring in ``daemon._build_feat009_services``.
    tx_lock = threading.Lock()
    dao = MessageQueueDao(conn, tx_lock=tx_lock)
    audit = QueueAuditWriter(conn, tmp_path / "events.jsonl", tx_lock=tx_lock)
    service = QueueService(
        dao=dao,
        routing_flag=RoutingFlagService(DaemonStateDao(conn, tx_lock=tx_lock)),
        agents_lookup=_AgentsLookup([sender, target]),
        container_pane_lookup=_ContainerPaneLookup(),
        audit_writer=audit,
    )
    return conn, service, dao, audit, sender, target


def test_delay_wakes_waiting_send_input(tmp_path: Path) -> None:
    _conn, service, dao, _audit, sender_record, target_record = _build_service(tmp_path)

    result_holder: dict[str, object] = {}
    finished = threading.Event()

    def _send() -> None:
        result_holder["result"] = service.send_input(
            sender=sender_record,
            target_input=target_record.agent_id,
            body_bytes=b"hello\nworld",
            wait=True,
            wait_timeout=2.0,
        )
        finished.set()

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()

    deadline = time.monotonic() + 1.0
    message_id: str | None = None
    while time.monotonic() < deadline:
        rows = dao.list_rows(QueueListFilter(limit=10))
        if rows:
            message_id = rows[0].message_id
            break
        time.sleep(0.01)
    assert message_id is not None

    service.delay(message_id, operator="host-operator")
    assert finished.wait(0.5), "send_input waiter did not wake after delay()"
    result = result_holder["result"]
    assert result.row.state == "blocked"
    assert result.row.block_reason == "operator_delayed"
    assert result.waited_to_terminal is False


def test_audit_writer_buffers_watermark_failure_after_jsonl_append(
    tmp_path: Path, monkeypatch
) -> None:
    conn, _service, _dao, audit, _sender, _target = _build_service(tmp_path)

    from agenttower.routing import audit_writer as audit_writer_mod
    original_mark_jsonl_appended = audit_writer_mod.mark_jsonl_appended

    def _raise_once(*args, **kwargs):  # noqa: ANN002, ANN003
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(audit_writer_mod, "mark_jsonl_appended", _raise_once)
    event_id = audit.append_queue_transition(
        event_type="queue_message_enqueued",
        message_id="11111111-1111-1111-1111-111111111111",
        from_state=None,
        to_state="queued",
        reason=None,
        operator=None,
        observed_at="2026-05-15T12:00:00.000Z",
        sender={"agent_id": "agt_aaaaaaaaaaaa", "label": "master-a", "role": "master", "capability": "codex"},
        target={"agent_id": "agt_bbbbbbbbbbbb", "label": "slave-1", "role": "slave", "capability": "codex"},
        excerpt="hello world",
    )
    assert audit.degraded is True
    assert audit.pending_count == 1

    monkeypatch.setattr(
        audit_writer_mod, "mark_jsonl_appended", original_mark_jsonl_appended
    )
    drained = audit.drain_pending()
    assert drained == 1
    assert audit.degraded is False
    row = select_event_by_id(conn, event_id)
    assert row is not None
    assert row.jsonl_appended_at == "2026-05-15T12:00:00.000Z"
