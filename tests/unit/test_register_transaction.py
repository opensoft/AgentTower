"""Unit tests for FEAT-006 single-transaction commit / rollback (T036 / FR-035).

Covers:
* On INSERT failure (forced ``IntegrityError``), no agent row is written.
* On INSERT failure, no audit row is appended.
* The daemon stays alive (the service raises ``RegistrationError`` with
  code ``internal_error``).
"""

from __future__ import annotations

import sqlite3
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


def test_register_failure_rolls_back_and_skips_audit(
    tmp_path: Path, monkeypatch
) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    from agenttower.agents import service as service_mod
    from agenttower.state import agents as state_agents

    def boom_insert(*args, **kwargs):
        raise sqlite3.OperationalError("forced for test")

    monkeypatch.setattr(state_agents, "insert_agent", boom_insert)

    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(role="slave"), socket_peer_uid=1000
        )
    assert info.value.code == "internal_error"

    # No agent row was written.
    conn = service.connection_factory()
    try:
        count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    finally:
        conn.close()
    assert count == 0
    # No audit row was appended.
    assert read_events(service) == []
