"""Tmux adapter Protocol and shared dataclasses for FEAT-004 + FEAT-009.

The Protocol decouples discovery code from the in-container subprocess
mechanism so the production ``SubprocessTmuxAdapter`` and the test
``FakeTmuxAdapter`` are interchangeable behind the same surface (R-001).

FEAT-004 discovery methods (FR-033 closed set):

1. ``docker exec -u <bench-user> <container-id> id -u``
2. ``docker exec -u <bench-user> <container-id> ls -1 -- /tmp/tmux-<uid>``
3. ``docker exec -u <bench-user> <container-id> tmux -S <socket-path>
   list-panes -a -F <format>``

FEAT-009 delivery methods (FR-037 — FR-039, four-step paste sequence):

4. ``docker exec -u <bench-user> <container-id> tmux -S <socket-path>
   load-buffer -b <buffer_name> -`` (body piped via stdin; argv-only;
   NO shell interpolation per FR-038 + research §R-007)
5. ``docker exec -u <bench-user> <container-id> tmux -S <socket-path>
   paste-buffer -t <pane> -b <buffer_name>``
6. ``docker exec -u <bench-user> <container-id> tmux -S <socket-path>
   send-keys -t <pane> Enter`` (submit keystroke; closed-set to "Enter"
   in MVP per Assumptions)
7. ``docker exec -u <bench-user> <container-id> tmux -S <socket-path>
   delete-buffer -b <buffer_name>``

Adapters MUST raise :class:`TmuxError` (with a closed-set ``code``) for
every failure mode; they MUST NOT raise :class:`subprocess.CalledProcessError`,
:class:`subprocess.TimeoutExpired`, ``FileNotFoundError``, etc. through to
callers.

For FEAT-009, :class:`TmuxError` carries an additional ``failure_reason``
field — one of the FR-018 closed-set values
(``tmux_paste_failed``, ``tmux_send_keys_failed``, ``docker_exec_failed``,
``pane_disappeared_mid_attempt``). The delivery worker reads this to
populate ``message_queue.failure_reason`` (FR-043).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, Union

from .parsers import MalformedRow, ParsedPane


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

    Use the closed-set codes from :mod:`agenttower.socket_api.errors`
    for the ``code`` field (FEAT-002 envelope). Carries optional
    ``container_id`` and ``tmux_socket_path`` so per-scope failures can
    be attributed correctly during reconciliation.

    ``failure_reason`` (FEAT-009): when raised by the FEAT-009 delivery
    methods (load_buffer / paste_buffer / send_keys / delete_buffer),
    carries the FR-018 closed-set failure_reason value
    (``tmux_paste_failed``, ``tmux_send_keys_failed``,
    ``docker_exec_failed``, ``pane_disappeared_mid_attempt``). The
    delivery worker reads this to populate ``message_queue.failure_reason``
    (FR-043). FEAT-004 callers leave it ``None``.
    """

    code: str
    message: str
    container_id: str | None = None
    tmux_socket_path: str | None = None
    partial_panes: tuple[ParsedPane, ...] = ()
    malformed_rows: tuple[MalformedRow, ...] = ()
    failure_reason: str | None = None

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
        When malformed rows are encountered alongside parseable rows, adapters
        attach the successfully parsed subset on ``TmuxError.partial_panes`` so
        the service layer can persist the socket as degraded without losing the
        good rows.
        """

    # ─── FEAT-009 delivery surface (FR-037 — FR-039) ──────────────────

    def load_buffer(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        buffer_name: str,
        body: bytes,
    ) -> None:
        """Load ``body`` bytes into the named tmux paste buffer.

        Invokes ``docker exec -u <bench-user> <container-id> tmux -S
        <socket-path> load-buffer -b <buffer-name> -`` with ``body``
        piped via stdin. The body MUST NEVER be interpolated into a
        shell command string or any argv element (FR-038 + research
        §R-007 — enforced by the AST gate test).

        Raises :class:`TmuxError` with ``failure_reason='tmux_paste_failed'``
        on tmux non-zero return / TimeoutExpired, and with
        ``failure_reason='docker_exec_failed'`` on docker-exec failure
        (FileNotFoundError or docker-side error).
        """

    def paste_buffer(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
        buffer_name: str,
    ) -> None:
        """Paste the named buffer into ``pane_id``.

        Invokes ``docker exec ... tmux paste-buffer -t <pane> -b <buffer>``.

        Raises :class:`TmuxError` with ``failure_reason='tmux_paste_failed'``
        on tmux non-zero return / timeout, or
        ``failure_reason='pane_disappeared_mid_attempt'`` when tmux
        reports the pane is gone (distinct from the pre-paste re-check
        which would catch this BEFORE stamping).
        """

    def send_keys(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
        key: str,
    ) -> None:
        """Send a single key (``Enter`` in MVP) to ``pane_id``.

        Invokes ``docker exec ... tmux send-keys -t <pane> <key>``. The
        ``key`` parameter is a tmux key-name string; MVP closed set is
        ``{"Enter"}`` (Assumptions; future Codex/Claude submit patterns
        are out of scope for FEAT-009).

        Raises :class:`TmuxError` with ``failure_reason='tmux_send_keys_failed'``
        on tmux non-zero return / timeout, or
        ``failure_reason='pane_disappeared_mid_attempt'`` when the pane
        is gone.
        """

    def delete_buffer(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        buffer_name: str,
    ) -> None:
        """Delete the named tmux paste buffer (FR-039 cleanup).

        Invokes ``docker exec ... tmux delete-buffer -b <buffer>``. Called
        in two places per Group-A walk Q1/Q2:

        * Happy path after a successful ``paste_buffer`` + ``send_keys``
          (the row's terminal state is committed AFTER this; a
          delete_buffer failure here does NOT downgrade the row — it
          stays ``delivered`` with an orphaned-buffer warning per Q2).
        * Cleanup-on-failure: after a successful ``load_buffer`` but
          failed ``paste_buffer`` / ``send_keys`` (Q1). Errors here are
          logged and ignored.

        Raises :class:`TmuxError` with ``failure_reason='tmux_paste_failed'``
        when called on the happy path and the worker decides to surface
        the cleanup failure (rare; Q2 says we don't).
        """

    # ─── FEAT-013 managed-session surface (T057) ──────────────────────
    #
    # Verbs used by the managed-session spawn backend to *create* tmux
    # state inside a bench container (research §R6). Argv-first — launch
    # commands are passed as separate argv items after ``--`` and NEVER
    # interpolated into a shell string (Principle III). Each verb runs
    # through the same ``docker exec -u <bench-user>`` channel as the
    # discovery / delivery surfaces above.

    def has_session(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        session_name: str,
    ) -> bool:
        """Return whether a tmux session named ``session_name`` exists.

        Invokes ``docker exec ... tmux -S <socket> has-session -t
        <session_name>``. Exit 0 → ``True``; a tmux "can't find session"
        / "no server running" non-zero exit → ``False`` (these are the
        normal "absent" signals, not errors). Raises :class:`TmuxError`
        only when ``docker exec`` itself fails (missing container, OCI
        runtime error, docker daemon unreachable). Used as the FR-016
        ``managed_session_name_conflict`` pre-check before the first
        ``new-session`` of a layout.
        """

    def new_session(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        session_name: str,
        window_name: str,
        launch_argv: Sequence[str],
        working_dir: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Create a detached session with its first pane; return the pane id.

        Invokes ``docker exec ... tmux -S <socket> new-session -d -s
        <session> -n <window> [-c <dir>] [-e K=V ...] -P -F '#{pane_id}'
        [-- <launch_argv...>]`` (research §R6). With an empty
        ``launch_argv`` tmux starts the bench's default shell. Returns
        the ``%N`` pane id printed by ``-P -F``. Raises :class:`TmuxError`
        on non-zero exit / docker-exec failure (the spawn backend maps
        this to ``failed_stage=pane_create``).
        """

    def split_window(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        session_name: str,
        direction: str,
        launch_argv: Sequence[str],
        working_dir: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Split the session's active pane; return the new pane id.

        Invokes ``docker exec ... tmux -S <socket> split-window -t
        <session> -h|-v [-c <dir>] [-e K=V ...] -P -F '#{pane_id}'
        [-- <launch_argv...>]``. ``direction`` MUST be ``"h"`` or
        ``"v"``. Targeting the session (not a numeric pane index) avoids
        DB-vs-tmux pane-index drift — the returned ``%N`` id is the
        durable handle the register backend threads downstream. Raises
        :class:`TmuxError` on failure (``failed_stage=pane_create``).
        """

    def set_pane_title(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
        title: str,
    ) -> None:
        """Set ``pane_id``'s title (``select-pane -t <pane_id> -T <title>``).

        Used to stamp the ``@MANAGED:<token>:<label>`` pending-managed
        marker (FR-014 / research §R1) and to clear it to the bare label
        after registration. Targets the ``%N`` pane id so it is immune to
        pane-index renumbering. Raises :class:`TmuxError` on failure.
        """

    def kill_pane(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
    ) -> None:
        """Kill ``pane_id`` (``kill-pane -t <pane_id>``) — FR-010 remove.

        Raises :class:`TmuxError` on failure; callers treat a
        pane-already-gone signal as idempotent success.
        """

    def is_pane_dead(
        self,
        *,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
    ) -> bool:
        """Return whether ``pane_id``'s foreground process has exited.

        Invokes ``docker exec ... tmux -S <socket> display-message -p -t
        <pane_id> '#{pane_dead}'`` — the research §R8 launch-exit probe.
        Returns ``True`` when tmux reports ``pane_dead == 1`` *or* when the
        pane no longer exists (with tmux's default ``remain-on-exit off`` a
        launch command that exits immediately destroys its pane, which
        tmux reports as a "can't find pane" non-zero exit). Returns
        ``False`` when the pane is alive (``pane_dead == 0``).

        Raises :class:`TmuxError` only when ``docker exec`` itself fails;
        the spawn backend treats such an indeterminate probe as
        "assume-alive" so a transient probe error never spuriously
        downgrades a freshly-spawned pane to ``degraded``.
        """
