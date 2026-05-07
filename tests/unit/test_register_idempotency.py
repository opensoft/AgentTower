"""Unit tests for FEAT-006 idempotent re-registration (T026 / FR-007).

Covers:
* Re-registration with the same composite key returns the same agent_id.
* Mutable fields supplied REPLACE stored values.
* Mutable fields not supplied LEAVE stored values unchanged.
* ``created_at`` / ``parent_agent_id`` / pane composite key never change.
* ``last_registered_at`` updates on every re-registration.
"""

from __future__ import annotations

import time
from pathlib import Path

from ._agent_test_helpers import (
    CK_DEFAULT,
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def test_idempotent_returns_same_agent_id(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    first = service.register_agent(
        register_params(role="slave", capability="codex", label="lbl"),
        socket_peer_uid=1000,
    )
    time.sleep(0.001)
    second = service.register_agent(
        register_params(role="slave", capability="codex", label="lbl"),
        socket_peer_uid=1000,
    )

    assert first["agent_id"] == second["agent_id"]
    assert first["created_at"] == second["created_at"]
    # last_registered_at advances strictly.
    assert second["last_registered_at"] > first["last_registered_at"]
    assert first["created_or_reactivated"] == "created"
    assert second["created_or_reactivated"] == "updated"


def test_supplied_fields_replace_stored(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    service.register_agent(
        register_params(role="slave", capability="codex", label="orig"),
        socket_peer_uid=1000,
    )
    second = service.register_agent(
        register_params(label="new", capability="claude"),
        socket_peer_uid=1000,
    )
    assert second["label"] == "new"
    assert second["capability"] == "claude"
    # Role was NOT supplied this time → stored value preserved.
    assert second["role"] == "slave"


def test_omitted_fields_preserve_stored(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    service.register_agent(
        register_params(role="slave", capability="codex", label="orig", project_path="/w/a"),
        socket_peer_uid=1000,
    )
    # Re-register with NO mutable flags — every stored value should survive.
    second = service.register_agent(
        register_params(),
        socket_peer_uid=1000,
    )
    assert second["role"] == "slave"
    assert second["capability"] == "codex"
    assert second["label"] == "orig"
    assert second["project_path"] == "/w/a"


def test_pane_key_and_created_at_immutable(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    second = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Composite key columns survive byte-for-byte.
    for key in (
        "container_id",
        "tmux_socket_path",
        "tmux_session_name",
        "tmux_window_index",
        "tmux_pane_index",
        "tmux_pane_id",
        "created_at",
        "parent_agent_id",
    ):
        assert first[key] == second[key]
