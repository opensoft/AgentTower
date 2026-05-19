"""FEAT-011 T011 / T012 / T013 unit tests.

In-process tests for the foundational stores and the audit emission
helper. No socket, no subprocess.
"""

from __future__ import annotations

import dataclasses
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import audit as audit_mod
from agenttower.app_contract import idempotency, scans
from agenttower.app_contract.sessions import AppSession


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def session() -> AppSession:
    """Stand-in AppSession for audit attribution tests."""
    return AppSession(
        app_session_token="test-token-deadbeef-deadbeef-deadbeef",
        app_session_id=42,
        client_id="test-client",
        client_version="0.0.1",
        client_app_contract_major=1,
        host_user_id=str(os.geteuid()),
        connection_started_at_ms=int(time.time() * 1000),
    )


# ─── T011 IdempotencyStore ───────────────────────────────────────────────


def test_idempotency_lookup_miss_returns_none() -> None:
    store = idempotency.IdempotencyStore()
    assert store.lookup("never-recorded") is None


def test_idempotency_record_then_lookup_returns_entry() -> None:
    store = idempotency.IdempotencyStore()
    now = int(time.time() * 1000)
    response = {"ok": True, "result": {"message_id": "msg-1"}}
    entry = store.record("key-1", "msg-1", response, now)
    assert entry.idempotency_key == "key-1"
    assert entry.message_id == "msg-1"
    assert entry.deduplicated_response == response
    assert entry.created_at_ms == now

    again = store.lookup("key-1")
    assert again is not None
    assert again.message_id == "msg-1"


def test_idempotency_lru_eviction_at_cap() -> None:
    """FR-031a: cap 256 entries, LRU eviction."""
    store = idempotency.IdempotencyStore(max_entries=3)
    now = int(time.time() * 1000)
    for i in range(3):
        store.record(f"key-{i}", f"msg-{i}", {"result": i}, now + i)
    assert store.size() == 3

    # Touch key-0 so key-1 becomes LRU.
    assert store.lookup("key-0") is not None

    # Insert a 4th → key-1 (now LRU) should be evicted.
    store.record("key-3", "msg-3", {"result": 3}, now + 3)
    assert store.size() == 3
    assert store.lookup("key-0") is not None  # touched, retained
    assert store.lookup("key-1") is None  # LRU evicted
    assert store.lookup("key-2") is not None
    assert store.lookup("key-3") is not None


def test_idempotency_re_record_refreshes_existing_entry() -> None:
    """Same-key re-record replaces in place without growing size."""
    store = idempotency.IdempotencyStore(max_entries=3)
    now = int(time.time() * 1000)
    store.record("key-1", "msg-1a", {"v": "a"}, now)
    store.record("key-1", "msg-1b", {"v": "b"}, now + 1)
    assert store.size() == 1
    entry = store.lookup("key-1")
    assert entry is not None
    assert entry.message_id == "msg-1b"
    assert entry.deduplicated_response == {"v": "b"}


def test_idempotency_clear_drops_all() -> None:
    store = idempotency.IdempotencyStore()
    store.record("k1", "m1", {}, 0)
    store.record("k2", "m2", {}, 0)
    assert store.size() == 2
    store.clear()
    assert store.size() == 0
    assert store.lookup("k1") is None


# ─── T012 ScanRegistry ───────────────────────────────────────────────────


def test_scan_registry_start_returns_fresh_record() -> None:
    reg = scans.ScanRegistry()
    record, coalesced = reg.start(scan_kind="panes", issued_by_app_session_id=1)
    assert coalesced is False
    assert record.state == scans.STATE_RUNNING
    assert record.scan_kind == "panes"
    assert record.completed_at_ms is None
    assert record.result is None
    assert reg.in_flight_count() == 1


def test_scan_registry_coalesces_same_kind_in_flight() -> None:
    """FR-030d: second caller for same kind receives in-flight scan_id."""
    reg = scans.ScanRegistry()
    a, a_coalesced = reg.start(scan_kind="panes", issued_by_app_session_id=1)
    b, b_coalesced = reg.start(scan_kind="panes", issued_by_app_session_id=2)
    assert a_coalesced is False
    assert b_coalesced is True
    assert a.scan_id == b.scan_id
    assert reg.in_flight_count() == 1


