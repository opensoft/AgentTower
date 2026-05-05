"""Raw-socket protocol integration tests (T023 / FR-021 / SC-005).

For each error code in the closed FEAT-002 set we send a malformed
request, verify the structured error response, and immediately follow
up with a valid ``ping`` on a new connection to assert the daemon is
still alive.
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


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _send_raw(socket_path: Path, payload: bytes) -> bytes:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    saved_cwd = os.getcwd()
    try:
        os.chdir(socket_path.parent)
        sock.connect(socket_path.name)
    finally:
        os.chdir(saved_cwd)
    try:
        sock.sendall(payload)
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf
    finally:
        sock.close()


def _ping_alive(socket_path: Path) -> None:
    response = _send_raw(socket_path, b'{"method": "ping"}\n')
    envelope = json.loads(response.decode("utf-8"))
    assert envelope == {"ok": True, "result": {}}


@pytest.fixture
def socket_path(env: dict[str, str]) -> Path:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    return resolved_paths(Path(env["HOME"]))["socket"]


def test_bad_json_invalid_utf8(socket_path: Path) -> None:
    response = _send_raw(socket_path, b"\xff\xfeoops\n")
    envelope = json.loads(response.decode("utf-8"))
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "bad_json"
    _ping_alive(socket_path)


def test_bad_request_top_level_array(socket_path: Path) -> None:
    response = _send_raw(socket_path, b"[1,2,3]\n")
    envelope = json.loads(response.decode("utf-8"))
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "bad_request"
    _ping_alive(socket_path)


def test_unknown_method(socket_path: Path) -> None:
    response = _send_raw(socket_path, b'{"method": "frobnicate"}\n')
    envelope = json.loads(response.decode("utf-8"))
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "unknown_method"
    _ping_alive(socket_path)


def test_request_too_large(socket_path: Path) -> None:
    payload = b'{"method":"ping","x":"' + (b"a" * (66 * 1024)) + b'"}\n'
    response = _send_raw(socket_path, payload)
    envelope = json.loads(response.decode("utf-8"))
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "request_too_large"
    _ping_alive(socket_path)


def test_status_method_round_trip(socket_path: Path) -> None:
    response = _send_raw(socket_path, b'{"method": "status"}\n')
    envelope = json.loads(response.decode("utf-8"))
    assert envelope["ok"] is True
    assert envelope["result"]["alive"] is True


def test_extra_bytes_after_first_newline_ignored(socket_path: Path) -> None:
    # The first request gets answered; extra bytes don't crash the daemon.
    response = _send_raw(
        socket_path,
        b'{"method": "ping"}\n{"method": "ping"}\n',
    )
    # Server replies to the first request and closes; verify ok envelope.
    envelope = json.loads(response.decode("utf-8"))
    assert envelope == {"ok": True, "result": {}}
    _ping_alive(socket_path)
