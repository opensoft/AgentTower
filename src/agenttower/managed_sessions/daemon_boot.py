"""FEAT-013 daemon-boot wiring (Workstream 1 / C4 + C6).

Bundles the four follow-ups previously documented in module docstrings:

1. Build the per-container :class:`ContainerSerializer` (FR-019).
2. Build the production spawn backends (tmux + register + log-attach)
   via :mod:`spawn_backends`.
3. Run :func:`recovery.reconcile` BEFORE the daemon's socket accepts
   requests (SC-008 + SC-009).
4. Register :func:`pending_marker.sweep` on a 60-second periodic
   :class:`threading.Timer` so FR-022 TTL fires cumulatively.

Plus the handler-side kick-off helper :func:`kickoff_spawn_pipeline`
that ``handlers/cli.py`` and ``handlers/app.py`` call after
``create_layout`` returns successfully — runs ``spawn_layout_in_background``
in a daemon thread so the synchronous response time stays bounded by
the row-insert latency, not the tmux RPC chain.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Any, Callable, Optional

from . import pending_marker, recovery
from .serializer import ContainerSerializer
from .service import spawn_layout_in_background
from .tmux_create import TIMEOUT_SECONDS as STAGE_TIMEOUT_SECONDS


LOG = logging.getLogger(__name__)


# Type aliases re-exported for the daemon module to consume without
# importing service.py's internal alias names.
TmuxSpawnBackend = Callable[..., Any]
RegisterAgentBackend = Callable[..., Any]
LogAttachBackend = Callable[..., Any]
TmuxKillBackend = Callable[..., Any]
CleanupBackend = Callable[..., Any]
TmuxListPanesBackend = Callable[..., Any]


def make_managed_serializer() -> ContainerSerializer:
    """Construct the per-container ``threading.Lock`` map.

    Called once at daemon boot. Stored on ``DaemonContext.managed_serializer``.
    The same instance is shared by every FEAT-013 service entry point
    so a single bench container always serializes through the same
    lock (FR-019).
    """
    return ContainerSerializer()


def reconcile_managed_state_at_boot(
    *,
    conn: sqlite3.Connection,
    serializer: ContainerSerializer,
    tmux_list_panes_fn: Optional[Callable[[str], list[dict[str, object]]]],
    tx_lock: Optional[threading.Lock],
    event_emitter: Optional[Callable[[dict[str, object]], None]] = None,
) -> Optional[Any]:
    """Run the FR-020 / SC-008 reconcile BEFORE the socket opens.

    Returns the :class:`recovery.ReconcileOutcome` summary so the
    daemon can log it (and so ``app.status`` can surface it as part of
    diagnostics).

    If ``tmux_list_panes_fn`` is None, the reconcile is skipped — this
    is the safe-fail default during initial daemon-boot wiring when
    the production tmux backend isn't ready. Without a real
    list-panes channel, reconcile cannot distinguish surviving panes
    from dead ones, so the right action is to leave the rows alone
    and let the next operator action surface failures.
    """
    if tmux_list_panes_fn is None:
        LOG.info(
            "managed_sessions: skipping boot reconcile — no "
            "tmux_list_panes backend wired"
        )
        return None
    try:
        outcome = recovery.reconcile(
            conn=conn,
            serializer=serializer,
            tmux_list_panes_fn=tmux_list_panes_fn,
            event_emitter=event_emitter,
            tx_lock=tx_lock,
        )
    except Exception:  # noqa: BLE001 — fail-soft at boot: log and continue
        LOG.exception("managed_sessions: boot reconcile raised; continuing")
        return None
    LOG.info(
        "managed_sessions: boot reconcile complete — "
        "layouts=%d panes=%d reattached=%d failed=%d resumed=%d",
        outcome.layouts_examined,
        outcome.panes_examined,
        outcome.panes_reattached,
        outcome.panes_failed,
        outcome.panes_resumed_creating,
    )
    return outcome


def start_pending_marker_sweep(
    *,
    conn: sqlite3.Connection,
    tx_lock: Optional[threading.Lock],
    shutdown_event: threading.Event,
    interval_seconds: float = float(pending_marker.SWEEP_INTERVAL_SECONDS),
) -> Callable[[], None]:
    """Schedule the FR-022 5-minute TTL sweep on a ``threading.Timer``.

    Returns a zero-argument cancel function the daemon's shutdown
    path calls to stop the timer cleanly. Subsequent calls to the
    returned cancel function are no-ops.

    Design choice: ``threading.Timer`` over a dedicated thread with a
    ``time.sleep(interval)`` loop because the daemon already owns
    shutdown signaling via ``shutdown_event`` — a one-shot Timer that
    re-arms itself respects the event without polling. A long sleep
    would block shutdown for up to the interval.
    """
    timer_holder: dict[str, Optional[threading.Timer]] = {"timer": None}

    def tick() -> None:
        if shutdown_event.is_set():
            return
        try:
            outcome = pending_marker.sweep(conn, tx_lock=tx_lock)
            if outcome.panes_swept > 0:
                LOG.info(
                    "managed_sessions: sweep transitioned "
                    "%d stale creating row(s) to failed "
                    "(pane_create=%d registration=%d)",
                    outcome.panes_swept,
                    outcome.pane_create_failures,
                    outcome.registration_failures,
                )
        except Exception:  # noqa: BLE001 — never let a sweep crash leak
            LOG.exception("managed_sessions: sweep raised; rescheduling")
        # Re-arm only if shutdown hasn't been requested in the meantime.
        if not shutdown_event.is_set():
            t = threading.Timer(interval_seconds, tick)
            t.daemon = True
            t.name = "feat013-pending-marker-sweep"
            timer_holder["timer"] = t
            t.start()

    # Initial tick — first scheduled invocation happens after one
    # ``interval_seconds`` window so we don't race the boot reconcile
    # (which runs SYNCHRONOUSLY before this function is called).
    first = threading.Timer(interval_seconds, tick)
    first.daemon = True
    first.name = "feat013-pending-marker-sweep"
    timer_holder["timer"] = first
    first.start()

    cancelled = [False]

    def cancel() -> None:
        if cancelled[0]:
            return
        cancelled[0] = True
        t = timer_holder["timer"]
        if t is not None:
            try:
                t.cancel()
            except Exception:  # noqa: BLE001 — defensive on shutdown
                pass

    return cancel


def kickoff_spawn_pipeline(
    *,
    layout_id: str,
    ctx: Any,
) -> None:
    """Start the background spawn pipeline for a freshly-created layout.

    Called by the M1 handler immediately after ``create_layout``
    returns success. Pulls the backends + tx_lock + serializer from
    the daemon context and kicks off a daemon thread running
    ``spawn_layout_in_background``.

    Fails silently (with a log line) if any required ctx field is
    None — i.e. when FEAT-013 hasn't been fully boot-wired. In that
    state ``managed.layout.create`` still returns a valid
    ``creating``-state row, but the row never transitions out of
    ``creating``. The next daemon restart's reconcile + sweep will
    eventually transition it to ``failed`` with
    ``failed_stage=recovery_reattach`` or ``pane_create``.
    """
    backends = getattr(ctx, "managed_spawn_backends", None)
    serializer = getattr(ctx, "managed_serializer", None)
    conn = getattr(ctx, "state_conn", None)
    tx_lock = getattr(ctx, "state_tx_lock", None)
    if backends is None or serializer is None or conn is None:
        LOG.warning(
            "managed_sessions: skipping spawn pipeline kick-off for "
            "layout_id=%s — daemon-boot wiring incomplete "
            "(backends=%s serializer=%s conn=%s)",
            layout_id,
            backends is not None,
            serializer is not None,
            conn is not None,
        )
        return

    # The lifecycle audit writer (when wired) is the event emitter.
    audit = getattr(ctx, "queue_audit_writer", None)
    event_emitter = None
    if audit is not None and hasattr(audit, "append_managed_event"):
        event_emitter = audit.append_managed_event  # type: ignore[assignment]

    def _run() -> None:
        try:
            spawn_layout_in_background(
                layout_id,
                conn=conn,
                serializer=serializer,
                tmux_spawn_fn=backends["tmux_spawn"],
                register_fn=backends["register"],
                log_attach_fn=backends["log_attach"],
                event_emitter=event_emitter,
                tx_lock=tx_lock,
                # FR-013: enforce the 30s per-stage timeout in production
                # (a hung docker exec must not hold the per-container lock
                # forever). Direct test callers default to None to avoid
                # cross-thread issues with in-memory SQLite.
                stage_timeout_seconds=STAGE_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001 — never let a bg crash leak
            LOG.exception(
                "managed_sessions: spawn pipeline raised for layout_id=%s",
                layout_id,
            )

    thread = threading.Thread(
        target=_run,
        name=f"feat013-spawn-{layout_id[:8]}",
        daemon=True,
    )
    thread.start()


__all__ = [
    "STAGE_TIMEOUT_SECONDS",
    "kickoff_spawn_pipeline",
    "make_managed_serializer",
    "reconcile_managed_state_at_boot",
    "start_pending_marker_sweep",
]