def test_scan_registry_does_not_coalesce_different_kinds() -> None:
    reg = scans.ScanRegistry()
    a, _ = reg.start(scan_kind="panes", issued_by_app_session_id=1)
    b, b_coalesced = reg.start(scan_kind="containers", issued_by_app_session_id=2)
    assert b_coalesced is False
    assert a.scan_id != b.scan_id
    assert reg.in_flight_count() == 2


def test_scan_registry_in_flight_cap_enforced() -> None:
    """FR-030e: in-flight cap enforced when a non-coalescing kind would
    push the count over the limit. v1.0 has only 2 kinds (containers,
    panes); same-kind calls coalesce per FR-030d, so the cap only
    bites with distinct kinds. We test with max_in_flight=1 to exercise
    the gate clearly.
    """
    reg = scans.ScanRegistry(max_in_flight=1)
    reg.start(scan_kind="panes", issued_by_app_session_id=1)
    with pytest.raises(scans.ScanCapExceeded):
        reg.start(scan_kind="containers", issued_by_app_session_id=2)


def test_scan_registry_completed_scan_frees_slot() -> None:
    """Completing a scan removes it from the in-flight count, even if it
    stays in the records list."""
    reg = scans.ScanRegistry(max_in_flight=1)
    a, _ = reg.start(scan_kind="panes", issued_by_app_session_id=1)
    reg.complete(a.scan_id, {"panes_total": 0})
    assert reg.in_flight_count() == 0
    # New scan now succeeds.
    b, _ = reg.start(scan_kind="containers", issued_by_app_session_id=2)
    assert b.state == scans.STATE_RUNNING


def test_scan_registry_complete_sets_state_and_done_event() -> None:
    reg = scans.ScanRegistry()
    record, _ = reg.start(scan_kind="panes", issued_by_app_session_id=1)
    assert not record.done.is_set()
    reg.complete(record.scan_id, {"panes_total": 7})
    looked = reg.lookup(record.scan_id)
    assert looked is not None
    assert looked.state == scans.STATE_COMPLETED
    assert looked.completed_at_ms is not None
    assert looked.result == {"panes_total": 7}
    assert looked.done.is_set()


def test_scan_registry_fail_sets_state_and_done_event() -> None:
    reg = scans.ScanRegistry()
    record, _ = reg.start(scan_kind="containers", issued_by_app_session_id=1)
    reg.fail(record.scan_id, {"error": "docker_unavailable"})
    looked = reg.lookup(record.scan_id)
    assert looked is not None
    assert looked.state == scans.STATE_FAILED
    assert looked.result == {"error": "docker_unavailable"}
    assert looked.done.is_set()


def test_scan_registry_fifo_eviction_at_record_cap() -> None:
    """FR-030c: at most MAX_RECORDS records; FIFO eviction."""
    reg = scans.ScanRegistry(max_records=3)
    ids: list[str] = []
    for i in range(3):
        rec, _ = reg.start(scan_kind="panes", issued_by_app_session_id=i)
        reg.complete(rec.scan_id, {"i": i})
        ids.append(rec.scan_id)
    assert reg.size() == 3

    # 4th completed scan evicts the oldest.
    rec, _ = reg.start(scan_kind="panes", issued_by_app_session_id=99)
    reg.complete(rec.scan_id, {"i": 99})
    assert reg.size() == 3
    assert reg.lookup(ids[0]) is None  # evicted
    assert reg.lookup(ids[1]) is not None
    assert reg.lookup(rec.scan_id) is not None


def test_scan_registry_lookup_unknown_returns_none() -> None:
    reg = scans.ScanRegistry()
    assert reg.lookup("does-not-exist") is None


def test_scan_registry_rejects_invalid_kind() -> None:
    reg = scans.ScanRegistry()
    with pytest.raises(ValueError):
        reg.start(scan_kind="agents", issued_by_app_session_id=1)


