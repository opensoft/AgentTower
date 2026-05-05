"""Minimal AF_UNIX client for the local control API (T008)."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any


class DaemonUnavailable(RuntimeError):
    """Raised when the daemon socket is missing, refused, or unresponsive."""


class DaemonError(RuntimeError):
    """Raised when the daemon returned a structured error envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def send_request(
    socket_path: Path,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    connect_timeout: float = 1.0,
    read_timeout: float = 1.0,
) -> dict[str, Any]:
    """Send one newline-delimited JSON request and return the parsed result.

    Returns the ``result`` object on success. Raises
    :class:`DaemonUnavailable` if the socket cannot be reached and
    :class:`DaemonError` if the daemon returned ``{"ok": false}``.
    """
    request = {"method": method}
    if params is not None:
        request["params"] = params
    payload = (json.dumps(request) + "\n").encode("utf-8")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(connect_timeout)
    socket_path = Path(socket_path)
    try:
        try:
            _connect_via_chdir(sock, socket_path)
        except FileNotFoundError as exc:
            raise DaemonUnavailable(f"socket missing: {socket_path}") from exc
        except ConnectionRefusedError as exc:
            raise DaemonUnavailable(f"socket refused: {socket_path}") from exc
        except OSError as exc:
            raise DaemonUnavailable(f"connect failed: {exc}") from exc

        sock.settimeout(read_timeout)
        try:
            sock.sendall(payload)
            data = _recv_line(sock)
        except (TimeoutError, socket.timeout) as exc:  # noqa: UP041
            raise DaemonUnavailable("daemon read timeout") from exc
        except OSError as exc:
            raise DaemonUnavailable(f"socket I/O failed: {exc}") from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass

    if not data:
        raise DaemonUnavailable("daemon returned no data")

    try:
        envelope = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DaemonUnavailable(f"daemon returned invalid JSON: {exc}") from exc

    if not isinstance(envelope, dict) or "ok" not in envelope:
        raise DaemonUnavailable("daemon returned malformed envelope")

    if envelope["ok"] is True:
        result = envelope.get("result", {})
        if not isinstance(result, dict):
            raise DaemonUnavailable("daemon result is not an object")
        return result

    err = envelope.get("error", {})
    raise DaemonError(
        code=str(err.get("code", "")),
        message=str(err.get("message", "")),
    )


def _connect_via_chdir(sock: socket.socket, socket_path: Path) -> None:
    """Connect to *socket_path* via ``chdir(parent) + connect(basename)``.

    Sidesteps the kernel's 108-byte ``sun_path`` limit when *socket_path*
    is long (deeply-nested test temp dirs, home directories with long
    paths, etc.).
    """
    if not socket_path.parent.exists():
        raise FileNotFoundError(socket_path)
    saved_cwd = os.getcwd()
    try:
        os.chdir(socket_path.parent)
        sock.connect(socket_path.name)
    finally:
        try:
            os.chdir(saved_cwd)
        except OSError:
            pass


def _recv_line(sock: socket.socket, *, max_bytes: int = 65536) -> bytes:
    """Read up to ``max_bytes`` and return the bytes up to the first newline."""
    buf = bytearray()
    while True:
        chunk = sock.recv(min(4096, max_bytes - len(buf) + 1))
        if not chunk:
            break
        buf.extend(chunk)
        nl = buf.find(b"\n")
        if nl != -1:
            return bytes(buf[: nl + 1])
        if len(buf) > max_bytes:
            break
    return bytes(buf)
