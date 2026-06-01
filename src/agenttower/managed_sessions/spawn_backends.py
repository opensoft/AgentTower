"""FEAT-013 spawn-backend factory (T028 / T029 / T030 + T057 production wiring).

The background spawn task (``service.spawn_layout_in_background``) takes
three **injectable Callable backends** so it can be unit-tested without
a real bench container:

    TmuxSpawnFn:     (pane) -> {ok, tmux_pane_id, launch_alive, socket_path}
    RegisterAgentFn: (pane, tmux_pane_id) -> {ok, agent_id}
    LogAttachFn:     (pane, agent_id) -> {ok}

This module is the production-side factory: at daemon boot the daemon
constructs concrete backends from the FEAT-004 ``TmuxAdapter`` +
FEAT-006 ``AgentService`` + FEAT-007 ``LogService`` and stores them on
``DaemonContext.managed_spawn_backends`` so the ``managed.layout.create``
handler's ``kickoff_spawn_pipeline()`` can run the background task with
real backends.

**Status (T057)**: all three backends are production-wired. The tmux
spawn backend composes ``new-session`` / ``split-window`` /
``select-pane -T`` through the shared FEAT-004 docker-exec channel
(``TmuxAdapter``), resolves the bench socket via ``resolve_uid``, and
returns the durable ``%N`` pane id. A ``has-session`` pre-check enforces
the FR-016 ``managed_session_name_conflict`` gate before the first
``new-session`` of a layout. Pane targeting uses the ``%N`` id (not a
numeric index) so it is immune to tmux pane-index renumbering.

**Deferred to T057b** (tracked, not silently dropped): fine-grained
launch-exit detection (research §R8's 1-second post-spawn poll →
``degraded`` / ``failed_stage=launch_command``). This backend currently
returns ``launch_alive=True`` on a successful spawn; the ``degraded``
transition for an immediately-exiting launch command is already exercised
by the fake-backend pipeline tests (T027) but is not yet *detected*
against a live pane. The bench-container integration test bodies
(``test_story1``) are the other T057b deliverable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

from ..tmux.adapter import TmuxAdapter, TmuxError
from .dao import ManagedPaneRow
from .errors import MANAGED_SESSION_NAME_CONFLICT, ManagedSessionsError
from .launch_profiles import resolve_profile
from .service import (
    LogAttachFn,
    RegisterAgentFn,
    TmuxSpawnFn,
)

if TYPE_CHECKING:
    from ..agents.service import AgentService
    from ..logs.service import LogService


# A resolver mapping a container_id to the bench user to pass to
# ``docker exec -u <bench-user>``. Defaults to ``$USER`` (the constitution's
# ``-u "$USER"`` convention); the daemon may inject a registry-backed
# resolver that honours ``containers.config_user`` per FEAT-004's
# ``_resolve_bench_user`` precedence.
BenchUserResolver = Callable[[str], str]

DEFAULT_SOCKET_NAME = "default"
DEFAULT_WINDOW_NAME = "agenttower"
DEFAULT_SPLIT_DIRECTION = "h"


def _default_bench_user_resolver(
    env: Mapping[str, str],
) -> BenchUserResolver:
    def resolve(_container_id: str) -> str:
        return env.get("USER") or env.get("LOGNAME") or "root"

    return resolve


def _socket_path_for(adapter: TmuxAdapter, container_id: str, bench_user: str,
                     socket_name: str) -> str:
    """Resolve the bench tmux socket path the managed session lives on.

    Managed sessions are created on the bench's ``default`` tmux socket
    (``/tmp/tmux-<uid>/default``) so the FEAT-004 scan and FEAT-009
    delivery surfaces discover them through the same channel they
    already use for adopted panes.
    """
    uid = adapter.resolve_uid(container_id=container_id, bench_user=bench_user)
    return f"/tmp/tmux-{uid}/{socket_name}"  # NOSONAR - tmux socket path inside bench container.


def _resolve_launch(
    pane: ManagedPaneRow, profile_override_dir: Optional[Path]
) -> tuple[tuple[str, ...], Optional[str], dict[str, str]]:
    """Return ``(launch_argv, working_dir, env)`` for a pane.

    When the pane carries no ``launch_command_ref`` the argv is empty,
    which makes tmux start the bench's default shell. Raises
    ``ManagedSessionsError(MANAGED_LAUNCH_COMMAND_NOT_FOUND)`` if a named
    profile cannot be resolved (the spawn backend maps that to
    ``failed_stage=pane_create``).
    """
    if pane.launch_command_ref:
        profile = resolve_profile(
            pane.launch_command_ref, override_dir=profile_override_dir
        )
        return tuple(profile.command), profile.working_dir, dict(profile.env)
    return (), None, {}


# ─── Tmux spawn backend (T057) ──────────────────────────────────────────


def make_tmux_spawn_backend(
    *,
    adapter: TmuxAdapter,
    bench_user_resolver: Optional[BenchUserResolver] = None,
    env: Optional[Mapping[str, str]] = None,
    profile_override_dir: Optional[Path] = None,
    socket_name: str = DEFAULT_SOCKET_NAME,
    window_name: str = DEFAULT_WINDOW_NAME,
    split_direction: str = DEFAULT_SPLIT_DIRECTION,
) -> TmuxSpawnFn:
    """Build a production ``TmuxSpawnFn`` over a FEAT-004 ``TmuxAdapter``.

    The returned callable, per pane:

        1. Resolves the bench user + ``/tmp/tmux-<uid>/<socket>`` path.
        2. Resolves the launch argv / working_dir / env from the pane's
           launch profile (empty argv → default shell).
        3. For the first pane (``tmux_pane_index == 0``): runs the FR-016
           ``has-session`` conflict pre-check, then ``new-session``.
           For later panes: ``split-window`` against the session.
        4. Stamps the ``@MANAGED:<token>:<label>`` marker title on the
           new ``%N`` pane (FR-014 / research §R1).
        5. Returns ``{ok, tmux_pane_id, launch_alive, socket_path}``.

    Any :class:`TmuxError` (or launch-profile ``ManagedSessionsError``)
    becomes ``{ok: False, error: {code, message}}`` so the spawn task can
    drive the ``failed_stage=pane_create`` transition.
    """
    env_map = dict(env if env is not None else os.environ)
    resolve_bench_user = bench_user_resolver or _default_bench_user_resolver(env_map)

    def spawn(pane: ManagedPaneRow) -> dict[str, Any]:
        try:
            bench_user = resolve_bench_user(pane.container_id)
            socket_path = _socket_path_for(
                adapter, pane.container_id, bench_user, socket_name
            )
            launch_argv, working_dir, launch_env = _resolve_launch(
                pane, profile_override_dir
            )

            if pane.tmux_pane_index == 0:
                # FR-016 conflict pre-check before creating the session.
                if adapter.has_session(
                    container_id=pane.container_id,
                    bench_user=bench_user,
                    socket_path=socket_path,
                    session_name=pane.tmux_session_name,
                ):
                    raise ManagedSessionsError(
                        MANAGED_SESSION_NAME_CONFLICT,
                        details={
                            "container_id": pane.container_id,
                            "tmux_session_name": pane.tmux_session_name,
                        },
                    )
                tmux_pane_id = adapter.new_session(
                    container_id=pane.container_id,
                    bench_user=bench_user,
                    socket_path=socket_path,
                    session_name=pane.tmux_session_name,
                    window_name=window_name,
                    launch_argv=launch_argv,
                    working_dir=working_dir,
                    env=launch_env,
                )
            else:
                tmux_pane_id = adapter.split_window(
                    container_id=pane.container_id,
                    bench_user=bench_user,
                    socket_path=socket_path,
                    session_name=pane.tmux_session_name,
                    direction=split_direction,
                    launch_argv=launch_argv,
                    working_dir=working_dir,
                    env=launch_env,
                )

            # Stamp the pending-managed marker title on the new pane so
            # the FEAT-004 scan skips it until registration clears it.
            marker_title = f"@MANAGED:{pane.pending_marker_token or ''}:{pane.label}"
            adapter.set_pane_title(
                container_id=pane.container_id,
                bench_user=bench_user,
                socket_path=socket_path,
                pane_id=tmux_pane_id,
                title=marker_title,
            )

            return {
                "ok": True,
                "tmux_pane_id": tmux_pane_id,
                "launch_alive": True,  # T057b: live launch-exit detection
                "socket_path": socket_path,
            }
        except ManagedSessionsError as exc:
            return {
                "ok": False,
                "error": {"code": exc.code, "message": str(exc)},
            }
        except TmuxError as exc:
            return {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
            }

    return spawn


# ─── Register backend (T029) ────────────────────────────────────────────


def make_register_backend(
    agent_service: "AgentService",
    *,
    adapter: Optional[TmuxAdapter] = None,
    bench_user_resolver: Optional[BenchUserResolver] = None,
    env: Optional[Mapping[str, str]] = None,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> RegisterAgentFn:
    """Build a ``RegisterAgentFn`` from a FEAT-006 ``AgentService``.

    The returned callable invokes ``register_agent`` with the FEAT-006
    ``pane_composite_key`` shape and returns either:

        {"ok": True, "agent_id": <newly-registered agent id>}
        {"ok": False, "error": {"code": <FEAT-006 code>, "message": <prose>}}

    When ``adapter`` is supplied (production), the bench ``tmux_socket_path``
    is resolved via ``resolve_uid`` so it matches the socket the spawn
    backend created the session on. Without an adapter (legacy callers /
    tests) it falls back to the canonical default socket name.
    """
    env_map = dict(env if env is not None else os.environ)
    resolve_bench_user = bench_user_resolver or _default_bench_user_resolver(env_map)

    def _socket_for(pane: ManagedPaneRow) -> str:
        if adapter is None:
            return f"/tmp/tmux-{socket_name}/{socket_name}"  # NOSONAR - legacy fallback path.
        bench_user = resolve_bench_user(pane.container_id)
        return _socket_path_for(adapter, pane.container_id, bench_user, socket_name)

    def register(pane: ManagedPaneRow, tmux_pane_id: str) -> dict[str, Any]:
        from ..agents.errors import RegistrationError

        # FEAT-013 single-window layout: window_index=0 (built-in
        # templates are single-window; richer layouts are a later feature).
        params: dict[str, Any] = {
            "container_id": pane.container_id,
            "pane_composite_key": {
                "container_id": pane.container_id,
                "tmux_socket_path": _socket_for(pane),
                "tmux_session_name": pane.tmux_session_name,
                "tmux_window_index": 0,
                "tmux_pane_index": pane.tmux_pane_index,
                "tmux_pane_id": tmux_pane_id,
            },
            "role": pane.role,
            "capability": pane.capability,
            "label": pane.label,
        }
        try:
            outcome = agent_service.register_agent(params, socket_peer_uid=-1)
        except RegistrationError as exc:
            return {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
            }
        agent_payload = outcome.get("agent") if isinstance(outcome, dict) else None
        if isinstance(agent_payload, dict) and "agent_id" in agent_payload:
            return {"ok": True, "agent_id": agent_payload["agent_id"]}
        # Defensive — FEAT-006 returned a different shape than expected.
        return {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": "register_agent returned an unexpected shape",
            },
        }

    return register


# ─── Log-attach backend (T030) ──────────────────────────────────────────


def make_log_attach_backend(log_service: "LogService") -> LogAttachFn:
    """Build a ``LogAttachFn`` from a FEAT-007 ``LogService``.

    Calls ``LogService.attach_log`` with the just-registered ``agent_id``
    and the canonical default log path (FEAT-007 FR-005 default). Returns
    ``{"ok": True}`` on success or ``{"ok": False, "error": ...}`` on
    failure; the spawn task maps failure to ``failed_stage=log_attach``
    via the ``degraded`` transition.
    """

    def attach(pane: ManagedPaneRow, agent_id: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "agent_id": agent_id,
            # No log_path supplied → FEAT-007 uses its FR-005 default.
        }
        try:
            log_service.attach_log(params, socket_peer_uid=-1, source="managed_spawn")
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001 — envelope-shape safety net
            return {
                "ok": False,
                "error": {
                    "code": getattr(exc, "code", "internal_error"),
                    "message": str(exc),
                },
            }

    return attach


# ─── Convenience: assemble all three from DaemonContext ─────────────────


def build_spawn_backends(
    *,
    adapter: TmuxAdapter,
    agent_service: "AgentService",
    log_service: "LogService",
    bench_user_resolver: Optional[BenchUserResolver] = None,
    env: Optional[Mapping[str, str]] = None,
    profile_override_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Assemble the three concrete backends as the dict the daemon stores.

    The daemon calls this once at boot and stores the result on
    ``DaemonContext.managed_spawn_backends``; ``kickoff_spawn_pipeline``
    reads ``backends["tmux_spawn"|"register"|"log_attach"]`` off it.
    """
    return {
        "tmux_spawn": make_tmux_spawn_backend(
            adapter=adapter,
            bench_user_resolver=bench_user_resolver,
            env=env,
            profile_override_dir=profile_override_dir,
        ),
        "register": make_register_backend(
            agent_service,
            adapter=adapter,
            bench_user_resolver=bench_user_resolver,
            env=env,
        ),
        "log_attach": make_log_attach_backend(log_service),
    }


__all__ = [
    "BenchUserResolver",
    "build_spawn_backends",
    "make_register_backend",
    "make_log_attach_backend",
    "make_tmux_spawn_backend",
]
