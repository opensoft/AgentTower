"""T090 — Degraded queue-audit persistence under JSONL write failure.

**Test mode**: socket-level integration. Simulates an
``events.jsonl`` write failure by chmod-ing the file to a mode the
FEAT-008 writer's strict-mode-verify check (``_verify_file_mode``)
rejects (anything other than 0o600). The audit writer's broad-
Exception catch (Group-A walk Q6) absorbs the failure, buffers the
record, sets the degraded flag, and lets SQLite remain authoritative.

Verifies the four invariants from spec §"Degraded queue audit
persistence":

1. The row's terminal state commits to SQLite even when JSONL fails.
2. ``agenttower status`` (queue_audit block) reports
   ``degraded=true`` and a non-zero ``pending_rows``.
3. Restoring write access and triggering another delivery drains the
   buffer (the next delivered audit drain cycle picks up the pending
   record).
4. After drain, ``queue_audit`` reports ``degraded=false`` with
   ``pending_rows=0``.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from agenttower.socket_api.client import send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"


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


def _send(paths: dict[str, Path], *, body: bytes) -> dict:
    return send_request(
        paths["socket"], "queue.send_input",
        {
            "target": _SLAVE_ID,
            "body_bytes": base64.b64encode(body).decode("ascii"),
            "caller_pane": {"agent_id": _MASTER_ID},
            "wait": True,
            "wait_timeout_seconds": 15.0,
        },
        connect_timeout=2.0, read_timeout=20.0,
    )


def _status(env: dict[str, str]) -> dict:
    proc = subprocess.run(
        ["agenttower", "status", "--json"],
        env=env, capture_output=True, text=True, timeout=10.0,
    )
    return json.loads(proc.stdout)["result"]


def test_degraded_audit_isolates_sqlite_from_jsonl_failure(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave

    # First send — succeeds normally; events.jsonl now exists.
    first = _send(paths, body=b"first")
    assert first["state"] == "delivered"
    assert paths["events_file"].exists()

    # Break the JSONL file's mode so the writer's strict mode-check
    # (_verify_file_mode) fires with EPERM. ``0o444`` is broader than
    # the required ``0o600`` → mode check rejects.
    os.chmod(paths["events_file"], 0o444)

    # Second send — SQLite path still commits, but the JSONL append
    # fails. The audit writer's broad-Exception catch absorbs the
    # OSError and buffers the record.
    second = _send(paths, body=b"second")
    assert second["state"] == "delivered", second

    # Status should now report degraded=True with at least one
    # pending row.
    deadline = time.monotonic() + 3.0
    audit_status = None
    while time.monotonic() < deadline:
        audit_status = _status(env)["queue_audit"]
        if audit_status["degraded"]:
            break
        time.sleep(0.05)
    assert audit_status is not None
    assert audit_status["degraded"] is True, audit_status
    assert audit_status["pending_rows"] >= 1, audit_status
    assert audit_status["last_failure_exc_class"] is not None

    # Restore the file's mode so the drain on the next worker cycle
    # succeeds.
    os.chmod(paths["events_file"], 0o600)

    # Drive a third send — the next worker cycle drains the buffer
    # at the top of its loop (before picking the next row).
    third = _send(paths, body=b"third")
    assert third["state"] == "delivered"

    # Wait for the buffer to drain.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        audit_status = _status(env)["queue_audit"]
        if not audit_status["degraded"]:
            break
        time.sleep(0.1)

    assert audit_status["degraded"] is False, (
        f"buffer did not drain: {audit_status}"
    )
    assert audit_status["pending_rows"] == 0
