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
from .methods import (
    DISPATCH,
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)

MAX_REQUEST_BYTES = 65536  # 64 KiB; FR-029 / R-006.

# Linux ucred is "{ pid_t pid; uid_t uid; gid_t gid; }" — three 32-bit ints.
_UCRED_STRUCT = struct.Struct("iII")
_NO_PEER_UID = -1
_NO_PEER_PID = -1


def _peer_cred_from_socket(conn: _socket.socket) -> tuple[int, int]:
    """Return ``(peer_pid, peer_uid)`` from ``SO_PEERCRED`` or sentinels.

    The uid is injected out-of-band into method dispatch so a request
    body cannot spoof it. Failures (non-Linux kernel, connection torn
    down before getsockopt, etc.) degrade to the sentinel ``-1`` pair.
    """
    try:
        raw = conn.getsockopt(
            _socket.SOL_SOCKET, _socket.SO_PEERCRED, _UCRED_STRUCT.size
        )
    except (OSError, AttributeError):
        return _NO_PEER_PID, _NO_PEER_UID
    if len(raw) < _UCRED_STRUCT.size:
        return _NO_PEER_PID, _NO_PEER_UID
    pid, uid, _gid = _UCRED_STRUCT.unpack(raw)
    return int(pid), int(uid)


def _peer_uid_from_socket(conn: _socket.socket) -> int:
    """Back-compat shim for tests and older call sites that only need uid."""
    _pid, uid = _peer_cred_from_socket(conn)
    return uid


def _peer_pid_from_socket(conn: _socket.socket) -> int:
    """Internal helper for methods that need the peer pid."""
    pid, _uid = _peer_cred_from_socket(conn)
    return pid


# ---------------------------------------------------------------------------
# FEAT-011 envelope helpers (FR-003b, T098)
# ---------------------------------------------------------------------------


def _make_malformed_request_envelope(reason: str) -> dict[str, Any]:
    """Build the FEAT-011 ``malformed_request`` envelope (FR-003b).

    Lazy-imports ``app_contract.envelope`` to keep the module-load free
    of a cycle (``socket_api/server.py`` imports ``methods.py``, which
    imports ``app_contract/dispatcher.py``, which imports
    ``app_contract/envelope.py``).
    """
    from ..app_contract import envelope as _app_envelope
    from ..app_contract.errors import MALFORMED_REQUEST

    return _app_envelope.failure(
        MALFORMED_REQUEST,
        f"malformed request line ({reason})",
        details={"reason": reason},
    )


def _make_unknown_app_method_envelope(method: str) -> dict[str, Any]:
    """Build the FR-033-compliant ``unknown_method`` envelope for ``app.*``
    methods not present in DISPATCH (T098).
    """
    from ..app_contract import dispatcher as _app_dispatcher

    return _app_dispatcher.make_unknown_method_envelope(method)


def _make_payload_too_large_envelope(actual_size_bytes: int) -> dict[str, Any]:
    """Build the FR-003a / FR-034a ``payload_too_large`` envelope for an
    oversized ``app.*`` request line. Carries the FEAT-011 required
    keys ``size_limit_bytes`` and ``actual_size_bytes`` so clients can
    surface the limit precisely.
    """
    from ..app_contract import envelope as _app_envelope
    from ..app_contract.errors import PAYLOAD_TOO_LARGE

    return _app_envelope.failure(
        PAYLOAD_TOO_LARGE,
        f"request line exceeds {MAX_REQUEST_BYTES} bytes",
        details={
            "size_limit_bytes": MAX_REQUEST_BYTES,
            "actual_size_bytes": actual_size_bytes,
        },
    )


