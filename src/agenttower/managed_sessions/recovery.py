"""FEAT-013 daemon-boot recovery (T046 / T047 / T049).

Reconciles durable ``managed_layout`` / ``managed_pane`` rows against
live tmux panes after a daemon restart. Reattaches surviving panes;
transitions unreachable rows to ``failed`` with
``failed_stage = recovery_reattach``. Per spec §FR-020 + §SC-008 +
contracts/state-machine.md §Recovery.

Pluggable backend: ``TmuxListPanesFn``. Production wiring constructs a
backend that invokes ``tmux list-panes`` through the FEAT-004 docker-exec
channel; tests pass canned dicts. Same injection pattern as
``service.spawn_layout_in_background``'s tmux/register/log backends.

Recovery rules (from state-machine.md §Recovery, step 3):

1. Load every ``managed_layout`` + ``managed_pane`` row where
   ``state IN ('creating', 'ready', 'degraded')``. Group panes by
   ``container_id`` so the tmux list-panes RPC fires once per container.

2. For each container, invoke ``tmux_list_panes_fn(container_id)`` and
   match against the stored panes by
   ``(tmux_session_name, tmux_pane_index)``:

   - **Match** (pane is alive in tmux):
     - ``creating`` + marker still set + age < TTL → left in ``creating``.
       review #11: the original spawn thread died with the previous
       daemon process and is NOT re-driven at boot (re-running the spawn
       pipeline would re-issue ``new-session``/``split-window`` against a
       pane that already exists). The row is kept in ``creating`` only
       until its marker ages past the TTL, at which point the periodic
       ``pending_marker.sweep`` transitions it to ``failed``. (Driving an
       alive-but-unregistered pane through register/log-attach only — a
       true continuation — is a tracked follow-up, not a boot behavior.)
     - ``creating`` + marker still set + age ≥ TTL → move to ``failed``
       with ``failed_stage = recovery_reattach``.
     - ``ready`` / ``degraded`` → keep state, emit
       ``managed_layout_recovery_reattached``.
   - **No match** (pane gone from tmux): move to ``failed`` with
     ``failed_stage = recovery_reattach``; emit
     ``managed_layout_recovery_failed``.

3. After all containers processed, recompute aggregate layout state via
   ``state_machine.aggregate_layout_state`` and write the layout row.

4. Drop ``pending_marker_token`` on any row that transitioned out of
   ``creating`` (CHECK constraint invariant).

T047 daemon-boot wiring: the daemon calls ``reconcile(...)`` BEFORE the
FEAT-002 socket starts accepting requests (SC-008 + SC-009 budget the
reattach + visibility within 5 seconds of socket-ready). Per-container
locks are held for the duration of the reconcile so concurrent operator
requests can't race — but in practice the lock is uncontended because
the socket isn't open yet.

T049 detail-surface readability: M3 (``app.managed_layout_detail``) +
M5 (``app.managed_pane_detail``) already surface ``failed_stage`` in
their payloads (per Phase 4a's handler wiring), so once the reconcile
writes ``state=failed`` + ``failed_stage=recovery_reattach`` via
``dao.update_pane_state``, the detail surfaces round-trip the recovery
outcome without extra plumbing. The test for SC-009 is in
``tests/contract/test_managed_recovery_visibility.py``.
"""

from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ._tx import tx_guard
from .dao import (
    ManagedPaneRow,
    select_non_terminal_layouts,
    select_non_terminal_panes_for_container,
    select_panes_for_layout,
    update_layout_state,
    update_pane_state,
)
from .events import (
    LAYOUT_RECOVERY_FAILED,
    LAYOUT_RECOVERY_REATTACHED,
    PANE_PENDING_MARKER_CLEARED,
    PANE_STATE_CHANGED,
    build_event,
)
from .pending_marker import MARKER_TTL_SECONDS
from .serializer import ContainerSerializer
from .state_machine import FailedStage, ManagedState, aggregate_layout_state


LOG = logging.getLogger(__name__)


# Backend protocol — same shape as the spawn task's injectable backends.
# Returns a sequence of dicts describing live panes in the container:
#   [{"tmux_session_name": "...", "tmux_pane_index": int}, ...]
# Production wires this to tmux_create.list_panes_for_container through
# the FEAT-004 docker-exec channel.
TmuxListPanesFn = Callable[[str], list[dict[str, object]]]


