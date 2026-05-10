"""Unit tests for socket_api error helpers and JSON envelope shapes (FEAT-002 T005)."""

from __future__ import annotations

import json

import pytest

from agenttower.socket_api import errors


def test_closed_code_set_contains_feat002_through_feat007_codes() -> None:
    # FEAT-002 codes (FR-022 backward-compat).
    feat002 = {
        errors.BAD_JSON,
        errors.BAD_REQUEST,
        errors.UNKNOWN_METHOD,
        errors.REQUEST_TOO_LARGE,
        errors.INTERNAL_ERROR,
    }
    assert feat002 <= errors.CLOSED_CODE_SET
    # FEAT-003 additions (research R-014).
    feat003 = {
        errors.CONFIG_INVALID,
        errors.DOCKER_UNAVAILABLE,
        errors.DOCKER_PERMISSION_DENIED,
        errors.DOCKER_TIMEOUT,
        errors.DOCKER_FAILED,
        errors.DOCKER_MALFORMED,
    }
    assert feat003 <= errors.CLOSED_CODE_SET
    # FEAT-004 additions (research R-011 / FR-019).
    feat004 = {
        errors.TMUX_UNAVAILABLE,
        errors.TMUX_NO_SERVER,
        errors.SOCKET_DIR_MISSING,
        errors.SOCKET_UNREADABLE,
        errors.DOCKER_EXEC_FAILED,
        errors.DOCKER_EXEC_TIMEOUT,
        errors.OUTPUT_MALFORMED,
        errors.BENCH_USER_UNRESOLVED,
    }
    assert feat004 <= errors.CLOSED_CODE_SET
    # FEAT-006 additions (research R-010 / FR-040).
    feat006 = {
        errors.HOST_CONTEXT_UNSUPPORTED,
        errors.CONTAINER_UNRESOLVED,
        errors.NOT_IN_TMUX,
        errors.TMUX_PANE_MALFORMED,
        errors.PANE_UNKNOWN_TO_DAEMON,
        errors.AGENT_NOT_FOUND,
        errors.AGENT_INACTIVE,
        errors.PARENT_NOT_FOUND,
        errors.PARENT_INACTIVE,
        errors.PARENT_ROLE_INVALID,
        errors.PARENT_ROLE_MISMATCH,
        errors.PARENT_IMMUTABLE,
        errors.SWARM_PARENT_REQUIRED,
        errors.SWARM_ROLE_VIA_SET_ROLE_REJECTED,
        errors.MASTER_VIA_REGISTER_SELF_REJECTED,
        errors.MASTER_CONFIRM_REQUIRED,
        errors.VALUE_OUT_OF_SET,
        errors.FIELD_TOO_LONG,
        errors.PROJECT_PATH_INVALID,
        errors.UNKNOWN_FILTER,
        errors.SCHEMA_VERSION_NEWER,
    }
    assert feat006 <= errors.CLOSED_CODE_SET
    # FEAT-007 additions (FR-038).
    feat007 = {
        errors.LOG_PATH_INVALID,
        errors.LOG_PATH_NOT_HOST_VISIBLE,
        errors.LOG_PATH_IN_USE,
        errors.PIPE_PANE_FAILED,
        errors.ATTACHMENT_NOT_FOUND,
        errors.LOG_FILE_MISSING,
    }
    assert feat007 <= errors.CLOSED_CODE_SET
    # FEAT-008 additions (data-model.md §8).
    feat008 = {
        errors.EVENTS_SESSION_UNKNOWN,
        errors.EVENTS_SESSION_EXPIRED,
        errors.EVENTS_INVALID_CURSOR,
        errors.EVENTS_FILTER_INVALID,
    }
    assert feat008 <= errors.CLOSED_CODE_SET
    # No surprise codes beyond the documented sets.
    assert errors.CLOSED_CODE_SET == (
        feat002 | feat003 | feat004 | feat006 | feat007 | feat008
    )


@pytest.mark.parametrize(
    "code",
    [
        errors.BAD_JSON,
        errors.BAD_REQUEST,
        errors.UNKNOWN_METHOD,
        errors.REQUEST_TOO_LARGE,
        errors.INTERNAL_ERROR,
    ],
)
def test_make_error_shape_for_each_code(code: str) -> None:
    envelope = errors.make_error(code, "demo")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == code
    assert envelope["error"]["message"] == "demo"
    # Round-trip through JSON.
    serialized = json.dumps(envelope)
    assert json.loads(serialized) == envelope


def test_make_error_rejects_unknown_code() -> None:
    with pytest.raises(ValueError):
        errors.make_error("frobnicate", "nope")


def test_make_ok_default_empty_result() -> None:
    envelope = errors.make_ok()
    assert envelope == {"ok": True, "result": {}}


def test_make_ok_with_result_round_trip() -> None:
    envelope = errors.make_ok({"alive": True, "pid": 12345})
    assert envelope["ok"] is True
    assert envelope["result"] == {"alive": True, "pid": 12345}
    assert json.loads(json.dumps(envelope)) == envelope


# ---------------------------------------------------------------------------
# T012: full request-envelope validation cases against the server handler.
# ---------------------------------------------------------------------------


from datetime import datetime, timezone
from pathlib import Path

from agenttower.socket_api import server as server_module
from agenttower.socket_api.methods import DaemonContext


