"""T063 — ``--target`` resolution end-to-end (Research §R-001).

**Test mode**: socket-level integration. Drives queue.send_input over
the FEAT-002 client to exercise the target_resolver's full match
behavior against the live daemon's agents registry. Unit-level
coverage of the pure resolver lives in
``tests/unit/test_routing_target_resolver.py``.

Covered cases:

1. agent_id (``agt_<12-hex>``) → resolves and delivers.
2. Unique label → resolves and delivers.
3. Ambiguous label (matches ≥ 2 active agents) → ``target_label_ambiguous``,
   no row created.
4. Unknown target (neither agent_id nor any active label match) →
   ``agent_not_found``, no row created.
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
_SLAVE_A = "agt_bbbbbbbbbbbb"
_SLAVE_B = "agt_dddddddddddd"


def _send(
    paths: dict[str, Path], *, sender: str, target: str,
) -> dict:
    body_b64 = base64.b64encode(b"hi").decode("ascii")
    return send_request(
        paths["socket"], "queue.send_input",
        {
            "target": target,
            "body_bytes": body_b64,
            "caller_pane": f9.caller_pane_from_db(paths["state_db"], sender),
            "wait": False,
        },
        connect_timeout=2.0, read_timeout=10.0,
    )


def _row_count(state_db: Path) -> int:
    conn = sqlite3.connect(state_db)
    try:
        return conn.execute("SELECT COUNT(*) FROM message_queue").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def daemon_with_resolver_targets(tmp_path: Path):
    """Master + two slaves; the two slaves share a label so that label
    is ambiguous, while each has a distinct agent_id."""
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
            paths["state_db"], tmux_pane_id="%slave-a",
            tmux_window_index=0, tmux_pane_index=1,
        )
        f9.seed_pane(
            paths["state_db"], tmux_pane_id="%slave-b",
            tmux_window_index=0, tmux_pane_index=2,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_MASTER_ID, role="master", label="queen",
            tmux_pane_id="%master",
            tmux_window_index=0, tmux_pane_index=0,
        )
        # Both slaves share the label "worker" → ambiguous.
        f9.seed_agent(
            paths["state_db"],
            agent_id=_SLAVE_A, role="slave", label="worker",
            tmux_pane_id="%slave-a",
            tmux_window_index=0, tmux_pane_index=1,
        )
        f9.seed_agent(
            paths["state_db"],
            agent_id=_SLAVE_B, role="slave", label="worker",
            tmux_pane_id="%slave-b",
            tmux_window_index=0, tmux_pane_index=2,
        )
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


# ──────────────────────────────────────────────────────────────────────
# Case 1 — agent_id resolves directly
# ──────────────────────────────────────────────────────────────────────


def test_target_agent_id_resolves(daemon_with_resolver_targets) -> None:
    env, paths = daemon_with_resolver_targets
    row = _send(paths, sender=_MASTER_ID, target=_SLAVE_A)
    # Either delivered (worker won the race) or queued — both confirm
    # the resolver matched the agent_id without raising.
    assert row["state"] in ("queued", "delivered")
    assert row["target"]["agent_id"] == _SLAVE_A


# ──────────────────────────────────────────────────────────────────────
# Case 2 — unique label resolves
# ──────────────────────────────────────────────────────────────────────


def test_unique_label_resolves(tmp_path: Path) -> None:
    """Fresh daemon with ONE slave whose label is unique so the
    resolver succeeds via label match."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(
            paths["state_db"],
            slave_label="solo-worker",
        )
        row = _send(paths, sender=_MASTER_ID, target="solo-worker")
        assert row["state"] in ("queued", "delivered")
        assert row["target"]["label"] == "solo-worker"
    finally:
        helpers.stop_daemon_if_alive(env)


# ──────────────────────────────────────────────────────────────────────
# Case 3 — ambiguous label → target_label_ambiguous, no row
# ──────────────────────────────────────────────────────────────────────


def test_ambiguous_label_refused_with_no_row(
    daemon_with_resolver_targets,
) -> None:
    env, paths = daemon_with_resolver_targets
    initial_rows = _row_count(paths["state_db"])
    with pytest.raises(DaemonError) as exc_info:
        _send(paths, sender=_MASTER_ID, target="worker")
    assert exc_info.value.code == "target_label_ambiguous"
    assert _row_count(paths["state_db"]) == initial_rows


# ──────────────────────────────────────────────────────────────────────
# Case 4 — unknown target → agent_not_found, no row
# ──────────────────────────────────────────────────────────────────────


def test_unknown_target_refused_with_no_row(
    daemon_with_resolver_targets,
) -> None:
    env, paths = daemon_with_resolver_targets
    initial_rows = _row_count(paths["state_db"])
    with pytest.raises(DaemonError) as exc_info:
        _send(paths, sender=_MASTER_ID, target="nonexistent-label")
    assert exc_info.value.code == "agent_not_found"
    assert _row_count(paths["state_db"]) == initial_rows
