"""T077 — `routing_toggled` audit emission rules (FR-046 / FR-027).

Asserts that the dispatcher emits exactly one ``routing_toggled``
audit row per ``changed=True`` toggle, that the row contains the
documented fields (``previous_value`` / ``current_value`` /
``operator`` / ``observed_at``), and that idempotent toggles
(``changed=False``) emit NOTHING.

Caller-context refusal (bench-container origin) is also asserted to
NOT emit any audit row.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agenttower.routing.audit_writer import QueueAuditWriter
from agenttower.routing.dao import DaemonStateDao
from agenttower.routing.kill_switch import RoutingFlagService
from agenttower.socket_api.methods import DISPATCH, DaemonContext
from agenttower.state import schema


_HOST_OPERATOR = "host-operator"


def _open_v7(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (7)")
    for v in (2, 3, 4, 5, 6, 7):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    return conn


def _ctx(
    tmp_path: Path, *, queue_service: Any = None,
) -> tuple[DaemonContext, QueueAuditWriter, RoutingFlagService, Path]:
    conn = _open_v7(tmp_path)
    state_dao = DaemonStateDao(conn)
    routing_flag = RoutingFlagService(state_dao)
    jsonl = tmp_path / "events.jsonl"
    audit_writer = QueueAuditWriter(conn, jsonl)

    # Minimal stub QueueService so the dispatcher's
    # _routing_services_or_error gate passes.
    class _StubQS:
        pass
    if queue_service is None:
        queue_service = _StubQS()

    ctx = DaemonContext(
        pid=4242,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=tmp_path,
        daemon_version="0.0.0+test",
        schema_version=7,
        queue_service=queue_service,
        routing_flag_service=routing_flag,
        queue_audit_writer=audit_writer,
    )
    return ctx, audit_writer, routing_flag, jsonl


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line]


# ──────────────────────────────────────────────────────────────────────
# 1. changed=True → exactly one routing_toggled audit row with the
#    documented fields.
# ──────────────────────────────────────────────────────────────────────


def test_disable_emits_one_routing_toggled_audit_when_changed(tmp_path: Path) -> None:
    """Flag starts ``enabled`` (migration seed); ``routing.disable``
    changes it → one audit row with previous_value=enabled,
    current_value=disabled, operator=host-operator, observed_at set."""
    ctx, audit_writer, _routing_flag, jsonl = _ctx(tmp_path)
    import os
    envelope = DISPATCH["routing.disable"](ctx, {}, peer_uid=os.getuid())
    assert envelope["ok"] is True
    assert envelope["result"]["changed"] is True
    assert envelope["result"]["current_value"] == "disabled"

    records = _read_jsonl(jsonl)
    toggled = [r for r in records if r["event_type"] == "routing_toggled"]
    assert len(toggled) == 1, f"expected 1 audit row, got {len(toggled)}"
    audit = toggled[0]
    assert audit["previous_value"] == "enabled"
    assert audit["current_value"] == "disabled"
    assert audit["operator"] == _HOST_OPERATOR
    assert "observed_at" in audit
    assert audit["schema_version"] == 1


def test_enable_after_disable_emits_second_routing_toggled_audit(
    tmp_path: Path,
) -> None:
    """Flag starts enabled. disable → 1 audit; enable → 2nd audit
    with previous_value=disabled."""
    ctx, audit_writer, _routing_flag, jsonl = _ctx(tmp_path)
    import os
    DISPATCH["routing.disable"](ctx, {}, peer_uid=os.getuid())
    DISPATCH["routing.enable"](ctx, {}, peer_uid=os.getuid())

    records = _read_jsonl(jsonl)
    toggled = [r for r in records if r["event_type"] == "routing_toggled"]
    assert len(toggled) == 2
    assert toggled[0]["current_value"] == "disabled"
    assert toggled[1]["previous_value"] == "disabled"
    assert toggled[1]["current_value"] == "enabled"


# ──────────────────────────────────────────────────────────────────────
# 2. changed=False (idempotent) → NO audit row
# ──────────────────────────────────────────────────────────────────────


def test_idempotent_enable_emits_no_audit(tmp_path: Path) -> None:
    """The flag starts enabled (migration seed). ``routing.enable``
    is a no-op → changed=false → NO audit row."""
    ctx, audit_writer, _routing_flag, jsonl = _ctx(tmp_path)
    import os
    envelope = DISPATCH["routing.enable"](ctx, {}, peer_uid=os.getuid())
    assert envelope["ok"] is True
    assert envelope["result"]["changed"] is False
    assert envelope["result"]["current_value"] == "enabled"

    records = _read_jsonl(jsonl)
    toggled = [r for r in records if r["event_type"] == "routing_toggled"]
    assert len(toggled) == 0


def test_idempotent_disable_then_disable_emits_one_audit(tmp_path: Path) -> None:
    """Sequence: disable (changed) → disable (no-op). Only the first
    emits an audit row."""
    ctx, audit_writer, _routing_flag, jsonl = _ctx(tmp_path)
    import os
    DISPATCH["routing.disable"](ctx, {}, peer_uid=os.getuid())
    envelope2 = DISPATCH["routing.disable"](ctx, {}, peer_uid=os.getuid())
    assert envelope2["result"]["changed"] is False

    records = _read_jsonl(jsonl)
    toggled = [r for r in records if r["event_type"] == "routing_toggled"]
    assert len(toggled) == 1


# ──────────────────────────────────────────────────────────────────────
# 3. Bench-container caller refused → no flag change, no audit
# ──────────────────────────────────────────────────────────────────────


def test_bench_caller_routing_toggle_host_only_emits_no_audit(
    tmp_path: Path,
) -> None:
    """A bench-container caller (caller_pane is not None) is refused
    with routing_toggle_host_only. The flag value MUST NOT change and
    NO audit row is emitted."""
    ctx, audit_writer, routing_flag, jsonl = _ctx(tmp_path)
    initial_value, _, _ = routing_flag.read_full()
    envelope = DISPATCH["routing.disable"](
        ctx, {"caller_pane": {"agent_id": "agt_000000000001"}},
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "routing_toggle_host_only"

    # Flag unchanged.
    value_after, _, _ = routing_flag.read_full()
    assert value_after == initial_value

    # No audit row.
    records = _read_jsonl(jsonl)
    toggled = [r for r in records if r["event_type"] == "routing_toggled"]
    assert len(toggled) == 0


# ──────────────────────────────────────────────────────────────────────
# 4. Audit row has the documented JSON shape
# ──────────────────────────────────────────────────────────────────────


def test_audit_row_carries_all_documented_fields(tmp_path: Path) -> None:
    ctx, audit_writer, _routing_flag, jsonl = _ctx(tmp_path)
    import os
    DISPATCH["routing.disable"](ctx, {}, peer_uid=os.getuid())
    audit = next(
        r for r in _read_jsonl(jsonl)
        if r["event_type"] == "routing_toggled"
    )
    # Per contracts/queue-audit-schema.md "Routing toggle audit entry".
    expected = {
        "schema_version", "event_type",
        "previous_value", "current_value",
        "observed_at", "operator",
    }
    assert expected <= set(audit.keys()), (
        f"missing fields: {expected - set(audit.keys())}"
    )
