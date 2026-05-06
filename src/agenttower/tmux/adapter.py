"""Tmux adapter Protocol and shared dataclasses for FEAT-004.

The Protocol decouples discovery code from the in-container subprocess
mechanism so the production ``SubprocessTmuxAdapter`` and the test
``FakeTmuxAdapter`` are interchangeable behind the same surface (R-001).

Per FR-033 the closed set of in-container subprocess invocations is:

1. ``docker exec -u <bench-user> <container-id> id -u``
2. ``docker exec -u <bench-user> <container-id> ls -1 -- /tmp/tmux-<uid>``
3. ``docker exec -u <bench-user> <container-id> tmux -S <socket-path>
   list-panes -a -F <format>``

Adapters MUST raise :class:`TmuxError` (with a closed-set ``code``) for
every failure mode; they MUST NOT raise :class:`subprocess.CalledProcessError`,
:class:`subprocess.TimeoutExpired`, ``FileNotFoundError``, etc. through to
callers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, Union

from .parsers import ParsedPane


@dataclass(frozen=True)
class SocketListing:
    """Result of one ``ls -1 -- /tmp/tmux-<uid>/`` call (data-model §3.2)."""

    container_id: str
    uid: str
    sockets: tuple[str, ...]


@dataclass(frozen=True)
class OkSocketScan:
    """A successful per-socket ``tmux list-panes`` result (data-model §3.3)."""

    panes: tuple[ParsedPane, ...]


@dataclass(frozen=True)
class FailedSocketScan:
    """A failed per-socket scan on a container whose tmux is otherwise reachable."""

    error_code: str
    error_message: str


SocketScanOutcome = Union[OkSocketScan, FailedSocketScan]


@dataclass(frozen=True)
class TmuxError(Exception):
    """Normalized tmux/docker-exec subprocess failure.

    Use the closed-set codes from :mod:`agenttower.socket_api.errors`.
    Carries optional ``container_id`` and ``tmux_socket_path`` so per-scope
    failures can be attributed correctly during reconciliation.
    """

    code: str
    message: str
    container_id: str | None = None
    tmux_socket_path: str | None = None

    def __str__(self) -> str:
        scope = []
        if self.container_id is not None:
            scope.append(f"container={self.container_id}")
        if self.tmux_socket_path is not None:
            scope.append(f"socket={self.tmux_socket_path}")
        scope_repr = " ".join(scope)
        if scope_repr:
            return f"[{self.code}] {scope_repr}: {self.message}"
        return f"[{self.code}] {self.message}"


class TmuxAdapter(Protocol):
    """Protocol implemented by ``SubprocessTmuxAdapter`` and ``FakeTmuxAdapter``."""

    def resolve_uid(self, *, container_id: str, bench_user: str) -> str:
        """Run ``id -u`` inside the container and return the digit string.

        Raises :class:`TmuxError` on timeout, non-zero exit, or unparseable
        stdout. The ``container_id`` is attached to the error for the
        per-container error-detail entry.
        """

    def list_socket_dir(
        self, *, container_id: str, bench_user: str, uid: str
    ) -> SocketListing:
        """Run ``ls -1 -- /tmp/tmux-<uid>/`` inside the container.

        Raises :class:`TmuxError` with code ``socket_dir_missing`` if the
        directory is absent, ``socket_unreadable`` for permission errors,
        ``docker_exec_failed`` / ``docker_exec_timeout`` / ``output_malformed``
        for the other closed-set codes (R-007 / R-011).
        """

    def list_panes(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
    ) -> Sequence[ParsedPane]:
        """Run ``tmux -S <socket-path> list-panes -a -F <format>`` (R-002).

        Returns the parsed pane rows. Raises :class:`TmuxError` for the
        closed-set codes (``tmux_unavailable``, ``tmux_no_server``,
        ``docker_exec_failed``, ``docker_exec_timeout``, ``output_malformed``).
        Malformed rows produce a single ``output_malformed`` error so the
        reconciler can attribute the failure per-(container, socket).
        """
