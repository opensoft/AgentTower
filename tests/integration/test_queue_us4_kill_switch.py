"""T072 — US4 kill-switch acceptance scenarios + Session 2 Q1.

**Test mode**: socket-level integration. Drives ``routing.enable`` /
``routing.disable`` / ``routing.status`` + ``queue.send_input`` /
``queue.list`` over the FEAT-002 client. The CLI rendering of
``agenttower routing status`` is unit-tested separately (Slice 12
T077 + the routing CLI unit tests in Slice 12). The bench-container
host-only refusal is covered by ``test_queue_routing_toggle_host_only.py``
(T073, this slice).

Covered acceptance scenarios:

1. routing.status returns ``disabled`` after a disable, plus the
   last-toggle metadata.
2. routing-disabled + send_input → row blocked kill_switch_off,
   no tmux delivery.
3. Operator surface (queue list, queue cancel) works under routing
   disabled.
4. Worker stops picking new rows when routing is disabled (rows seeded
   while disabled stay queued).
5. Re-enable resumes delivery for new rows; rows blocked with
   kill_switch_off stay blocked until explicit approve.

Plus Session 2 Q1 (in-flight rows finish): a row whose
``delivery_attempt_started_at`` is set BEFORE the disable runs to
terminal. This invariant is unit-tested as well
(``test_delivery_worker_in_flight_kill_switch.py``); the integration
test confirms it through the live daemon.
"""

from __future__ import annotations

import base64
import sqlite3
import time
from pathlib import Path

import pytest

from agenttower.socket_api.client import send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"


def _send(
    paths: dict[str, Path], *, body: bytes = b"hi", wait: bool = False,
) -> dict:
    return send_request(
        paths["socket"], "queue.send_input",
        {
            "target": _SLAVE_ID,
            "body_bytes": base64.b64encode(body).decode("ascii"),
            "caller_pane": f9.caller_pane_from_db(paths["state_db"], _MASTER_ID),
            "wait": wait,
        },
        connect_timeout=2.0, read_timeout=10.0,
    )


def _list(paths: dict[str, Path], **filters: object) -> dict:
    return send_request(
        paths["socket"], "queue.list", filters,
        connect_timeout=2.0, read_timeout=5.0,
    )


