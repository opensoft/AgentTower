"""Unit tests for FEAT-006 JSONL audit-row shape (T064 / FR-014).

Covers:
* Exactly one row per successful role transition.
* Required fields: ``ts`` (microsecond UTC), ``type``, ``payload`` containing
  ``agent_id``, ``prior_role``, ``new_role``, ``confirm_provided``,
  ``socket_peer_uid``.
* Failed transitions append no row.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError

from ._agent_test_helpers import (
    make_service,
    read_events,
    register_params,
    seed_container,
    seed_pane,
)


def test_single_audit_row_per_transition(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    rows = read_events(service)
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert rows[0]["type"] == "agent_role_change"
    assert payload["prior_role"] is None
    assert payload["new_role"] == "slave"
    assert payload["confirm_provided"] is False
    assert payload["socket_peer_uid"] == 1000
    # ts is ISO-8601 microsecond UTC with explicit +00:00 offset.
    assert re.match(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00", rows[0]["ts"]
    )


def test_failed_transition_appends_no_row(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    pre = len(read_events(service))
    with pytest.raises(RegistrationError):
        service.set_role(
            {"agent_id": first["agent_id"], "role": "master"},  # missing confirm
            socket_peer_uid=1000,
        )
    assert len(read_events(service)) == pre


def test_set_role_appends_audit_row(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    service.set_role(
        {"agent_id": first["agent_id"], "role": "master", "confirm": True},
        socket_peer_uid=1000,
    )
    rows = read_events(service)
    # Two: creation + role change.
    assert len(rows) == 2
    payload = rows[1]["payload"]
    assert payload["prior_role"] == "slave"
    assert payload["new_role"] == "master"
    assert payload["confirm_provided"] is True
