"""FEAT-011 T073 — Story 5 capability_flags unit tests.

Covers FR-039: ``capability_flags`` is always present on every
``app.hello`` success envelope and is exactly ``{}`` at v1.0 (every
v1.0 method is required, so there is nothing to feature-flag).

Also a forward-compat smoke (SC-009): a synthetic *future-daemon*
``capability_flags`` carrying an unknown named flag must not break a
v1.0 client's flag-reading pattern. A v1.0 client reads flags by name
via ``.get(...)`` (default-false) and merges the daemon's map onto its
local defaults — unknown keys ride along harmlessly.

Pure in-process tests — handlers called directly (SC-001).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import hello as hello_mod
from agenttower.app_contract import sessions, versioning
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures (copied from test_app_contract_smoke.py) ───────────────────


@pytest.fixture
def daemon_ctx(tmp_path: Path) -> DaemonContext:
    """Minimal DaemonContext for handlers that only need version + schema."""
    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=tmp_path / "state.db",
        daemon_version="0.0.0-test",
        schema_version=10,
    )


@pytest.fixture(autouse=True)
def fresh_session_registry() -> None:
    """Ensure each test sees a clean SessionRegistry."""
    sessions.set_registry(sessions.SessionRegistry())


@pytest.fixture
def host_peer(monkeypatch: pytest.MonkeyPatch):
    """Set thread-local request peer context to the daemon's own pid (host)."""
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    uid = os.geteuid()
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield uid
    finally:
        _clear_request_peer_context()


# ─── FR-039: capability_flags is present and {} at v1.0 ──────────────────


def test_hello_capability_flags_present_and_empty(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-039: app.hello success → capability_flags present and exactly {}."""
    env = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"] is True
    assert "capability_flags" in env["result"]
    assert env["result"]["capability_flags"] == {}


def test_capability_flags_empty_on_every_hello_variant(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-039: capability_flags is {} on every v1.0 app.hello success,
    regardless of which optional client params are supplied."""
    variants = [
        {},
        {"client_id": "cap-test"},
        {"client_version": "9.9.9"},
        {"client_app_contract_major": 1},
        {"client_id": "c", "client_version": "v", "client_app_contract_major": 1},
    ]
    for params in variants:
        env = hello_mod.app_hello(daemon_ctx, params, peer_uid=host_peer)
        assert env["ok"] is True, (params, env)
        assert env["result"]["capability_flags"] == {}, params


def test_capability_flags_constant_is_empty_at_v1_0() -> None:
    """FR-039: the module-level v1.0 constant is the empty closed set."""
    assert versioning.CAPABILITY_FLAGS_V1_0 == {}


def test_capability_flags_is_a_fresh_copy_per_call(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """Defensive-copy guarantee: mutating the returned capability_flags map
    must not corrupt the module constant or a later app.hello response."""
    env1 = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    env1["result"]["capability_flags"]["injected"] = True  # caller mutation

    env2 = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert env2["result"]["capability_flags"] == {}
    assert versioning.CAPABILITY_FLAGS_V1_0 == {}


# ─── SC-009 forward-compat: unknown capability_flags keys are tolerated ──


def _read_capability_flag(flags: dict, name: str) -> bool:
    """v1.0 client-side flag read: name-keyed, default-false ``.get``.

    A v1.0 client never enumerates the map; it asks for the specific
    flags it knows about. Unknown keys are simply never queried.
    """
    return bool(flags.get(name, False))


def _merge_capability_flags(local_defaults: dict, daemon_flags: dict) -> dict:
    """v1.0 client-side flag merge: daemon's map overlays local defaults.

    Unknown daemon keys ride along without error — the merge is a plain
    dict update, and the client only ever *reads* keys it knows.
    """
    merged = dict(local_defaults)
    merged.update(daemon_flags)
    return merged


def test_unknown_capability_flag_key_does_not_break_get_pattern() -> None:
    """SC-009: a synthetic future-daemon capability_flags carrying an
    unknown named flag is parsed without error by a v1.0 client."""
    future_flags = {"events_subscribe": True}  # not a v1.0 flag
    # A v1.0 client asks only for flags it knows; the unknown key is
    # never queried and never raises.
    assert _read_capability_flag(future_flags, "some_v1_flag") is False
    # Querying the future key still works (it's just a dict.get) — the
    # point is no KeyError / parse failure occurs.
    assert _read_capability_flag(future_flags, "events_subscribe") is True


def test_unknown_capability_flag_survives_merge() -> None:
    """SC-009: merging a future-daemon flag map onto a v1.0 client's
    local defaults tolerates unknown keys (plain dict update)."""
    local_defaults: dict = {}  # v1.0 client has no known flags
    future_flags = {"events_subscribe": True, "another_future_flag": False}

    merged = _merge_capability_flags(local_defaults, future_flags)
    # The unknown keys merged in cleanly.
    assert merged == {"events_subscribe": True, "another_future_flag": False}
    # And the v1.0 client still reads its known (absent) flags safely.
    assert _read_capability_flag(merged, "some_v1_flag") is False


def test_v1_0_hello_flags_merge_is_a_no_op() -> None:
    """SC-009: at v1.0 the daemon's capability_flags is {}, so a client
    merge against local defaults leaves the defaults unchanged."""
    local_defaults: dict = {}
    merged = _merge_capability_flags(
        local_defaults, dict(versioning.CAPABILITY_FLAGS_V1_0)
    )
    assert merged == {}
