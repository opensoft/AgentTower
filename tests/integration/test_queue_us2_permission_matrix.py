"""T061 — US2 permission-gate refusal acceptance scenarios.

**Test mode**: socket-level integration. Drives queue.send_input via
the FEAT-002 ``send_request`` client. The CLI's host-side refusal is
covered by ``test_queue_send_input_host_refused.py`` (T062, CLI mode).
The byte-exact tmux non-delivery for blocked rows is implicit — a row
in ``blocked`` is never picked up by the worker, so the FakeTmuxAdapter
in the test daemon records zero ``paste_buffer`` calls.

Each scenario asserts:

* The wire response carries the matching closed-set error code (for
  no-row-created paths) OR the row's ``state == 'blocked'`` with the
  matching ``block_reason`` (for row-created paths).
* The CLI exit-code mapping is exercised by the unit tests
  (``test_send_input_cli_*.py``); this file checks the socket payload.

Covered acceptance scenarios:

1. Unknown sender → ``sender_role_not_permitted``, NO row created.
2. Slave sender → row created in ``blocked sender_role_not_permitted``.
3. Swarm sender → row created in ``blocked sender_role_not_permitted``.
4. Master to disallowed target role (master target) → row created in
   ``blocked target_role_not_permitted``.
5. Master to unknown target → ``agent_not_found``, NO row created.
6. Master to inactive slave → row created in ``blocked target_not_active``.
7. Master to inactive target container → row created in
   ``blocked target_container_inactive``.
8. Master to target whose pane was deregistered → row created in
   ``blocked target_pane_missing``.
"""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

import pytest

from agenttower.socket_api.client import DaemonError, send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"
_OTHER_MASTER_ID = "agt_dddddddddddd"
_BENCH_SLAVE_ID = "agt_eeeeeeeeeeee"


def _send(
    paths: dict[str, Path],
    *,
    sender_agent_id: str,
    target: str,
) -> dict:
    body_b64 = base64.b64encode(b"hello").decode("ascii")
    return send_request(
        paths["socket"], "queue.send_input",
        {
            "target": target,
            "body_bytes": body_b64,
            "caller_pane": {"agent_id": sender_agent_id},
            "wait": False,  # no need to wait; we check the enqueue outcome
        },
        connect_timeout=2.0, read_timeout=10.0,
    )


@pytest.fixture()
def daemon_seeded(tmp_path: Path):
    """Spawn the daemon and seed default master+slave; individual tests
    layer additional state on top."""
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


def _row_count(state_db: Path) -> int:
    conn = sqlite3.connect(state_db)
    try:
        return conn.execute("SELECT COUNT(*) FROM message_queue").fetchone()[0]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# AS1 — unknown sender → sender_role_not_permitted, no row
# ──────────────────────────────────────────────────────────────────────


def test_us2_as1_unknown_sender_refused_no_row(daemon_seeded) -> None:
    env, paths = daemon_seeded
    with pytest.raises(DaemonError) as exc_info:
        _send(paths, sender_agent_id="agt_999999999999", target=_SLAVE_ID)
    assert exc_info.value.code == "sender_role_not_permitted"
    # No row was created — the gate refuses before insert.
    assert _row_count(paths["state_db"]) == 0


# ──────────────────────────────────────────────────────────────────────
# AS2 — slave-role sender → row created blocked sender_role_not_permitted
# ──────────────────────────────────────────────────────────────────────


def test_us2_as2_slave_sender_blocked(daemon_seeded) -> None:
    env, paths = daemon_seeded
    # The seeded slave (_SLAVE_ID) is a registered active agent with role=slave.
    # Adding a second slave as the target so we have a slave→slave attempt.
    f9.seed_pane(
        paths["state_db"], tmux_pane_id="%slave2",
        tmux_window_index=0, tmux_pane_index=2,
    )
    f9.seed_agent(
        paths["state_db"],
        agent_id=_BENCH_SLAVE_ID, role="slave", label="worker-2",
        tmux_pane_id="%slave2",
        tmux_window_index=0, tmux_pane_index=2,
    )
    row = _send(paths, sender_agent_id=_SLAVE_ID, target=_BENCH_SLAVE_ID)
    assert row["state"] == "blocked"
    assert row["block_reason"] == "sender_role_not_permitted"


# ──────────────────────────────────────────────────────────────────────
# AS3 — swarm-role sender → row created blocked sender_role_not_permitted
# ──────────────────────────────────────────────────────────────────────


def test_us2_as3_swarm_sender_blocked(daemon_seeded) -> None:
    env, paths = daemon_seeded
    swarm_id = "agt_cccccccccccc"
    f9.seed_pane(
        paths["state_db"], tmux_pane_id="%swarm",
        tmux_window_index=0, tmux_pane_index=3,
    )
    f9.seed_agent(
        paths["state_db"],
        agent_id=swarm_id, role="swarm", label="planner",
        tmux_pane_id="%swarm",
        tmux_window_index=0, tmux_pane_index=3,
        parent_agent_id=_MASTER_ID,
    )
    row = _send(paths, sender_agent_id=swarm_id, target=_SLAVE_ID)
    assert row["state"] == "blocked"
    assert row["block_reason"] == "sender_role_not_permitted"


