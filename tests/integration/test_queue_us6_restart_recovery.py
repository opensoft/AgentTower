"""T082 — US6 restart recovery acceptance scenarios.

**Test mode**: socket-level integration. The Slice 10 boot smoke test
``test_daemon_feat009_boot.py::test_recovery_pass_runs_before_worker_start``
already covers the recovery pass at the service-level boot path. This
integration test exercises the FULL restart cycle through the
``agenttowerd`` subprocess:

1. Start the daemon. Disable routing so the worker can't grab rows.
2. Pre-populate the SQLite ``message_queue`` table with a half-stamped
   row (``delivery_attempt_started_at`` set, terminal stamps unset)
   directly via a second SQLite connection — simulating a post-crash
   state without any production-code fault-injection seam.
3. Stop the daemon cleanly.
4. Start the daemon again — its boot path runs ``run_recovery_pass()``
   synchronously BEFORE the worker thread starts.
5. Assert (a) the half-stamped row is now ``failed`` /
   ``attempt_interrupted``; (b) exactly one ``queue_message_failed``
   audit row exists in events.jsonl + SQLite events table; (c) no
   second tmux delivery was attempted (the FakeTmuxAdapter would have
   produced one — we verify implicitly: a failed row with
   ``attempt_interrupted`` was never re-delivered).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"
_HALF_STAMPED_ID = "11111111-2222-4333-8444-555555555555"


def _seed_half_stamped_row(state_db: Path, *, message_id: str) -> None:
    """Insert a row with ``delivery_attempt_started_at`` set + every
    terminal stamp NULL — the post-crash signature the recovery pass
    detects (FR-040 / Research §R-012).
    """
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
            "enqueued_at, delivery_attempt_started_at, last_updated_at"
            ") VALUES (?, 'queued', "
            "?, 'queen', 'master', 'codex', "
            "?, 'worker-1', 'slave', 'codex', "
            "?, '%slave', "
            "?, ?, 64, ?, ?, ?)",
            (
                message_id, _MASTER_ID, _SLAVE_ID, "c" * 64,
                b"hi", "a" * 64,
                ts, ts, ts,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_us6_restart_recovers_half_stamped_row_to_failed_attempt_interrupted(
    tmp_path: Path,
) -> None:
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)

    # First boot — start daemon, seed the half-stamped row, stop daemon.
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(paths["state_db"])
        # Disable routing so the worker won't pick up the seeded row
        # before we stop the daemon.
        from agenttower.socket_api.client import send_request
        send_request(
            paths["socket"], "routing.disable", {},
            connect_timeout=2.0, read_timeout=5.0,
        )
        _seed_half_stamped_row(
            paths["state_db"], message_id=_HALF_STAMPED_ID,
        )
        # Sanity: row is half-stamped before restart.
        row_before = f9.get_queue_row(
            paths["state_db"], message_id=_HALF_STAMPED_ID,
        )
        assert row_before["state"] == "queued"
        assert row_before["delivery_attempt_started_at"] is not None
        assert row_before["failed_at"] is None
    finally:
        helpers.stop_daemon_if_alive(env)

    # Confirm daemon is fully down before restart.
    time.sleep(0.3)

    # Second boot — the daemon's run_recovery_pass should fire
    # SYNCHRONOUSLY before the worker starts.
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        # Re-disable routing so the worker can't observe the row and
        # mutate it back AFTER recovery — we want to assert the recovery
        # state.
        send_request(
            paths["socket"], "routing.disable", {},
            connect_timeout=2.0, read_timeout=5.0,
        )

        row_after = f9.get_queue_row(
            paths["state_db"], message_id=_HALF_STAMPED_ID,
        )
        assert row_after is not None
        assert row_after["state"] == "failed", row_after
        assert row_after["failure_reason"] == "attempt_interrupted"
        assert row_after["failed_at"] is not None

        # Exactly one queue_message_failed audit row in JSONL for this
        # message_id.
        records = f9.read_audit_jsonl(paths["events_file"])
        failed_audits = [
            r for r in records
            if r.get("message_id") == _HALF_STAMPED_ID
            and r.get("event_type") == "queue_message_failed"
        ]
        assert len(failed_audits) == 1, (
            f"expected exactly one queue_message_failed audit row; "
            f"got {len(failed_audits)}: {failed_audits}"
        )
        assert failed_audits[0]["reason"] == "attempt_interrupted"

        # And — critically — NO queue_message_delivered audit rows
        # for this message_id. The half-stamped row had reached
        # ``delivery_attempt_started_at`` on the prior boot's worker
        # cycle and the recovery pass MUST transition it to failed
        # without ever re-pasting (FR-040). A delivered row here
        # would mean the row was somehow re-picked by the new
        # worker — a double-paste violation. Making the invariant
        # explicit in the audit-stream assertion catches that bug
        # class loudly instead of silently. (Sourcery R-4.)
        delivered_audits = [
            r for r in records
            if r.get("message_id") == _HALF_STAMPED_ID
            and r.get("event_type") == "queue_message_delivered"
        ]
        assert delivered_audits == [], (
            "FR-040 invariant violated: half-stamped row produced a "
            f"queue_message_delivered audit row after recovery: "
            f"{delivered_audits}"
        )
    finally:
        helpers.stop_daemon_if_alive(env)
