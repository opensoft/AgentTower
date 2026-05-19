"""FEAT-011 view-model builder unit tests (T015, data-model.md §View Models).

Pure projection tests — feed each builder a synthetic DAO row (dict
form), assert the output shape matches the data-model spec, and
exercise the derived-field semantics (registered/agent_id on pane,
log_attached/pane_active on agent, state_priority on queue, etc.).
"""

from __future__ import annotations

import pytest

from agenttower.app_contract import view_models as vm


# ─── ContainerViewModel ──────────────────────────────────────────────────


def test_container_view_minimal_row() -> None:
    row = {
        "container_id": "ctr-1",
        "name": "bench-1",
        "state": "active",
        "created_at": 1000,
        "last_seen_at": 2000,
        "image": "agenttower/bench:latest",
    }
    out = vm.container_view(row)
    assert out["container_id"] == "ctr-1"
    assert out["name"] == "bench-1"
    assert out["state"] == "active"
    assert out["created_at"] == 1000
    assert out["last_seen_at"] == 2000
    assert out["image"] == "agenttower/bench:latest"
    assert out["pane_count"] == 0
    assert out["registered_agent_count"] == 0


def test_container_view_derived_state_override() -> None:
    """FR-016a: caller can override state to degraded_scan when join
    with last-scan health classifies it that way."""
    row = {"container_id": "ctr-1", "name": "bench", "state": "active"}
    out = vm.container_view(row, derived_state="degraded_scan")
    assert out["state"] == "degraded_scan"


def test_container_view_derived_counts() -> None:
    row = {"container_id": "ctr-1"}
    out = vm.container_view(row, pane_count=5, registered_agent_count=2)
    assert out["pane_count"] == 5
    assert out["registered_agent_count"] == 2


# ─── PaneViewModel ───────────────────────────────────────────────────────


def test_pane_view_unregistered() -> None:
    """FR-022: pane with no linked agent → registered=False, agent_id=None."""
    row = {
        "pane_id": "p-1",
        "container_id": "ctr-1",
        "tmux_socket": "/tmp/tmux-1000/default",
        "session_name": "main",
        "window_index": 0,
        "pane_index": 1,
        "discovered_at": 1000,
        "last_seen_at": 2000,
    }
    out = vm.pane_view(row, container_name="bench-1")
    assert out["pane_id"] == "p-1"
    assert out["container_name"] == "bench-1"
    assert out["registered"] is False
    assert out["agent_id"] is None
    assert out["window_index"] == 0
    assert out["pane_index"] == 1


def test_pane_view_registered() -> None:
    """FR-022: when a linked agent exists, registered=True + agent_id set."""
    row = {"pane_id": "p-1", "container_id": "ctr-1"}
    out = vm.pane_view(row, linked_agent_id="agt-1", container_name="bench-1")
    assert out["registered"] is True
    assert out["agent_id"] == "agt-1"


# ─── AgentViewModel ──────────────────────────────────────────────────────


def test_agent_view_role_priority_derived_from_role() -> None:
    """FR-021a: role_priority comes from the normative mapping."""
    row = {
        "agent_id": "agt-1",
        "role": "master",
        "capability": "general",
        "label": "main",
        "pane_id": "p-1",
        "container_id": "ctr-1",
        "registered_at": 1000,
    }
    out = vm.agent_view(row)
    assert out["role"] == "master"
    assert out["role_priority"] == 1  # FR-021a: master = 1


@pytest.mark.parametrize(
    "role,expected_priority",
    [
        ("master", 1),
        ("slave", 2),
        ("swarm", 3),
        ("test-runner", 4),
        ("shell", 5),
        ("unknown", 6),
    ],
)
def test_agent_view_role_priority_normative_mapping(
    role: str, expected_priority: int
) -> None:
    """FR-021a: role_priority mapping is normative."""
    out = vm.agent_view({"agent_id": "a", "role": role})
    assert out["role_priority"] == expected_priority


def test_agent_view_derived_log_and_pane_flags() -> None:
    """FR-023: log_attached / pane_active are derived joins."""
    row = {"agent_id": "agt-1", "role": "slave"}
    out = vm.agent_view(row, log_attached=True, pane_active=False)
    assert out["log_attached"] is True
    assert out["pane_active"] is False

    out2 = vm.agent_view(row, log_attached=False, pane_active=True)
    assert out2["log_attached"] is False
    assert out2["pane_active"] is True


def test_agent_view_clearable_fields_can_be_null() -> None:
    """project_path and parent_agent_id are nullable."""
    row = {"agent_id": "agt-1", "role": "slave"}
    out = vm.agent_view(row)
    assert out["project_path"] is None
    assert out["parent_agent_id"] is None


