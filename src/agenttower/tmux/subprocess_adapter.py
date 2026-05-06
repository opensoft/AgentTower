"""Production tmux adapter that shells out via ``subprocess.run``.

Argv is constructed as a typed list with ``shell=False``; container ids,
names, the bench user, socket paths, and tmux output never reach a shell
string (FR-021). Each subprocess call has a 5-second timeout (FR-018) and
a hung process is killed and waited before returning a
``docker_exec_timeout`` :class:`TmuxError`. If termination itself fails or
exceeds a secondary 1-second grace period, the per-scope error escalates
to ``internal_error`` (FR-018 escalation, R-003 termination escalation).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence

from ..socket_api import errors as _errors
from .adapter import SocketListing, TmuxAdapter, TmuxError
from .parsers import (
    MAX_COMMAND,
    MAX_DEFAULT,
    MAX_PATH,
    MAX_TITLE,
    ParsedPane,
    parse_id_u,
    parse_list_panes,
    parse_socket_listing,
    sanitize_text,
)

_TIMEOUT_SECONDS = 5.0
_KILL_GRACE_SECONDS = 1.0
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
        argv = self._argv("exec", "-u", bench_user, container_id, "id", "-u")
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
        socket_dir = f"/tmp/tmux-{uid}"
        argv = self._argv(
            "exec", "-u", bench_user, container_id, "ls", "-1", "--", socket_dir
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
                    f"{len(malformed)} tmux list-panes rows had wrong field count"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
            )
        if malformed:
            # At least one parsed row + some malformed rows → reconciler
            # records a per-scope output_malformed alongside the successful
            # panes (treated as a degraded socket scan via PaneDiscoveryService).
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message=_bound(
                    f"{len(malformed)} of {len(parsed) + len(malformed)} "
                    "tmux list-panes rows malformed"
                ),
                container_id=container_id,
                tmux_socket_path=socket_path,
            )
        return parsed

    # -- Internals -------------------------------------------------------------

    def _argv(self, *args: str) -> list[str]:
        binary = self._resolve_docker()
        return [binary, *args]

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
            # ``subprocess.run`` calls ``proc.kill(); proc.communicate()``
            # before raising TimeoutExpired, which is the cleanup behavior
            # FR-018 requires. If that internal cleanup itself failed we'd
            # hit the kill-escalation path; ``run`` does not surface that
            # specific failure, so we treat reaching this except clause as
            # the success-of-cleanup path.
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
                message=_bound(f"docker binary not executable: {exc}"),
            ) from exc