class _FakeRFile:
    def __init__(self, line: bytes) -> None:
        self._line = line

    def readline(self, limit: int) -> bytes:
        # Mimic socketserver's readline contract: stop at '\n' or after `limit`.
        if len(self._line) > limit:
            return self._line[:limit]
        return self._line


class _FakeWFile:
    def __init__(self) -> None:
        self.buffer = b""

    def write(self, data: bytes) -> None:
        self.buffer += data

    def flush(self) -> None:
        # The fake stores writes immediately, so there is no buffered state to flush.
        return None


class _FakeServer:
    def __init__(self, ctx: DaemonContext) -> None:
        self.context = ctx


def _make_handler(line: bytes) -> tuple[server_module._RequestHandler, _FakeWFile]:
    handler = server_module._RequestHandler.__new__(server_module._RequestHandler)
    handler.rfile = _FakeRFile(line)
    handler.wfile = _FakeWFile()
    handler.server = _FakeServer(  # type: ignore[assignment]
        DaemonContext(
            pid=4242,
            start_time_utc=datetime.now(timezone.utc),
            socket_path=Path("agenttowerd.sock"),
            state_path=Path("."),
            daemon_version="0.0.0+test",
            schema_version=1,
        )
    )
    return handler, handler.wfile  # type: ignore[return-value]


def _dispatch_line(line: bytes) -> dict[str, Any]:
    handler, _ = _make_handler(line)
    return handler._read_and_dispatch()


@pytest.mark.parametrize(
    "line, expected_code",
    [
        (b"\xff\xfe not utf-8\n", errors.BAD_JSON),
        (b"this is not json\n", errors.BAD_JSON),
        (b"[1,2,3]\n", errors.BAD_REQUEST),
        (b"42\n", errors.BAD_REQUEST),
        (b'{"params": {}}\n', errors.BAD_REQUEST),
        (b'{"method": 7}\n', errors.BAD_REQUEST),
        (b'{"method": ""}\n', errors.BAD_REQUEST),
        (b'{"method": "ping", "params": "no"}\n', errors.BAD_REQUEST),
        (b'{"method": "frobnicate"}\n', errors.UNKNOWN_METHOD),
    ],
)
def test_dispatch_rejects_malformed_request(line: bytes, expected_code: str) -> None:
    envelope = _dispatch_line(line)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == expected_code


def test_dispatch_rejects_oversized_request() -> None:
    big_line = (b"{" + b" " * (server_module.MAX_REQUEST_BYTES + 4096)) + b"\n"
    envelope = _dispatch_line(big_line)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == errors.REQUEST_TOO_LARGE


def test_dispatch_accepts_valid_ping() -> None:
    envelope = _dispatch_line(b'{"method": "ping"}\n')
    assert envelope == {"ok": True, "result": {}}


def test_dispatch_handles_internal_exception_gracefully() -> None:
    handler, _ = _make_handler(b'{"method": "ping"}\n')

    def boom(ctx, params, peer_uid=-1):  # noqa: ANN001
        raise RuntimeError("kaboom")

    from agenttower.socket_api.methods import DISPATCH

    saved = DISPATCH["ping"]
    DISPATCH["ping"] = boom
    try:
        envelope = handler._read_and_dispatch()
    finally:
        DISPATCH["ping"] = saved

    assert envelope["ok"] is False
    assert envelope["error"]["code"] == errors.INTERNAL_ERROR
    assert "RuntimeError" in envelope["error"]["message"]


def test_handle_writes_envelope_on_uid_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-058 / Copilot review: a peer with mismatched SO_PEERCRED uid MUST get
    a closed-set ``internal_error`` envelope, not an empty close.

    Pre-fix the handler returned silently on mismatch; the client then saw
    an empty read and surfaced ``DaemonUnavailable(kind="protocol_error")``,
    which is misleading for what is in fact an authorization refusal.
    """
    handler, wfile = _make_handler(b'{"method": "ping"}\n')

    # Synthesize a non-None ``connection`` attribute so the uid check
    # branch fires; the value is never inspected because we monkeypatch
    # the helper that reads from it.
    handler.connection = object()  # type: ignore[assignment]

    monkeypatch.setattr(server_module, "_peer_uid_from_socket", lambda _conn: 9999)
    monkeypatch.setattr(server_module.os, "geteuid", lambda: 1000)

    handler.handle()

    payload = wfile.buffer.rstrip(b"\n")
    envelope = json.loads(payload.decode("utf-8"))
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == errors.INTERNAL_ERROR
    # Generic message; lifecycle log carries the observed/expected uids.
    assert "peer credential" in envelope["error"]["message"].lower()


def test_handle_dispatches_normally_when_peer_uid_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity counter-test: a matching peer uid must NOT short-circuit dispatch."""
    handler, wfile = _make_handler(b'{"method": "ping"}\n')
    handler.connection = object()  # type: ignore[assignment]

    monkeypatch.setattr(server_module, "_peer_uid_from_socket", lambda _conn: 1000)
    monkeypatch.setattr(server_module.os, "geteuid", lambda: 1000)

    handler.handle()

    envelope = json.loads(wfile.buffer.rstrip(b"\n").decode("utf-8"))
    assert envelope == {"ok": True, "result": {}}
