"""Threaded ``AF_UNIX`` control server for the FEAT-002 daemon (T007).

One request per connection (FR-026): read one newline-delimited JSON line
≤ 64 KiB, dispatch via :data:`methods.DISPATCH`, write one response line,
close the connection.

US4 (T029) extends this module with shutdown sequencing.
"""

from __future__ import annotations

import json
import os
import socket as _socket
import socketserver
import stat
import struct
import threading
from pathlib import Path
from typing import Any

from . import errors
from .methods import DISPATCH, DaemonContext

MAX_REQUEST_BYTES = 65536  # 64 KiB; FR-029 / R-006.

# Linux ucred is "{ pid_t pid; uid_t uid; gid_t gid; }" — three 32-bit ints.
_UCRED_STRUCT = struct.Struct("iII")
_NO_PEER_UID = -1


def _peer_uid_from_socket(conn: _socket.socket) -> int:
    """Return the peer's uid from ``SO_PEERCRED`` or ``-1`` on failure.

    The uid is injected out-of-band into method dispatch so a request
    body cannot spoof it. Failures (non-Linux kernel, connection torn
    down before getsockopt, etc.) degrade to the sentinel ``-1`` —
    audit rows then record ``-1`` rather than dropping the request.
    """
    try:
        raw = conn.getsockopt(
            _socket.SOL_SOCKET, _socket.SO_PEERCRED, _UCRED_STRUCT.size
        )
    except (OSError, AttributeError):
        return _NO_PEER_UID
    if len(raw) < _UCRED_STRUCT.size:
        return _NO_PEER_UID
    _pid, uid, _gid = _UCRED_STRUCT.unpack(raw)
    return int(uid)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


