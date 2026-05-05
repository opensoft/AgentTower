"""Unit tests for socket_api error helpers and JSON envelope shapes (FEAT-002 T005)."""

from __future__ import annotations

import json

import pytest

from agenttower.socket_api import errors


def test_closed_code_set_is_exactly_five() -> None:
    assert errors.CLOSED_CODE_SET == frozenset(
        {
            errors.BAD_JSON,
            errors.BAD_REQUEST,
            errors.UNKNOWN_METHOD,
            errors.REQUEST_TOO_LARGE,
            errors.INTERNAL_ERROR,
        }
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
            socket_path=Path("/tmp/agenttowerd.sock"),
            state_path=Path("/tmp"),
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

    def boom(ctx, params):  # noqa: ANN001
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
