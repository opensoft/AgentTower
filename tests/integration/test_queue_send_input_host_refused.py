"""T062 — Host-side ``agenttower send-input`` is refused.

**Test mode**: CLI integration. This is one of the few FEAT-009
integration tests that drives the ``agenttower`` CLI as a subprocess
end-to-end (rather than calling ``queue.send_input`` over the socket
directly). It exists to validate the caller-origin gate from the
operator's actual entry point — a host-shell ``agenttower send-input``
invocation.

What this test verifies:

* The CLI's :func:`agents.client_resolve.resolve_pane_composite_key`
  refuses host-origin callers with ``host_context_unsupported`` (the
  FEAT-006 closed code; the FEAT-009 dispatcher would equally refuse
  with ``sender_not_in_pane`` if the call reached the daemon).
* The CLI exits non-zero.
* No row is created in ``message_queue`` (the request never reached
  the daemon dispatcher).

Per Clarifications Q3 (2026-05-11 session): ``send-input`` from the
host shell is refused outright; the operator is told to register-self
inside a bench container first.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


def _write_host_proc_root(root: Path) -> None:
    """Materialize a fake /proc + /etc tree that asserts HOST context.

    FEAT-005 :func:`runtime_detect.detect` classifies the caller as
    :class:`HostContext` when no ``.dockerenv`` marker file exists and
    the cgroup paths don't carry a container id. We write the
    minimum-fake-tree that satisfies the detector AND avoids the test
    sandbox's own in-container signals leaking into the subprocess.
    """
    (root / "proc" / "self").mkdir(parents=True, exist_ok=True)
    (root / "proc" / "1").mkdir(parents=True, exist_ok=True)
    (root / "etc").mkdir(parents=True, exist_ok=True)
    (root / "run").mkdir(parents=True, exist_ok=True)
    # NO .dockerenv — that's the host marker absence.
    # Empty cgroup so no container id is parsed.
    (root / "proc" / "self" / "cgroup").write_text("0::/\n")
    (root / "proc" / "1" / "cgroup").write_text("0::/\n")


@pytest.fixture()
def daemon_with_master_and_slave_host_proc_root(tmp_path: Path):
    """Spawn the daemon, seed master + slave, and point the CLI's
    ``AGENTTOWER_TEST_PROC_ROOT`` at a fake host-context filesystem so
    the CLI classifies the caller as host-origin and refuses BEFORE
    reaching the daemon dispatcher."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    proc_root = tmp_path / "proc-root-host"
    _write_host_proc_root(proc_root)
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(proc_root)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(paths["state_db"])
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


def _row_count(state_db: Path) -> int:
    conn = sqlite3.connect(state_db)
    try:
        return conn.execute("SELECT COUNT(*) FROM message_queue").fetchone()[0]
    finally:
        conn.close()


def test_host_origin_send_input_refused_with_no_row_created(
    daemon_with_master_and_slave_host_proc_root,
) -> None:
    env, paths = daemon_with_master_and_slave_host_proc_root
    initial_rows = _row_count(paths["state_db"])

    proc = subprocess.run(
        [
            "agenttower", "send-input",
            "--target", "agt_bbbbbbbbbbbb",
            "--message", "do thing",
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    # Host-origin caller MUST exit non-zero.
    assert proc.returncode != 0, proc.stdout

    # --json mode emits a closed-set error envelope on stdout.
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    code = payload["error"]["code"]
    # The CLI's first refusal point is FEAT-006's host_context_unsupported,
    # which is the operator-visible code for the "this is the host shell,
    # not a bench container" path. Both that and sender_not_in_pane are
    # acceptable surfaces — accept either to keep the test robust against
    # CLI-side reordering of the resolve / dispatch boundary.
    assert code in {"host_context_unsupported", "sender_not_in_pane"}

    # CRITICAL: no row was created (FR-006 + Clarifications Q3).
    assert _row_count(paths["state_db"]) == initial_rows


def test_host_origin_send_input_human_mode_writes_to_stderr(
    daemon_with_master_and_slave_host_proc_root,
) -> None:
    """Without ``--json``, the CLI emits the error line on stderr and
    leaves stdout empty (contracts/cli-send-input.md §"Stdout / stderr")."""
    env, paths = daemon_with_master_and_slave_host_proc_root
    proc = subprocess.run(
        [
            "agenttower", "send-input",
            "--target", "agt_bbbbbbbbbbbb",
            "--message", "do thing",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    assert proc.returncode != 0
    # The exact rendering uses the FEAT-006 ``_emit_local_error`` shape
    # (``error: <msg>`` + ``code: <code>``) — assert both lines land on
    # stderr and stdout is empty.
    assert proc.stdout == ""
    assert "host_context_unsupported" in proc.stderr or (
        "sender_not_in_pane" in proc.stderr
    )
