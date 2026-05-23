"""FEAT-011 T076 — Story 5 contract-version-drift socket-level test.

Walks the version-negotiation failure paths against a real daemon over a
real Unix socket, validating the NDJSON framing on the wire (the unit
suite for US5 exercises the same code paths in-process but does not
prove the on-wire envelope shape).

Assertions:

* **FR-036 / SC-005** — a synthetic client request declaring
  ``client_app_contract_major: 2`` against the v1.x daemon receives the
  ``app_contract_major_unsupported`` failure envelope, carrying the full
  ``details`` shape and issuing no ``app_session_token``.
* **FR-007** — a follow-up session-gated ``app.dashboard`` with no token
  surfaces ``app_session_required`` (the rejected hello minted nothing).
* **SC-027 / FR-034b** — an unknown ``app.*`` method over the socket →
  ``unknown_method`` with the FR-033 stamp and ``details == {}``.
* **FR-036** — a matching major (1) still succeeds over the socket.

Socket-client helpers (``_open_socket`` / ``_call`` / ``_one_shot_call``)
and the ``env`` / ``socket_path`` fixtures mirror
``test_story1_dashboard_bootstrap.py``.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


# ─── Wire-level helpers (mirrors test_story1_dashboard_bootstrap.py) ─────


def _open_socket(socket_path: Path) -> socket.socket:
    """Open a fresh connection to the daemon socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    saved_cwd = os.getcwd()
    try:
        os.chdir(socket_path.parent)
        sock.connect(socket_path.name)
    finally:
        os.chdir(saved_cwd)
    return sock


def _call(sock: socket.socket, method: str, params: dict | None = None) -> dict:
    """Send one NDJSON request, return one NDJSON response envelope."""
    request: dict = {"method": method}
    if params is not None:
        request["params"] = params
    sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.decode("utf-8"))


def _one_shot_call(socket_path: Path, method: str, params: dict | None = None) -> dict:
    """Open a fresh connection, send one request, close (FEAT-002's
    one-request-per-connection model)."""
    sock = _open_socket(socket_path)
    try:
        return _call(sock, method, params)
    finally:
        sock.close()


# ─── Fixtures (mirrors test_story1_dashboard_bootstrap.py) ───────────────


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


@pytest.fixture
def socket_path(env: dict[str, str]) -> Path:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    return resolved_paths(Path(env["HOME"]))["socket"]


# ─── Tests ───────────────────────────────────────────────────────────────


def test_hello_major_2_returns_major_unsupported_over_socket(
    socket_path: Path,
) -> None:
    """FR-036 / SC-005: client declares major 2 over the socket →
    app_contract_major_unsupported with the full details shape, no token."""
    envelope = _one_shot_call(
        socket_path, "app.hello", {"client_app_contract_major": 2}
    )
    assert envelope["ok"] is False, envelope
    assert envelope["error"]["code"] == "app_contract_major_unsupported"
    assert envelope["app_contract_version"] == "1.0"
    # FR-034a: details carry both versions.
    details = envelope["error"]["details"]
    assert details["daemon_app_contract_version"] == "1.0"
    assert details["client_app_contract_major"] == 2
    # FR-036: no session was issued — failure envelope has no result.
    assert "result" not in envelope


def test_dashboard_without_token_after_rejected_hello_is_session_required(
    socket_path: Path,
) -> None:
    """FR-007: after a major-mismatch app.hello (which mints no token), a
    follow-up app.dashboard with no token → app_session_required."""
    rejected = _one_shot_call(
        socket_path, "app.hello", {"client_app_contract_major": 2}
    )
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "app_contract_major_unsupported"

    dashboard = _one_shot_call(socket_path, "app.dashboard")
    assert dashboard["ok"] is False, dashboard
    assert dashboard["error"]["code"] == "app_session_required"
    assert dashboard["app_contract_version"] == "1.0"
    assert dashboard["error"]["details"] == {}


def test_unknown_app_method_returns_unknown_method_over_socket(
    socket_path: Path,
) -> None:
    """SC-027 / FR-034b: an unknown app.* method over the socket →
    unknown_method, FR-033-stamped, details == {}."""
    envelope = _one_shot_call(socket_path, "app.future_method")
    assert envelope["ok"] is False, envelope
    assert envelope["error"]["code"] == "unknown_method"
    assert envelope["app_contract_version"] == "1.0"
    assert envelope["error"]["details"] == {}


def test_hello_matching_major_still_succeeds_over_socket(
    socket_path: Path,
) -> None:
    """FR-036: a matching major (1) still negotiates a session over the
    socket — the drift check rejects only a mismatch."""
    envelope = _one_shot_call(
        socket_path, "app.hello", {"client_app_contract_major": 1}
    )
    assert envelope["ok"] is True, envelope
    assert envelope["result"]["app_contract_version"] == "1.0"
    assert isinstance(envelope["result"]["app_session_token"], str)
    assert envelope["result"]["app_session_token"]