# Event emitter — same signature as ``service.EventEmitter``.
EventEmitter = Callable[[dict[str, object]], None]


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    """Summary of one reconcile pass."""

    layouts_examined: int
    panes_examined: int
    panes_reattached: int           # state preserved (ready/degraded)
    panes_failed: int               # transitioned to failed (recovery_reattach)
    panes_resumed_creating: int     # creating + marker fresh (let spawn continue)
    # review P2#6/P2#7: containers whose list-panes RPC raised (transient
    # docker/tmux failure). Their rows were left untouched for the next
    # reconcile; surfaced so ``status`` can report a degraded boot recovery
    # instead of it looking like "nothing to recover".
    containers_skipped: int = 0


def reconcile(
    *,
    conn: sqlite3.Connection,
    serializer: ContainerSerializer,
    tmux_list_panes_fn: TmuxListPanesFn,
    event_emitter: Optional[EventEmitter] = None,
    clock: Optional[Callable[[], _dt.datetime]] = None,
    tx_lock: Optional[threading.Lock] = None,
) -> ReconcileOutcome:
    """Boot-time recovery reconcile (T046).

    See module docstring for the full rules. Returns a
    :class:`ReconcileOutcome` summary so the daemon-boot wiring can log
    the reconcile result + so tests can assert specific counts.

    Idempotent — a second call on a stable tree is a no-op (all
    non-terminal rows are already either reattached or transitioned to
    failed).
    """
    with tx_guard(tx_lock):
        layouts = select_non_terminal_layouts(conn)
    layouts_by_container: dict[str, set[str]] = {}
    for layout in layouts:
        layouts_by_container.setdefault(layout.container_id, set()).add(layout.id)

    panes_reattached = 0
    panes_failed = 0
    panes_resumed = 0
    panes_seen = 0
    containers_skipped = 0

    # Layout-scoped events accumulate per-layout so a single
    # LAYOUT_RECOVERY_REATTACHED / LAYOUT_RECOVERY_FAILED can carry the
    # right pane-id list per state-machine.md §Recovery.
    reattached_pane_ids_by_layout: dict[str, list[str]] = {}
    failed_pane_ids_by_layout: dict[str, list[str]] = {}

    for container_id, _layout_ids in layouts_by_container.items():
        lock = serializer.for_container(container_id)
        with lock:
            with tx_guard(tx_lock):
                panes = select_non_terminal_panes_for_container(conn, container_id)
            if not panes:
                continue

            # Build the live-tmux set for the container. The list-panes
            # RPC happens OUTSIDE tx_lock so its docker-exec latency
            # doesn't block FEAT-009 worker writes.
            #
            # review #7: a raising list-panes (transient docker/tmux
            # failure) must SKIP this container only — not abort the whole
            # reconcile. If it propagated, containers already processed in
            # this loop would keep their committed pane->failed transitions
            # (each container's pane transitions + layout-aggregate recompute
            # commit atomically below), and aborting here would skip every
            # not-yet-processed container, leaving their managed_layout.state
            # inconsistent with reality (FR-026 / SC-009). Skipping leaves
            # this container's rows untouched for the next reconcile.
            try:
                live = tmux_list_panes_fn(container_id)
            except Exception as exc:  # noqa: BLE001 — fail-soft per container
                # review P2#7: include the exception class + message so a
                # docker/tmux outage during boot recovery is diagnosable
                # without re-deriving it from a bare container id, and count
                # the skip so ``status`` (review P2#6) can report degraded
                # recovery rather than silent "nothing to do".
                containers_skipped += 1
                LOG.warning(
                    "managed_sessions: reconcile list-panes failed for "
                    "container=%s; skipping (rows untouched): %s: %s",
                    container_id,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                continue
            live_keys: set[tuple[str, int]] = set()
            for entry in live:
                session = str(entry.get("tmux_session_name", ""))
                pane_index = int(entry.get("tmux_pane_index", -1))
                if session and pane_index >= 0:
                    live_keys.add((session, pane_index))

            # review P1: per-container pane-state transitions AND the
            # layout aggregate recompute commit together in ONE
            # BEGIN IMMEDIATE. Splitting them across transactions opens a
            # crash window: if the daemon dies (or the DB write fails)
            # after the pane transaction commits but before the layout
            # write, panes are left ``failed``/``recovery_reattach`` while
            # the layout stays ``ready``/``creating`` — and a later
            # reconcile can't repair it, because already-``failed`` panes
            # are excluded from the non-terminal recovery query
            # (state-machine.md §Recovery, FR-026 / SC-009).
            container_changed_layouts: set[str] = set()
            with tx_guard(tx_lock):
                # Close any caller-side implicit tx (e.g. test fixture
                # INSERTs that didn't commit) so our explicit
                # BEGIN IMMEDIATE is the only open transaction.
                if conn.in_transaction:
                    conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for pane in panes:
                        panes_seen += 1
                        pane_key = (pane.tmux_session_name, pane.tmux_pane_index)
                        disposition = _classify(pane, pane_key in live_keys, clock=clock)
                        if disposition is _RECOVERY_RESUME_CREATING:
                            panes_resumed += 1
                            continue
                        if disposition is _RECOVERY_REATTACHED:
                            reattached_pane_ids_by_layout.setdefault(
                                pane.layout_id, []
                            ).append(pane.id)
                            panes_reattached += 1
                            container_changed_layouts.add(pane.layout_id)
                            continue
                        # _RECOVERY_FAILED: transition to failed (recovery_reattach).
                        _transition_to_failed_reattach(
                            conn=conn,
                            pane=pane,
                            event_emitter=event_emitter,
                            clock=clock,
                        )
                        failed_pane_ids_by_layout.setdefault(
                            pane.layout_id, []
                        ).append(pane.id)
                        panes_failed += 1
                        container_changed_layouts.add(pane.layout_id)
                    # Recompute + persist each touched layout's aggregate
                    # state INSIDE the same transaction (review P1). The
                    # reads here see the pane UPDATEs above because they
                    # share this open BEGIN IMMEDIATE; a layout belongs to
                    # exactly one container, so every pane of a changed
                    # layout was just transitioned in this loop.
                    for layout_id in container_changed_layouts:
                        refreshed = select_panes_for_layout(conn, layout_id)
                        if not refreshed:
                            continue
                        new_state = aggregate_layout_state(
                            [p.state for p in refreshed]
                        )
                        layout_failed_stage: Optional[FailedStage] = (
                            FailedStage.RECOVERY_REATTACH
                            if new_state == ManagedState.FAILED
                            else None
                        )
                        update_layout_state(
                            conn,
                            layout_id,
                            state=new_state,
                            failed_stage=layout_failed_stage,
                            now=_utc_now_rfc3339(clock),
                        )
                    conn.execute("COMMIT")
                except Exception:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise

            # review P2: emit layout-scoped JSONL events only AFTER the
            # combined pane+aggregate transaction commits, so a crash
            # before COMMIT never leaves a recovery event on disk
            # describing an outcome that was rolled back.
            if event_emitter is not None:
                for layout_id in container_changed_layouts:
                    if reattached_pane_ids_by_layout.get(layout_id):
                        event_emitter(
                            build_event(
                                LAYOUT_RECOVERY_REATTACHED,
                                actor="daemon",
                                layout_id=layout_id,
                                sequence=10_000,
                                payload={
                                    "reattached_pane_ids": list(
                                        reattached_pane_ids_by_layout[layout_id]
                                    ),
                                },
                            )
                        )
                    if failed_pane_ids_by_layout.get(layout_id):
                        event_emitter(
                            build_event(
                                LAYOUT_RECOVERY_FAILED,
                                actor="daemon",
                                layout_id=layout_id,
                                sequence=10_001,
                                payload={
                                    "failed_pane_ids": list(
                                        failed_pane_ids_by_layout[layout_id]
                                    ),
                                    "failed_stage": FailedStage.RECOVERY_REATTACH.value,
                                },
                            )
                        )

    return ReconcileOutcome(
        layouts_examined=len(layouts),
        panes_examined=panes_seen,
        panes_reattached=panes_reattached,
        panes_failed=panes_failed,
        panes_resumed_creating=panes_resumed,
        containers_skipped=containers_skipped,
    )


# ─── classification helpers ─────────────────────────────────────────────


_RECOVERY_RESUME_CREATING = object()
_RECOVERY_REATTACHED = object()
_RECOVERY_FAILED = object()


def _classify(
    pane: ManagedPaneRow,
    matched_in_tmux: bool,
    *,
    clock: Optional[Callable[[], _dt.datetime]] = None,
) -> object:
    """Apply state-machine.md §Recovery rules to one pane.

    Returns one of the three sentinels above.
    """
    if not matched_in_tmux:
        # No live tmux pane backs this row → failed (recovery_reattach).
        return _RECOVERY_FAILED

    # Matched — apply per-state rules.
    if pane.state in (ManagedState.READY, ManagedState.DEGRADED):
        return _RECOVERY_REATTACHED

    if pane.state == ManagedState.CREATING:
        # Check marker TTL. If marker is fresh (<TTL), leave in creating
        # (NOT re-driven at boot — review #11; the TTL sweep will fail it
        # if it never settles). If stale, move to failed now.
        if pane.pending_marker_token is None:
            # Defensive — creating without a marker is a bug. Treat as
            # failed so we don't loop.
            return _RECOVERY_FAILED
        if _marker_is_stale(pane, clock=clock):
            return _RECOVERY_FAILED
        return _RECOVERY_RESUME_CREATING

    # Defensive fallback — shouldn't reach here because
    # select_non_terminal_panes_for_container filters to
    # creating/ready/degraded.
    return _RECOVERY_FAILED


def _marker_is_stale(
    pane: ManagedPaneRow,
    *,
    clock: Optional[Callable[[], _dt.datetime]] = None,
) -> bool:
    """Return True iff the pane's pending marker is older than the
    FR-022 TTL (5 minutes). Uses ``pane.created_at`` as the marker's
    birth time per research §R5 (the marker is set on row insert).
    """
    try:
        created = _dt.datetime.fromisoformat(pane.created_at.replace("Z", "+00:00"))
    except ValueError:
        # Malformed timestamp → treat as stale to be safe (the row is
        # broken anyway).
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=_dt.UTC)
    now = (clock() if clock is not None else _dt.datetime.now(_dt.UTC))
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.UTC)
    age = (now - created).total_seconds()
    return age >= MARKER_TTL_SECONDS