class _RequestHandler(socketserver.StreamRequestHandler):
    """Read one line, dispatch one method, write one line, close."""

    server: "ControlServer"  # type: ignore[assignment]

    def handle(self) -> None:  # noqa: D401 — name mandated by socketserver
        # FR-058 (FEAT-007): defense-in-depth peer-uid match. The 0600 socket
        # inode mode (FEAT-002) is the primary control; this check refuses
        # any connection whose SO_PEERCRED uid disagrees with the daemon's
        # effective uid. ``-1`` means SO_PEERCRED was unavailable (e.g. unit
        # tests) — we tolerate the sentinel and rely on the inode mode
        # boundary in that case.
        connection = getattr(self, "connection", None)
        observed_uid = (
            _peer_uid_from_socket(connection) if connection is not None else _NO_PEER_UID
        )
        if observed_uid != _NO_PEER_UID:
            try:
                expected_uid = os.geteuid()
            except OSError:
                expected_uid = -1
            if expected_uid >= 0 and observed_uid != expected_uid:
                # Emit lifecycle event and refuse without dispatching.
                self._emit_uid_mismatch(observed_uid=observed_uid, expected_uid=expected_uid)
                envelope = errors.make_error(
                    errors.INTERNAL_ERROR,
                    "socket peer uid mismatch; connection refused",
                )
                self._write_response(envelope)
                return

        envelope = self._read_and_dispatch()
        self._write_response(envelope)

    def _emit_uid_mismatch(self, *, observed_uid: int, expected_uid: int) -> None:
        """Best-effort emit of ``socket_peer_uid_mismatch``; never crashes dispatch."""
        ctx = getattr(self.server, "context", None)
        logger = getattr(ctx, "lifecycle_logger", None) if ctx is not None else None
        if logger is None:
            return
        try:
            from ..logs import lifecycle as logs_lifecycle

            logs_lifecycle.emit_socket_peer_uid_mismatch(
                logger,
                observed_uid=int(observed_uid),
                expected_uid=int(expected_uid),
            )
        except Exception:  # pragma: no cover — defensive
            pass

    def _read_and_dispatch(self) -> dict[str, Any]:
        try:
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        except OSError:
            return errors.make_error(errors.INTERNAL_ERROR, "read failed")

        if not line:
            # Peer closed without writing; we still need to write *something*
            # so the connection has a deterministic close, but a no-data peer
            # is not a protocol violation. Return an internal_error envelope
            # only if the underlying state is broken; otherwise stay silent.
            return errors.make_error(errors.BAD_JSON, "empty request")

        if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
            return errors.make_error(
                errors.REQUEST_TOO_LARGE,
                f"request line exceeds {MAX_REQUEST_BYTES} bytes",
            )

        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            return errors.make_error(errors.BAD_JSON, "request is not UTF-8")

        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            return errors.make_error(errors.BAD_JSON, f"json decode failed: {exc.msg}")

        if not isinstance(request, dict):
            return errors.make_error(errors.BAD_REQUEST, "request must be a JSON object")

        method = request.get("method")
        if not isinstance(method, str) or not method:
            return errors.make_error(
                errors.BAD_REQUEST, "missing or invalid 'method' field"
            )

        params = request.get("params", {})
        if not isinstance(params, dict):
            return errors.make_error(errors.BAD_REQUEST, "'params' must be an object")

        handler = DISPATCH.get(method)
        if handler is None:
            return errors.make_error(errors.UNKNOWN_METHOD, f"unknown method: {method}")

        # ``self.connection`` is set by ``StreamRequestHandler.setup``; tests
        # that synthesize a handler via ``__new__`` skip setup, so fall back
        # to the sentinel rather than crashing dispatch on a missing attr.
        connection = getattr(self, "connection", None)
        peer_uid = (
            _peer_uid_from_socket(connection) if connection is not None else _NO_PEER_UID
        )
        try:
            return handler(self.server.context, params, peer_uid)
        except Exception as exc:  # noqa: BLE001 — never crash the daemon (FR-021).
            return errors.make_error(errors.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

    def _write_response(self, envelope: dict[str, Any]) -> None:
        try:
            self.wfile.write((json.dumps(envelope) + "\n").encode("utf-8"))
            self.wfile.flush()
        except OSError:
            # SIGPIPE is ignored daemon-wide; client closed early.
            return


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class ControlServer(socketserver.ThreadingUnixStreamServer):
    """Threaded ``AF_UNIX`` server bound at the FEAT-002 socket path."""

    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 16

    def __init__(self, socket_path: Path, context: DaemonContext) -> None:
        socket_path = Path(socket_path)
        self._socket_path = socket_path
        self.context = context
        # ``umask`` trick → bind creates the socket inode at mode 0600.
        # Bind via chdir + basename so the kernel's 108-byte AF_UNIX limit
        # never trips on long state-dir paths (a real concern in
        # ``$TMPDIR`` test layouts and deeply-nested home directories).
        saved_cwd = os.getcwd()
        # umask 0o177 strips the owner-execute bit too so the socket inode
        # ends up at exact 0o600 instead of 0o700.
        previous_umask = os.umask(0o177)
        try:
            os.chdir(socket_path.parent)
            super().__init__(
                socket_path.name, _RequestHandler, bind_and_activate=True
            )
        finally:
            try:
                os.chdir(saved_cwd)
            except OSError:
                pass
            os.umask(previous_umask)
        # Override the server_address with the absolute path so callers
        # (and ``socket_path`` introspection) see the canonical location.
        self.server_address = str(socket_path)
        self._verify_socket_safe()

    def _verify_socket_safe(self) -> None:
        st = self._socket_path.lstat()
        mode = stat.S_IMODE(st.st_mode)
        if not stat.S_ISSOCK(st.st_mode):
            raise PermissionError(f"bound path is not a socket: {self._socket_path}")
        if mode != 0o600:
            self._unbind_and_raise(
                f"socket mode is {oct(mode)}, expected 0o600 (path={self._socket_path})"
            )
        if st.st_uid != os.geteuid():
            self._unbind_and_raise(
                f"socket owned by uid {st.st_uid}, expected {os.geteuid()}"
            )

    def _unbind_and_raise(self, reason: str) -> None:
        try:
            self.server_close()
            self._socket_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise PermissionError(reason)

    @property
    def socket_path(self) -> Path:
        return self._socket_path


def serve_forever_in_thread(server: ControlServer) -> threading.Thread:
    """Start ``server.serve_forever`` on a background thread and return it."""
    thread = threading.Thread(
        target=server.serve_forever, name="agenttowerd-accept", daemon=True
    )
    thread.start()
    return thread
