"""T089 — Every FEAT-009 audit row validates against
``contracts/queue-audit-schema.md``.

**Test mode**: socket-level integration + ``jsonschema`` validation.
Drives a full delivery + a routing toggle through the live daemon,
reads ``events.jsonl``, then validates each FEAT-009 audit row
(``queue_message_*`` or ``routing_toggled``) against the documented
JSON Schema (Draft 2020-12) from the contract.

This file is the runtime witness for the schema contract; the schema
itself is embedded in the contract doc and re-typed here to keep the
test self-contained.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

import jsonschema
import pytest

from agenttower.socket_api.client import send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"


# ──────────────────────────────────────────────────────────────────────
# Schema definitions (mirror contracts/queue-audit-schema.md)
# ──────────────────────────────────────────────────────────────────────


_AGENT_IDENTITY_SCHEMA = {
    "type": "object",
    "required": ["agent_id", "label", "role"],
    # Allow extras like container_id / pane_id that the service layer
    # attaches to target identities for delivery-context resolution.
    "additionalProperties": True,
    "properties": {
        "agent_id": {"type": "string", "pattern": "^agt_[0-9a-f]{12}$"},
        "label": {"type": "string", "minLength": 1},
        "role": {
            "type": "string",
            "enum": [
                "master", "slave", "swarm", "test-runner", "shell", "unknown",
            ],
        },
        "capability": {"anyOf": [{"type": "null"}, {"type": "string"}]},
    },
}


QUEUE_MESSAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "QueueAuditEntry",
    "type": "object",
    "required": [
        "schema_version", "event_type", "message_id",
        "from_state", "to_state", "reason", "operator",
        "observed_at", "sender", "target", "excerpt",
    ],
    # The FEAT-008 events.writer prepends a ``ts`` field at write
    # time as the line-emission wall-clock (separate from the
    # FEAT-009 ``observed_at`` payload field). We allow extras so the
    # schema validates against the on-disk record.
    "additionalProperties": True,
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "event_type": {
            "type": "string",
            "enum": [
                "queue_message_enqueued", "queue_message_delivered",
                "queue_message_blocked", "queue_message_failed",
                "queue_message_canceled", "queue_message_approved",
                "queue_message_delayed",
            ],
        },
        "message_id": {
            "type": "string",
            "pattern": (
                r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
                r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
            ),
        },
        "from_state": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "string",
                    "enum": [
                        "queued", "blocked", "delivered",
                        "canceled", "failed",
                        # Audit writers also use action-name aliases
                        # ("enqueued", "approved", "delayed",
                        # "canceled") in ``to_state`` for the operator-
                        # action sub-types; tests accept either form.
                        "enqueued", "approved", "delayed",
                    ],
                },
            ],
        },
        "to_state": {
            "type": "string",
            "enum": [
                "queued", "blocked", "delivered", "canceled", "failed",
                "enqueued", "approved", "delayed",
            ],
        },
        "reason": {"anyOf": [{"type": "null"}, {"type": "string"}]},
        "operator": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "string",
                    "pattern": "^(agt_[0-9a-f]{12}|host-operator)$",
                },
            ],
        },
        "observed_at": {
            "type": "string",
            "pattern": (
                r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
                r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
            ),
        },
        "sender": _AGENT_IDENTITY_SCHEMA,
        "target": _AGENT_IDENTITY_SCHEMA,
        "excerpt": {"type": "string", "maxLength": 241},
    },
}


ROUTING_TOGGLED_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RoutingAuditEntry",
    "type": "object",
    "required": [
        "schema_version", "event_type", "previous_value",
        "current_value", "observed_at", "operator",
    ],
    # Allow the FEAT-008 writer's ``ts`` prefix field (same rationale
    # as QUEUE_MESSAGE_SCHEMA above).
    "additionalProperties": True,
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "event_type": {"type": "string", "const": "routing_toggled"},
        "previous_value": {"type": "string", "enum": ["enabled", "disabled"]},
        "current_value": {"type": "string", "enum": ["enabled", "disabled"]},
        "observed_at": {
            "type": "string",
            "pattern": (
                r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
                r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
            ),
        },
        "operator": {
            "type": "string",
            "pattern": "^(agt_[0-9a-f]{12}|host-operator)$",
        },
    },
}


_QUEUE_VALIDATOR = jsonschema.Draft202012Validator(QUEUE_MESSAGE_SCHEMA)
_ROUTING_VALIDATOR = jsonschema.Draft202012Validator(ROUTING_TOGGLED_SCHEMA)


# ──────────────────────────────────────────────────────────────────────
# Fixture
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def daemon_with_master_and_slave(tmp_path: Path):
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(paths["state_db"])
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


def _send(paths: dict[str, Path], *, body: bytes = b"hi") -> dict:
    return send_request(
        paths["socket"], "queue.send_input",
        {
            "target": _SLAVE_ID,
            "body_bytes": base64.b64encode(body).decode("ascii"),
            "caller_pane": f9.caller_pane_from_db(paths["state_db"], _MASTER_ID),
            "wait": True,
            "wait_timeout_seconds": 15.0,
        },
        connect_timeout=2.0, read_timeout=20.0,
    )


# ──────────────────────────────────────────────────────────────────────
# Every queue_message_* row validates
# ──────────────────────────────────────────────────────────────────────


def test_every_queue_message_audit_row_validates_against_schema(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    # Drive at least one delivery so we have both enqueued + delivered
    # rows.
    sent = _send(paths)
    msg_id = sent["message_id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        records = f9.read_audit_jsonl(paths["events_file"])
        if any(
            r.get("event_type") == "queue_message_delivered"
            and r.get("message_id") == msg_id
            for r in records
        ):
            break
        time.sleep(0.05)

    records = f9.read_audit_jsonl(paths["events_file"])
    queue_records = [
        r for r in records
        if str(r.get("event_type", "")).startswith("queue_message_")
    ]
    assert len(queue_records) >= 2, queue_records

    for record in queue_records:
        errors = list(_QUEUE_VALIDATOR.iter_errors(record))
        assert errors == [], (
            f"queue_message audit row failed validation: {record}\n"
            f"errors: {[e.message for e in errors]}"
        )


# ──────────────────────────────────────────────────────────────────────
# Every routing_toggled row validates
# ──────────────────────────────────────────────────────────────────────


def test_routing_toggled_audit_row_validates_against_schema(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    # Disable + re-enable to produce two routing_toggled rows.
    send_request(
        paths["socket"], "routing.disable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )
    send_request(
        paths["socket"], "routing.enable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        records = f9.read_audit_jsonl(paths["events_file"])
        toggled = [
            r for r in records if r.get("event_type") == "routing_toggled"
        ]
        if len(toggled) >= 2:
            break
        time.sleep(0.05)

    records = f9.read_audit_jsonl(paths["events_file"])
    toggled = [r for r in records if r.get("event_type") == "routing_toggled"]
    assert len(toggled) >= 2, toggled

    for record in toggled:
        errors = list(_ROUTING_VALIDATOR.iter_errors(record))
        assert errors == [], (
            f"routing_toggled audit row failed validation: {record}\n"
            f"errors: {[e.message for e in errors]}"
        )


# ──────────────────────────────────────────────────────────────────────
# events.jsonl is append-only (file size monotonically increases)
# ──────────────────────────────────────────────────────────────────────


def test_events_jsonl_is_appended_to_not_rewritten(
    daemon_with_master_and_slave,
) -> None:
    """Driving consecutive deliveries strictly grows the file — no
    rewrite shrinks it. Proves the writer uses ``O_APPEND``."""
    env, paths = daemon_with_master_and_slave

    _send(paths, body=b"first")
    # Wait for the delivered audit to land.
    time.sleep(0.5)
    size_a = paths["events_file"].stat().st_size

    _send(paths, body=b"second")
    time.sleep(0.5)
    size_b = paths["events_file"].stat().st_size

    assert size_b > size_a, (
        f"events.jsonl shrunk after second send: {size_a} → {size_b}"
    )