def test_scan_registry_state_set_excludes_expired() -> None:
    """FR-030c v1.0: scan_state closed set is exactly {running, completed,
    failed}; ``expired`` is intentionally absent."""
    valid = {scans.STATE_RUNNING, scans.STATE_COMPLETED, scans.STATE_FAILED}
    assert "expired" not in valid


# ─── T013 audit.emit_app_mutation ────────────────────────────────────────


def test_audit_emit_writes_row_with_origin_app(
    session: AppSession, tmp_path: Path
) -> None:
    """FR-044: row carries origin='app' + app_session_id."""
    events_file = tmp_path / "events.jsonl"
    ok = audit_mod.emit_app_mutation(
        events_file,
        event_type="agent_registered",
        payload={"agent_id": "agt-1"},
        session=session,
    )
    assert ok is True
    assert events_file.exists()
    lines = events_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json

    row = json.loads(lines[0])
    assert row["event_type"] == "agent_registered"
    assert row["origin"] == "app"
    assert row["app_session_id"] == session.app_session_id
    assert row["agent_id"] == "agt-1"
    assert "ts" in row  # FEAT-008 timestamp


def test_audit_never_writes_token(session: AppSession, tmp_path: Path) -> None:
    """SC-008: the opaque app_session_token MUST NOT appear in any row."""
    events_file = tmp_path / "events.jsonl"
    audit_mod.emit_app_mutation(
        events_file,
        event_type="route_created",
        payload={"route_id": "r-1"},
        session=session,
    )
    contents = events_file.read_text(encoding="utf-8")
    assert session.app_session_token not in contents


def test_audit_rejects_protected_payload_keys(
    session: AppSession, tmp_path: Path
) -> None:
    """event_type / origin / app_session_id / app_session_token are
    owned by the helper. event_type protection prevents accidental
    override of the upstream audit-event vocabulary."""
    events_file = tmp_path / "events.jsonl"
    for protected in ("event_type", "origin", "app_session_id", "app_session_token"):
        with pytest.raises(ValueError):
            audit_mod.emit_app_mutation(
                events_file,
                event_type="queue_approved",
                payload={protected: "should-not-pass"},
                session=session,
            )


def test_audit_no_events_file_is_noop(session: AppSession) -> None:
    """Synthetic harness path: events_file=None → returns False, no error."""
    ok = audit_mod.emit_app_mutation(
        None,
        event_type="agent_registered",
        payload={"agent_id": "agt-1"},
        session=session,
    )
    assert ok is False


def _force_jsonl_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch the underlying events writer to raise OSError every
    time. Simulates a JSONL outage deterministically across CI runner
    privilege levels — relying on directory-mode-based unwritability
    is unreliable because some CI runners run as root and ignore mode
    bits.
    """
    from agenttower.app_contract import audit as _audit_mod

    def _always_raise(*_args, **_kwargs):
        raise OSError(28, "No space left on device (simulated outage)")

    monkeypatch.setattr(_audit_mod._events_writer, "append_event", _always_raise)


def test_audit_jsonl_outage_does_not_raise(
    session: AppSession,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-044b: JSONL outage → mutation still succeeds; row dropped;
    one stderr warning per outage window."""
    audit_mod._reset_outage_warn_state()
    _force_jsonl_outage(monkeypatch)

    events_file = tmp_path / "events.jsonl"
    ok = audit_mod.emit_app_mutation(
        events_file,
        event_type="agent_registered",
        payload={"agent_id": "agt-1"},
        session=session,
    )
    assert ok is False, "audit emit must return False on JSONL outage"
    captured = capsys.readouterr()
    assert "JSONL audit write failed" in captured.err


def test_audit_outage_warning_is_rate_limited(
    session: AppSession,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-044b: one stderr warning per outage window (not per row)."""
    audit_mod._reset_outage_warn_state()
    _force_jsonl_outage(monkeypatch)

    events_file = tmp_path / "events.jsonl"
    for _ in range(5):
        audit_mod.emit_app_mutation(
            events_file,
            event_type="agent_registered",
            payload={"agent_id": "agt-1"},
            session=session,
        )
    captured = capsys.readouterr()
    # Exactly one warning across 5 attempts.
    assert captured.err.count("JSONL audit write failed") == 1
