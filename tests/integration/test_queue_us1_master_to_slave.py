"""T055 — US1 master-to-slave delivery acceptance scenarios.

**Test mode**: socket-level integration. Talks to the daemon via the
FEAT-002 ``send_request`` client and bypasses the CLI's pane-discovery
layer. Caller-context handling is exercised by the CLI integration
tests under ``test_queue_us2_*.py`` (host-side refusal) and by the
fresh-container E2E (the real master pane → real send-input flow).

What this test does NOT cover:

* Byte-exact tmux paste correctness — covered by unit tests
  (``test_tmux_adapter_*.py``, ``test_delivery_worker_*.py``) and by
  the fresh-container E2E.
* CLI ``send-input`` pane resolution from a simulated bench container
  — covered by ``test_queue_us2_send_input_host_refused.py`` (refusal
  path) and the fresh-container E2E (happy path).

What this test DOES cover (all five US1 acceptance scenarios):

1. End-to-end ``queue.send_input`` reaches ``delivered``.
2. Response payload matches the FR-011 row schema.
3. ``queue.list`` returns the delivered row.
4. ``events.jsonl`` contains both ``queue_message_enqueued`` and
   ``queue_message_delivered`` rows referencing the same ``message_id``.
5. ``master → swarm`` permission is allowed (parametrized).
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

import pytest

from agenttower.socket_api.client import send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"
_SWARM_ID = "agt_cccccccccccc"
_SWARM_PANE = "%swarm"


@pytest.fixture()
def daemon_with_master_and_slave(tmp_path: Path):
    """Spawn the daemon with FEAT-009 tmux-fake wired and seed one
    master + one slave agent so ``send-input`` can flow end-to-end."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(
            paths["state_db"],
            master_agent_id=_MASTER_ID,
            slave_agent_id=_SLAVE_ID,
        )
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