# ──────────────────────────────────────────────────────────────────────
# AS4 — master to disallowed target role (master) → target_role_not_permitted
# ──────────────────────────────────────────────────────────────────────


def test_us2_as4_master_to_master_blocked(daemon_seeded) -> None:
    env, paths = daemon_seeded
    f9.seed_pane(
        paths["state_db"], tmux_pane_id="%master2",
        tmux_window_index=0, tmux_pane_index=4,
    )
    f9.seed_agent(
        paths["state_db"],
        agent_id=_OTHER_MASTER_ID, role="master", label="king",
        tmux_pane_id="%master2",
        tmux_window_index=0, tmux_pane_index=4,
    )
    row = _send(paths, sender_agent_id=_MASTER_ID, target=_OTHER_MASTER_ID)
    assert row["state"] == "blocked"
    assert row["block_reason"] == "target_role_not_permitted"


# ──────────────────────────────────────────────────────────────────────
# AS5 — master to unknown target → agent_not_found, no row
# ──────────────────────────────────────────────────────────────────────


def test_us2_as5_unknown_target_refused_no_row(daemon_seeded) -> None:
    env, paths = daemon_seeded
    initial_rows = _row_count(paths["state_db"])
    with pytest.raises(DaemonError) as exc_info:
        _send(paths, sender_agent_id=_MASTER_ID, target="agt_ffffffffffff")
    assert exc_info.value.code == "agent_not_found"
    assert _row_count(paths["state_db"]) == initial_rows


# ──────────────────────────────────────────────────────────────────────
# AS6 — master to inactive slave → target_not_active
# ──────────────────────────────────────────────────────────────────────


def test_us2_as6_inactive_target_blocked(daemon_seeded) -> None:
    env, paths = daemon_seeded
    inactive_id = "agt_111111111111"
    f9.seed_pane(
        paths["state_db"], tmux_pane_id="%inactive",
        tmux_window_index=0, tmux_pane_index=5,
        active=0,
    )
    f9.seed_agent(
        paths["state_db"],
        agent_id=inactive_id, role="slave", label="zombie",
        tmux_pane_id="%inactive",
        tmux_window_index=0, tmux_pane_index=5,
        active=0,
    )
    row = _send(paths, sender_agent_id=_MASTER_ID, target=inactive_id)
    assert row["state"] == "blocked"
    assert row["block_reason"] == "target_not_active"


# ──────────────────────────────────────────────────────────────────────
# AS7 — target's container inactive → target_container_inactive
# ──────────────────────────────────────────────────────────────────────


def test_us2_as7_container_inactive_blocked(tmp_path: Path) -> None:
    """Build a fresh daemon with an INACTIVE container, then a slave
    pane in that container. The permission gate's step 5 should fire."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        # First the sender (master) in the default ACTIVE container.
        f9.seed_container(paths["state_db"])
        f9.seed_pane(
            paths["state_db"], tmux_pane_id="%master",
            tmux_window_index=0, tmux_pane_index=0,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_MASTER_ID, role="master", label="queen",
            tmux_pane_id="%master",
            tmux_window_index=0, tmux_pane_index=0,
        )
        # Then a target in an INACTIVE container.
        dead_container = "d" * 64
        f9.seed_container(paths["state_db"], container_id=dead_container, active=0)
        f9.seed_pane(
            paths["state_db"],
            container_id=dead_container, tmux_pane_id="%target",
            tmux_window_index=0, tmux_pane_index=0,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_SLAVE_ID, role="slave", label="worker-orphan",
            container_id=dead_container, tmux_pane_id="%target",
            tmux_window_index=0, tmux_pane_index=0,
        )
        row = _send(paths, sender_agent_id=_MASTER_ID, target=_SLAVE_ID)
        assert row["state"] == "blocked"
        assert row["block_reason"] == "target_container_inactive"
    finally:
        helpers.stop_daemon_if_alive(env)


# ──────────────────────────────────────────────────────────────────────
# AS8 — target pane was deregistered → target_pane_missing
# ──────────────────────────────────────────────────────────────────────


def test_us2_as8_target_pane_missing_blocked(tmp_path: Path) -> None:
    """The agent's pane composite key has no matching ACTIVE row in the
    panes table — the permission gate's step 6 fires."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_container(paths["state_db"])
        # Master pane present, master agent present.
        f9.seed_pane(
            paths["state_db"], tmux_pane_id="%master",
            tmux_window_index=0, tmux_pane_index=0,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_MASTER_ID, role="master", label="queen",
            tmux_pane_id="%master",
            tmux_window_index=0, tmux_pane_index=0,
        )
        # Slave agent present, but its pane is INACTIVE (deregistered).
        f9.seed_pane(
            paths["state_db"], tmux_pane_id="%slave-gone",
            tmux_window_index=0, tmux_pane_index=1,
            active=0,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_SLAVE_ID, role="slave", label="worker-gone",
            tmux_pane_id="%slave-gone",
            tmux_window_index=0, tmux_pane_index=1,
            active=1,  # agent still active in registry
        )
        row = _send(paths, sender_agent_id=_MASTER_ID, target=_SLAVE_ID)
        assert row["state"] == "blocked"
        assert row["block_reason"] == "target_pane_missing"
    finally:
        helpers.stop_daemon_if_alive(env)
