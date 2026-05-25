"""FEAT-013 spawn-backend factory (T028 / T029 / T030 production wiring).

The background spawn task (``service.spawn_layout_in_background``) takes
three **injectable Callable backends** so it can be unit-tested without
a real bench container:

    TmuxSpawnFn:     (pane) -> {ok, tmux_pane_id, launch_alive, ...}
    RegisterAgentFn: (pane, tmux_pane_id) -> {ok, agent_id}
    LogAttachFn:     (pane, agent_id) -> {ok}

This module is the production-side factory: at daemon boot, the daemon
constructs concrete backends from the existing FEAT-006 / FEAT-007 /
FEAT-004 surfaces and stores them on ``DaemonContext`` so the
``managed.layout.create`` / ``app.managed_layout_create`` handler can
kick off the background task with real backends.

**Status (Phase 4c)**: the **register** + **log-attach** backends below
are implemented as thin wrappers around ``AgentService.register_agent``
and ``LogService.attach_log`` and are ready for daemon-boot wiring. The
**tmux spawn** backend is a stub that returns ``ok=False`` with an
explanatory error code so the spawn pipeline can't accidentally succeed
against a non-existent tmux session; the real backend lives in
``tmux_create.py`` (T011 — already implemented) but requires the
FEAT-004 docker-exec channel + a running bench container to actually
spawn panes. Concrete tmux wiring + daemon-boot integration are
follow-up work (the existing test_story1 integration tests stay skipped
pending this wiring per the N34 sub-scope split).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .dao import ManagedPaneRow
from .service import (
    LogAttachFn,
    RegisterAgentFn,
    TmuxSpawnFn,
)

if TYPE_CHECKING:
    from ..agents.service import AgentService
    from ..logs.service import LogService


# ─── Register backend (T029) ────────────────────────────────────────────


def make_register_backend(agent_service: "AgentService") -> RegisterAgentFn:
    """Build a ``RegisterAgentFn`` from a FEAT-006 ``AgentService``.

    The returned callable invokes ``register_agent`` with the FEAT-006
    ``pane_composite_key`` shape, passes the managed pane's role /
    capability / label, and returns either:

        {"ok": True, "agent_id": <newly-registered agent id>}
        {"ok": False, "error": {"code": <FEAT-006 code>, "message": <prose>}}

    Maps every FEAT-006 ``RegistrationError`` to its closed-set code so
    ``service.spawn_layout_in_background`` can categorize the failure
    cleanly via the FR-013 ``failed_stage = registration`` path.

    The ``container_id`` + tmux composite key are read off the pane row
    that the spawn task just inserted; the ``tmux_socket_path`` defaults
    to the FEAT-004 canonical path inside the bench container's tmpfs
    (``/tmp/tmux-<uid>/default``) and the ``tmux_window_index`` is hard-
    coded to 0 because the FEAT-013 template currently lays out a single
    window per session.
    """

    def register(pane: ManagedPaneRow, tmux_pane_id: str) -> dict[str, Any]:
        from ..agents.errors import RegistrationError

        # FEAT-013 single-window layout: window_index=0 (templates may
        # extend later but the current built-ins are single-window).
        params: dict[str, Any] = {
            "container_id": pane.container_id,
            "pane_composite_key": {
                "container_id": pane.container_id,
                # tmux_socket_path is the path used by `tmux -S <path>`
                # inside the bench container's tmpfs. FEAT-004 enumerates
                # these via its socket-listing step; the spawn task knows
                # which one it spawned into, but the current spawn
                # backend stub doesn't surface it back. Once the tmux
                # backend is wired (follow-up), it should be returned in
                # the spawn result and threaded through to here.
                "tmux_socket_path": "/tmp/tmux-default/default",
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
            outcome = agent_service.register_agent(
                params, socket_peer_uid=-1
            )
        except RegistrationError as exc:
            return {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
            }
        agent_payload = outcome.get("agent") if isinstance(outcome, dict) else None
        if isinstance(agent_payload, dict) and "agent_id" in agent_payload:
            return {"ok": True, "agent_id": agent_payload["agent_id"]}
        # Defensive — FEAT-006 returns a different shape than expected.
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
    and the canonical default log path (FEAT-007 FR-005 default — the
    caller can override later via ``managed.pane.attach_log`` if needed).
    Returns ``{"ok": True}`` on success or ``{"ok": False, "error": ...}``
    on failure; the spawn task maps failure to
    ``failed_stage = log_attach`` via the ``degraded`` transition.
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


# ─── Tmux spawn backend (T011 wiring — placeholder) ─────────────────────


def make_tmux_spawn_backend(
    *, docker_exec_channel: Any = None, marker_writer: Any = None,
) -> TmuxSpawnFn:
    """Build a ``TmuxSpawnFn`` from the FEAT-004 docker-exec channel +
    the FEAT-013 pending-marker writer.

    **Phase 4c status**: This factory is a placeholder. The full tmux-
    spawn implementation lives in ``tmux_create.py`` (T011 — already
    written) and ``pending_marker.py`` (T012 — already written), but
    they need to be composed and wired against the docker-exec channel
    that FEAT-004's ``TmuxAdapter`` exposes. That composition + the
    FEAT-004 list-sessions pre-check (T034 follow-up — `Q6 / FR-016`
    `managed_session_name_conflict`) are the remaining production gates.

    The returned callable currently returns a deterministic failure so
    the spawn pipeline can't accidentally succeed against a non-wired
    tmux backend: ``{"ok": False, "error": {"code": "not_implemented",
    "message": "production tmux spawn backend is wired by a follow-up;
    use a test fake for now"}}``. Once T011 + T012 + the docker-exec
    channel are composed here, this body should:

        1. Resolve the operator's launch_profile YAML (R9).
        2. Set the pending-managed marker title via tmux_create
           (``@MANAGED:<token>:<label>``).
        3. Invoke ``tmux new-session -d -s <name> -- <argv>`` (for the
           first pane in a layout) or ``tmux split-window -t ... -- <argv>``
           (for subsequent panes), through the docker-exec channel.
        4. Observe the pane post-spawn (e.g., wait 1s + check the launch
           process is still alive) and return ``launch_alive`` accordingly.
        5. Return the tmux pane id (``%N``) that the spawn-task will
           pass into the register backend.
    """

    def spawn(pane: ManagedPaneRow) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": "not_implemented",
                "message": (
                    "production tmux spawn backend wiring is a follow-up "
                    "(compose tmux_create.py + pending_marker.py + FEAT-004 "
                    "docker-exec channel). Use a test fake for now."
                ),
            },
        }

    return spawn


# ─── Convenience: assemble all three from DaemonContext ─────────────────


def make_default_backends(
    *,
    agent_service: "AgentService",
    log_service: "LogService",
    docker_exec_channel: Any = None,
) -> tuple[TmuxSpawnFn, RegisterAgentFn, LogAttachFn]:
    """Assemble the three concrete backends from the existing services.

    Daemon-boot wiring (follow-up): call this once at boot and store
    the resulting tuple on ``DaemonContext.managed_spawn_backends``. The
    ``managed.layout.create`` handler reads the tuple off ctx and passes
    them to ``service.spawn_layout_in_background`` started in a
    ``threading.Thread`` after the synchronous ``create_layout`` returns.
    """
    return (
        make_tmux_spawn_backend(docker_exec_channel=docker_exec_channel),
        make_register_backend(agent_service),
        make_log_attach_backend(log_service),
    )


__all__ = [
    "make_register_backend",
    "make_log_attach_backend",
    "make_tmux_spawn_backend",
    "make_default_backends",
]