def _line_looks_like_app_method(line_bytes: bytes) -> bool:
    """Peek-detect whether an unparseable / oversized request line names
    an ``app.*`` method. Heuristic — we can't json.loads the line (it's
    either too big or malformed), so we substring-scan the first ~1 KB
    for ``"method":"app.``.

    False positives are bounded to lines that genuinely contain that
    literal string in a non-method field (e.g., a payload value), which
    is acceptable: surfacing a FEAT-011 envelope to such a peer is a
    strict superset of the legacy envelope (adds version + details),
    and legacy clients can still parse ``ok: false`` + ``error.code``.
    """
    # Bound the scan to keep this cheap even on a 1 MiB line.
    head = line_bytes[:2048]
    # Strip whitespace tolerant matches: ``"method":"app.`` and
    # ``"method": "app.`` (with optional space).
    return b'"method":"app.' in head or b'"method": "app.' in head


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
            _peer_uid_from_socket(connection)
            if connection is not None
            else _NO_PEER_UID
        )
        if observed_uid != _NO_PEER_UID:
            try:
                expected_uid = os.geteuid()
            except OSError:
                expected_uid = -1
            if expected_uid >= 0 and observed_uid != expected_uid:
                # Emit lifecycle event and refuse without dispatching. Write
                # a closed-set error envelope so the client sees a normal
                # protocol response instead of an empty read (which would
                # surface as ``DaemonUnavailable(kind="protocol_error")``).
                # The message is intentionally generic — the lifecycle log
                # carries the observed/expected uids for forensics.
                self._emit_uid_mismatch(observed_uid=observed_uid, expected_uid=expected_uid)
                self._write_response(
                    errors.make_error(
                        errors.INTERNAL_ERROR,
                        "request refused: peer credential check failed",
                    )
                )
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

        # Peer closed without writing.
        if not line:
            return errors.make_error(errors.BAD_JSON, "empty request")

        if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
            # FR-003a / FR-034a: ``app.*`` oversized lines emit the
            # FEAT-011 ``payload_too_large`` envelope (carries
            # ``size_limit_bytes`` + ``actual_size_bytes``). Legacy
            # methods keep the FEAT-002 ``request_too_large`` shape per
            # FR-002. Detection is best-effort substring peek since the
            # line is too big to JSON-decode reliably.
            if _line_looks_like_app_method(line):
                return _make_payload_too_large_envelope(len(line))
            return errors.make_error(
                errors.REQUEST_TOO_LARGE,
                f"request line exceeds {MAX_REQUEST_BYTES} bytes",
            )

        # FR-003b wire-framing gate. Five cases are caught BEFORE handler
        # dispatch and emitted in the FEAT-011 envelope with the
        # ``malformed_request`` closed-set code and a short ``details.reason``:
        # (a) stray ``\r`` byte, (b) embedded ``\x00`` byte, (e) empty line.
        # Cases (c) trailing content + (d) JSON decode error are caught
        # below post-decode. The FEAT-011 envelope is a strict superset of
        # the legacy FEAT-002 shape (it adds ``app_contract_version`` and
        # ``error.details``), so legacy clients still see ``ok: false`` +
        # ``error.code/message`` they can parse; they just see an
        # unfamiliar closed-set code, which is acceptable for inputs that
        # were always malformed.
        body = line[:-1]  # strip trailing \n for the byte checks below
        if body == b"":
            return _make_malformed_request_envelope("empty line")
        if b"\r" in body:
            return _make_malformed_request_envelope("stray CR")
        if b"\x00" in body:
            return _make_malformed_request_envelope("embedded NUL")

        # Invalid UTF-8 and JSON decode errors:
        # - ``app.*`` requests (detected via substring peek per
        #   ``_line_looks_like_app_method``) get the FR-003b
        #   ``malformed_request`` envelope so SC-028 is fully satisfied.
        # - Legacy requests stay on the FEAT-002 ``bad_json`` envelope
        #   to preserve the lock-in in ``test_socket_api_framing.py``
        #   (FR-002: legacy CLI surface unchanged).
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            if _line_looks_like_app_method(line):
                return _make_malformed_request_envelope("invalid utf-8")
            return errors.make_error(errors.BAD_JSON, "request is not UTF-8")

        # FR-003b case (c)/(d): use raw_decode so we can distinguish
        # "extra content after the first JSON object" from a clean
        # parse failure.
        text_stripped = text.lstrip()
        decoder = json.JSONDecoder()
        try:
            request, idx = decoder.raw_decode(text_stripped)
        except json.JSONDecodeError as exc:
            if _line_looks_like_app_method(line):
                return _make_malformed_request_envelope(
                    f"json decode error: {exc.msg}"
                )
            return errors.make_error(errors.BAD_JSON, f"json decode failed: {exc.msg}")
        # Anything non-whitespace remaining is trailing content.
        if text_stripped[idx:].strip():
            return _make_malformed_request_envelope("trailing content")

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
            # T098: ``app.*`` methods get the FR-033-compliant FEAT-011
            # envelope (with ``app_contract_version`` + ``details: {}``);
            # legacy methods stay on the FEAT-002 envelope.
            from ..app_contract.dispatcher import is_app_method
            if is_app_method(method):
                return _make_unknown_app_method_envelope(method)
            return errors.make_error(errors.UNKNOWN_METHOD, f"unknown method: {method}")

        # ``self.connection`` is set by ``StreamRequestHandler.setup``; tests
        # that synthesize a handler via ``__new__`` skip setup, so fall back
        # to the sentinel rather than crashing dispatch on a missing attr.
        connection = getattr(self, "connection", None)
        peer_pid = (
            _peer_pid_from_socket(connection)
            if connection is not None
            else _NO_PEER_PID
        )
        peer_uid = (
            _peer_uid_from_socket(connection)
            if connection is not None
            else _NO_PEER_UID
        )
        try:
            _set_request_peer_context(peer_pid=peer_pid)
            return handler(self.server.context, params, peer_uid)
        except Exception as exc:  # noqa: BLE001 — never crash the daemon (FR-021).
            return errors.make_error(errors.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        finally:
            _clear_request_peer_context()

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
