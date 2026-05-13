"""T088 — Host vs bench-container CLI parity.

**Test mode**: socket-level integration. Drives ``queue.list`` /
``routing.status`` over the FEAT-002 client with and without a
``caller_pane`` payload to model host-origin vs bench-container thin
client. Asserts the documented parity (FR-029) for read paths and the
origin-gated rejection for write paths.

Parity expectations:

* ``queue.list`` — accepts both host and bench-container callers
  (FR-029 — operator surface stays online).
* ``routing.status`` — same.
* ``queue.send_input`` — host-origin (caller_pane=None) → refused
  with ``sender_not_in_pane`` (Q3 from Clarifications).
* ``routing.enable`` / ``routing.disable`` — bench-container caller
  (caller_pane set) → refused with ``routing_toggle_host_only``
  (Q2 from Clarifications + Research §R-005).

This file consolidates the parity invariants that were spread across
US2 (host send-input refusal) and US4 (bench-container toggle
refusal) into a single per-method matrix.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from agenttower.socket_api.client import DaemonError, send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"
_BENCH_CALLER_PANE = {"agent_id": _MASTER_ID}


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


# ──────────────────────────────────────────────────────────────────────
# Read parity: queue.list + routing.status from both origins
# ──────────────────────────────────────────────────────────────────────


def test_queue_list_accepts_host_and_bench_with_same_shape(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave

    # Host-origin invocation (no caller_pane).
    host_result = send_request(
        paths["socket"], "queue.list", {},
        connect_timeout=2.0, read_timeout=5.0,
    )
    assert "rows" in host_result
    assert "next_cursor" in host_result

    # Bench-container invocation (caller_pane present).
    bench_result = send_request(
        paths["socket"], "queue.list", {"caller_pane": _BENCH_CALLER_PANE},
        connect_timeout=2.0, read_timeout=5.0,
    )
    # Same shape, same keys.
    assert set(host_result.keys()) == set(bench_result.keys())


def test_routing_status_accepts_host_and_bench_with_same_shape(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave

    host_result = send_request(
        paths["socket"], "routing.status", {},
        connect_timeout=2.0, read_timeout=5.0,
    )
    bench_result = send_request(
        paths["socket"], "routing.status",
        {"caller_pane": _BENCH_CALLER_PANE},
        connect_timeout=2.0, read_timeout=5.0,
    )
    # Same documented fields from both origins.
    expected = {"value", "last_updated_at", "last_updated_by"}
    assert set(host_result.keys()) == expected == set(bench_result.keys())
    # Identical content too — no state has changed between the calls.
    assert host_result["value"] == bench_result["value"]


# ──────────────────────────────────────────────────────────────────────
# Write parity: send-input origin gate (host refused)
# ──────────────────────────────────────────────────────────────────────


def test_queue_send_input_host_origin_refused_at_dispatch(
    daemon_with_master_and_slave,
) -> None:
    """Without ``caller_pane``, the dispatcher refuses with
    ``sender_not_in_pane`` — this is the daemon-side gate (separate
    from the CLI's ``host_context_unsupported`` early refusal in
    test_queue_send_input_host_refused.py)."""
    env, paths = daemon_with_master_and_slave
    body_b64 = base64.b64encode(b"hi").decode("ascii")
    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"], "queue.send_input",
            {
                "target": _SLAVE_ID,
                "body_bytes": body_b64,
                "wait": False,
                # caller_pane intentionally omitted.
            },
            connect_timeout=2.0, read_timeout=5.0,
        )
    assert exc_info.value.code == "sender_not_in_pane"


def test_queue_send_input_bench_origin_accepted(
    daemon_with_master_and_slave,
) -> None:
    """Same call WITH ``caller_pane`` succeeds at the dispatch
    boundary — proves the gate is solely on caller_pane presence."""
    env, paths = daemon_with_master_and_slave
    body_b64 = base64.b64encode(b"hi").decode("ascii")
    result = send_request(
        paths["socket"], "queue.send_input",
        {
            "target": _SLAVE_ID,
            "body_bytes": body_b64,
            "caller_pane": _BENCH_CALLER_PANE,
            "wait": False,
        },
        connect_timeout=2.0, read_timeout=5.0,
    )
    # Either queued or delivered (worker race) — both prove acceptance.
    assert result["state"] in ("queued", "delivered")


# ──────────────────────────────────────────────────────────────────────
# Write parity: routing.enable/disable origin gate (bench refused)
# ──────────────────────────────────────────────────────────────────────


def test_routing_disable_bench_origin_refused(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"], "routing.disable",
            {"caller_pane": _BENCH_CALLER_PANE},
            connect_timeout=2.0, read_timeout=5.0,
        )
    assert exc_info.value.code == "routing_toggle_host_only"


def test_routing_enable_bench_origin_refused(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    # Disable first from host so the flag is currently disabled.
    send_request(
        paths["socket"], "routing.disable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )
    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"], "routing.enable",
            {"caller_pane": _BENCH_CALLER_PANE},
            connect_timeout=2.0, read_timeout=5.0,
        )
    assert exc_info.value.code == "routing_toggle_host_only"


def test_routing_disable_host_origin_accepted(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    result = send_request(
        paths["socket"], "routing.disable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )
    assert result["current_value"] == "disabled"
    assert result["changed"] is True
