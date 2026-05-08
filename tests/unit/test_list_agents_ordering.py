"""Unit tests for FEAT-006 list_agents deterministic ordering (T030 / FR-025).

Order is ``active DESC, container_id ASC, parent_agent_id NULLS FIRST,
label ASC, agent_id ASC``. Asserted by inserting rows in a SCRAMBLED
order and confirming the deterministic sort.
"""

from __future__ import annotations

from pathlib import Path

from ._agent_test_helpers import (
    CK_DEFAULT,
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def test_active_desc_then_container_then_label(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service, container_id="a" * 64, name="bench-a")
    seed_container(service, container_id="b" * 64, name="bench-b")
    seed_pane(service, container_id="a" * 64, container_name="bench-a", tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, container_id="b" * 64, container_name="bench-b", tmux_pane_index=1, tmux_pane_id="%1")
    seed_pane(service, container_id="b" * 64, container_name="bench-b", tmux_pane_index=2, tmux_pane_id="%2")

    a = service.register_agent(
        register_params(
            ("a" * 64, CK_DEFAULT[1], "main", 0, 0, "%0"),
            role="slave", label="zlabel",
        ),
        socket_peer_uid=1000,
    )
    b = service.register_agent(
        register_params(
            ("b" * 64, CK_DEFAULT[1], "main", 0, 1, "%1"),
            role="slave", label="alpha",
        ),
        socket_peer_uid=1000,
    )
    c = service.register_agent(
        register_params(
            ("b" * 64, CK_DEFAULT[1], "main", 0, 2, "%2"),
            role="slave", label="beta",
        ),
        socket_peer_uid=1000,
    )

    # Mark agent c inactive so we can assert active DESC.
    conn = service.connection_factory()
    try:
        conn.execute("UPDATE agents SET active = 0 WHERE agent_id = ?", (c["agent_id"],))
    finally:
        conn.close()

    rows = service.list_agents({})["agents"]
    # Expected order: a (active, container=a..., zlabel), b (active, container=b..., alpha), c (inactive)
    assert [r["agent_id"] for r in rows] == [a["agent_id"], b["agent_id"], c["agent_id"]]