# ─── LogAttachmentViewModel ──────────────────────────────────────────────


def test_log_attachment_view_minimal_row() -> None:
    row = {
        "agent_id": "agt-1",
        "attached_at": 1000,
        "last_output_at": 1500,
        "bytes_written": 4096,
        "status": "active",
    }
    out = vm.log_attachment_view(row)
    assert out == {
        "agent_id": "agt-1",
        "attached_at": 1000,
        "last_output_at": 1500,
        "bytes_written": 4096,
        "status": "active",
    }


def test_log_attachment_view_handles_missing_bytes_written() -> None:
    """Robust to schema drift: missing bytes_written → 0, not crash."""
    row = {"agent_id": "agt-1", "status": "stopped"}
    out = vm.log_attachment_view(row)
    assert out["bytes_written"] == 0
    assert out["status"] == "stopped"


# ─── EventViewModel ──────────────────────────────────────────────────────


def test_event_view_full_shape() -> None:
    row = {
        "event_id": 100,
        "event_type": "agent_registered",
        "origin": "app",
        "created_at": 1000,
        "agent_id": "agt-1",
        "payload": {"role": "slave"},
    }
    out = vm.event_view(row)
    assert out["event_id"] == 100
    assert out["event_type"] == "agent_registered"
    assert out["origin"] == "app"
    assert out["payload"] == {"role": "slave"}
    assert "agent_registered" in out["summary"]
    assert "agt-1" in out["summary"]


def test_event_view_payload_defaults_to_empty_object() -> None:
    """Payload must always be a dict — non-dict values get replaced with {}."""
    row = {"event_id": 1, "payload": "not-a-dict"}
    out = vm.event_view(row)
    assert out["payload"] == {}


# ─── QueueViewModel ──────────────────────────────────────────────────────


def test_queue_view_state_priority_derived() -> None:
    """FR-021a: state_priority comes from the normative mapping."""
    row = {
        "message_id": "msg-1",
        "state": "pending",
        "origin": "direct",
        "target_agent_id": "agt-1",
        "payload": {"text": "hi"},
        "created_at": 1000,
        "last_updated_at": 1500,
    }
    out = vm.queue_view(row)
    assert out["state"] == "pending"
    assert out["state_priority"] == 1  # FR-021a: pending = 1


@pytest.mark.parametrize(
    "state,expected_priority",
    [
        ("pending", 1),
        ("in_flight", 2),
        ("blocked", 3),
        ("expired", 4),
        ("cancelled", 5),
        ("delivered", 6),
    ],
)
def test_queue_view_state_priority_normative_mapping(
    state: str, expected_priority: int
) -> None:
    """FR-021a: state_priority mapping is normative."""
    out = vm.queue_view({"state": state})
    assert out["state_priority"] == expected_priority


def test_queue_view_unknown_state_falls_back_to_high_priority() -> None:
    """Defensive: unknown state → priority 99 so it sorts last."""
    out = vm.queue_view({"state": "frobnicated"})
    assert out["state_priority"] == 99


# ─── RouteViewModel ──────────────────────────────────────────────────────


def test_route_view_full_shape() -> None:
    row = {
        "route_id": "r-1",
        "enabled": True,
        "source_scope": {"event_type": "task_done"},
        "template": {"body": "hello {agent}"},
        "target": {"role": "slave"},
        "last_consumed_event_id": 99,
        "created_at": 1000,
        "last_used_at": 2000,
    }
    out = vm.route_view(row)
    assert out["route_id"] == "r-1"
    assert out["enabled"] is True
    assert out["source_scope"] == {"event_type": "task_done"}
    assert out["template"] == {"body": "hello {agent}"}
    assert out["target"] == {"role": "slave"}
    assert out["last_consumed_event_id"] == 99


def test_route_view_disabled_route_enabled_is_false() -> None:
    row = {"route_id": "r-1", "enabled": False}
    out = vm.route_view(row)
    assert out["enabled"] is False


# ─── Compact builders (regression coverage from pre-existing) ────────────


def test_compact_event_summary_includes_agent_when_present() -> None:
    out = vm.compact_event({"event_id": 1, "event_type": "task_done", "agent_id": "agt-1"})
    assert out["summary"] == "task_done from agt-1"


def test_compact_event_summary_fallbacks_to_type_only() -> None:
    out = vm.compact_event({"event_id": 1, "event_type": "task_done"})
    assert out["summary"] == "task_done"
