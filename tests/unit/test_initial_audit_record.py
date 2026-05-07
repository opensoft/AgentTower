"""Unit tests for FEAT-006 initial-creation audit row (T065 / Clarifications Q4).

Covers:
* First successful ``register-self`` for a pane appends one audit row
  with ``prior_role: null`` (JSON literal), regardless of role —
  including default ``--role unknown``.
* Idempotent re-registration with unchanged role appends NO new row
  (FR-027).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._agent_test_helpers import (
    make_service,
    read_events,
    register_params,
    seed_container,
    seed_pane,
)


@pytest.mark.parametrize(
    "role",
    ["slave", "swarm", "test-runner", "shell", "unknown"],
)
def test_initial_register_writes_audit_row_with_prior_role_null(
    tmp_path: Path, role: str
) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    if role == "swarm":
        # Swarm needs a parent slave first.
        seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")
        parent = service.register_agent(
            register_params(role="slave"), socket_peer_uid=1000
        )
        ck1 = ("c" * 64, "/tmp/tmux-1000/default", "main", 0, 1, "%1")
        service.register_agent(
            register_params(ck1, role="swarm", parent_agent_id=parent["agent_id"]),
            socket_peer_uid=1000,
        )
        rows = read_events(service)
        # parent registration + swarm registration → two rows.
        assert len(rows) == 2
        assert rows[0]["payload"]["prior_role"] is None
        assert rows[1]["payload"]["prior_role"] is None
        assert rows[1]["payload"]["new_role"] == "swarm"
    else:
        params = register_params() if role == "unknown" else register_params(role=role)
        service.register_agent(params, socket_peer_uid=1000)
        rows = read_events(service)
        assert len(rows) == 1
        assert rows[0]["payload"]["prior_role"] is None
        assert rows[0]["payload"]["new_role"] == role


def test_idempotent_unchanged_role_writes_no_new_row(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    pre = len(read_events(service))
    # Re-register with the same role — no new audit row (FR-027).
    service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    assert len(read_events(service)) == pre
