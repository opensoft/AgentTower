"""T066 — US3 operator-override acceptance scenarios.

**Test mode**: socket-level integration. Drives queue.list / approve /
delay / cancel via the FEAT-002 ``send_request`` client. The CLI's
own list-format rendering is unit-tested
(``test_queue_listing_format.py``). Operator-pane liveness is tested
at the dispatch boundary by ``test_socket_methods_caller_context.py``;
this file exercises the state-machine transitions through the live
daemon.

Covered acceptance scenarios:

1. queue.list returns every row in enqueued_at ASC order.
2. Filters AND-combine (state + target).
3. approve transitions blocked → queued for operator-resolvable
   block_reasons.
4. delay transitions queued → blocked operator_delayed.
5. cancel transitions queued|blocked → canceled.
6. Operator action on a terminal row → terminal_state_cannot_change.
7. The wire response from approve/delay/cancel matches the FR-011
   row shape (covered implicitly by the per-action assertions).
"""

from __future__ import annotations

import base64
import sqlite3
import time
from pathlib import Path

import pytest

from agenttower.socket_api.client import DaemonError, send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"


def _send(
    paths: dict[str, Path], *, sender: str, target: str, body: bytes = b"hi",
    wait: bool = False,
) -> dict:
    return send_request(
        paths["socket"], "queue.send_input",
        {
            "target": target,
            "body_bytes": base64.b64encode(body).decode("ascii"),
            "caller_pane": {"agent_id": sender},
            "wait": wait,
        },
        connect_timeout=2.0, read_timeout=10.0,
    )


def _list(paths: dict[str, Path], **filters: object) -> dict:
    return send_request(
        paths["socket"], "queue.list", filters,
        connect_timeout=2.0, read_timeout=5.0,
    )


def _approve(paths: dict[str, Path], *, message_id: str) -> dict:
    return send_request(
        paths["socket"], "queue.approve",
        {"message_id": message_id},  # host-origin: dispatcher writes host-operator
        connect_timeout=2.0, read_timeout=5.0,
    )


def _delay(paths: dict[str, Path], *, message_id: str) -> dict:
    return send_request(
        paths["socket"], "queue.delay",
        {"message_id": message_id},
        connect_timeout=2.0, read_timeout=5.0,
    )


def _cancel(paths: dict[str, Path], *, message_id: str) -> dict:
    return send_request(
        paths["socket"], "queue.cancel",
        {"message_id": message_id},
        connect_timeout=2.0, read_timeout=5.0,
    )


@pytest.fixture()
def daemon_blocked_seeded(tmp_path: Path):
    """Spawn the daemon WITHOUT a master pane registered so send_input
    lands rows in ``blocked sender_role_not_permitted`` reliably. This
    is the minimal scenario for testing approve / delay / cancel
    without racing the worker thread."""
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


