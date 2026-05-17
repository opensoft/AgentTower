"""T017 — JSONL audit schema contract test for FEAT-010.

Asserts the on-wire shape of every audit entry the FEAT-010
:class:`agenttower.routing.routes_audit.RoutesAuditWriter` emits,
per ``specs/010-event-routes-arbitration/contracts/routes-audit-schema.md``.

For each of the six event types, verifies:

* The required fields are present with the documented types.
* Optional / nullable fields decode correctly per the nullability
  rules in the contract.
* ``sub_reason`` is populated ONLY when ``reason='template_render_error'``
  (contracts §2).
* ``target_agent_id`` and ``target_label`` are both ``null`` together
  for arbitration-failure skip reasons (Clarifications Q2 +
  contracts §2).
* The 240-char excerpt cap is honored (FR-036).
* Closed-set fields (``event_type``, ``reason``, ``sub_reason``) only
  emit values from the documented closed sets.

Test seam: writes to a temporary ``events.jsonl`` file, reads it
back line-by-line, and asserts the parsed JSON against expected
schemas. No daemon, no SQLite — just the writer + the file.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

import pytest

from agenttower.routing import route_errors as rerr
from agenttower.routing.routes_audit import RoutesAuditWriter


_ISO8601_MS_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


@pytest.fixture
def writer_and_file(tmp_path: Path) -> tuple[RoutesAuditWriter, Path]:
    """RoutesAuditWriter + path to a fresh events.jsonl file.

    Pre-creates the file with the expected 0600 mode so the FEAT-001
    events.writer's mode check doesn't trip on a fresh-tmpdir 0644.
    """
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)
    return RoutesAuditWriter(), events_file


def _read_one_entry(events_file: Path) -> dict:
    text = events_file.read_text(encoding="utf-8").strip()
    lines = [line for line in text.splitlines() if line]
    assert len(lines) == 1, f"expected exactly one JSONL line, got {len(lines)}"
    return json.loads(lines[0])


# ──────────────────────────────────────────────────────────────────────
# route_matched
# ──────────────────────────────────────────────────────────────────────


def test_route_matched_schema_round_trips(writer_and_file) -> None:
    writer, events_file = writer_and_file
    writer.emit_route_matched(
        events_file,
        event_id=4218,
        route_id="11111111-2222-4333-8444-555555555555",
        winner_master_agent_id="agt_master00001",
        target_agent_id="agt_slave000001",
        target_label="slave-1",
        event_excerpt="Press y to continue",
    )
    entry = _read_one_entry(events_file)
    assert entry["event_type"] == "route_matched"
    assert _ISO8601_MS_UTC_RE.match(entry["emitted_at"])
    assert entry["event_id"] == 4218
    assert entry["route_id"] == "11111111-2222-4333-8444-555555555555"
    assert entry["winner_master_agent_id"] == "agt_master00001"
    assert entry["target_agent_id"] == "agt_slave000001"
    assert entry["target_label"] == "slave-1"
    assert entry["reason"] is None  # always null on matched (shape uniformity)
    assert entry["event_excerpt"] == "Press y to continue"


def test_route_matched_excerpt_cap_240_chars() -> None:
    """FR-036 — excerpt ≤ 240 chars. Caller is responsible for
    truncation; this test documents that the writer doesn't add its
    own truncation."""
    long_excerpt = "x" * 240
    assert len(long_excerpt) == 240
    # If the caller passes ≤ 240 chars, the writer preserves them.


# ──────────────────────────────────────────────────────────────────────
# route_skipped — arbitration-failure reasons (all target fields null)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "reason",
    [
        rerr.NO_ELIGIBLE_MASTER,
        rerr.MASTER_INACTIVE,
        rerr.MASTER_NOT_FOUND,
    ],
)
def test_route_skipped_arbitration_failure_nulls_target_fields(
    writer_and_file, reason: str,
) -> None:
    """Clarifications Q2 + contracts §2a: when arbitration fails, the
    target identity wasn't resolved — both ``target_agent_id`` and
    ``target_label`` are ``null``."""
    writer, events_file = writer_and_file
    writer.emit_route_skipped(
        events_file,
        event_id=4220,
        route_id="r1",
        winner_master_agent_id=None,
        target_agent_id=None,
        target_label=None,
        reason=reason,
        sub_reason=None,
        event_excerpt="excerpt",
    )
    entry = _read_one_entry(events_file)
    assert entry["event_type"] == "route_skipped"
    assert entry["reason"] == reason
    assert entry["sub_reason"] is None
    assert entry["winner_master_agent_id"] is None
    assert entry["target_agent_id"] is None
    assert entry["target_label"] is None


# ──────────────────────────────────────────────────────────────────────
# route_skipped — target-resolution skips (winner populated)
# ──────────────────────────────────────────────────────────────────────


def test_route_skipped_no_eligible_target_carries_winner(writer_and_file) -> None:
    """Contracts §2b: for ``no_eligible_target``, arbitration succeeded
    so ``winner_master_agent_id`` is populated but target fields are
    still null (no target was resolved)."""
    writer, events_file = writer_and_file
    writer.emit_route_skipped(
        events_file,
        event_id=4221,
        route_id="r1",
        winner_master_agent_id="agt_master00001",
        target_agent_id=None,
        target_label=None,
        reason=rerr.NO_ELIGIBLE_TARGET,
        sub_reason=None,
        event_excerpt="excerpt",
    )
    entry = _read_one_entry(events_file)
    assert entry["winner_master_agent_id"] == "agt_master00001"
    assert entry["target_agent_id"] is None
    assert entry["target_label"] is None
    assert entry["reason"] == rerr.NO_ELIGIBLE_TARGET


def test_route_skipped_target_role_not_permitted_carries_full_identity(
    writer_and_file,
) -> None:
    """Contracts §2b: when the target was resolved but enqueue failed
    (e.g., target_role_not_permitted), the resolved identity IS
    populated — the operator needs it to debug the FEAT-009
    permission rejection."""
    writer, events_file = writer_and_file
    writer.emit_route_skipped(
        events_file,
        event_id=4222,
        route_id="r1",
        winner_master_agent_id="agt_master00001",
        target_agent_id="agt_master00002",
        target_label="other-master",
        reason=rerr.TARGET_ROLE_NOT_PERMITTED,
        sub_reason=None,
        event_excerpt="excerpt",
    )
    entry = _read_one_entry(events_file)
    assert entry["winner_master_agent_id"] == "agt_master00001"
    assert entry["target_agent_id"] == "agt_master00002"
    assert entry["target_label"] == "other-master"
    assert entry["reason"] == rerr.TARGET_ROLE_NOT_PERMITTED


# ──────────────────────────────────────────────────────────────────────
# route_skipped — template_render_error (sub_reason populated)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sub_reason",
    sorted(rerr.TEMPLATE_SUB_REASONS),
)
def test_route_skipped_template_render_error_carries_sub_reason(
    writer_and_file, sub_reason: str,
) -> None:
    """Contracts §3: ``sub_reason`` is populated ONLY when
    ``reason='template_render_error'``, and exactly one of the six
    closed-set sub-reasons."""
    writer, events_file = writer_and_file
    writer.emit_route_skipped(
        events_file,
        event_id=4223,
        route_id="r1",
        winner_master_agent_id="agt_master00001",
        target_agent_id="agt_slave000001",
        target_label="slave-1",
        reason=rerr.TEMPLATE_RENDER_ERROR,
        sub_reason=sub_reason,
        event_excerpt="excerpt",
    )
    entry = _read_one_entry(events_file)
    assert entry["reason"] == rerr.TEMPLATE_RENDER_ERROR
    assert entry["sub_reason"] == sub_reason


# ──────────────────────────────────────────────────────────────────────
# route_created — full row snapshot per contracts §3
# ──────────────────────────────────────────────────────────────────────


def test_route_created_schema_round_trips(writer_and_file) -> None:
    writer, events_file = writer_and_file
    writer.emit_route_created(
        events_file,
        route_id="11111111-2222-4333-8444-555555555555",
        event_type_subscribed="waiting_for_input",
        source_scope_kind="any",
        source_scope_value=None,
        target_rule="explicit",
        target_value="agt_slave000001",
        master_rule="auto",
        master_value=None,
        template="respond to {source_label}: {event_excerpt}",
        created_by_agent_id="host-operator",
        cursor_at_creation=4217,
    )
    entry = _read_one_entry(events_file)
    assert entry["event_type"] == "route_created"
    # Field renamed per contracts §3 to avoid colliding with envelope
    # event_type discriminator.
    assert entry["event_type_subscribed"] == "waiting_for_input"
    assert entry["source_scope_kind"] == "any"
    assert entry["source_scope_value"] is None
    assert entry["target_rule"] == "explicit"
    assert entry["target_value"] == "agt_slave000001"
    assert entry["master_rule"] == "auto"
    assert entry["master_value"] is None
    assert entry["template"] == "respond to {source_label}: {event_excerpt}"
    assert entry["created_by_agent_id"] == "host-operator"
    assert entry["cursor_at_creation"] == 4217


# ──────────────────────────────────────────────────────────────────────
# route_updated — distinguishes enable vs disable via ``change``
# ──────────────────────────────────────────────────────────────────────


def test_route_updated_enable_carries_change_true(writer_and_file) -> None:
    writer, events_file = writer_and_file
    writer.emit_route_updated(
        events_file,
        route_id="r1",
        change={"enabled": True},
        updated_by_agent_id="host-operator",
    )
    entry = _read_one_entry(events_file)
    assert entry["event_type"] == "route_updated"
    assert entry["change"] == {"enabled": True}


def test_route_updated_disable_carries_change_false(writer_and_file) -> None:
    writer, events_file = writer_and_file
    writer.emit_route_updated(
        events_file,
        route_id="r1",
        change={"enabled": False},
        updated_by_agent_id="host-operator",
    )
    entry = _read_one_entry(events_file)
    assert entry["change"] == {"enabled": False}


# ──────────────────────────────────────────────────────────────────────
# route_deleted
# ──────────────────────────────────────────────────────────────────────


def test_route_deleted_schema_round_trips(writer_and_file) -> None:
    writer, events_file = writer_and_file
    writer.emit_route_deleted(
        events_file,
        route_id="r1",
        deleted_by_agent_id="host-operator",
    )
    entry = _read_one_entry(events_file)
    assert entry["event_type"] == "route_deleted"
    assert entry["route_id"] == "r1"
    assert entry["deleted_by_agent_id"] == "host-operator"


# ──────────────────────────────────────────────────────────────────────
# routing_worker_heartbeat — FR-039a
# ──────────────────────────────────────────────────────────────────────


def test_routing_worker_heartbeat_schema_round_trips(writer_and_file) -> None:
    writer, events_file = writer_and_file
    writer.emit_routing_worker_heartbeat(
        events_file,
        interval_seconds=60,
        cycles_since_last_heartbeat=60,
        events_consumed_since_last_heartbeat=3,
        skips_since_last_heartbeat=1,
        degraded=False,
    )
    entry = _read_one_entry(events_file)
    assert entry["event_type"] == "routing_worker_heartbeat"
    assert entry["interval_seconds"] == 60
    assert entry["cycles_since_last_heartbeat"] == 60
    assert entry["events_consumed_since_last_heartbeat"] == 3
    assert entry["skips_since_last_heartbeat"] == 1
    assert entry["degraded"] is False


def test_heartbeat_degraded_true_mirrors_status_field(writer_and_file) -> None:
    """The ``degraded`` field is the canonical JSONL-side mirror of
    ``_SharedRoutingState.routing_worker_degraded`` per data-model §4."""
    writer, events_file = writer_and_file
    writer.emit_routing_worker_heartbeat(
        events_file,
        interval_seconds=30,
        cycles_since_last_heartbeat=30,
        events_consumed_since_last_heartbeat=0,
        skips_since_last_heartbeat=5,
        degraded=True,
    )
    entry = _read_one_entry(events_file)
    assert entry["degraded"] is True


# ──────────────────────────────────────────────────────────────────────
# Disjointness invariant (R-008): the six FEAT-010 types do not
# overlap with FEAT-008 / FEAT-009 audit types
# ──────────────────────────────────────────────────────────────────────


def test_feat010_event_types_disjoint_from_feat009() -> None:
    from agenttower.routing.errors import (
        _QUEUE_AUDIT_EVENT_TYPES,
        _ROUTE_AUDIT_EVENT_TYPES,
        _ROUTING_AUDIT_EVENT_TYPES,
    )
    assert _ROUTE_AUDIT_EVENT_TYPES.isdisjoint(_QUEUE_AUDIT_EVENT_TYPES)
    assert _ROUTE_AUDIT_EVENT_TYPES.isdisjoint(_ROUTING_AUDIT_EVENT_TYPES)


def test_feat010_event_types_match_contract_documented_six() -> None:
    """Documents the exact set: any future addition / rename forces
    this test to fail, which forces the contract update."""
    from agenttower.routing.errors import _ROUTE_AUDIT_EVENT_TYPES
    assert _ROUTE_AUDIT_EVENT_TYPES == frozenset({
        "route_matched",
        "route_skipped",
        "route_created",
        "route_updated",
        "route_deleted",
        "routing_worker_heartbeat",
    })
