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
    """FR-021a: state_priority comes from the normative mapping
    (Round-5 corrected FEAT-009 vocabulary)."""
    row = {
        "message_id": "msg-1",
        "state": "queued",
        "sender_agent_id": "agt-0",
        "target_agent_id": "agt-1",
        "enqueued_at": 1000,
        "last_updated_at": 1500,
    }
    out = vm.queue_view(row)
    assert out["state"] == "queued"
    assert out["state_priority"] == 1  # FR-021a: queued = 1
    # Round-5 QueueViewModel field set.
    assert out["sender_agent_id"] == "agt-0"
    assert out["enqueued_at"] == 1000
    assert "origin" not in out
    assert "route_id" not in out
    assert "created_at" not in out


@pytest.mark.parametrize(
    "state,expected_priority",
    [
        ("queued", 1),
        ("blocked", 2),
        ("failed", 3),
        ("delivered", 4),
        ("canceled", 5),
    ],
)
def test_queue_view_state_priority_normative_mapping(
    state: str, expected_priority: int
) -> None:
    """FR-021a: state_priority mapping is normative (FEAT-009 states)."""
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


def test_compact_event_summary_blank_when_no_type_or_agent() -> None:
    out = vm.compact_event({"event_id": 1})
    assert out["summary"] == "(event)"


def test_compact_queue_full_shape() -> None:
    out = vm.compact_queue({
        "message_id": "msg-1",
        "state": "queued",
        "target_agent_id": "agt-1",
        "created_at": 1000,
    })
    assert out["id"] == "msg-1"
    assert out["state"] == "queued"
    assert out["state_priority"] == 1  # FR-021a: queued = 1
    assert out["target_agent_id"] == "agt-1"
    assert out["timestamp"] == 1000
    assert "queued" in out["summary"]
    assert "agt-1" in out["summary"]


def test_compact_queue_unknown_state_falls_back_to_high_priority() -> None:
    out = vm.compact_queue({"message_id": "m", "state": "weird"})
    assert out["state_priority"] == 99


def test_compact_route_enabled_summary() -> None:
    out = vm.compact_route({"route_id": "r-1", "enabled": True, "created_at": 1000})
    assert out["id"] == "r-1"
    assert out["enabled"] is True
    assert out["type"] == "route"
    assert out["summary"] == "route r-1 (enabled)"


def test_compact_route_disabled_summary() -> None:
    out = vm.compact_route({"route_id": "r-2", "enabled": False, "created_at": 1000})
    assert out["enabled"] is False
    assert out["summary"] == "route r-2 (disabled)"


# ─── Helper coverage: _get / _coerce_int / _summarize_* ──────────────────


def test_get_helper_returns_default_for_none_row() -> None:
    """_get(None, ...) → default."""
    out = vm.container_view(None, pane_count=5)
    assert out["pane_count"] == 5


def test_get_helper_handles_object_with_attributes() -> None:
    """_get works on dataclass-like objects (getattr path)."""
    class Row:
        agent_id = "a-1"
        role = "slave"
        capability = "claude"
        label = "x"
        pane_id = "p-1"
        container_id = "c-1"
        registered_at = 1000
    out = vm.agent_view(Row())
    assert out["agent_id"] == "a-1"
    assert out["role"] == "slave"


def test_get_helper_handles_object_with_none_attribute() -> None:
    """getattr returning None should fall through to default (FR-022/023
    handling for optional fields)."""
    class Row:
        agent_id = "a-1"
        role = None  # noqa: deliberately None
        capability = "claude"
        label = "x"
        pane_id = "p-1"
        container_id = "c-1"
        registered_at = 1000
    out = vm.agent_view(Row())
    # role defaults to "unknown" in agent_view when row's role is None.
    assert out["role"] == "unknown"


def test_get_helper_handles_object_with_index_access() -> None:
    """sqlite3.Row-style mapping access via __getitem__."""
    class MappingLike:
        def __init__(self, data):
            self._data = data
        def __getitem__(self, key):
            return self._data[key]
    row = MappingLike({"container_id": "c-1", "name": "bench"})
    # _get should hit the __getitem__ branch when attribute access fails.
    # Note: agent_view doesn't help here because it expects agent fields;
    # use container_view which only needs container_id + name.
    out = vm.container_view(row)
    # container_view's _get path goes attribute-first; for this fake
    # object getattr raises AttributeError so __getitem__ fires.
    assert out["container_id"] == "c-1"
    assert out["name"] == "bench"


def test_log_attachment_view_coerce_int_handles_non_int() -> None:
    """_coerce_int handles strings, None, and weird values gracefully."""
    out = vm.log_attachment_view({
        "agent_id": "a",
        "status": "active",
        "bytes_written": "not-an-int",
    })
    assert out["bytes_written"] == 0


def test_log_attachment_view_coerce_int_handles_none() -> None:
    out = vm.log_attachment_view({
        "agent_id": "a",
        "status": "active",
        "bytes_written": None,
    })
    assert out["bytes_written"] == 0


def test_log_attachment_view_coerce_int_handles_numeric_string() -> None:
    out = vm.log_attachment_view({
        "agent_id": "a",
        "status": "active",
        "bytes_written": "4096",
    })
    assert out["bytes_written"] == 4096


def test_container_view_derived_state_only_when_provided() -> None:
    row = {"container_id": "c-1", "state": "inactive"}
    out = vm.container_view(row)
    assert out["state"] == "inactive"


def test_pane_view_full_shape_with_all_optional_kwargs() -> None:
    row = {
        "pane_id": "p-1",
        "container_id": "c-1",
        "tmux_socket": "/tmp/tmux/default",
        "session_name": "main",
        "window_index": 0,
        "pane_index": 1,
        "discovered_at": 1000,
        "last_seen_at": 2000,
    }
    out = vm.pane_view(row, linked_agent_id="a-1", container_name="bench")
    assert out["pane_id"] == "p-1"
    assert out["container_name"] == "bench"
    assert out["agent_id"] == "a-1"
    assert out["registered"] is True


def test_event_view_with_non_dict_payload_normalizes_to_empty() -> None:
    """payload must always serialize as a dict — strings/ints/None reset to {}."""
    out = vm.event_view({"event_id": 1, "event_type": "t", "payload": None})
    assert out["payload"] == {}

    out2 = vm.event_view({"event_id": 1, "event_type": "t", "payload": 42})
    assert out2["payload"] == {}


def test_queue_view_payload_preview_and_reason_fields() -> None:
    """Round-5 QueueViewModel: payload surfaces as a redacted
    ``payload_preview`` string; block_reason / failure_reason are
    nullable and projected from the row."""
    out = vm.queue_view({
        "message_id": "m",
        "state": "blocked",
        "block_reason": "operator_delayed",
        "payload_preview": "send build status…",
    })
    assert out["state"] == "blocked"
    assert out["state_priority"] == 2
    assert out["block_reason"] == "operator_delayed"
    assert out["failure_reason"] is None
    assert out["payload_preview"] == "send build status…"
    # Dropped fields must not reappear.
    assert "payload" not in out


def test_route_view_optional_target_template_defaults() -> None:
    """When source_scope/template/target are absent, defaults to {}."""
    out = vm.route_view({"route_id": "r-1", "enabled": True})
    assert out["source_scope"] == {}
    assert out["template"] == {}
    assert out["target"] == {}
