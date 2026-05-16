"""T083 — Clarifications Q1 (2026-05-12): unstamped queued row
survives a clean daemon restart and remains deliverable.

**Test mode**: socket-level integration. The pair of US6 acceptance
checks (T082 + T083) together establish:

* A row WITH a partial delivery attempt is recovered to ``failed/
  attempt_interrupted`` on next boot (T082).
* A row WITHOUT any delivery attempt (purely ``queued``,
  ``delivery_attempt_started_at IS NULL``) remains ``queued`` across
  a clean restart and is delivered by the next boot's worker (T083).

This invariant locks the "queued rows are not lost" property:
operators can stop and restart the daemon without forgetting any
pending work.
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
_PENDING_ID = "22222222-2222-4333-8444-555555555555"


def _seed_queued_row(state_db: Path, *, message_id: str) -> None:
    """Insert a strictly-queued row (no delivery_attempt_started_at)."""
    ts = "2026-05-12T00:00:01.000Z"
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
                message_id, _MASTER_ID, _SLAVE_ID, "c" * 64,
                b"hi", "a" * 64, ts, ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_us6_queued_row_survives_clean_daemon_restart_and_delivers(
    tmp_path: Path,
) -> None:
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)

    # Boot the daemon, register agents, disable routing, seed a queued
    # row, stop the daemon.
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(paths["state_db"])
        send_request(
            paths["socket"], "routing.disable", {},
            connect_timeout=2.0, read_timeout=5.0,
        )
        _seed_queued_row(paths["state_db"], message_id=_PENDING_ID)
        before = f9.get_queue_row(
            paths["state_db"], message_id=_PENDING_ID,
        )
        assert before is not None
        assert before["state"] == "queued"
        assert before["delivery_attempt_started_at"] is None
    finally:
        helpers.stop_daemon_if_alive(env)

    time.sleep(0.3)

    # Restart the daemon — the recovery pass MUST leave the row
    # untouched (no delivery_attempt_started_at to recover from).
    # Then re-enable routing and confirm delivery completes.
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        after_boot = f9.get_queue_row(
            paths["state_db"], message_id=_PENDING_ID,
        )
        assert after_boot is not None
        # The row MUST NOT be failed/attempt_interrupted — that would
        # mean the recovery pass mis-classified it.
        assert after_boot["state"] != "failed", (
            f"queued row mis-recovered to failed: {after_boot}"
        )
        assert after_boot["failure_reason"] != "attempt_interrupted"

        # The routing flag persists across restarts (it's stored in
        # daemon_state) — we disabled it pre-restart, so the worker
        # won't pick the row up until we re-enable.
        send_request(
            paths["socket"], "routing.enable", {},
            connect_timeout=2.0, read_timeout=5.0,
        )

        # Verify it eventually reaches delivered.
        deadline = time.monotonic() + 10.0
        final = after_boot
        while time.monotonic() < deadline and final["state"] != "delivered":
            time.sleep(0.1)
            final = f9.get_queue_row(
                paths["state_db"], message_id=_PENDING_ID,
            ) or final
        assert final["state"] == "delivered", final
    finally:
        helpers.stop_daemon_if_alive(env)
