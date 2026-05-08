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
    # 5 ms sleep is enough margin to keep the strict ``>`` assertion
    # below stable on fast hardware where two ISO-8601-microsecond
    # timestamps could otherwise collide (review-pass-6 N34).
    time.sleep(0.005)
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


def test_different_pane_creates_distinct_agent(tmp_path: Path) -> None:
    """FR-006 / spec edge case line 88 (review-pass-6 N17).

    A second register-self from a *different* composite pane key MUST
    create a NEW agent rather than rebinding the first one. The old
    agent stays in the table with whatever ``active`` flag FEAT-004
    last assigned (here we force it inactive to assert both rows
    coexist as the spec requires).
    """
    from ._agent_test_helpers import CONTAINER_ID

    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")

    first = service.register_agent(
        register_params(role="slave", label="alpha"),
        socket_peer_uid=1000,
    )
    # Force first agent inactive to exercise the "old row stays in
    # history" half of the spec.
    conn = service.connection_factory()
    try:
        conn.execute(
            "UPDATE agents SET active = 0 WHERE agent_id = ?",
            (first["agent_id"],),
        )
    finally:
        conn.close()

    ck1 = (CONTAINER_ID, CK_DEFAULT[1], CK_DEFAULT[2], 0, 1, "%1")
    second = service.register_agent(
        register_params(ck1, role="slave", label="beta"),
        socket_peer_uid=1000,
    )

    assert second["agent_id"] != first["agent_id"]
    assert second["created_or_reactivated"] == "created"

    listed = service.list_agents({})["agents"]
    ids = {a["agent_id"] for a in listed}
    assert {first["agent_id"], second["agent_id"]} <= ids


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
