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
    """Round-6: FEAT-003 containers row uses first_seen_at /
    last_scanned_at, not created_at / last_seen_at."""
    row = {
        "container_id": "ctr-1",
        "name": "bench-1",
        "state": "active",
        "first_seen_at": "2026-05-19T00:00:00Z",
        "last_scanned_at": "2026-05-20T00:00:00Z",
        "image": "agenttower/bench:latest",
    }
    out = vm.container_view(row)
    assert out["container_id"] == "ctr-1"
    assert out["name"] == "bench-1"
    assert out["state"] == "active"
    assert out["first_seen_at"] == "2026-05-19T00:00:00Z"
    assert out["last_scanned_at"] == "2026-05-20T00:00:00Z"
    assert out["image"] == "agenttower/bench:latest"
    assert out["pane_count"] == 0
    assert out["registered_agent_count"] == 0
    assert "created_at" not in out
    assert "last_seen_at" not in out


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
    """Round-6: FEAT-007 log_attachments has attachment_id /
    container_id / log_path / source / last_status_at — and no
    last_output_at or bytes_written."""
    row = {
        "attachment_id": "la-1",
        "agent_id": "agt-1",
        "container_id": "ctr-1",
        "log_path": "/logs/agt-1.log",
        "status": "active",
        "source": "explicit",
        "attached_at": "2026-05-19T00:00:00Z",
        "last_status_at": "2026-05-19T01:00:00Z",
    }
    out = vm.log_attachment_view(row)
    assert out == {
        "attachment_id": "la-1",
        "agent_id": "agt-1",
        "container_id": "ctr-1",
        "log_path": "/logs/agt-1.log",
        "status": "active",
        "source": "explicit",
        "attached_at": "2026-05-19T00:00:00Z",
        "last_status_at": "2026-05-19T01:00:00Z",
    }


def test_log_attachment_view_handles_missing_optional_fields() -> None:
    """Robust to schema drift: absent fields default rather than crash."""
    row = {"agent_id": "agt-1", "status": "stale"}
    out = vm.log_attachment_view(row)
    assert out["status"] == "stale"
    assert out["log_path"] == ""
    assert out["attachment_id"] is None
    # Dropped fields must not reappear.
    assert "bytes_written" not in out
    assert "last_output_at" not in out


# ─── EventViewModel ──────────────────────────────────────────────────────


def test_event_view_full_shape() -> None:
    """Round-6: FEAT-008 events row has observed_at + excerpt +
    classifier_rule_id — no origin, no structured payload."""
    row = {
        "event_id": 100,
        "event_type": "completed",
        "agent_id": "agt-1",
        "observed_at": "2026-05-20T00:00:00Z",
        "excerpt": "build finished ok",
        "classifier_rule_id": "rule-7",
    }
    out = vm.event_view(row)
    assert out["event_id"] == 100
    assert out["event_type"] == "completed"
    assert out["agent_id"] == "agt-1"
    assert out["observed_at"] == "2026-05-20T00:00:00Z"
    assert out["excerpt"] == "build finished ok"
    assert out["classifier_rule_id"] == "rule-7"
    assert "completed" in out["summary"]
    assert "agt-1" in out["summary"]
    # Dropped fields must not reappear.
    assert "origin" not in out
    assert "payload" not in out
    assert "created_at" not in out


def test_event_view_missing_optional_fields_default() -> None:
    """Absent excerpt / classifier_rule_id default to empty string."""
    row = {"event_id": 1, "event_type": "activity"}
    out = vm.event_view(row)
    assert out["excerpt"] == ""
    assert out["classifier_rule_id"] == ""


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
    """Round-6: FEAT-010 routes row stores source-scope / target /
    master as paired *_kind|*_rule + *_value columns; view composes
    them into nested objects. Timestamp is updated_at, not last_used_at."""
    row = {
        "route_id": "r-1",
        "enabled": True,
        "event_type": "completed",
        "source_scope_kind": "role",
        "source_scope_value": "master",
        "target_rule": "role",
        "target_value": "slave",
        "master_rule": "auto",
        "master_value": None,
        "template": "hello {agent}",
        "last_consumed_event_id": 99,
        "created_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-20T00:00:00Z",
    }
    out = vm.route_view(row)
    assert out["route_id"] == "r-1"
    assert out["enabled"] is True
    assert out["event_type"] == "completed"
    assert out["source_scope"] == {"kind": "role", "value": "master"}
    assert out["target"] == {"rule": "role", "value": "slave"}
    assert out["master"] == {"rule": "auto", "value": None}
    assert out["template"] == "hello {agent}"
    assert out["last_consumed_event_id"] == 99
    assert out["created_at"] == "2026-05-19T00:00:00Z"
    assert out["updated_at"] == "2026-05-20T00:00:00Z"
    assert "last_used_at" not in out


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


def test_coerce_int_handles_numeric_string() -> None:
    """container_view coerces a caller-supplied numeric-string count."""
    out = vm.container_view(
        {"container_id": "c-1"}, pane_count="5", registered_agent_count="2"  # type: ignore[arg-type]
    )
    assert out["pane_count"] == 5
    assert out["registered_agent_count"] == 2


def test_coerce_int_handles_garbage_string() -> None:
    """A non-numeric count coerces to 0 rather than crashing."""
    out = vm.container_view(
        {"container_id": "c-1"}, pane_count="not-an-int"  # type: ignore[arg-type]
    )
    assert out["pane_count"] == 0


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


def test_event_view_excerpt_is_a_string() -> None:
    """Round-6: events carry an `excerpt` string (already redacted by
    FEAT-008), not a structured payload object."""
    out = vm.event_view({
        "event_id": 1,
        "event_type": "error",
        "agent_id": "agt-9",
        "excerpt": "traceback: ValueError",
    })
    assert out["excerpt"] == "traceback: ValueError"
    assert isinstance(out["excerpt"], str)


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


def test_route_view_paired_columns_default_when_absent() -> None:
    """Round-6: source_scope/target/master compose from paired
    *_kind|*_rule + *_value columns; absent → {kind|rule: "", value: None}.
    template defaults to "" (it is a string column, not an object)."""
    out = vm.route_view({"route_id": "r-1", "enabled": True})
    assert out["source_scope"] == {"kind": "", "value": None}
    assert out["target"] == {"rule": "", "value": None}
    assert out["master"] == {"rule": "", "value": None}
    assert out["template"] == ""
