"""Production tmux adapter that shells out via ``subprocess.run``.

Argv is constructed as a typed list with ``shell=False``; container ids,
names, the bench user, socket paths, and tmux output never reach a shell
string (FR-021). Each subprocess call has a 5-second timeout (FR-018). When
``subprocess.run`` raises ``TimeoutExpired`` we normalize it to
``docker_exec_timeout`` after stdlib cleanup; deeper kill-escalation behavior
would require a ``Popen``-based implementation and is documented as a known
follow-up in the FEAT-004 artifacts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence

from ..socket_api import errors as _errors
from .adapter import SocketListing, TmuxAdapter, TmuxError
from .parsers import (
    ParsedPane,
    parse_id_u,
    parse_list_panes,
    parse_socket_listing,
    sanitize_text,
)

_TIMEOUT_SECONDS = 5.0
_LIST_PANES_FORMAT = (
    "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t"
    "#{pane_pid}\t#{pane_tty}\t#{pane_current_command}\t#{pane_current_path}\t"
    "#{pane_title}\t#{pane_active}"
)
_MAX_ERROR_MESSAGE = 2048


def _bound(text: str | None) -> str:
    if text is None:
        return ""
    cleaned, _ = sanitize_text(text, _MAX_ERROR_MESSAGE)
    return cleaned


_NO_SERVER_PATTERNS = (
    "no server running",
    "error connecting to",
    "no current server",
)
_TMUX_NOT_FOUND_PATTERNS = (
    "tmux: not found",
    "tmux: command not found",
    "executable file not found",
    'exec: "tmux"',
)
_PERMISSION_DENIED_PATTERNS = (
    "permission denied",
    "operation not permitted",
)
_DIR_MISSING_PATTERNS = (
    "no such file or directory",
    "cannot access",
)


def _classify_tmux_failure(stderr: str) -> str:
    s = (stderr or "").lower()
    for pattern in _TMUX_NOT_FOUND_PATTERNS:
        if pattern in s:
            return _errors.TMUX_UNAVAILABLE
    for pattern in _NO_SERVER_PATTERNS:
        if pattern in s:
            return _errors.TMUX_NO_SERVER
    return _errors.DOCKER_EXEC_FAILED


def _classify_socket_listing_failure(stderr: str, returncode: int) -> str:
    s = (stderr or "").lower()
    for pattern in _PERMISSION_DENIED_PATTERNS:
        if pattern in s:
            return _errors.SOCKET_UNREADABLE
    for pattern in _DIR_MISSING_PATTERNS:
        if pattern in s:
            return _errors.SOCKET_DIR_MISSING
    return _errors.DOCKER_EXEC_FAILED


def _classify_id_u_failure(stderr: str) -> str:
    """Pick the closed-set code for an ``id -u`` failure."""
    s = (stderr or "").lower()
    if "not found" in s or "no such" in s:
        return _errors.DOCKER_EXEC_FAILED
    return _errors.DOCKER_EXEC_FAILED


class SubprocessTmuxAdapter(TmuxAdapter):
    """Real :class:`TmuxAdapter` implementation using the ``docker`` CLI."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env: dict[str, str] = dict(env if env is not None else os.environ)

    # -- TmuxAdapter Protocol --------------------------------------------------

    def resolve_uid(self, *, container_id: str, bench_user: str) -> str:
        argv = self._argv(
            "exec", *self._exec_env_args(),
            "-u", bench_user, container_id, "id", "-u",
        )
        completed = self._run(argv, container_id=container_id, socket_path=None)
        if completed.returncode != 0:
            raise TmuxError(
                code=_classify_id_u_failure(completed.stderr),
                message=_bound(
                    f"id -u exited {completed.returncode}: {completed.stderr.strip()}"
                ),
                container_id=container_id,
            )
        try:
            return parse_id_u(completed.stdout or "")
        except ValueError as exc:
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message=_bound(str(exc)),
                container_id=container_id,
            ) from exc

    def list_socket_dir(
        self, *, container_id: str, bench_user: str, uid: str
    ) -> SocketListing:
        socket_dir = f"/tmp/tmux-{uid}"  # NOSONAR - intentional tmux socket dir on Linux benches.
        argv = self._argv(
            "exec", *self._exec_env_args(),
            "-u", bench_user, container_id,
            "ls", "-1", "--", socket_dir,
        )
        completed = self._run(argv, container_id=container_id, socket_path=None)
        if completed.returncode != 0:
            code = _classify_socket_listing_failure(completed.stderr, completed.returncode)
            raise TmuxError(
                code=code,
                message=_bound(
                    f"ls {socket_dir} exited {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                ),
                container_id=container_id,
            )
        sockets = parse_socket_listing(completed.stdout or "")
        return SocketListing(
            container_id=container_id,
            uid=uid,
            sockets=tuple(sockets),
        )

    def list_panes(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
    ) -> Sequence[ParsedPane]:
        argv = self._argv(
            "exec",
            *self._exec_env_args(),
            "-u",
            bench_user,
            container_id,
            "tmux",
            "-S",
            socket_path,
            "list-panes",
            "-a",
            "-F",
            _LIST_PANES_FORMAT,
        )
        completed = self._run(argv, container_id=container_id, socket_path=socket_path)
        if completed.returncode != 0:
            raise TmuxError(
                code=_classify_tmux_failure(completed.stderr),
                message=_bound(
                    f"tmux list-panes exited {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
            )
        parsed, malformed = parse_list_panes(completed.stdout or "")
        if malformed and not parsed:
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message=_bound(
                    f"{len(malformed)} tmux list-panes rows malformed or unparseable"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                malformed_rows=tuple(malformed),
            )
        if malformed:
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message=_bound(
                    f"{len(malformed)} of {len(parsed) + len(malformed)} "
                    "tmux list-panes rows malformed"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                partial_panes=tuple(parsed),
                malformed_rows=tuple(malformed),
            )
        return parsed

    # -- Internals -------------------------------------------------------------

    def _argv(self, *args: str) -> list[str]:
        binary = self._resolve_docker()
        return [binary, *args]

    @staticmethod
    def _exec_env_args() -> list[str]:
        """Return the ``-e KEY=VAL`` arguments for ``docker exec``.

        Forces a UTF-8 locale inside the bench container so tmux 3.4 with
        a POSIX/C locale does not silently substitute tabs and other
        control characters in ``-F`` format output (which would surface
        here as ``output_malformed``).
        """
        return ["-e", "LANG=C.UTF-8", "-e", "LC_ALL=C.UTF-8"]

    def _resolve_docker(self) -> str:
        path = self._env.get("PATH", os.defpath)
        binary = shutil.which("docker", path=path)
        if not binary:
            raise TmuxError(
                code=_errors.DOCKER_UNAVAILABLE,
                message="docker binary not found on PATH",
            )
        return binary

    def _run(
        self,
        argv: list[str],
        *,
        container_id: str | None,
        socket_path: str | None,
    ) -> "subprocess.CompletedProcess[str]":
        try:
            return subprocess.run(  # noqa: S603 — typed argv, shell=False
                argv,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
                shell=False,
                env=self._env,
            )
        except subprocess.TimeoutExpired as exc:
            # ``subprocess.run`` performs stdlib cleanup before surfacing
            # TimeoutExpired. We normalize the timeout here; deeper
            # kill-escalation handling would require a ``Popen`` rewrite.
            raise TmuxError(
                code=_errors.DOCKER_EXEC_TIMEOUT,
                message=_bound(
                    f"docker exec exceeded {_TIMEOUT_SECONDS:.1f}s budget"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
            ) from exc
        except FileNotFoundError as exc:
            raise TmuxError(
                code=_errors.DOCKER_UNAVAILABLE,
                message=_bound(f"docker binary not found or not executable: {exc}"),
            ) from exc

    # ─── FEAT-009 delivery surface ────────────────────────────────────

    # MVP closed set for `send_keys` key argument (research §"Submit
    # keystroke" + Assumptions).
    _ALLOWED_SUBMIT_KEYS = frozenset({"Enter"})

    # Pane-disappeared signatures emitted by tmux. The exact text varies
    # across tmux versions; we use a substring match.
    _PANE_DISAPPEARED_PATTERNS = (
        "can't find pane",
        "no such pane",
    )

    def _run_bytes(
        self,
        argv: list[str],
        *,
        input_bytes: bytes | None,
        container_id: str | None,
        socket_path: str | None,
        timeout_seconds: float,
    ) -> "subprocess.CompletedProcess[bytes]":
        """Like :meth:`_run` but returns ``bytes`` outputs so ``input``
        can be raw bytes (FEAT-009 ``load_buffer`` body)."""
        try:
            return subprocess.run(  # noqa: S603 — typed argv, shell=False
                argv,
                input=input_bytes,
                capture_output=True,
                text=False,  # bytes-mode
                timeout=timeout_seconds,
                check=False,
                shell=False,
                env=self._env,
            )
        except subprocess.TimeoutExpired as exc:
            raise TmuxError(
                code=_errors.DOCKER_EXEC_TIMEOUT,
                message=_bound(
                    f"docker exec exceeded {timeout_seconds:.1f}s budget"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                failure_reason="docker_exec_failed",
            ) from exc
        except FileNotFoundError as exc:
            raise TmuxError(
                code=_errors.DOCKER_UNAVAILABLE,
                message=_bound(f"docker binary not found or not executable: {exc}"),
                failure_reason="docker_exec_failed",
            ) from exc

    @classmethod
    def _classify_delivery_stderr(
        cls,
        stderr_bytes: bytes,
        *,
        default_failure_reason: str,
    ) -> str:
        """Pick the FR-018 ``failure_reason`` value for a delivery-time
        tmux stderr. Returns ``default_failure_reason`` unless the
        stderr matches a known "pane disappeared" pattern, in which
        case returns ``pane_disappeared_mid_attempt``."""
        try:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").lower()
        except Exception:
            return default_failure_reason
        for pattern in cls._PANE_DISAPPEARED_PATTERNS:
            if pattern in stderr_text:
                return "pane_disappeared_mid_attempt"
        return default_failure_reason

    def load_buffer(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        buffer_name: str,
        body: bytes,
    ) -> None:
        if not isinstance(body, (bytes, bytearray)):
            # Programmer error — body MUST be bytes (FR-038, research §R-007).
            raise TmuxError(
                code=_errors.DOCKER_EXEC_FAILED,
                message=_bound(
                    f"load_buffer body must be bytes, got {type(body).__name__}"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                failure_reason="tmux_paste_failed",
            )
        argv = self._argv(
            "exec",
            *self._exec_env_args(),
            "-i",  # keep stdin open for the body pipe
            "-u", bench_user, container_id,
            "tmux", "-S", socket_path,
            "load-buffer", "-b", buffer_name, "-",
        )
        completed = self._run_bytes(
            argv,
            input_bytes=bytes(body),
            container_id=container_id,
            socket_path=socket_path,
            timeout_seconds=_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            failure_reason = self._classify_delivery_stderr(
                completed.stderr, default_failure_reason="tmux_paste_failed",
            )
            raise TmuxError(
                code=_errors.DOCKER_EXEC_FAILED,
                message=_bound(
                    f"tmux load-buffer exited {completed.returncode}: "
                    f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                failure_reason=failure_reason,
            )

    def paste_buffer(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
        buffer_name: str,
    ) -> None:
        argv = self._argv(
            "exec",
            *self._exec_env_args(),
            "-u", bench_user, container_id,
            "tmux", "-S", socket_path,
            "paste-buffer", "-t", pane_id, "-b", buffer_name,
        )
        completed = self._run(argv, container_id=container_id, socket_path=socket_path)
        if completed.returncode != 0:
            failure_reason = self._classify_delivery_stderr(
                (completed.stderr or "").encode("utf-8"),
                default_failure_reason="tmux_paste_failed",
            )
            raise TmuxError(
                code=_errors.DOCKER_EXEC_FAILED,
                message=_bound(
                    f"tmux paste-buffer exited {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                failure_reason=failure_reason,
            )

    def send_keys(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
        key: str,
    ) -> None:
        if key not in self._ALLOWED_SUBMIT_KEYS:
            # Closed-set check — Assumptions §"Submit keystroke" + research.
            # A future config-file override that opened the set could allow
            # arbitrary keystroke injection; we reject anything outside MVP.
            raise TmuxError(
                code=_errors.DOCKER_EXEC_FAILED,
                message=_bound(
                    f"send_keys key {key!r} is not in the MVP allowed set "
                    f"{sorted(self._ALLOWED_SUBMIT_KEYS)}"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                failure_reason="tmux_send_keys_failed",
            )
        argv = self._argv(
            "exec",
            *self._exec_env_args(),
            "-u", bench_user, container_id,
            "tmux", "-S", socket_path,
            "send-keys", "-t", pane_id, key,
        )
        completed = self._run(argv, container_id=container_id, socket_path=socket_path)
        if completed.returncode != 0:
            failure_reason = self._classify_delivery_stderr(
                (completed.stderr or "").encode("utf-8"),
                default_failure_reason="tmux_send_keys_failed",
            )
            raise TmuxError(
                code=_errors.DOCKER_EXEC_FAILED,
                message=_bound(
                    f"tmux send-keys exited {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                failure_reason=failure_reason,
            )

    def delete_buffer(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        buffer_name: str,
    ) -> None:
        argv = self._argv(
            "exec",
            *self._exec_env_args(),
            "-u", bench_user, container_id,
            "tmux", "-S", socket_path,
            "delete-buffer", "-b", buffer_name,
        )
        completed = self._run(argv, container_id=container_id, socket_path=socket_path)
        if completed.returncode != 0:
            # The caller (delivery worker) decides whether to surface or
            # suppress a delete_buffer failure (Group-A walk Q1/Q2).
            raise TmuxError(
                code=_errors.DOCKER_EXEC_FAILED,
                message=_bound(
                    f"tmux delete-buffer exited {completed.returncode}: "
                    f"{completed.stderr.strip()}"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
                failure_reason="tmux_paste_failed",
            )