@pytest.fixture()
def daemon_with_master_and_swarm(tmp_path: Path):
    """Variant for US1 acceptance #5 — master sending to a swarm
    target (also permitted per FR-019)."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_container(paths["state_db"])
        f9.seed_pane(
            paths["state_db"], tmux_pane_id="%master",
            tmux_window_index=0, tmux_pane_index=0,
        )
        f9.seed_pane(
            paths["state_db"], tmux_pane_id=_SWARM_PANE,
            tmux_window_index=0, tmux_pane_index=2,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_MASTER_ID, role="master", label="queen",
            tmux_pane_id="%master",
            tmux_window_index=0, tmux_pane_index=0,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_SWARM_ID, role="swarm", label="planner",
            tmux_pane_id=_SWARM_PANE,
            tmux_window_index=0, tmux_pane_index=2,
            parent_agent_id=_MASTER_ID,
        )
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


def _send_input(
    paths: dict[str, Path],
    *,
    sender_agent_id: str,
    target: str,
    body: bytes,
    wait: bool = True,
    wait_timeout_seconds: float = 15.0,
) -> dict:
    """Invoke ``queue.send_input`` over the socket. Bypasses the CLI's
    pane resolution by passing ``caller_pane`` with the sender's
    agent_id directly. Default wait_timeout is generous (15 s) so a
    cold daemon worker still completes a single FakeTmuxAdapter delivery
    well inside the budget — unit tests cover the strict-timing path."""
    body_b64 = base64.b64encode(body).decode("ascii")
    return send_request(
        paths["socket"],
        "queue.send_input",
        {
            "target": target,
            "body_bytes": body_b64,
            "caller_pane": f9.caller_pane_from_db(paths["state_db"], sender_agent_id),
            "wait": wait,
            "wait_timeout_seconds": wait_timeout_seconds,
        },
        connect_timeout=2.0,
        read_timeout=20.0,
    )


# ──────────────────────────────────────────────────────────────────────
# AS1 — end-to-end delivery: row reaches `delivered`
# ──────────────────────────────────────────────────────────────────────


def test_us1_as1_send_input_reaches_delivered(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    result = _send_input(
        paths, sender_agent_id=_MASTER_ID, target=_SLAVE_ID, body=b"do thing",
    )
    assert result["state"] == "delivered", result
    assert result["delivered_at"] is not None
    assert result["failure_reason"] is None
    assert result["block_reason"] is None


# ──────────────────────────────────────────────────────────────────────
# AS2 — response payload matches the FR-011 row schema
# ──────────────────────────────────────────────────────────────────────


_REQUIRED_KEYS = frozenset({
    "message_id", "state", "block_reason", "failure_reason",
    "sender", "target", "envelope_size_bytes", "envelope_body_sha256",
    "enqueued_at", "delivery_attempt_started_at", "delivered_at",
    "failed_at", "canceled_at", "last_updated_at",
    "operator_action", "operator_action_at", "operator_action_by",
    "excerpt",
})


def test_us1_as2_response_payload_matches_fr011_schema(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    result = _send_input(
        paths, sender_agent_id=_MASTER_ID, target=_SLAVE_ID, body=b"do thing",
    )
    missing = _REQUIRED_KEYS - set(result.keys())
    assert not missing, f"FR-011 fields missing from response: {missing}"
    assert result["sender"]["agent_id"] == _MASTER_ID
    assert result["target"]["agent_id"] == _SLAVE_ID
    assert isinstance(result["envelope_size_bytes"], int)
    assert isinstance(result["envelope_body_sha256"], str)
    assert len(result["envelope_body_sha256"]) == 64


# ──────────────────────────────────────────────────────────────────────
# AS3 — `queue.list` includes the delivered row
# ──────────────────────────────────────────────────────────────────────


def test_us1_as3_queue_list_returns_delivered_row(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    sent = _send_input(
        paths, sender_agent_id=_MASTER_ID, target=_SLAVE_ID, body=b"hello",
    )
    msg_id = sent["message_id"]

    listing = send_request(
        paths["socket"], "queue.list", {},
        connect_timeout=2.0, read_timeout=5.0,
    )
    rows = listing["rows"]
    matches = [r for r in rows if r["message_id"] == msg_id]
    assert len(matches) == 1, f"message_id {msg_id} not in queue.list rows"
    assert matches[0]["state"] == "delivered"


# ──────────────────────────────────────────────────────────────────────
# AS4 — JSONL audit contains both enqueued + delivered referencing
#       the same message_id
# ──────────────────────────────────────────────────────────────────────


def test_us1_as4_audit_jsonl_contains_enqueued_and_delivered(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    sent = _send_input(
        paths, sender_agent_id=_MASTER_ID, target=_SLAVE_ID, body=b"hello",
    )
    msg_id = sent["message_id"]

    # The worker's delivered-audit write is best-effort and lands a
    # moment after the row commits — poll up to 10 s so a slow-boot
    # daemon (cold-cache SQLite, first scan, etc.) doesn't flake.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        records = f9.read_audit_jsonl(paths["events_file"])
        msg_records = [r for r in records if r.get("message_id") == msg_id]
        types = {r["event_type"] for r in msg_records}
        if {"queue_message_enqueued", "queue_message_delivered"} <= types:
            break
        time.sleep(0.05)

    records = f9.read_audit_jsonl(paths["events_file"])
    msg_records = [r for r in records if r.get("message_id") == msg_id]
    types = {r["event_type"] for r in msg_records}
    assert "queue_message_enqueued" in types, (
        f"missing enqueue audit: {sorted(types)}"
    )
    assert "queue_message_delivered" in types, (
        f"missing delivered audit: {sorted(types)}"
    )


# ──────────────────────────────────────────────────────────────────────
# AS5 — master → swarm permission allowed (FR-019)
# ──────────────────────────────────────────────────────────────────────


def test_us1_as5_master_to_swarm_permitted(
    daemon_with_master_and_swarm,
) -> None:
    env, paths = daemon_with_master_and_swarm
    result = _send_input(
        paths, sender_agent_id=_MASTER_ID, target=_SWARM_ID, body=b"plan task",
    )
    assert result["state"] == "delivered", result
    assert result["target"]["role"] == "swarm"
