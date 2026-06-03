"""FEAT-013 pending-managed marker (T012 + T050).

Tracks ``managed_pane`` rows mid-creation via:

* SQLite — the ``managed_pane.pending_marker_token TEXT NULL`` column
  (set on row insert before tmux spawn; cleared on transition to ``ready``).
* Tmux pane title — ``@MANAGED:<token>:<label>`` set via ``tmux select-pane -T``
  immediately before the spawning ``new-session`` / ``split-window`` call.
  Visible to FEAT-004's ``list-panes -F '#{pane_title}'`` formatter so the
  scan can skip pending-managed panes without modification.

Per FR-022 (research §R5), markers older than 5 minutes are swept:
``managed_pane`` rows still in ``state='creating'`` are transitioned to
``failed`` with ``failed_stage='pane_create'`` (no tmux pane) or
``'registration'`` (tmux pane exists but never registered). The sweep
runs at boot and every 60 seconds.

Daemon-boot wiring (T050): ``sweep(conn, clock)`` below is the function
the daemon's periodic task scheduler invokes every 60 seconds. The
scheduler integration itself (registering the task with the daemon's
existing `run_periodic(...)` infrastructure) is the same kind of follow-
up as the spawn-backends daemon-boot wiring from Phase 4c — both are
small daemon.py modifications outside FEAT-013's natural scope. Tests
exercise `sweep` directly.

This module exposes the data-shape constants + sweep + parse helpers.
The SQLite read/write side is owned by ``service.py`` (T022) +
``recovery.py`` (T046); the tmux title side is owned by ``tmux_create.py``
(T011).
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Final, Optional

from ._tx import tx_guard
from .state_machine import ManagedState, aggregate_layout_state

# Marker TTL — research §R5, codified in FR-022.
MARKER_TTL_SECONDS: Final[int] = 5 * 60

# Periodic sweep cadence (research §R5: "boot + 60s periodic").
SWEEP_INTERVAL_SECONDS: Final[int] = 60

# Tmux pane-title prefix that the FEAT-004 scan skips on.
MARKER_TITLE_PREFIX: Final[str] = "@MANAGED:"

# Regex for parsing a tmux pane title set by this module:
#   ``@MANAGED:<token>:<label>``
# ``<token>`` is a uuid4 string (or an operator-supplied idempotency_key
# per research §R10). ``<label>`` is the human-readable pane label
# (FR-003).
_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"^@MANAGED:(?P<token>[^:]+):(?P<label>.+)$"
)


def new_marker_token() -> str:
    """Return a fresh marker token (uuid4 string).

    Service callers use the operator-supplied ``idempotency_key`` when
    present (research §R10 collapses dedupe-key and marker-token into a
    single identifier); this helper is the fallback.
    """
    return str(uuid.uuid4())


def format_title(token: str, label: str) -> str:
    """Build the tmux pane title for a pending-managed pane.

    Service callers set this title via ``tmux select-pane -T <title>``
    BEFORE the spawning ``new-session`` / ``split-window`` call so the
    FEAT-004 scan never sees a pane without the marker.
    """
    if not token:
        raise ValueError("token must be non-empty")
    if not label:
        raise ValueError("label must be non-empty")
    if ":" in token:
        raise ValueError("token must not contain ':'")
    return f"{MARKER_TITLE_PREFIX}{token}:{label}"


def parse_title(title: str) -> tuple[str, str] | None:
    """Return ``(token, label)`` if ``title`` is a marker title, else ``None``.

    The FEAT-004 scan calls this on every observed tmux pane title; a
    non-``None`` return value means "this pane belongs to an in-flight
    managed creation — skip adoption" (FR-014).
    """
    match = _TITLE_RE.match(title)
    if match is None:
        return None
    return match.group("token"), match.group("label")


def is_marker_title(title: str) -> bool:
    """Convenience: True iff ``title`` is a marker title."""
    return parse_title(title) is not None


# ─── Sweep (T050 — Phase 6) ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SweepOutcome:
    """Summary of one sweep pass."""

    panes_examined: int        # creating-state rows with a non-null marker
    panes_swept: int           # transitioned to failed by this sweep
    pane_create_failures: int  # transitioned with failed_stage=pane_create
    registration_failures: int # transitioned with failed_stage=registration


def sweep(
    conn: sqlite3.Connection,
    *,
    clock: Optional[Callable[[], _dt.datetime]] = None,
    tx_lock: Optional[threading.Lock] = None,
) -> SweepOutcome:
    """FR-022 / R5 — sweep stale pending-managed markers.

    Scans ``managed_pane`` rows where ``state = 'creating'`` and
    ``pending_marker_token IS NOT NULL``. For each row whose
    ``created_at`` is older than ``MARKER_TTL_SECONDS`` (5 minutes):

    - If ``agent_id IS NULL`` (registration never happened) → transition
      to ``failed`` with ``failed_stage = 'pane_create'``.
      Interpretation: per state-machine.md §Recovery, no tmux pane is
      assumed to back the row.
    - If ``agent_id IS NOT NULL`` (registration ran but the spawn task
      didn't complete) → transition to ``failed`` with
      ``failed_stage = 'registration'``. This branch is rare —
      registration is the LAST step before ``ready`` — but it covers
      the case where the daemon crashed between FEAT-006 register and
      the ``state=ready`` write.
    - Marker token is cleared in both cases (CHECK invariant
      ``pending_marker_token IS NULL OR state = 'creating'``).

    The function does NOT emit lifecycle events directly — the daemon
    wiring layer captures the returned :class:`SweepOutcome` and emits
    one ``managed_pane_state_changed`` event per swept row through the
    FEAT-008 audit pipeline. This keeps ``pending_marker.sweep`` pure
    (SQLite-only) and unit-testable.

    Idempotent: a second call against the same already-swept rows is a
    no-op because the WHERE clause filters to ``state='creating'``.
    """
    now = clock() if clock is not None else _dt.datetime.now(_dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.UTC)
    # FR-022 / R5 cutoff: anything created at or before this timestamp
    # is stale.
    cutoff = now - _dt.timedelta(seconds=MARKER_TTL_SECONDS)
    cutoff_str = cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z")
    now_str = now.isoformat(timespec="microseconds").replace("+00:00", "Z")

    # C2 fix: the UPDATE includes a re-check on state + marker so a
    # spawn task that flipped the row to 'ready' AFTER our SELECT but
    # BEFORE our UPDATE doesn't get clobbered back to 'failed'. SQLite
    # guarantees single-statement atomicity, so the re-check makes the
    # SELECT-then-UPDATE racy pair safe without holding a long
    # transaction across both. ``UPDATE ... RETURNING`` would also work,
    # but the per-row count tracking below needs the agent_id snapshot
    # from the SELECT, which RETURNING doesn't help with.
    with tx_guard(tx_lock):
        cur = conn.execute(
            "SELECT id, agent_id, layout_id "
            "FROM managed_pane "
            "WHERE state = 'creating' "
            "  AND pending_marker_token IS NOT NULL "
            "  AND created_at < ?",
            (cutoff_str,),
        )
        stale_rows = cur.fetchall()

    pane_create_failures = 0
    registration_failures = 0
    panes_actually_swept = 0
    affected_layouts: set[str] = set()
    for pane_id, agent_id, layout_id in stale_rows:
        if agent_id is None:
            failed_stage = "pane_create"
        else:
            failed_stage = "registration"
        with tx_guard(tx_lock):
            cur = conn.execute(
                "UPDATE managed_pane SET "
                "state = 'failed', "
                "failed_stage = ?, "
                "pending_marker_token = NULL, "
                "updated_at = ? "
                "WHERE id = ? "
                # C2: re-check the row state under single-statement
                # atomicity. If the spawn task flipped the row to
                # 'ready'/'degraded'/'failed' between our SELECT and
                # this UPDATE, rowcount will be 0 and we skip the count.
                "  AND state = 'creating' "
                "  AND pending_marker_token IS NOT NULL",
                (failed_stage, now_str, pane_id),
            )
        if cur.rowcount and cur.rowcount > 0:
            panes_actually_swept += 1
            affected_layouts.add(layout_id)
            if agent_id is None:
                pane_create_failures += 1
            else:
                registration_failures += 1

    # review #12: recompute each affected layout's aggregate state. The
    # sweep is the TERMINAL transition for a crashed / never-wired spawn
    # pipeline (no live spawn thread will aggregate the layout), so without
    # this the managed_layout row stays stale (e.g. 'creating') while its
    # panes are 'failed' — managed.layout.detail would report a state
    # inconsistent with its panes. Mirrors spawn_layout_in_background's
    # aggregate write (failed_stage = first failed pane's stage).
    for layout_id in affected_layouts:
        with tx_guard(tx_lock):
            pane_rows = conn.execute(
                "SELECT state, failed_stage FROM managed_pane WHERE layout_id = ?",
                (layout_id,),
            ).fetchall()
            if not pane_rows:
                continue
            agg = aggregate_layout_state([ManagedState(r[0]) for r in pane_rows])
            layout_row = conn.execute(
                "SELECT state FROM managed_layout WHERE id = ?", (layout_id,)
            ).fetchone()
            if layout_row is None or ManagedState(layout_row[0]) == agg:
                continue
            layout_failed_stage = None
            if agg == ManagedState.FAILED:
                for st, fs in pane_rows:
                    if st == ManagedState.FAILED.value and fs is not None:
                        layout_failed_stage = fs
                        break
            conn.execute(
                "UPDATE managed_layout SET state = ?, failed_stage = ?, "
                "updated_at = ? WHERE id = ?",
                (agg.value, layout_failed_stage, now_str, layout_id),
            )

    return SweepOutcome(
        panes_examined=len(stale_rows),
        panes_swept=panes_actually_swept,
        pane_create_failures=pane_create_failures,
        registration_failures=registration_failures,
    )
