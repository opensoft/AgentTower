"""Minimal AF_UNIX client for the local control API (T008).

FEAT-005 R-009 / contracts/socket-api.md §C-API-502 add an additive
``kind`` attribute on :class:`DaemonUnavailable` so the doctor's
``socket_reachable`` check can dispatch on a closed-set sub-code without
parsing the exception's message string. ``str(exc)`` and ``repr(exc)``
remain byte-for-byte unchanged from the FEAT-002 build (FR-026).
"""

from __future__ import annotations

import errno
import json
import os
import socket
from pathlib import Path
from typing import Any, Literal


# Closed-set FR-016 transport sub-codes for ``DaemonUnavailable.kind``.
DaemonUnavailableKind = Literal[
    "socket_missing",
    "socket_not_unix",
    "connection_refused",
    "permission_denied",
    "connect_timeout",
    "protocol_error",
]


class DaemonUnavailable(RuntimeError):
    """Raised when the daemon socket is missing, refused, or unresponsive.

    Carries an additive ``kind`` attribute (R-009, FR-016) that is one of
    the closed-set transport sub-codes. ``kind`` defaults to
    ``"connect_timeout"`` only on the generic ``OSError`` fallback path.
    Existing callers that pass a single positional message argument continue
    to work unmodified — ``kind`` is keyword-only.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: DaemonUnavailableKind = "connect_timeout",
    ) -> None:
        super().__init__(message)
        self.kind: DaemonUnavailableKind = kind


class DaemonError(RuntimeError):
    """Raised when the daemon returned a structured error envelope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _do_connect(sock: socket.socket, socket_path: Path) -> None:
    """Connect ``sock`` to ``socket_path`` and translate transport errors
    into :class:`DaemonUnavailable` with the FR-016 closed-set ``kind``.

    Existing exception messages are preserved byte-for-byte (locked by
    ``test_socket_client_back_compat.py``).
    """
    try:
        _connect_via_chdir(sock, socket_path)
    except FileNotFoundError as exc:
        raise DaemonUnavailable(
            f"socket missing: {socket_path}", kind="socket_missing"
        ) from exc
    except ConnectionRefusedError as exc:
        raise DaemonUnavailable(
            f"socket refused: {socket_path}", kind="connection_refused"
        ) from exc
    except OSError as exc:
        kind = "permission_denied" if exc.errno == errno.EACCES else "connect_timeout"
        raise DaemonUnavailable(f"connect failed: {exc}", kind=kind) from exc


def _do_send_and_recv(sock: socket.socket, payload: bytes) -> bytes:
    """Send ``payload`` and read one newline-delimited response, mapping
    I/O errors into :class:`DaemonUnavailable` with the FR-016 closed-set
    ``kind``. Existing exception messages are preserved byte-for-byte.
    """
    try:
        sock.sendall(payload)
        return _recv_line(sock)
    except (TimeoutError, socket.timeout) as exc:  # noqa: UP041
        raise DaemonUnavailable(
            "daemon read timeout", kind="connect_timeout"
        ) from exc
    except OSError as exc:
        raise DaemonUnavailable(
            f"socket I/O failed: {exc}", kind="connect_timeout"
        ) from exc


def _parse_envelope(data: bytes) -> dict[str, Any]:
    """Decode the daemon's JSON envelope or raise
    :class:`DaemonUnavailable` with ``kind="protocol_error"``."""
    if not data:
        raise DaemonUnavailable("daemon returned no data", kind="protocol_error")
    try:
        envelope = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DaemonUnavailable(
            f"daemon returned invalid JSON: {exc}", kind="protocol_error"
        ) from exc
    if not isinstance(envelope, dict) or "ok" not in envelope:
        raise DaemonUnavailable(
            "daemon returned malformed envelope", kind="protocol_error"
        )
    return envelope


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
        _do_connect(sock, socket_path)
        sock.settimeout(read_timeout)
        data = _do_send_and_recv(sock, payload)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    envelope = _parse_envelope(data)

    if envelope["ok"] is True:
        result = envelope.get("result", {})
        if not isinstance(result, dict):
            raise DaemonUnavailable(
                "daemon result is not an object", kind="protocol_error"
            )
        return result

    err = envelope.get("error", {})
    raise DaemonError(
        code=str(err.get("code", "")),
        message=str(err.get("message", "")),
    )


def register_agent(
    socket_path: Path, params: dict[str, Any]
) -> dict[str, Any]:
    """Typed wrapper for FEAT-006 ``register_agent`` (FR-023).

    Reuses the same connect / framing path as :func:`send_request`. Raises
    :class:`DaemonUnavailable` on socket-level failure and
    :class:`DaemonError` carrying the closed-set ``code`` on a daemon
    error envelope.
    """
    return send_request(socket_path, "register_agent", params)


def list_agents(
    socket_path: Path, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    return send_request(socket_path, "list_agents", params)


def set_role(socket_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    return send_request(socket_path, "set_role", params)


def set_label(socket_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    return send_request(socket_path, "set_label", params)


def set_capability(socket_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    return send_request(socket_path, "set_capability", params)


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
