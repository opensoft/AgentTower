"""T073 — Bench-container routing toggle rejection.

**Test mode**: socket-level integration. The CLI host-only refusal is
covered by the existing dispatcher unit tests
(``test_socket_methods_caller_context.py``) and would also be
exercised by a CLI-integration test from inside a bench-container
proc_root fake. This integration test reaches the live daemon's
``routing.enable`` / ``routing.disable`` dispatchers with a bench-
container ``caller_pane`` payload to verify the wire refusal end-to-end.

Per Clarifications Q2 (2026-05-11 session) + Research §R-005: the
host-only constraint is enforced at the dispatch boundary via
``caller_pane is None AND peer_uid == os.getuid()``. A bench-container
caller (``caller_pane`` set in the request) is refused with
``routing_toggle_host_only``; the flag value MUST NOT change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.socket_api.client import DaemonError, send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


@pytest.fixture()
def daemon_with_master(tmp_path: Path):
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


def _routing_status(paths: dict[str, Path]) -> dict:
    return send_request(
        paths["socket"], "routing.status", {},
        connect_timeout=2.0, read_timeout=5.0,
    )


# ──────────────────────────────────────────────────────────────────────
# routing.disable refused with caller_pane present
# ──────────────────────────────────────────────────────────────────────


def test_bench_container_routing_disable_refused(daemon_with_master) -> None:
    env, paths = daemon_with_master
    initial = _routing_status(paths)
    assert initial["value"] == "enabled"

    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"], "routing.disable",
            {"caller_pane": {"agent_id": "agt_aaaaaaaaaaaa"}},
            connect_timeout=2.0, read_timeout=5.0,
        )
    assert exc_info.value.code == "routing_toggle_host_only"

    # CRITICAL: flag value unchanged.
    after = _routing_status(paths)
    assert after["value"] == initial["value"]
    assert after["last_updated_at"] == initial["last_updated_at"]
    assert after["last_updated_by"] == initial["last_updated_by"]


# ──────────────────────────────────────────────────────────────────────
# routing.enable refused with caller_pane present
# ──────────────────────────────────────────────────────────────────────


def test_bench_container_routing_enable_refused(daemon_with_master) -> None:
    """Even if the flag is currently disabled, a bench-container
    caller's enable is refused at the dispatch boundary BEFORE the
    flag changes."""
    env, paths = daemon_with_master
    # First disable the flag from host-origin so the test has a
    # "currently disabled" baseline.
    send_request(
        paths["socket"], "routing.disable", {},
        connect_timeout=2.0, read_timeout=5.0,
    )
    disabled = _routing_status(paths)
    assert disabled["value"] == "disabled"

    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"], "routing.enable",
            {"caller_pane": {"agent_id": "agt_aaaaaaaaaaaa"}},
            connect_timeout=2.0, read_timeout=5.0,
        )
    assert exc_info.value.code == "routing_toggle_host_only"

    after = _routing_status(paths)
    assert after["value"] == "disabled"
    assert after["last_updated_at"] == disabled["last_updated_at"]


# ──────────────────────────────────────────────────────────────────────
# routing.status accepts bench-container caller (no host-only gate)
# ──────────────────────────────────────────────────────────────────────


def test_bench_container_routing_status_accepted(daemon_with_master) -> None:
    """``routing.status`` has no origin gate — bench-container callers
    can read it (contracts/socket-routing.md §"Caller context")."""
    env, paths = daemon_with_master
    result = send_request(
        paths["socket"], "routing.status",
        {"caller_pane": {"agent_id": "agt_aaaaaaaaaaaa"}},
        connect_timeout=2.0, read_timeout=5.0,
    )
    assert result["value"] in ("enabled", "disabled")
    assert "last_updated_at" in result
    assert "last_updated_by" in result