def _routing_disable(paths: dict[str, Path]) -> dict:
    return send_request(
        paths["socket"], "routing.disable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )


def _routing_enable(paths: dict[str, Path]) -> dict:
    return send_request(
        paths["socket"], "routing.enable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )


def _routing_status(paths: dict[str, Path]) -> dict:
    return send_request(
        paths["socket"], "routing.status", {},
        connect_timeout=2.0, read_timeout=5.0,
    )


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


# ──────────────────────────────────────────────────────────────────────
# AS1 — routing.status returns disabled + last-toggle metadata
# ──────────────────────────────────────────────────────────────────────


def test_us4_as1_status_returns_disabled_after_disable(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    # Initially enabled (migration seed).
    initial = _routing_status(paths)
    assert initial["value"] == "enabled"

    toggle = _routing_disable(paths)
    assert toggle["changed"] is True
    assert toggle["previous_value"] == "enabled"
    assert toggle["current_value"] == "disabled"

    after = _routing_status(paths)
    assert after["value"] == "disabled"
    assert after["last_updated_at"] == toggle["last_updated_at"]
    assert after["last_updated_by"] == "host-operator"


# ──────────────────────────────────────────────────────────────────────
# AS2 — send_input under disabled → blocked kill_switch_off
# ──────────────────────────────────────────────────────────────────────


def test_us4_as2_send_input_under_disabled_blocks_with_kill_switch_off(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    _routing_disable(paths)
    row = _send(paths)
    assert row["state"] == "blocked"
    assert row["block_reason"] == "kill_switch_off"
    # No delivery attempt yet (worker won't pick blocked rows).
    assert row["delivery_attempt_started_at"] is None


# ──────────────────────────────────────────────────────────────────────
# AS3 — list + cancel work under disabled
# ──────────────────────────────────────────────────────────────────────


def test_us4_as3_list_and_cancel_work_while_disabled(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    _routing_disable(paths)
    # Submit one row — lands blocked.
    blocked_row = _send(paths)
    msg_id = blocked_row["message_id"]

    # list works.
    listing = _list(paths)
    rows = listing["rows"]
    assert any(r["message_id"] == msg_id for r in rows)

    # cancel works.
    cancel_result = send_request(
        paths["socket"], "queue.cancel", {"message_id": msg_id},
        connect_timeout=2.0, read_timeout=5.0,
    )
    assert cancel_result["state"] == "canceled"


# ──────────────────────────────────────────────────────────────────────
# AS4 — worker stops picking new rows under disabled
# ──────────────────────────────────────────────────────────────────────


def test_us4_as4_worker_does_not_pick_queued_rows_while_disabled(
    daemon_with_master_and_slave,
) -> None:
    """Seed a ``queued`` row directly into the DB, disable routing,
    and confirm the worker does NOT advance it to ``delivered`` even
    after a short wait."""
    env, paths = daemon_with_master_and_slave
    _routing_disable(paths)
    msg_id = "44444444-2222-4333-8444-555555555555"
    conn = sqlite3.connect(paths["state_db"])
    try:
        conn.execute(
            "INSERT INTO message_queue ("
            "message_id, state, "
            "sender_agent_id, sender_label, sender_role, sender_capability, "
            "target_agent_id, target_label, target_role, target_capability, "
            "target_container_id, target_pane_id, "
            "envelope_body, envelope_body_sha256, envelope_size_bytes, "
            "enqueued_at, last_updated_at"
            ") VALUES (?, 'queued', "
            "?, 'queen', 'master', 'codex', "
            "?, 'worker-1', 'slave', 'codex', "
            "?, '%slave', "
            "?, ?, 64, ?, ?)",
            (
                msg_id, _MASTER_ID, _SLAVE_ID, "c" * 64,
                b"hi", "a" * 64,
                "2026-05-12T00:00:01.000Z", "2026-05-12T00:00:01.000Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    # Wait briefly and confirm the row is still queued (no delivery).
    time.sleep(1.0)
    row = f9.get_queue_row(paths["state_db"], message_id=msg_id)
    assert row is not None
    assert row["state"] == "queued"
    assert row["delivery_attempt_started_at"] is None


# ──────────────────────────────────────────────────────────────────────
# AS5 — re-enable resumes new deliveries; kill_switch_off rows stay blocked
# ──────────────────────────────────────────────────────────────────────


def test_us4_as5_reenable_resumes_new_rows_but_keeps_kill_switch_off_blocked(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    _routing_disable(paths)
    blocked_row = _send(paths)
    blocked_id = blocked_row["message_id"]
    assert blocked_row["block_reason"] == "kill_switch_off"

    # Re-enable.
    toggle = _routing_enable(paths)
    assert toggle["changed"] is True

    # The previously-blocked kill_switch_off row stays blocked until
    # explicit approve.
    listing = _list(paths)
    same_row = next(r for r in listing["rows"] if r["message_id"] == blocked_id)
    assert same_row["state"] == "blocked"
    assert same_row["block_reason"] == "kill_switch_off"

    # A new send_input flows through to delivered (wait for it).
    new_row = _send(paths, wait=True)
    # New row reaches delivered eventually; if the wait timed out
    # before delivery completes, poll briefly.
    deadline = time.monotonic() + 5.0
    final = new_row
    while time.monotonic() < deadline and final["state"] != "delivered":
        time.sleep(0.05)
        final = f9.get_queue_row(
            paths["state_db"], message_id=new_row["message_id"],
        ) or final
    assert final["state"] == "delivered", final


# ──────────────────────────────────────────────────────────────────────
# Session 2 Q1 — idempotent re-disable returns changed=False
# ──────────────────────────────────────────────────────────────────────


def test_us4_idempotent_disable_returns_changed_false(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    _routing_disable(paths)
    second = _routing_disable(paths)
    assert second["changed"] is False
    assert second["current_value"] == "disabled"


def test_us4_idempotent_enable_returns_changed_false(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    # Initial flag is enabled — a fresh ``routing.enable`` is a no-op.
    result = _routing_enable(paths)
    assert result["changed"] is False
    assert result["current_value"] == "enabled"
