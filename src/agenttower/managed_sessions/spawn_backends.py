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

**Status (T057b)**: fine-grained launch-exit detection (research §R8) is
now wired. After a successful spawn the backend settles for
``launch_probe_delay_s`` (1s by default) then queries ``#{pane_dead}``
once via the new ``is_pane_dead`` adapter verb; a pane whose launch
command has already exited reports ``launch_alive=False`` so the spawn
task drives ``degraded`` / ``failed_stage=launch_command``. An
indeterminate probe (docker-exec failure) is swallowed as "assume-alive"
so it never spuriously downgrades a pane that genuinely spawned.

This module also exposes ``make_session_conflict_checker`` (T057b part 3):
a ``(container_id, session_name) -> bool`` probe over the FEAT-004
``has_session`` verb that lets ``create_layout`` reject an out-of-band
tmux session-name collision synchronously (FR-016) before any DB rows
are inserted. It is included in ``build_spawn_backends`` under the
``session_conflict`` key and threaded into the M1 handlers.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

from ..socket_api import errors as _sock_errors
from ..state import agents as _state_agents
from ..tmux.adapter import TmuxAdapter, TmuxError
from .dao import ManagedPaneRow
from .errors import MANAGED_SESSION_NAME_CONFLICT, ManagedSessionsError
from .launch_profiles import resolve_profile
from .service import (
    CleanupFn,
    LogAttachFn,
    RegisterAgentFn,
    TmuxKillFn,
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

# Research §R8: a launch command that exits within ~1s of spawn is a
# failed launch (→ degraded / failed_stage=launch_command). After
# spawning we settle for this long, then probe ``#{pane_dead}`` once.
DEFAULT_LAUNCH_PROBE_DELAY_S = 1.0


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


def _probe_launch_alive(
    adapter: TmuxAdapter,
    *,
    container_id: str,
    bench_user: str,
    socket_path: str,
    pane_id: str,
    delay_s: float,
    sleep_fn: Callable[[float], None],
) -> bool:
    """Research §R8 launch-exit probe: is the pane still alive after settle?

    Settles for ``delay_s`` seconds (so an immediately-exiting launch
    command has reset the pane to dead / destroyed) then queries
    ``#{pane_dead}`` once. Returns ``True`` (alive) when ``delay_s <= 0``
    (probe disabled) or when the probe itself raises a :class:`TmuxError`
    — an indeterminate probe must not spuriously downgrade a pane that
    genuinely spawned.
    """
    if delay_s <= 0:
        return True
    sleep_fn(delay_s)
    try:
        dead = adapter.is_pane_dead(
            container_id=container_id,
            bench_user=bench_user,
            socket_path=socket_path,
            pane_id=pane_id,
        )
    except TmuxError:
        return True
    return not dead


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
    launch_probe_delay_s: float = DEFAULT_LAUNCH_PROBE_DELAY_S,
    sleep_fn: Callable[[float], None] = time.sleep,
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
        5. Runs the research §R8 launch-exit probe: settles for
           ``launch_probe_delay_s`` then queries ``#{pane_dead}`` once.
           A pane that has already exited reports ``launch_alive=False``
           so the spawn task drives ``degraded`` /
           ``failed_stage=launch_command``.
        6. Returns ``{ok, tmux_pane_id, launch_alive, socket_path}``.

    Any :class:`TmuxError` (or launch-profile ``ManagedSessionsError``)
    becomes ``{ok: False, error: {code, message}}`` so the spawn task can
    drive the ``failed_stage=pane_create`` transition.

    The launch-exit probe is bypassed when ``launch_probe_delay_s <= 0``
    (returns ``launch_alive=True`` immediately) — used by callers that
    don't want the post-spawn settle. A probe that raises
    :class:`TmuxError` (docker exec failure) is swallowed and treated as
    ``launch_alive=True`` so a transient probe error never spuriously
    downgrades a pane that actually spawned.
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

            launch_alive = _probe_launch_alive(
                adapter,
                container_id=pane.container_id,
                bench_user=bench_user,
                socket_path=socket_path,
                pane_id=tmux_pane_id,
                delay_s=launch_probe_delay_s,
                sleep_fn=sleep_fn,
            )

            return {
                "ok": True,
                "tmux_pane_id": tmux_pane_id,
                "launch_alive": launch_alive,
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


# ─── Session-name conflict checker (T057b part 3) ───────────────────────


def make_session_conflict_checker(
    *,
    adapter: TmuxAdapter,
    bench_user_resolver: Optional[BenchUserResolver] = None,
    env: Optional[Mapping[str, str]] = None,
    socket_name: str = DEFAULT_SOCKET_NAME,
) -> Callable[[str, str], bool]:
    """Build a ``(container_id, session_name) -> bool`` conflict probe.

    The returned callable resolves the bench socket and runs the FEAT-004
    ``has_session`` verb so ``create_layout`` can reject an out-of-band
    tmux session-name collision *synchronously* (FR-016) — before any DB
    rows are inserted — instead of letting it surface as a failed pane in
    the async spawn task. ``has_session`` already maps an absent
    session/server to ``False`` and raises :class:`TmuxError` only on a
    genuine docker-exec failure; ``create_layout`` swallows that
    indeterminate case so a transient probe error never masquerades as a
    name conflict.
    """
    env_map = dict(env if env is not None else os.environ)
    resolve_bench_user = bench_user_resolver or _default_bench_user_resolver(env_map)

    def has_session(container_id: str, session_name: str) -> bool:
        bench_user = resolve_bench_user(container_id)
        socket_path = _socket_path_for(
            adapter, container_id, bench_user, socket_name
        )
        return adapter.has_session(
            container_id=container_id,
            bench_user=bench_user,
            socket_path=socket_path,
            session_name=session_name,
        )

    return has_session


# ─── Recovery list-panes channel (T058) ─────────────────────────────────


def make_recovery_list_panes_channel(
    *,
    adapter: TmuxAdapter,
    bench_user_resolver: Optional[BenchUserResolver] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Callable[[str], list[dict[str, object]]]:
    """Build the FR-020 recovery ``tmux_list_panes_fn(container_id)``.

    Mirrors the FEAT-004 ``resolve_uid -> list_socket_dir -> list_panes``
    traversal but returns the minimal ``{tmux_session_name,
    tmux_pane_index}`` rows ``recovery.reconcile`` matches managed DB
    panes against. Unlike the FEAT-004 scan it does NOT strip
    pending-managed panes — reconcile must see a mid-spawn pane as live
    (a ``creating`` pane's disposition is decided by marker TTL, while
    ``ready``/``degraded`` panes have already had their marker cleared).

    Conservative liveness contract: the channel contributes a pane row
    only when it is confident the live set is COMPLETE.
    ``socket_dir_missing`` (no tmux at all) and per-socket
    ``tmux_no_server`` are confident "nothing here" signals → they
    contribute no rows. Any OTHER :class:`TmuxError` (docker-exec
    failure/timeout, unreadable socket dir, malformed output with no
    salvageable partial) is PROPAGATED so the boot reconcile's fail-soft
    wrapper leaves the rows untouched rather than risk a false
    ``failed_stage=recovery_reattach`` transition on a transient blip.
    """
    env_map = dict(env if env is not None else os.environ)
    resolve_bench_user = bench_user_resolver or _default_bench_user_resolver(env_map)

    def list_panes(container_id: str) -> list[dict[str, object]]:
        bench_user = resolve_bench_user(container_id)
        # resolve_uid failure propagates → reconcile skips this boot
        # (safe-fail; rows untouched).
        uid = adapter.resolve_uid(container_id=container_id, bench_user=bench_user)
        try:
            listing = adapter.list_socket_dir(
                container_id=container_id, bench_user=bench_user, uid=uid
            )
        except TmuxError as exc:
            if exc.code == _sock_errors.SOCKET_DIR_MISSING:
                return []  # no tmux socket dir → confidently no live panes
            raise

        rows: list[dict[str, object]] = []
        for socket_name in listing.sockets:
            socket_path = f"/tmp/tmux-{uid}/{socket_name}"  # NOSONAR - tmux socket path inside bench container.
            try:
                panes = adapter.list_panes(
                    container_id=container_id,
                    bench_user=bench_user,
                    socket_path=socket_path,
                )
            except TmuxError as exc:
                if exc.code == _sock_errors.TMUX_NO_SERVER:
                    continue  # this socket has no server → no panes on it
                if exc.code == _sock_errors.OUTPUT_MALFORMED and exc.partial_panes:
                    panes = exc.partial_panes  # salvage the parseable subset
                else:
                    raise
            for pane in panes:
                rows.append(
                    {
                        "tmux_session_name": pane.tmux_session_name,
                        "tmux_pane_index": pane.tmux_pane_index,
                    }
                )
        return rows

    return list_panes


# ─── Remove-pane backends (T059) ────────────────────────────────────────


def make_tmux_kill_backend(
    *,
    adapter: TmuxAdapter,
    agent_service: "AgentService",
    bench_user_resolver: Optional[BenchUserResolver] = None,
    env: Optional[Mapping[str, str]] = None,
) -> TmuxKillFn:
    """Build the FR-010 ``tmux_kill_fn(pane) -> {ok, error?}`` backend.

    ``managed_pane`` stores ``tmux_pane_index`` (which renumbers when
    sibling panes close), NOT the durable ``%N`` pane id ``kill-pane``
    targets. We resolve the durable id by joining
    ``managed_pane.agent_id`` → the FEAT-006 agent registry's
    ``tmux_pane_id`` + ``tmux_socket_path`` (the design decision recorded
    on T059). A pane with no ``agent_id`` (never registered — e.g.
    ``failed`` at ``pane_create``) has no durable target, so kill is a
    no-op success (idempotent: "the pane is gone" is satisfied). A
    :class:`TmuxError` from ``kill-pane`` becomes ``{ok: False}`` so
    ``remove_pane`` can record ``tmux_kill_succeeded=False`` (it still
    archives the row — removal is not blocked on the kill).
    """
    env_map = dict(env if env is not None else os.environ)
    resolve_bench_user = bench_user_resolver or _default_bench_user_resolver(env_map)

    def kill(pane: ManagedPaneRow) -> dict[str, Any]:
        if not pane.agent_id:
            return {"ok": True}
        conn = agent_service.connection_factory()
        try:
            agent = _state_agents.select_agent_by_id(conn, agent_id=pane.agent_id)
        finally:
            conn.close()
        if agent is None:
            # Registry row already gone → nothing durable to target.
            return {"ok": True}
        try:
            adapter.kill_pane(
                container_id=pane.container_id,
                bench_user=resolve_bench_user(pane.container_id),
                socket_path=agent.tmux_socket_path,
                pane_id=agent.tmux_pane_id,
            )
            return {"ok": True}
        except TmuxError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.message}}

    return kill


def make_route_cleanup_backend(routes_service: Optional[Any]) -> CleanupFn:
    """Build the FR-010 ``route_cleanup_fn(pane)`` backend over FEAT-010.

    Removes every route that references the removed pane's agent in any
    role — ``source_scope_value`` / ``target_value`` / ``master_value``.
    FEAT-010 has no bulk "delete routes for agent" verb, so we
    ``list_routes`` then ``remove_route`` each match. Best-effort: a
    pane with no ``agent_id`` or an absent ``routes_service`` is a no-op,
    and a per-route ``RouteIdNotFound`` race is skipped (the caller —
    ``remove_pane`` — also wraps this in a best-effort guard).
    """

    def cleanup(pane: ManagedPaneRow) -> None:
        if not pane.agent_id or routes_service is None:
            return
        agent_id = pane.agent_id
        routes = routes_service.list_routes()
        for route in routes:
            if agent_id in (
                route.source_scope_value,
                route.target_value,
                route.master_value,
            ):
                try:
                    routes_service.remove_route(
                        route.route_id, deleted_by_agent_id=None
                    )
                except Exception:  # noqa: BLE001 — RouteIdNotFound race / best-effort
                    continue

    return cleanup


def make_log_detach_backend(log_service: "LogService") -> CleanupFn:
    """Build the FR-010 ``log_detach_fn(pane)`` backend over FEAT-007.

    Mirrors ``make_log_attach_backend``: detaches the pane's agent log
    follow by ``agent_id`` (the attachment is keyed by agent, not by a
    handle). Best-effort — a pane with no ``agent_id`` or an
    ``attachment_not_found`` (never attached / already detached) is a
    no-op (``remove_pane`` wraps this in a best-effort guard too).
    """

    def detach(pane: ManagedPaneRow) -> None:
        if not pane.agent_id:
            return
        log_service.detach_log({"agent_id": pane.agent_id}, socket_peer_uid=-1)

    return detach


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

        # Socket resolution can hit the adapter (resolve_uid → docker exec);
        # a TmuxError here must become a clean {ok: False} failure, NOT
        # propagate — TmuxError is a frozen dataclass and would raise
        # FrozenInstanceError if it bubbled through the spawn pipeline's
        # tx_guard contextmanager.
        try:
            socket_path = _socket_for(pane)
        except TmuxError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.message}}

        # FEAT-013 single-window layout: window_index=0 (built-in
        # templates are single-window; richer layouts are a later feature).
        params: dict[str, Any] = {
            "container_id": pane.container_id,
            "pane_composite_key": {
                "container_id": pane.container_id,
                "tmux_socket_path": socket_path,
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
    routes_service: Optional[Any] = None,
    bench_user_resolver: Optional[BenchUserResolver] = None,
    env: Optional[Mapping[str, str]] = None,
    profile_override_dir: Optional[Path] = None,
    launch_probe_delay_s: float = DEFAULT_LAUNCH_PROBE_DELAY_S,
) -> dict[str, Any]:
    """Assemble the production managed-session backends as the dict the
    daemon stores on ``DaemonContext.managed_spawn_backends``.

    Keys:

    * ``tmux_spawn`` / ``register`` / ``log_attach`` — the create/spawn
      pipeline (T028–T030 / T057), read by ``kickoff_spawn_pipeline``.
    * ``session_conflict`` — the FR-016 synchronous conflict pre-check
      (T057b), read by the M1 handlers.
    * ``tmux_kill`` / ``route_cleanup`` / ``log_detach`` — the FR-010
      remove-pane side-effect backends (T059), read by the M6 handlers.

    ``routes_service`` is optional; when ``None`` the ``route_cleanup``
    backend is a no-op (routes can't be reached without it).
    """
    return {
        "tmux_spawn": make_tmux_spawn_backend(
            adapter=adapter,
            bench_user_resolver=bench_user_resolver,
            env=env,
            profile_override_dir=profile_override_dir,
            launch_probe_delay_s=launch_probe_delay_s,
        ),
        "register": make_register_backend(
            agent_service,
            adapter=adapter,
            bench_user_resolver=bench_user_resolver,
            env=env,
        ),
        "log_attach": make_log_attach_backend(log_service),
        "session_conflict": make_session_conflict_checker(
            adapter=adapter,
            bench_user_resolver=bench_user_resolver,
            env=env,
        ),
        "tmux_kill": make_tmux_kill_backend(
            adapter=adapter,
            agent_service=agent_service,
            bench_user_resolver=bench_user_resolver,
            env=env,
        ),
        "route_cleanup": make_route_cleanup_backend(routes_service),
        "log_detach": make_log_detach_backend(log_service),
    }


__all__ = [
    "BenchUserResolver",
    "build_spawn_backends",
    "make_log_attach_backend",
    "make_log_detach_backend",
    "make_recovery_list_panes_channel",
    "make_register_backend",
    "make_route_cleanup_backend",
    "make_session_conflict_checker",
    "make_tmux_kill_backend",
    "make_tmux_spawn_backend",
]
