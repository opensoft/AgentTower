"""Unit tests for the FEAT-002 AF_UNIX client (T014).

Spins up a tiny throw-away ``AF_UNIX`` server in a thread to exercise the
``DaemonUnavailable`` and ``DaemonError`` surfaces.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from agenttower.socket_api.client import DaemonError, DaemonUnavailable, send_request


def test_missing_socket_raises_daemon_unavailable(tmp_path: Path) -> None:
    with pytest.raises(DaemonUnavailable):
        send_request(tmp_path / "absent.sock", "ping", connect_timeout=0.5)


def test_refused_socket_raises_daemon_unavailable(tmp_path: Path) -> None:
    # Create a regular file at the path so connect() yields ENOTSOCK / refused.
    bad = tmp_path / "not-a-socket"
    bad.write_text("hi")
    with pytest.raises(DaemonUnavailable):
        send_request(bad, "ping", connect_timeout=0.5)


def _serve_one(socket_path: Path, response: bytes) -> threading.Thread:
    """Tiny synchronous AF_UNIX server: accept once, send response, close."""
    server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server_sock.bind(str(socket_path))
    server_sock.listen(1)

    def run() -> None:
        conn, _ = server_sock.accept()
        try:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            conn.sendall(response)
        finally:
            conn.close()
            server_sock.close()
            try:
                socket_path.unlink()
            except FileNotFoundError:
                pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    # Brief settle for bind/listen to be visible to subsequent connect().
    for _ in range(20):
        if socket_path.exists():
            break
        time.sleep(0.005)
    return thread


def test_client_returns_result_on_ok(tmp_path: Path) -> None:
    sock_path = tmp_path / "ok.sock"
    body = (json.dumps({"ok": True, "result": {"alive": True}}) + "\n").encode("utf-8")
    thread = _serve_one(sock_path, body)
    try:
        result = send_request(sock_path, "ping")
    finally:
        thread.join(timeout=2.0)
    assert result == {"alive": True}


def test_client_raises_daemon_error_on_failure_envelope(tmp_path: Path) -> None:
    sock_path = tmp_path / "err.sock"
    body = (
        json.dumps({"ok": False, "error": {"code": "bad_request", "message": "nope"}})
        + "\n"
    ).encode("utf-8")
    thread = _serve_one(sock_path, body)
    try:
        with pytest.raises(DaemonError) as info:
            send_request(sock_path, "ping")
    finally:
        thread.join(timeout=2.0)
    assert info.value.code == "bad_request"
    assert info.value.message == "nope"


def test_client_raises_daemon_unavailable_on_invalid_json(tmp_path: Path) -> None:
    sock_path = tmp_path / "garbage.sock"
    thread = _serve_one(sock_path, b"not-json\n")
    try:
        with pytest.raises(DaemonUnavailable):
            send_request(sock_path, "ping")
    finally:
        thread.join(timeout=2.0)