def _transition_to_failed_reattach(
    *,
    conn: sqlite3.Connection,
    pane: ManagedPaneRow,
    event_emitter: Optional[EventEmitter],
    clock: Optional[Callable[[], _dt.datetime]],
) -> None:
    """Apply the ``recovery_reattach`` transition + emit per-pane events."""
    now = _utc_now_rfc3339(clock)
    prior = pane.state
    update_pane_state(
        conn, pane.id,
        state=ManagedState.FAILED,
        failed_stage=FailedStage.RECOVERY_REATTACH,
        clear_marker=True,  # marker cleared regardless of prior state
        now=now,
    )
    if event_emitter is not None:
        if pane.pending_marker_token is not None:
            event_emitter(
                build_event(
                    PANE_PENDING_MARKER_CLEARED,
                    actor="daemon",
                    pane_id=pane.id,
                    sequence=9_000,
                    payload={"marker_token": pane.pending_marker_token},
                )
            )
        event_emitter(
            build_event(
                PANE_STATE_CHANGED,
                actor="daemon",
                layout_id=pane.layout_id,
                pane_id=pane.id,
                sequence=9_001,
                payload={
                    "prev_state": prior.value,
                    "new_state": ManagedState.FAILED.value,
                    "failed_stage": FailedStage.RECOVERY_REATTACH.value,
                },
            )
        )


def _utc_now_rfc3339(clock: Optional[Callable[[], _dt.datetime]] = None) -> str:
    """Mirror of service.py's helper — recovery.py keeps its own copy to
    avoid importing service.py (which would create a cycle with the
    spawn-pipeline imports)."""
    if clock is None:
        ts = _dt.datetime.now(_dt.UTC)
    else:
        ts = clock()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.UTC)
    return ts.isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "reconcile",
    "ReconcileOutcome",
    "TmuxListPanesFn",
    "EventEmitter",
]