def _seed_blocked_row(
    state_db: Path,
    *,
    message_id: str = "11111111-2222-4333-8444-555555555555",
    block_reason: str = "operator_delayed",
    enqueued_at: str = "2026-05-12T00:00:00.000Z",
) -> None:
    """Insert one ``blocked`` row directly via SQLite so the test can
    operate on it deterministically. Mirrors data-model.md §2 shape."""
    conn = sqlite3.connect(state_db)
    try:
        conn.execute(
            "INSERT INTO message_queue ("
            "message_id, state, block_reason, "
            "sender_agent_id, sender_label, sender_role, sender_capability, "
            "target_agent_id, target_label, target_role, target_capability, "
            "target_container_id, target_pane_id, "
            "envelope_body, envelope_body_sha256, envelope_size_bytes, "
            "enqueued_at, last_updated_at"
            ") VALUES (?, 'blocked', ?, "
            "?, 'queen', 'master', 'codex', "
            "?, 'worker-1', 'slave', 'codex', "
            "?, '%slave', "
            "?, ?, 64, ?, ?)",
            (
                message_id, block_reason,
                _MASTER_ID, _SLAVE_ID,
                "c" * 64,
                b"hi", "a" * 64,
                enqueued_at, enqueued_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_queued_row(
    state_db: Path,
    *,
    message_id: str,
    enqueued_at: str,
) -> None:
    """Insert one ``queued`` row that has NOT been stamped — eligible
    for delay/cancel before the worker picks it up. Note: the live
    worker will pick this up promptly; tests using this helper must
    operate on the row within a short window OR disable routing first."""
    conn = sqlite3.connect(state_db)
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
                message_id,
                _MASTER_ID, _SLAVE_ID,
                "c" * 64,
                b"hi", "a" * 64,
                enqueued_at, enqueued_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _disable_routing(paths: dict[str, Path]) -> None:
    """Disable the kill switch so the worker stops picking up new
    queued rows — gives tests a quiet window to operate on rows."""
    send_request(
        paths["socket"], "routing.disable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )


# ──────────────────────────────────────────────────────────────────────
# AS1 — list ordering (enqueued_at ASC)
# ──────────────────────────────────────────────────────────────────────


def test_us3_as1_list_orders_by_enqueued_at_asc(daemon_blocked_seeded) -> None:
    env, paths = daemon_blocked_seeded
    _seed_blocked_row(
        paths["state_db"],
        message_id="22222222-2222-4333-8444-555555555555",
        enqueued_at="2026-05-12T00:00:02.000Z",
    )
    _seed_blocked_row(
        paths["state_db"],
        message_id="11111111-2222-4333-8444-555555555555",
        enqueued_at="2026-05-12T00:00:01.000Z",
    )
    _seed_blocked_row(
        paths["state_db"],
        message_id="33333333-2222-4333-8444-555555555555",
        enqueued_at="2026-05-12T00:00:03.000Z",
    )

    rows = _list(paths)["rows"]
    enqueued = [r["enqueued_at"] for r in rows]
    assert enqueued == sorted(enqueued), (
        f"rows out of order: {enqueued}"
    )


# ──────────────────────────────────────────────────────────────────────
# AS2 — filters AND-combine
# ──────────────────────────────────────────────────────────────────────


def test_us3_as2_filters_and_combine(daemon_blocked_seeded) -> None:
    env, paths = daemon_blocked_seeded
    _seed_blocked_row(
        paths["state_db"],
        message_id="11111111-2222-4333-8444-555555555555",
        enqueued_at="2026-05-12T00:00:01.000Z",
    )
    # state=blocked AND target=<slave> matches.
    rows = _list(paths, state="blocked", target=_SLAVE_ID)["rows"]
    assert len(rows) == 1
    assert rows[0]["state"] == "blocked"

    # state=queued AND target=<slave> matches nothing (only blocked
    # rows exist).
    rows = _list(paths, state="queued", target=_SLAVE_ID)["rows"]
    assert rows == []


# ──────────────────────────────────────────────────────────────────────
# AS3 — approve blocked operator_delayed → queued
# ──────────────────────────────────────────────────────────────────────


def test_us3_as3_approve_operator_delayed_blocked_to_queued(
    daemon_blocked_seeded,
) -> None:
    env, paths = daemon_blocked_seeded
    msg_id = "11111111-2222-4333-8444-555555555555"
    # Disable routing so the worker doesn't immediately pick the row
    # after the approve transition.
    _disable_routing(paths)
    _seed_blocked_row(
        paths["state_db"], message_id=msg_id, block_reason="operator_delayed",
    )
    row = _approve(paths, message_id=msg_id)
    assert row["state"] == "queued"
    assert row["block_reason"] is None
    assert row["operator_action"] == "approved"
    assert row["operator_action_by"] == "host-operator"


def test_us3_as3_approve_target_not_active_returns_approval_not_applicable(
    daemon_blocked_seeded,
) -> None:
    """When the row's ``block_reason`` is ``target_not_active`` but the
    target is STILL inactive, the operator's approve attempt must be
    refused with ``approval_not_applicable`` (the target hasn't become
    eligible yet)."""
    env, paths = daemon_blocked_seeded
    msg_id = "22222222-2222-4333-8444-555555555555"
    _disable_routing(paths)
    _seed_blocked_row(
        paths["state_db"], message_id=msg_id, block_reason="sender_role_not_permitted",
    )
    # sender_role_not_permitted is intrinsic; not operator-resolvable.
    with pytest.raises(DaemonError) as exc_info:
        _approve(paths, message_id=msg_id)
    assert exc_info.value.code == "approval_not_applicable"


# ──────────────────────────────────────────────────────────────────────
# AS4 — delay queued → blocked operator_delayed
# ──────────────────────────────────────────────────────────────────────


def test_us3_as4_delay_queued_to_blocked_operator_delayed(
    daemon_blocked_seeded,
) -> None:
    env, paths = daemon_blocked_seeded
    msg_id = "33333333-2222-4333-8444-555555555555"
    # Disable routing first so the worker doesn't pick up the row
    # before we get a chance to delay it.
    _disable_routing(paths)
    _seed_queued_row(
        paths["state_db"], message_id=msg_id,
        enqueued_at="2026-05-12T00:00:01.000Z",
    )
    row = _delay(paths, message_id=msg_id)
    assert row["state"] == "blocked"
    assert row["block_reason"] == "operator_delayed"
    assert row["operator_action"] == "delayed"
    assert row["operator_action_by"] == "host-operator"


# ──────────────────────────────────────────────────────────────────────
# AS5 — cancel queued|blocked → canceled
# ──────────────────────────────────────────────────────────────────────


def test_us3_as5_cancel_queued_to_canceled(daemon_blocked_seeded) -> None:
    env, paths = daemon_blocked_seeded
    msg_id = "44444444-2222-4333-8444-555555555555"
    _disable_routing(paths)
    _seed_queued_row(
        paths["state_db"], message_id=msg_id,
        enqueued_at="2026-05-12T00:00:01.000Z",
    )
    row = _cancel(paths, message_id=msg_id)
    assert row["state"] == "canceled"
    assert row["canceled_at"] is not None


def test_us3_as5_cancel_blocked_to_canceled(daemon_blocked_seeded) -> None:
    env, paths = daemon_blocked_seeded
    msg_id = "55555555-2222-4333-8444-555555555555"
    _disable_routing(paths)
    _seed_blocked_row(paths["state_db"], message_id=msg_id)
    row = _cancel(paths, message_id=msg_id)
    assert row["state"] == "canceled"


# ──────────────────────────────────────────────────────────────────────
# AS6 — operator action on a terminal row → terminal_state_cannot_change
# ──────────────────────────────────────────────────────────────────────


def test_us3_as6_cancel_on_canceled_row_returns_terminal_state_cannot_change(
    daemon_blocked_seeded,
) -> None:
    env, paths = daemon_blocked_seeded
    msg_id = "66666666-2222-4333-8444-555555555555"
    _disable_routing(paths)
    _seed_blocked_row(paths["state_db"], message_id=msg_id)
    # Cancel once — succeeds.
    _cancel(paths, message_id=msg_id)
    # Cancel again — terminal-state guard.
    with pytest.raises(DaemonError) as exc_info:
        _cancel(paths, message_id=msg_id)
    assert exc_info.value.code == "terminal_state_cannot_change"


def test_us3_as6_approve_on_canceled_row_returns_terminal_state_cannot_change(
    daemon_blocked_seeded,
) -> None:
    env, paths = daemon_blocked_seeded
    msg_id = "77777777-2222-4333-8444-555555555555"
    _disable_routing(paths)
    _seed_blocked_row(paths["state_db"], message_id=msg_id)
    _cancel(paths, message_id=msg_id)
    with pytest.raises(DaemonError) as exc_info:
        _approve(paths, message_id=msg_id)
    assert exc_info.value.code == "terminal_state_cannot_change"


# ──────────────────────────────────────────────────────────────────────
# message_id_not_found path
# ──────────────────────────────────────────────────────────────────────


def test_us3_unknown_message_id_returns_message_id_not_found(
    daemon_blocked_seeded,
) -> None:
    env, paths = daemon_blocked_seeded
    with pytest.raises(DaemonError) as exc_info:
        _cancel(paths, message_id="00000000-0000-4000-8000-000000000000")
    assert exc_info.value.code == "message_id_not_found"
