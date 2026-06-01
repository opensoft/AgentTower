"""FEAT-011 T069 — Story 4 socket-level integration test.

Story 4 ("degraded & unavailable states"): an operator dashboard must
render a *structured* picture of a partially-healthy system without
ever parsing CLI text. This test walks the degraded failure modes
against a real daemon over a real Unix socket and asserts every
response is a well-formed FEAT-011 envelope.

A fresh daemon started with no bench containers is the natural Story 4
fixture: it has nothing to coordinate, so the readiness/dashboard
surfaces must still render a *structured*, hint-bearing picture. Two
shapes can result depending on the host environment:

* if Docker is reachable from the daemon, every subsystem probes ``ok``
  and ``app.readiness`` reports ``state == "ready"`` with a
  ``start_bench_container`` hint (zero containers, but the system is
  healthy enough to start one);
* if Docker is *not* reachable, the ``docker`` subsystem probes
  ``unavailable``, the top-level ``state`` drops to ``degraded``, and a
  ``docker_unavailable_hint`` is emitted.

Either way the wire surface is structured and hint-bearing — that is
the Story 4 contract. The per-subsystem *degraded* branches are
exhaustively unit-tested in ``tests/unit/test_app_us4_readiness_degraded.py``;
this integration test pins the structured-envelope + socket-only
contract end to end. No fault injection needed.

Assertions:

* **SC-007 — zero CLI text parsed.** Every method here is reached via
  raw NDJSON-over-socket. The daemon is started once via
  ``ensure-daemon`` (a setup-only concern); after that the test drives
  ``app.preflight`` / ``app.readiness`` / ``app.dashboard`` purely with
  a hand-rolled socket client. No ``agenttower`` subprocess is invoked
  for any UI-rendering path, and no stdout/stderr text is ever parsed.
* Every envelope round-trips with the documented
  ``{ok, app_contract_version, ...}`` shape.
* ``app.readiness`` reports ``state`` from the closed set
  ``{ready, degraded, unavailable}`` and a non-empty, well-formed
  hints array (a zero-container daemon always emits at least one
  next-step hint).

Connection model note (FEAT-002 invariant): the daemon dispatches one
request per connection and closes the socket afterwards. FEAT-011
sessions live in a process-wide registry keyed by ``app_session_token``,
so the client opens a fresh socket per call and re-presents the token.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from agenttower.app_contract import versioning

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)

# The closed FEAT-011 readiness state set (FR-012) and subsystem names
# (FR-013). Hard-coded here (not imported) so the test pins the wire
# contract independently of the daemon's own constants.
_READINESS_STATES = {"ready", "degraded", "unavailable"}
_SUBSYSTEM_NAMES = (
    "docker",
    "tmux_discovery",
    "sqlite",
    "jsonl",
    "routing_worker",
    "log_attachment_workers",
)


# ─── Wire-level helpers (socket only — never a CLI subprocess) ───────────


def _open_socket(socket_path: Path) -> socket.socket:
    """Open a fresh connection to the daemon socket.

    Uses chdir-relative connect because some kernels limit ``AF_UNIX``
    paths to 108 bytes; the test-temp HOME tree can exceed that.
    """
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


def _one_shot_call(
    socket_path: Path, method: str, params: dict | None = None
) -> dict:
    """Open a fresh connection, send one request, close. Matches FEAT-002's
    one-request-per-connection model."""
    sock = _open_socket(socket_path)
    try:
        return _call(sock, method, params)
    finally:
        sock.close()


def _assert_feat011_envelope(envelope: dict) -> None:
    """Every FEAT-011 response — ok or not — carries the version stamp and
    exactly one of result / error."""
    assert isinstance(envelope, dict)
    assert envelope["app_contract_version"] == versioning.APP_CONTRACT_VERSION
    assert isinstance(envelope["ok"], bool)
    if envelope["ok"]:
        assert "result" in envelope
        assert "error" not in envelope
    else:
        assert "error" in envelope
        err = envelope["error"]
        assert isinstance(err["code"], str) and err["code"]
        assert isinstance(err["message"], str)
        assert isinstance(err["details"], dict)


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


@pytest.fixture
def socket_path(env: dict[str, str]) -> Path:
    """A running, freshly-booted daemon with NO bench containers.

    This is the natural degraded state Story 4 exercises.
    """
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    return resolved_paths(Path(env["HOME"]))["socket"]


@pytest.fixture
def token(socket_path: Path) -> str:
    """A valid app_session_token from app.hello — over the socket only."""
    hello = _one_shot_call(socket_path, "app.hello", {"client_id": "story4-test"})
    assert hello["ok"] is True, hello
    return hello["result"]["app_session_token"]


# ─── app.preflight over the socket ───────────────────────────────────────


def test_preflight_is_structured_envelope_over_socket(socket_path: Path) -> None:
    """app.preflight (no session needed) returns a structured FEAT-011
    envelope with a closed-set diagnostic ``code``."""
    envelope = _one_shot_call(socket_path, "app.preflight")
    _assert_feat011_envelope(envelope)
    assert envelope["ok"] is True
    result = envelope["result"]
    # A running daemon that is not shutting down → ok.
    assert result["code"] in {
        "ok",
        "daemon_unavailable",
        "socket_missing",
        "socket_permission_denied",
    }
    assert result["code"] == "ok"
    assert result["socket_reachable"] is True
    assert result["daemon_reachable"] is True


# ─── app.readiness degraded surface over the socket ──────────────────────


def test_readiness_reports_structured_state_over_socket(
    socket_path: Path, token: str
) -> None:
    """A fresh daemon with no bench containers → app.readiness returns a
    structured surface: every subsystem row is well-formed and carries
    the documented field set, the top-level ``state`` is from the closed
    set, and the ok/non-ok reason invariant holds per row."""
    envelope = _one_shot_call(
        socket_path, "app.readiness", {"app_session_token": token}
    )
    _assert_feat011_envelope(envelope)
    assert envelope["ok"] is True, envelope
    result = envelope["result"]

    # FR-012: state is from the closed set.
    assert result["state"] in _READINESS_STATES

    # FR-013: all six subsystem rows present, in fixed order, well-formed.
    assert [s["name"] for s in result["subsystems"]] == list(_SUBSYSTEM_NAMES)
    for row in result["subsystems"]:
        assert set(row.keys()) == {"name", "status", "reason", "hint"}
        assert row["status"] in {"ok", "degraded", "unavailable"}
        if row["status"] == "ok":
            assert row["reason"] == ""  # ok ⇒ empty-reason invariant
        else:
            assert row["reason"] != ""  # non-ok ⇒ explanatory reason

    # FR-014a: hints array always present, and a zero-container daemon
    # always surfaces at least one next-step hint (start_bench_container
    # if docker is reachable, docker_unavailable_hint if it is not).
    assert isinstance(result["hints"], list)
    assert len(result["hints"]) >= 1
    for hint in result["hints"]:
        assert isinstance(hint["code"], str) and hint["code"]
        assert hint["severity"] in {"info", "warning", "action_required"}
        assert isinstance(hint["message"], str) and hint["message"]


def test_readiness_emits_empty_system_hint_over_socket(
    socket_path: Path, token: str
) -> None:
    """A fresh daemon with no bench containers emits a structured,
    action-bearing hint over the socket: either ``start_bench_container``
    (docker reachable) or ``docker_unavailable_hint`` (docker not
    reachable). Whichever fires, it is ``action_required`` severity and
    structured — the operator UI never parses CLI text to learn this."""
    envelope = _one_shot_call(
        socket_path, "app.readiness", {"app_session_token": token}
    )
    assert envelope["ok"] is True, envelope
    by_code = {h["code"]: h for h in envelope["result"]["hints"]}
    # Exactly one of the two empty-system hints must be present.
    empty_system_codes = {"start_bench_container", "docker_unavailable_hint"}
    fired = empty_system_codes & set(by_code)
    assert fired, (
        f"expected one of {empty_system_codes} on an empty daemon, "
        f"got hints {sorted(by_code)}"
    )
    for code in fired:
        assert by_code[code]["severity"] == "action_required"


# ─── app.dashboard degraded surface over the socket ──────────────────────


def test_dashboard_reports_structured_empty_surface_over_socket(
    socket_path: Path, token: str
) -> None:
    """app.dashboard on a fresh daemon → structured zero-count surface +
    a hints array (the empty-system degraded view)."""
    envelope = _one_shot_call(
        socket_path, "app.dashboard", {"app_session_token": token}
    )
    _assert_feat011_envelope(envelope)
    assert envelope["ok"] is True, envelope
    result = envelope["result"]

    # All 7 count surfaces present.
    assert set(result["counts"].keys()) == {
        "containers",
        "panes",
        "agents",
        "log_attachments",
        "events",
        "queue",
        "routes",
    }
    # Empty system → zero containers across every bucket.
    for bucket in ("active", "inactive", "degraded_scan"):
        assert result["counts"]["containers"][bucket] == 0

    # Recents present and structured.
    assert set(result["recent"].keys()) == {"events", "queue", "routes"}
    for surface in ("events", "queue", "routes"):
        assert isinstance(result["recent"][surface], list)

    # Hints array present; a zero-container daemon surfaces an
    # action-bearing empty-system hint (start_bench_container if docker
    # is reachable, docker_unavailable_hint if not).
    assert isinstance(result["hints"], list)
    codes = {h["code"] for h in result["hints"]}
    assert codes & {"start_bench_container", "docker_unavailable_hint"}, codes


# ─── SC-007: the whole flow uses the socket only ─────────────────────────


def test_sc007_full_degraded_walk_uses_socket_only(
    socket_path: Path,
) -> None:
    """SC-007: an operator dashboard renders the degraded picture from
    the socket alone — zero CLI text parsed.

    This test deliberately walks the entire Story 4 surface
    (preflight → hello → readiness → dashboard) using only
    ``_one_shot_call`` (a raw socket client). It never spawns an
    ``agenttower`` subprocess and never reads stdout/stderr, proving the
    backend contract is fully self-describing over the wire.
    """
    # 1. preflight — no session.
    preflight = _one_shot_call(socket_path, "app.preflight")
    _assert_feat011_envelope(preflight)
    assert preflight["ok"] is True

    # 2. hello — mint a session token.
    hello = _one_shot_call(socket_path, "app.hello")
    _assert_feat011_envelope(hello)
    assert hello["ok"] is True
    session_token = hello["result"]["app_session_token"]

    # 3. readiness — structured degraded state.
    readiness = _one_shot_call(
        socket_path, "app.readiness", {"app_session_token": session_token}
    )
    _assert_feat011_envelope(readiness)
    assert readiness["ok"] is True
    assert readiness["result"]["state"] in _READINESS_STATES

    # 4. dashboard — structured count surface.
    dashboard = _one_shot_call(
        socket_path, "app.dashboard", {"app_session_token": session_token}
    )
    _assert_feat011_envelope(dashboard)
    assert dashboard["ok"] is True

    # Every surface above was reached purely as JSON over the socket;
    # no CLI subprocess, no text parsing. SC-007 holds.


def test_sc007_session_gate_failure_is_structured_over_socket(
    socket_path: Path,
) -> None:
    """A degraded-path error (missing session token) is *also* a
    structured FEAT-011 envelope — the client never has to parse a
    free-text error string to detect it."""
    envelope = _one_shot_call(socket_path, "app.readiness")  # no token
    _assert_feat011_envelope(envelope)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "app_session_required"
    assert envelope["error"]["details"] == {}
