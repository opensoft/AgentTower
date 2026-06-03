"""FEAT-013 service entry points (T022).

This module owns the **synchronous** half of ``create_layout``:

1. FR-016 amendment: validate operator-supplied identifiers
   (``container_id``, ``template_name``, ``tmux_session_name``,
   ``launch_command_overrides`` map keys) against ``[A-Za-z0-9_.-]``
   with length ≤ 64 and no control characters; reject with
   ``validation_failed`` BEFORE any tmux RPC.
2. Resolve the template + each referenced launch profile (raise
   ``managed_template_not_found`` / ``managed_launch_command_not_found``
   from the loaders).
3. Acquire the per-container lock (FR-019 serialization).
4. R10 replay: when an ``idempotency_key`` matches an existing
   ``(container_id, idempotency_key)`` layout, return that layout's
   current state without inserting a duplicate.
5. FR-025: reject the 41st concurrent layout with
   ``managed_layout_capacity_exceeded``.
6. Insert ``managed_layout`` + ``managed_pane`` rows under a SQLite
   immediate transaction; each pane carries the pending-managed marker
   token in its row (the tmux pane-title side is set later, by the
   background spawn task — see :func:`spawn_layout_in_background`).
7. Return a :class:`CreateLayoutResult` summary so the operator gets
   an immediate response with ``state = 'creating'``.

The **background spawn task** (FR-026 no-cascade-kill rollback, FR-013
30s per-stage timeout + retry, FEAT-006 register-self, FEAT-007 log
attach) is implemented in :func:`spawn_layout_in_background`. In Phase
3b that function exists with the orchestration scaffolding but the
actual tmux RPC + cross-FEAT calls are deferred to Phase 4 (T029/T030);
in this commit the background task simply marks each pane as ``ready``
in tests, so the synchronous service surface is exercisable.

Reserved entry points for later phases:

- :func:`remove_pane` → Phase 5 T042
- :func:`recreate_pane` → Phase 5 T043
- :func:`promote_from_adopted` → Phase 5 T045 (stub returning
  ``not_implemented``)
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Final, Optional

from ..tmux.adapter import TmuxError
from ._retry import run_stage_with_retry
from ._tx import tx_guard
from .dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    count_active_layouts,
    insert_layout,
    insert_pane,
    select_layout,
    select_layout_by_idempotency_key,
    select_pane,
    select_panes_for_layout,
    update_layout_state,
    update_pane_state,
)
from .errors import (
    MANAGED_LAYOUT_CAPACITY_EXCEEDED,
    MANAGED_LAUNCH_COMMAND_NOT_FOUND,
    MANAGED_PANE_CONCURRENT_RECREATE,
    MANAGED_PANE_ILLEGAL_RECREATE_SOURCE,
    MANAGED_PANE_ILLEGAL_TRANSITION,
    MANAGED_PANE_LABEL_CONFLICT,
    MANAGED_PANE_NOT_FOUND,
    MANAGED_PANE_PROTECTED_ADOPTED,
    MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP,
    MANAGED_SESSION_NAME_CONFLICT,
    MANAGED_TEMPLATE_NOT_FOUND,
    ManagedSessionsError,
)
from .events import (
    LAYOUT_CREATED,
    LAYOUT_STATE_CHANGED,
    PANE_CREATED,
    PANE_LAUNCH_COMMAND_EXITED,
    PANE_LOG_ATTACH_FAILED,
    PANE_PENDING_MARKER_CLEARED,
    PANE_PENDING_MARKER_SET,
    PANE_RECREATED,
    PANE_REMOVED,
    PANE_STATE_CHANGED,
    build_event,
)
from .launch_profiles import LaunchCommandProfile, load_profiles, resolve_profile
from .pending_marker import new_marker_token
from .serializer import ContainerSerializer
from .state_machine import FailedStage, ManagedState, aggregate_layout_state
from .templates import ManagedTemplate, resolve_template


# Type alias for the event emitter callback the handler layer passes in.
# Each emitted event is a fully-built dict from ``events.build_event``;
# the callback is responsible for the actual JSONL append. ``None`` is a
# valid default for tests that don't care about event side effects.
EventEmitter = Callable[[dict[str, object]], None]


# ─── FR-016 amendment: operator-input validation ─────────────────────────

# Allowed character set + length cap per spec §FR-016 amendment.
_IDENT_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_.-]+$")
_IDENT_MAX_LEN: int = 64


# Forbidden control characters: \x00-\x1f, \x7f. The regex above
# implicitly disallows them (the allow-list is ASCII letters/digits/dots/
# hyphens/underscores) but we keep an explicit check so the error
# message can distinguish "control char" from "out-of-charset" failures.
_CONTROL_CHARS: frozenset[str] = frozenset(chr(c) for c in range(0x00, 0x20)) | {
    "\x7f"
}


# ─── FR-025: capacity cap ────────────────────────────────────────────────

CAPACITY_LIMIT: int = 40


# ─── Result types ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CreatePaneSummary:
    """One pane's slice of the ``create_layout`` response."""

    pane_id: str
    role: str
    label: str
    state: ManagedState


@dataclass(frozen=True, slots=True)
class CreateLayoutResult:
    """Returned by :func:`create_layout` once the rows are inserted.

    ``state`` will be ``creating`` for a fresh layout. For an R10
    idempotency replay (same key + container), it will reflect the
    layout's current persisted state at the time of the replay.
    """

    layout_id: str
    state: ManagedState
    intended_pane_count: int
    panes: list[CreatePaneSummary] = field(default_factory=list)
    replay: bool = False  # True for R10 in-flight / completed match


# ─── Helpers ─────────────────────────────────────────────────────────────


def _utc_now_rfc3339(clock: Optional[Callable[[], _dt.datetime]] = None) -> str:
    if clock is None:
        ts = _dt.datetime.now(_dt.UTC)
    else:
        ts = clock()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.UTC)
    return ts.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_identifier(value: str, *, field_name: str) -> None:
    """FR-016 amendment: reject operator-supplied identifier shapes.

    Raises ``ManagedSessionsError("validation_failed", details={...})``.
    """
    if not isinstance(value, str) or not value:
        raise _validation_failed(
            field=field_name, reason="missing or empty",
        )
    if len(value) > _IDENT_MAX_LEN:
        raise _validation_failed(
            field=field_name,
            reason=f"length {len(value)} > {_IDENT_MAX_LEN}",
        )
    if any(ch in _CONTROL_CHARS for ch in value):
        raise _validation_failed(
            field=field_name, reason="contains control characters",
        )
    if not _IDENT_RE.match(value):
        raise _validation_failed(
            field=field_name,
            reason="must match [A-Za-z0-9_.-]",
        )


class ValidationFailedError(Exception):
    """Operator-input validation failure shape (FEAT-011 ``validation_failed``).

    ``code`` is the FEAT-011 closed-set ``validation_failed`` constant
    (NOT a FEAT-013 code); ``ManagedSessionsError`` is reserved for the
    FEAT-013 closed set in ``errors.py``. Handlers translate this into
    the wire envelope's ``error`` block (M1 error list per contracts/
    managed-methods.md).

    Stable exception type — callers can ``except ValidationFailedError``
    cleanly, unlike the prior local-class pattern.
    """

    code: Final[str] = "validation_failed"

    def __init__(self, *, field: str, reason: str) -> None:
        self.details: dict[str, str] = {"field": field, "reason": reason}
        super().__init__(f"validation_failed: {field}: {reason}")


def _validation_failed(*, field: str, reason: str) -> ValidationFailedError:
    """Build a ``ValidationFailedError`` (kept as a thin helper for
    call-site readability)."""
    return ValidationFailedError(field=field, reason=reason)


# ─── create_layout ──────────────────────────────────────────────────────


def create_layout(
    *,
    conn: sqlite3.Connection,
    serializer: ContainerSerializer,
    container_id: str,
    template_name: str,
    tmux_session_name: str,
    launch_command_overrides: Optional[dict[str, str]] = None,
    idempotency_key: Optional[str] = None,
    template_override_dir: Optional[Path] = None,
    profile_override_dir: Optional[Path] = None,
    clock: Optional[Callable[[], _dt.datetime]] = None,
    event_emitter: Optional[EventEmitter] = None,
    actor: str = "operator",
    tx_lock: Optional[threading.Lock] = None,
    tmux_has_session_fn: Optional[Callable[[str, str], bool]] = None,
) -> CreateLayoutResult:
    """Create a managed layout — synchronous orchestration entry point.

    The synchronous part returns once the SQLite rows are inserted with
    ``state = 'creating'`` and the pending-managed marker tokens are
    set. Background tmux spawn + FEAT-006 registration + FEAT-007 log
    attachment land in Phase 4 (T029/T030); for now the rows stay in
    ``creating`` until an explicit ``spawn_layout_in_background`` call
    (or a test fixture) advances them.

    Raises ``ManagedSessionsError`` (closed-set code from
    ``errors.ALL_CODES``) or ``ValidationFailedError`` (FEAT-011
    ``validation_failed`` shape) on contract violations. The handler
    layer (T023/T024 — Phase 3c) is responsible for translating these
    into envelope responses **and** for verifying that ``container_id``
    exists in the FEAT-003 container registry before calling this entry
    point (``container_not_found`` is a handler-layer concern; the
    service trusts the handler to pre-check, matching FEAT-011's
    mutations pattern).
    """
    launch_overrides = launch_command_overrides or {}

    # 1. FR-016 amendment: validate operator-supplied identifiers BEFORE
    #    any side effects (tmux RPC, DB write). The amendment names
    #    `tmux_session_name`, the resolved `label_pattern` substitution,
    #    and `launch_command_overrides` map keys; `template_name` is
    #    validated by ``resolve_template`` raising
    #    ``managed_template_not_found`` so we do NOT apply the charset
    #    check to it (built-ins use `+` in their names).
    if not container_id:
        raise _validation_failed(field="container_id", reason="missing or empty")
    _validate_identifier(tmux_session_name, field_name="tmux_session_name")
    # M3 fix: idempotency_key flows into the tmux pane title token
    # (``@MANAGED:<token>:<label>``) AND into the durable layout row.
    # The FR-016 charset gate keeps the title parseable and FEAT-004's
    # scan output clean even when the operator supplies a hostile value.
    if idempotency_key is not None:
        _validate_identifier(idempotency_key, field_name="idempotency_key")
    for key in launch_overrides:
        # Map keys are "<role>:<label>" — split and validate each side.
        # We accept ':' in the map key but not in the components.
        if ":" not in key:
            raise _validation_failed(
                field="launch_command_overrides",
                reason=f"key {key!r} must be '<role>:<label>'",
            )
        role_part, _, label_part = key.partition(":")
        _validate_identifier(role_part, field_name="launch_command_overrides.role")
        _validate_identifier(label_part, field_name="launch_command_overrides.label")

    # 2. Resolve template + launch profiles.
    template = resolve_template(template_name, override_dir=template_override_dir)
    resolved_profiles: dict[str, LaunchCommandProfile] = {}
    for key, profile_name in launch_overrides.items():
        resolved_profiles[key] = resolve_profile(
            profile_name, override_dir=profile_override_dir
        )

    # 3. Per-container lock (FR-019). All subsequent state mutation is
    #    inside the lock.
    lock = serializer.for_container(container_id)
    with lock:
        # 4. R10 replay — return the existing layout untouched. (Read
        #    under tx_lock per C1: shared worker_conn requires every
        #    statement to serialize through worker_tx_lock.)
        if idempotency_key is not None:
            with tx_guard(tx_lock):
                existing = select_layout_by_idempotency_key(
                    conn, container_id, idempotency_key
                )
            if existing is not None:
                with tx_guard(tx_lock):
                    return _summarize_layout(conn, existing, replay=True)

        # 4b. FR-016 synchronous session-name conflict pre-check. The DB
        #     partial unique index (below, in the insert tx) already
        #     rejects collisions against AgentTower's OWN non-terminal
        #     panes. This pre-check additionally rejects an out-of-band
        #     tmux session (one NOT tracked in our DB — e.g. an adopted
        #     or operator-created session) synchronously, so the conflict
        #     surfaces as a clean ``create`` rejection rather than a
        #     failed pane in the async spawn task. The async ``has-session``
        #     gate in the spawn backend REMAINS as the TOCTOU backstop (a
        #     session can appear between this check and ``new-session``).
        #     Placed AFTER the idempotency replay short-circuit so a
        #     legitimate replay of OUR own layout isn't rejected against
        #     the session it already owns. Skipped when no checker is
        #     injected (tests / incomplete boot wiring); an indeterminate
        #     probe (docker-exec failure) is swallowed and left for the
        #     async path to classify as ``failed_stage=pane_create``.
        if tmux_has_session_fn is not None:
            try:
                conflict = tmux_has_session_fn(container_id, tmux_session_name)
            except TmuxError:
                conflict = False
            if conflict:
                raise ManagedSessionsError(
                    MANAGED_SESSION_NAME_CONFLICT,
                    details={
                        "container_id": container_id,
                        "tmux_session_name": tmux_session_name,
                    },
                )

        # 5. FR-025 capacity check (cheap fast-path; the authoritative
        #    atomic re-count runs inside the BEGIN IMMEDIATE insert tx
        #    below per review #3).
        with tx_guard(tx_lock):
            active = count_active_layouts(conn)
        if active >= CAPACITY_LIMIT:
            raise ManagedSessionsError(
                MANAGED_LAYOUT_CAPACITY_EXCEEDED,
                details={
                    "current_count": active,
                    "limit": CAPACITY_LIMIT,
                },
            )

        # 6. Insert layout + panes under a single SQLite immediate
        #    transaction so partial inserts can't leak. tx_lock guards
        #    the connection against concurrent FEAT-009/010 transactions
        #    (C1 — shared worker_conn must serialize through worker_tx_lock).
        now = _utc_now_rfc3339(clock)
        layout_id = str(uuid.uuid4())
        layout_row = ManagedLayoutRow(
            id=layout_id,
            container_id=container_id,
            template_name=template.name,
            intended_pane_count=template.pane_count,
            state=ManagedState.CREATING,
            failed_stage=None,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )

        # Compose pane rows. Marker tokens collapse with idempotency_key
        # per R10 when present; else uuid4.
        pane_rows: list[ManagedPaneRow] = []
        pane_summaries: list[CreatePaneSummary] = []
        role_ordinals: dict[str, int] = {}
        for index, tmpl_pane in enumerate(template.panes):
            ord_n = role_ordinals.get(tmpl_pane.role, 0) + 1
            role_ordinals[tmpl_pane.role] = ord_n
            label = tmpl_pane.label_pattern.replace("{ordinal}", str(ord_n))
            # Validate the resolved label too (operator-controlled via
            # template; protects tmux from surprises).
            _validate_identifier(label, field_name="label_pattern result")

            # Pick launch profile: explicit override > template default.
            override_key = f"{tmpl_pane.role}:{label}"
            explicit_override = launch_overrides.get(override_key)
            profile_name: Optional[str] = (
                explicit_override or tmpl_pane.default_launch_command_ref
            )
            # review #14: explicit overrides were resolved up-front (step 2);
            # also resolve a TEMPLATE-DEFAULT ref synchronously so a missing
            # default profile surfaces as managed_launch_command_not_found at
            # create time (M1 contract) instead of as a delayed background
            # pane failure. (Built-in templates use None, so this only bites
            # operator-authored override templates per FR-024.)
            if explicit_override is None and profile_name is not None:
                resolve_profile(profile_name, override_dir=profile_override_dir)
            marker_token = idempotency_key or new_marker_token()

            pane_id = str(uuid.uuid4())
            row = ManagedPaneRow(
                id=pane_id,
                layout_id=layout_id,
                container_id=container_id,
                agent_id=None,
                role=tmpl_pane.role,
                capability=tmpl_pane.capability,
                label=label,
                launch_command_ref=profile_name,
                tmux_session_name=tmux_session_name,
                tmux_pane_index=index,
                pending_marker_token=marker_token,
                state=ManagedState.CREATING,
                failed_stage=None,
                predecessor_id=None,
                chain_depth=0,
                created_at=now,
                updated_at=now,
            )
            pane_rows.append(row)
            pane_summaries.append(
                CreatePaneSummary(
                    pane_id=pane_id,
                    role=tmpl_pane.role,
                    label=label,
                    state=ManagedState.CREATING,
                )
            )

        with tx_guard(tx_lock):
            # Close any open implicit tx from the caller (tests that
            # didn't commit setup INSERTs). Production
            # ``isolation_level=None`` makes this a no-op.
            if conn.in_transaction:
                conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            try:
                # review #3: FR-025 is a GLOBAL hard cap (40 layouts across
                # ALL containers), but create_layout only holds the
                # per-container lock — two concurrent creates for DIFFERENT
                # containers would both pass the pre-check at (5) and
                # overshoot. Re-count INSIDE this BEGIN IMMEDIATE: the
                # write lock makes the count consistent with the insert and
                # serializes every inserter, so the cap holds cross-container.
                active_now = count_active_layouts(conn)
                if active_now >= CAPACITY_LIMIT:
                    raise ManagedSessionsError(
                        MANAGED_LAYOUT_CAPACITY_EXCEEDED,
                        details={"current_count": active_now, "limit": CAPACITY_LIMIT},
                    )
                insert_layout(conn, layout_row)
                for row in pane_rows:
                    # Per-container label uniqueness enforced by the partial
                    # unique index. A duplicate label among non-terminal panes
                    # in the same container raises sqlite3.IntegrityError ->
                    # we surface it as managed_session_name_conflict if it's
                    # actually a tmux-session-name conflict, else propagate.
                    try:
                        insert_pane(conn, row)
                    except sqlite3.IntegrityError as exc:
                        conn.execute("ROLLBACK")
                        # SQLite IntegrityError text includes the colliding
                        # column names ("UNIQUE constraint failed: ...");
                        # the index name itself does NOT appear in the
                        # default message, so we detect by column patterns.
                        err_text = str(exc)
                        # (tmux_session_name, tmux_pane_index) → operator
                        # reused a session name attached to another non-
                        # terminal layout (FR-016).
                        if (
                            "tmux_session_name" in err_text
                            and "tmux_pane_index" in err_text
                        ):
                            raise ManagedSessionsError(
                                MANAGED_SESSION_NAME_CONFLICT,
                                details={
                                    "container_id": container_id,
                                    "tmux_session_name": tmux_session_name,
                                },
                            ) from exc
                        # (container_id, label) → two non-terminal panes
                        # in the same bench container collide on label
                        # (FR-003 partial unique index).
                        if "container_id" in err_text and "label" in err_text:
                            raise ManagedSessionsError(
                                MANAGED_PANE_LABEL_CONFLICT,
                                details={
                                    "container_id": container_id,
                                    "label": row.label,
                                },
                            ) from exc
                        raise
                conn.execute("COMMIT")
            except Exception:
                # We may have already rolled back above; rollback again is a
                # no-op on closed transactions.
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

        # 7. Emit FR-015-ordered synchronous lifecycle events. Per-layout
        #    sequence starts at 0; per-pane sequences start at 0 per pane.
        #    Background spawn events (state-change to ready/degraded/failed)
        #    land in Phase 4b alongside the FEAT-006/007 wiring.
        if event_emitter is not None:
            layout_seq = 0
            event_emitter(
                build_event(
                    LAYOUT_CREATED,
                    actor=actor,
                    layout_id=layout_id,
                    sequence=layout_seq,
                    payload={
                        "template_name": template.name,
                        "container_id": container_id,
                        "intended_pane_count": template.pane_count,
                    },
                )
            )
            for index, (row, summary) in enumerate(zip(pane_rows, pane_summaries)):
                event_emitter(
                    build_event(
                        PANE_CREATED,
                        actor=actor,
                        layout_id=layout_id,
                        pane_id=row.id,
                        sequence=0,
                        payload={
                            "role": row.role,
                            "label": row.label,
                            "tmux_session_name": row.tmux_session_name,
                            "tmux_pane_index": row.tmux_pane_index,
                        },
                    )
                )
                event_emitter(
                    build_event(
                        PANE_PENDING_MARKER_SET,
                        actor=actor,
                        pane_id=row.id,
                        sequence=1,
                        payload={"marker_token": row.pending_marker_token or ""},
                    )
                )

        return CreateLayoutResult(
            layout_id=layout_id,
            state=ManagedState.CREATING,
            intended_pane_count=template.pane_count,
            panes=pane_summaries,
            replay=False,
        )


def _summarize_layout(
    conn: sqlite3.Connection,
    layout: ManagedLayoutRow,
    *,
    replay: bool,
) -> CreateLayoutResult:
    """Build a :class:`CreateLayoutResult` from a persisted layout row.

    Used for R10 idempotency replays — returns the layout's current
    persisted state without re-creating anything.
    """
    panes = select_panes_for_layout(conn, layout.id)
    return CreateLayoutResult(
        layout_id=layout.id,
        state=layout.state,
        intended_pane_count=layout.intended_pane_count,
        panes=[
            CreatePaneSummary(
                pane_id=p.id, role=p.role, label=p.label, state=p.state
            )
            for p in panes
        ],
        replay=replay,
    )


# ─── Background spawn pipeline (T029 / T030 — Phase 4b) ────────────────
#
# `create_layout` returns synchronously after the SQLite rows are
# inserted with `state = 'creating'`. The actual tmux spawn + FEAT-006
# register + FEAT-007 log attach happens in a background task that
# `spawn_layout_in_background` drives. The task is injectable for
# testability — the production daemon wires real tmux/FEAT-006/FEAT-007
# backends; tests pass canned dicts.
#
# Per-pane stages (FR-013):
#   1. tmux spawn        → ok=False  → failed   (failed_stage=pane_create)
#                          ok=True+launch_alive=False → degraded (failed_stage=launch_command)
#                                                       AND emit PANE_LAUNCH_COMMAND_EXITED
#                          ok=True+launch_alive=True  → continue
#   2. register_agent    → ok=False → failed   (failed_stage=registration)
#                          ok=True  → continue with agent_id
#   3. attach_log        → ok=False → degraded (failed_stage=log_attach)
#                                     AND emit PANE_LOG_ATTACH_FAILED
#                          ok=True  → ready
#
# Per FR-026 no-cascade-kill: each pane runs its own pipeline; a
# sibling's failure does not affect others. After all panes settle,
# the layout-level state is recomputed via
# state_machine.aggregate_layout_state.
#
# Per FR-019 per-container serialization: the background task acquires
# the per-container lock for the duration of the spawn so concurrent
# spawns (or a remove/recreate against the same container) wait. The
# lock is the same one `create_layout` used; in production the
# `create_layout` handler releases it before starting the bg task, then
# the bg task re-acquires it.


# Backend protocols — plain Callables for minimum ceremony. Each takes
# the pane row + any preceding-stage outputs, returns a result dict.

# (pane) -> {ok: True, tmux_pane_id: str, launch_alive: bool}
#        or {ok: False, error: {code, message}}
TmuxSpawnFn = Callable[[ManagedPaneRow], dict[str, object]]

# (pane, tmux_pane_id) -> {ok: True, agent_id: str}
#                      or {ok: False, error: {code, message}}
RegisterAgentFn = Callable[[ManagedPaneRow, str], dict[str, object]]

# (pane, agent_id) -> {ok: True} or {ok: False, error: {code, message}}
LogAttachFn = Callable[[ManagedPaneRow, str], dict[str, object]]


@dataclass(frozen=True, slots=True)
class SpawnLayoutOutcome:
    """Summary of the background spawn task after all panes have settled.

    ``layout_state`` is the aggregate state computed from pane outcomes
    via ``state_machine.aggregate_layout_state``. ``pane_states`` maps
    each pane id to its final state. Useful for tests that want to
    assert the full layout disposition without re-reading SQLite.
    """

    layout_id: str
    layout_state: ManagedState
    pane_states: dict[str, ManagedState]


def spawn_layout_in_background(
    layout_id: str,
    *,
    conn: sqlite3.Connection,
    serializer: ContainerSerializer,
    tmux_spawn_fn: TmuxSpawnFn,
    register_fn: RegisterAgentFn,
    log_attach_fn: LogAttachFn,
    event_emitter: Optional[EventEmitter] = None,
    clock: Optional[Callable[[], _dt.datetime]] = None,
    tx_lock: Optional[threading.Lock] = None,
    stage_timeout_seconds: Optional[float] = None,
) -> SpawnLayoutOutcome:
    """Run the FEAT-013 spawn pipeline for a previously-inserted layout.

    Returns the :class:`SpawnLayoutOutcome` summary. Mutates the
    ``managed_pane`` rows in place; the layout state is recomputed once
    every pane has settled.

    In production this runs in a background thread launched by the
    handler layer. Tests call it synchronously to avoid threading
    nondeterminism.
    """
    with tx_guard(tx_lock):
        layout = select_layout(conn, layout_id)
    if layout is None:
        return SpawnLayoutOutcome(
            layout_id=layout_id,
            layout_state=ManagedState.FAILED,
            pane_states={},
        )

    pane_states: dict[str, ManagedState] = {}
    lock = serializer.for_container(layout.container_id)
    with lock:
        # Only process panes that are still in `creating` state. After
        # the initial spawn, ready/degraded/failed/removed panes don't
        # need (and shouldn't get) another spawn cycle — the spawn task
        # is re-runnable across recreate iterations (Phase 5c T041
        # chain-traversal: a recreated pane lands in creating and
        # subsequent spawn_layout_in_background calls pick it up without
        # disturbing already-settled siblings).
        with tx_guard(tx_lock):
            all_panes = select_panes_for_layout(conn, layout_id)
        panes = [p for p in all_panes if p.state == ManagedState.CREATING]
        for pane in panes:
            final_state = _spawn_single_pane(
                conn=conn,
                pane=pane,
                tmux_spawn_fn=tmux_spawn_fn,
                register_fn=register_fn,
                log_attach_fn=log_attach_fn,
                event_emitter=event_emitter,
                clock=clock,
                tx_lock=tx_lock,
                stage_timeout_seconds=stage_timeout_seconds,
            )
            pane_states[pane.id] = final_state

        # Aggregate layout state from the now-mutated pane rows. We
        # re-select so the aggregation runs on the persisted truth, not
        # the in-memory mapping. Re-select the LAYOUT row too (inside the
        # lock) so the prev-state baseline reflects any concurrent
        # remove/recreate/recovery mutation that landed between the
        # pre-lock read and lock acquisition (review #17 — the pre-lock
        # `layout.state` could be stale and skip a legitimate update or
        # emit a wrong prev_state).
        with tx_guard(tx_lock):
            refreshed = select_panes_for_layout(conn, layout_id)
            layout_fresh = select_layout(conn, layout_id)
        prev_layout_state = (layout_fresh or layout).state
        new_layout_state = aggregate_layout_state([p.state for p in refreshed])
        if new_layout_state != prev_layout_state:
            now = _utc_now_rfc3339(clock)
            # Layout-level failed_stage is set when the aggregate is
            # `failed`; otherwise cleared. (data-model.md §ManagedLayout
            # lifecycle: failed iff at least one pane is failed.)
            layout_failed_stage: Optional[FailedStage] = None
            if new_layout_state == ManagedState.FAILED:
                # Surface the FIRST failed pane's failed_stage as the
                # layout-level signal. Operators consult per-pane detail
                # for the full disposition.
                for p in refreshed:
                    if p.state == ManagedState.FAILED and p.failed_stage is not None:
                        layout_failed_stage = p.failed_stage
                        break
            with tx_guard(tx_lock):
                update_layout_state(
                    conn, layout_id,
                    state=new_layout_state,
                    failed_stage=layout_failed_stage,
                    now=now,
                )
            if event_emitter is not None:
                event_emitter(
                    build_event(
                        LAYOUT_STATE_CHANGED,
                        actor="daemon",
                        layout_id=layout_id,
                        # H2 fix: monotonic-time sequence prevents collision
                        # across multiple spawn_layout_in_background calls
                        # (recreate iterations re-enter this code path and
                        # would otherwise re-emit at sequence=1).
                        # FR-015 requires per-layout FIFO; monotonic_ns
                        # gives that AND uniqueness.
                        sequence=_layout_sequence_now(),
                        payload={
                            "prev_state": prev_layout_state.value,
                            "new_state": new_layout_state.value,
                        },
                    )
                )

    # review #18: new_layout_state is always the persisted aggregate truth
    # (computed from a fresh re-select), even on a no-op re-run where no
    # pane was in `creating`. The old `if pane_states else FAILED` guard
    # wrongly reported FAILED for an already-ready layout on re-entry.
    return SpawnLayoutOutcome(
        layout_id=layout_id,
        layout_state=new_layout_state,
        pane_states=pane_states,
    )


# ─── H2 fix: monotonic-time layout-scoped sequence generator ────────────


# Snapshot at module import — every subsequent call returns a strictly-
# increasing integer relative to this baseline, even across recreate
# iterations within the same daemon process.
_LAYOUT_SEQUENCE_EPOCH_NS: int = time.monotonic_ns()
_LAYOUT_SEQUENCE_OFFSET: int = 1_000  # leaves room for the create_layout
# sync-side LAYOUT_CREATED (sequence=0) and the documented LAYOUT_STATE_CHANGED
# numbering convention (1_000 for remove, 10_000 for recovery). All
# dynamic emissions are strictly above that range.


def _layout_sequence_now() -> int:
    """Return a strictly-increasing layout-scoped sequence integer.

    Uses ``time.monotonic_ns()`` so subsequent calls within the same
    process are strictly increasing — required for FR-015 per-layout
    FIFO when ``spawn_layout_in_background`` runs multiple times for the
    same layout (chain-traversal across recreates). The
    ``_LAYOUT_SEQUENCE_OFFSET`` floor keeps dynamic sequences well above
    the legacy fixed sequences (0/1, 1_000/1_001, 10_000/10_001) so the
    relative ordering between sync-side, remove-side, recovery-side, and
    spawn-pipeline emissions is preserved.
    """
    return _LAYOUT_SEQUENCE_OFFSET + (time.monotonic_ns() - _LAYOUT_SEQUENCE_EPOCH_NS)


def _spawn_single_pane(
    *,
    conn: sqlite3.Connection,
    pane: ManagedPaneRow,
    tmux_spawn_fn: TmuxSpawnFn,
    register_fn: RegisterAgentFn,
    log_attach_fn: LogAttachFn,
    event_emitter: Optional[EventEmitter],
    clock: Optional[Callable[[], _dt.datetime]],
    tx_lock: Optional[threading.Lock] = None,
    stage_timeout_seconds: Optional[float] = None,
) -> ManagedState:
    """Drive one pane through tmux → register → log attach. Returns the
    final ``ManagedState`` after persistence.

    Per-pane sequence counter starts at 2 — preserves FR-015 per-pane
    FIFO ordering from the synchronous side which emitted at sequences
    0 (`PANE_CREATED`) and 1 (`PANE_PENDING_MARKER_SET`).
    """
    seq = 2  # next per-pane sequence after the sync-side events

    def _emit_state_change(prev: ManagedState, new: ManagedState, failed_stage: Optional[FailedStage]) -> None:
        nonlocal seq
        if event_emitter is None:
            return
        payload: dict[str, object] = {
            "prev_state": prev.value,
            "new_state": new.value,
        }
        if failed_stage is not None:
            payload["failed_stage"] = failed_stage.value
        event_emitter(
            build_event(
                PANE_STATE_CHANGED,
                actor="daemon",
                layout_id=pane.layout_id,
                pane_id=pane.id,
                sequence=seq,
                payload=payload,
            )
        )
        seq += 1

    def _emit_marker_cleared() -> None:
        nonlocal seq
        if event_emitter is None:
            return
        event_emitter(
            build_event(
                PANE_PENDING_MARKER_CLEARED,
                actor="daemon",
                pane_id=pane.id,
                sequence=seq,
                payload={"marker_token": pane.pending_marker_token or ""},
            )
        )
        seq += 1

    def _emit_aux(event_type: str, payload: dict[str, object]) -> None:
        nonlocal seq
        if event_emitter is None:
            return
        event_emitter(
            build_event(
                event_type,
                actor="daemon",
                layout_id=pane.layout_id,
                pane_id=pane.id,
                sequence=seq,
                payload=payload,
            )
        )
        seq += 1

    # ── Stage 1: tmux spawn ─────────────────────────────────────────
    # FR-013 amendment: 30s per-attempt timeout + 2x retry with 1s / 2s
    # back-off on transient docker_exec / tmux_unavailable / tmux_no_server
    # / stage_timeout failures. Non-transient failures (label conflict,
    # session-name conflict, etc.) surface on the first attempt.
    spawn_result = run_stage_with_retry(
        lambda: tmux_spawn_fn(pane),
        stage_name="tmux_spawn",
        timeout_seconds=stage_timeout_seconds,
    )
    if not spawn_result.get("ok"):
        now = _utc_now_rfc3339(clock)
        with tx_guard(tx_lock):
            update_pane_state(
                conn, pane.id,
                state=ManagedState.FAILED,
                failed_stage=FailedStage.PANE_CREATE,
                clear_marker=True,
                now=now,
            )
        _emit_marker_cleared()
        _emit_state_change(ManagedState.CREATING, ManagedState.FAILED, FailedStage.PANE_CREATE)
        return ManagedState.FAILED

    tmux_pane_id = str(spawn_result.get("tmux_pane_id", ""))
    launch_alive = bool(spawn_result.get("launch_alive", True))

    if not launch_alive:
        # Pane exists but the launch command exited within 1s. Record
        # the event; we still attempt registration so the operator
        # sees the row in `degraded` with `failed_stage=launch_command`
        # rather than rolling back to `failed`.
        _emit_aux(
            PANE_LAUNCH_COMMAND_EXITED,
            {
                "exit_code": int(spawn_result.get("exit_code", -1)),
                "elapsed_ms": int(spawn_result.get("elapsed_ms", 0)),
            },
        )

    # ── Stage 2: FEAT-006 register ─────────────────────────────────
    register_result = run_stage_with_retry(
        lambda: register_fn(pane, tmux_pane_id),
        stage_name="register",
        timeout_seconds=stage_timeout_seconds,
    )
    if not register_result.get("ok"):
        now = _utc_now_rfc3339(clock)
        with tx_guard(tx_lock):
            update_pane_state(
                conn, pane.id,
                state=ManagedState.FAILED,
                failed_stage=FailedStage.REGISTRATION,
                clear_marker=True,
                now=now,
            )
        _emit_marker_cleared()
        _emit_state_change(ManagedState.CREATING, ManagedState.FAILED, FailedStage.REGISTRATION)
        return ManagedState.FAILED

    agent_id = str(register_result.get("agent_id", ""))

    # ── Stage 3: FEAT-007 log attach ──────────────────────────────
    log_result = run_stage_with_retry(
        lambda: log_attach_fn(pane, agent_id),
        stage_name="log_attach",
        timeout_seconds=stage_timeout_seconds,
    )
    log_ok = bool(log_result.get("ok"))

    now = _utc_now_rfc3339(clock)
    if not launch_alive:
        # Launch immediate-exit → degraded(launch_command). Log attach
        # outcome doesn't move us out of degraded.
        with tx_guard(tx_lock):
            update_pane_state(
                conn, pane.id,
                state=ManagedState.DEGRADED,
                failed_stage=FailedStage.LAUNCH_COMMAND,
                agent_id=agent_id,
                clear_marker=True,
                now=now,
            )
        _emit_marker_cleared()
        _emit_state_change(ManagedState.CREATING, ManagedState.DEGRADED, FailedStage.LAUNCH_COMMAND)
        return ManagedState.DEGRADED

    if not log_ok:
        # Log attach failed → degraded(log_attach).
        _emit_aux(
            PANE_LOG_ATTACH_FAILED,
            {
                "reason": str(
                    log_result.get("error", {}).get("message", "")
                    if isinstance(log_result.get("error"), dict) else ""
                ),
            },
        )
        with tx_guard(tx_lock):
            update_pane_state(
                conn, pane.id,
                state=ManagedState.DEGRADED,
                failed_stage=FailedStage.LOG_ATTACH,
                agent_id=agent_id,
                clear_marker=True,
                now=now,
            )
        _emit_marker_cleared()
        _emit_state_change(ManagedState.CREATING, ManagedState.DEGRADED, FailedStage.LOG_ATTACH)
        return ManagedState.DEGRADED

    # All stages green → ready.
    with tx_guard(tx_lock):
        update_pane_state(
            conn, pane.id,
            state=ManagedState.READY,
            agent_id=agent_id,
            clear_marker=True,
            now=now,
        )
    _emit_marker_cleared()
    _emit_state_change(ManagedState.CREATING, ManagedState.READY, None)
    return ManagedState.READY


# ─── Phase 5a: lifecycle operations (T042 + T043 + T044 + T045) ─────────
#
# remove_pane (T042) / recreate_pane (T043) / promote_from_adopted (T045)
# implement the M6 / M7 / M8 contract surface from contracts/managed-methods.md.
# Adopted-pane protection (T044) is woven through remove_pane + recreate_pane
# rather than a separate entry point — a pane_id without a managed_pane row
# is, by definition, adopted (FEAT-006 registered it directly), so the
# protect-adopted check is a missing-row probe.


# ─── Backend protocol additions ──────────────────────────────────────────


# tmux kill-pane backend for remove_pane (T042). Idempotent: pane already
# killed counts as success (data-model.md + state-machine.md §Recreate
# semantics step describe `tmux kill-pane` as not-found-tolerant).
# (pane) -> {ok: True} or {ok: False, error: {code, message}}
TmuxKillFn = Callable[[ManagedPaneRow], dict[str, object]]

# Route + log cleanup hooks for remove_pane (T042). Stubbed for testability
# the same way as the spawn backends — production wiring delegates to
# FEAT-010 routes service + FEAT-007 log service. Cleanup hooks MUST be
# idempotent (re-removal of an already-removed pane succeeds).
# (pane) -> None (side-effecting; failure is logged but does not block the
# state transition because the pane row is being archived regardless).
CleanupFn = Callable[[ManagedPaneRow], None]


# ─── T042: remove_pane (M6) ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RemovePaneResult:
    """Returned by :func:`remove_pane` on success."""

    pane_id: str
    state: ManagedState  # always ManagedState.REMOVED on success


def _pane_id_in_agents_table(conn: sqlite3.Connection, pane_id: str) -> bool:
    """Return True iff a FEAT-006 ``agents`` row exists with this id.

    Used by ``remove_pane`` / ``recreate_pane`` to distinguish between
    two distinct missing-row outcomes per contracts/error-codes.md:
    - ``managed_pane_protected_adopted`` — id IS in ``agents`` (adopted),
      but NOT in ``managed_pane`` (so we refuse to manage it).
    - ``managed_pane_not_found`` — id is unknown to both tables.

    Failure-tolerant: returns False if the ``agents`` table doesn't
    exist (FEAT-006 not wired in this fixture) so the legacy collapse
    behavior (everything → protected_adopted) is preserved as a fallback
    when no FK-target table is reachable. Tests that want the strict
    not_found path must seed the ``agents`` table explicitly.
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM agents WHERE agent_id = ?",
            (pane_id,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def remove_pane(
    *,
    conn: sqlite3.Connection,
    serializer: ContainerSerializer,
    pane_id: str,
    tmux_kill_fn: Optional[TmuxKillFn] = None,
    route_cleanup_fn: Optional[CleanupFn] = None,
    log_detach_fn: Optional[CleanupFn] = None,
    event_emitter: Optional[EventEmitter] = None,
    clock: Optional[Callable[[], _dt.datetime]] = None,
    actor: str = "operator",
    tx_lock: Optional[threading.Lock] = None,
) -> RemovePaneResult:
    """Remove a managed pane (M6 contract).

    1. Missing-row probe (T044 + M6 contract error split):
       - id IS in ``agents`` but NOT in ``managed_pane`` →
         ``managed_pane_protected_adopted`` (adopted-but-not-managed).
       - id is unknown to both tables →
         ``managed_pane_not_found``.
       The split matches contracts/error-codes.md's distinct ``When``
       clauses for the two codes (Pass 26 N38 fix).
    2. ``managed_pane_illegal_transition`` if the pane is in
       ``creating`` (FR-018: cancellation of in-flight create is out
       of scope; operator must wait or use recreate after failure).
    3. ``tmux kill-pane`` via ``tmux_kill_fn``; idempotent — backend
       returning ``{ok: False, error.code == 'tmux_pane_not_found'}``
       counts as success because the operator intent ("the pane is
       gone") is satisfied either way.
    4. Cleanup hooks (routes via FEAT-010, log detach via FEAT-007) are
       best-effort — failures are tolerated because the pane row is
       being archived regardless. Production wiring threads these
       through the daemon's RoutesService + LogService.
    5. Transition state to ``removed``; emit
       ``managed_pane_removed`` lifecycle event.
    """
    with tx_guard(tx_lock):
        pane = select_pane(conn, pane_id)
    if pane is None:
        # M6 error split per contracts/error-codes.md (Pass 26 N38 fix):
        # adopted (in agents, not in managed_pane) → protected_adopted;
        # truly unknown (not in either) → not_found.
        with tx_guard(tx_lock):
            adopted = _pane_id_in_agents_table(conn, pane_id)
        if adopted:
            raise ManagedSessionsError(
                MANAGED_PANE_PROTECTED_ADOPTED,
                details={"agent_id": pane_id, "is_adopted": True},
            )
        raise ManagedSessionsError(
            MANAGED_PANE_NOT_FOUND,
            details={"pane_id": pane_id},
        )

    if pane.state == ManagedState.CREATING:
        raise ManagedSessionsError(
            MANAGED_PANE_ILLEGAL_TRANSITION,
            details={
                "pane_id": pane.id,
                "current_state": pane.state.value,
                "requested_action": "remove",
            },
        )

    if pane.state == ManagedState.REMOVED:
        # Idempotent — already removed.
        return RemovePaneResult(pane_id=pane.id, state=ManagedState.REMOVED)

    lock = serializer.for_container(pane.container_id)
    with lock:
        # 3. tmux kill-pane (best-effort idempotent).
        tmux_ok = True
        if tmux_kill_fn is not None:
            kill_result = tmux_kill_fn(pane)
            tmux_ok = bool(kill_result.get("ok"))
            # ``tmux_pane_not_found`` is a synonym for "already gone";
            # treat as success.
            if not tmux_ok:
                err = kill_result.get("error", {})
                if isinstance(err, dict) and err.get("code") == "tmux_pane_not_found":
                    tmux_ok = True

        # 4. Best-effort cleanup (failures logged but ignored).
        if route_cleanup_fn is not None:
            try:
                route_cleanup_fn(pane)
            except Exception:  # noqa: BLE001 — defensive: cleanup is best-effort
                pass
        if log_detach_fn is not None:
            try:
                log_detach_fn(pane)
            except Exception:  # noqa: BLE001 — defensive
                pass

        # 5. State transition + event. M1 fix: wrap the multi-row write
        #    (pane state + layout state aggregation) in a single
        #    BEGIN IMMEDIATE so a crash between them can't leave the
        #    layout-row stale. The per-container lock already serializes
        #    concurrent operators; the transaction adds crash atomicity.
        now = _utc_now_rfc3339(clock)
        prior_state = pane.state
        new_layout_state: Optional[ManagedState] = None
        layout_prior_state: Optional[ManagedState] = None
        with tx_guard(tx_lock):
            # Close any open implicit transaction from the caller (test
            # fixtures that didn't commit, etc). In production with
            # ``isolation_level=None`` this is a no-op; in tests it
            # commits the setup INSERTs so our BEGIN IMMEDIATE is the
            # only open transaction.
            if conn.in_transaction:
                conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            try:
                update_pane_state(
                    conn, pane.id,
                    state=ManagedState.REMOVED,
                    clear_marker=True,  # any leftover marker is cleared on removal
                    now=now,
                )
                # Aggregate layout state — if all panes are now removed,
                # the layout transitions to removed too.
                layout = select_layout(conn, pane.layout_id)
                if layout is not None and layout.state != ManagedState.REMOVED:
                    refreshed = select_panes_for_layout(conn, pane.layout_id)
                    candidate_state = aggregate_layout_state(
                        [p.state for p in refreshed]
                    )
                    if candidate_state != layout.state:
                        update_layout_state(
                            conn, pane.layout_id,
                            state=candidate_state,
                            now=now,
                        )
                        new_layout_state = candidate_state
                        layout_prior_state = layout.state
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

        # Events emit AFTER the write commits so a partial-commit can't
        # surface a state-change event for state that never landed.
        if event_emitter is not None:
            event_emitter(
                build_event(
                    PANE_REMOVED,
                    actor=actor,
                    layout_id=pane.layout_id,
                    pane_id=pane.id,
                    sequence=1_000,
                    payload={"tmux_kill_succeeded": tmux_ok},
                )
            )
            event_emitter(
                build_event(
                    PANE_STATE_CHANGED,
                    actor=actor,
                    layout_id=pane.layout_id,
                    pane_id=pane.id,
                    sequence=1_001,
                    payload={
                        "prev_state": prior_state.value,
                        "new_state": ManagedState.REMOVED.value,
                    },
                )
            )
            if new_layout_state is not None and layout_prior_state is not None:
                event_emitter(
                    build_event(
                        LAYOUT_STATE_CHANGED,
                        actor=actor,
                        layout_id=pane.layout_id,
                        # H2 fix: monotonic sequence avoids collision
                        # with the spawn pipeline's emission for the
                        # same layout.
                        sequence=_layout_sequence_now(),
                        payload={
                            "prev_state": layout_prior_state.value,
                            "new_state": new_layout_state.value,
                        },
                    )
                )

    return RemovePaneResult(pane_id=pane.id, state=ManagedState.REMOVED)


# ─── T043: recreate_pane (M7) ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RecreatePaneResult:
    """Returned by :func:`recreate_pane` on success — references the
    new managed_pane row, NOT the predecessor."""

    pane_id: str
    predecessor_id: str
    layout_id: str  # the parent layout (= predecessor's layout) the new pane joins
    chain_depth: int
    state: ManagedState  # ManagedState.CREATING on a fresh recreate
    replay: bool = False  # True for an R10 idempotency-key replay (review #10)


# FR-023 / R4 — recreate-chain depth bound. The new row's chain_depth is
# `predecessor.chain_depth + 1`; we reject if predecessor.chain_depth ≥ 15
# (so the new depth would be ≥16, which is the configured bound).
_CHAIN_DEPTH_LIMIT: int = 16
_CHAIN_DEPTH_REJECTION_THRESHOLD: int = 15  # predecessor.chain_depth >= this


def recreate_pane(
    *,
    conn: sqlite3.Connection,
    serializer: ContainerSerializer,
    predecessor_pane_id: str,
    launch_command_override: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    profile_override_dir: Optional[Path] = None,
    event_emitter: Optional[EventEmitter] = None,
    clock: Optional[Callable[[], _dt.datetime]] = None,
    actor: str = "operator",
    tx_lock: Optional[threading.Lock] = None,
) -> RecreatePaneResult:
    """Recreate a managed pane from a predecessor (M7 contract).

    1. T044 adopted-pane protection: if ``predecessor_pane_id`` is not
       in ``managed_pane`` → ``managed_pane_protected_adopted`` (mirrors
       remove_pane's protection — we refuse to recreate from an
       adopted pane).
    2. ``managed_pane_illegal_recreate_source`` if the predecessor is
       not in ``removed`` or ``failed`` (per state-machine.md §Recreate
       semantics: ``ready`` / ``degraded`` / ``creating`` are invalid
       sources — operator must ``remove_pane`` first).
    3. ``managed_pane_recreate_chain_too_deep`` (FR-023 / R4) when
       ``predecessor.chain_depth >= 15`` (the new row would be at depth
       16, the configured bound).
    4. ``managed_pane_concurrent_recreate`` (FR-027) when there's
       already a ``creating``-state successor row pointing at this
       predecessor (operator must wait for the in-flight successor
       to settle to ``ready`` / ``degraded`` / ``failed`` first).
    5. Insert the new ``managed_pane`` row with ``predecessor_id`` set,
       ``chain_depth = predecessor.chain_depth + 1``, a fresh
       ``pending_marker_token`` (= idempotency_key if present, else
       uuid4), and ``state = 'creating'``.
    6. Emit ``managed_pane_recreated`` lifecycle event.
    7. The actual tmux spawn / FEAT-006 register / FEAT-007 log attach
       is the same background pipeline ``create_layout`` uses — kicked
       off by the caller via ``spawn_layout_in_background`` against
       the parent layout. (We don't re-spawn just the new pane here
       because the per-container serializer + the pending-managed
       marker already provide the right semantics; the bg pipeline
       picks up any pane row in ``creating`` state.)
    """
    # M3 fix: idempotency_key flows into the tmux pane title token
    # (``@MANAGED:<token>:<label>``); validate it against the FR-016
    # charset / length / control-char rules before any DB write or
    # tmux RPC.
    if idempotency_key is not None:
        _validate_identifier(idempotency_key, field_name="idempotency_key")
    with tx_guard(tx_lock):
        predecessor = select_pane(conn, predecessor_pane_id)
    if predecessor is None:
        # Same M7 error split as remove_pane (Pass 26 N38 fix):
        # adopted (in agents, not in managed_pane) → protected_adopted;
        # truly unknown (not in either) → not_found.
        with tx_guard(tx_lock):
            adopted = _pane_id_in_agents_table(conn, predecessor_pane_id)
        if adopted:
            raise ManagedSessionsError(
                MANAGED_PANE_PROTECTED_ADOPTED,
                details={"agent_id": predecessor_pane_id, "is_adopted": True},
            )
        raise ManagedSessionsError(
            MANAGED_PANE_NOT_FOUND,
            details={"pane_id": predecessor_pane_id},
        )

    if predecessor.state not in (ManagedState.REMOVED, ManagedState.FAILED):
        raise ManagedSessionsError(
            MANAGED_PANE_ILLEGAL_RECREATE_SOURCE,
            details={
                "predecessor_pane_id": predecessor.id,
                "current_state": predecessor.state.value,
            },
        )

    if predecessor.chain_depth >= _CHAIN_DEPTH_REJECTION_THRESHOLD:
        raise ManagedSessionsError(
            MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP,
            details={
                "predecessor_pane_id": predecessor.id,
                "predecessor_chain_depth": predecessor.chain_depth,
                "limit": _CHAIN_DEPTH_LIMIT,
            },
        )

    # N39 (Pass 26 fix): synchronously resolve the launch_command_override
    # so a bogus profile name surfaces as ``managed_launch_command_not_found``
    # BEFORE inserting the new managed_pane row. Mirrors create_layout's
    # upfront resolve_profile pattern — keeps the M7 contract honest
    # (a synchronous error response, not a delayed background failure).
    # The override is only resolved (not stored as a profile object) so
    # the spawn pipeline can re-read the YAML at spawn time (allowing
    # operators to edit the profile between recreate calls).
    if launch_command_override is not None:
        resolve_profile(launch_command_override, override_dir=profile_override_dir)

    lock = serializer.for_container(predecessor.container_id)
    with lock:
        # review #10: R10 idempotency replay ("same semantics as create").
        # If THIS idempotency_key already produced a successor of this
        # predecessor (its pending_marker_token, set while creating),
        # return that successor as a replay instead of rejecting the
        # safe retry as concurrent_recreate. (The marker is cleared once
        # the pane settles, so replay covers the in-flight retry window —
        # the realistic network-blip case the contract targets.)
        if idempotency_key is not None:
            with tx_guard(tx_lock):
                prior = conn.execute(
                    "SELECT id, state, chain_depth FROM managed_pane "
                    "WHERE predecessor_id = ? AND pending_marker_token = ?",
                    (predecessor.id, idempotency_key),
                ).fetchone()
            if prior is not None:
                return RecreatePaneResult(
                    pane_id=prior[0],
                    predecessor_id=predecessor.id,
                    layout_id=predecessor.layout_id,
                    chain_depth=int(prior[2]),
                    state=ManagedState(prior[1]),
                    replay=True,
                )

        # 4. FR-027: reject when the predecessor already has a NON-TERMINAL
        #    successor (review #6: broadened from 'creating' only to
        #    creating/ready/degraded — a live ready/degraded successor still
        #    occupies the predecessor's tmux-target + label slot, so a second
        #    recreate would trip the partial unique index and raise a raw
        #    IntegrityError). Recreating again is only valid once the prior
        #    successor is itself terminal (removed/failed).
        with tx_guard(tx_lock):
            in_flight = conn.execute(
                "SELECT id FROM managed_pane "
                "WHERE predecessor_id = ? "
                "AND state IN ('creating', 'ready', 'degraded')",
                (predecessor.id,),
            ).fetchone()
        if in_flight is not None:
            raise ManagedSessionsError(
                MANAGED_PANE_CONCURRENT_RECREATE,
                details={
                    "predecessor_pane_id": predecessor.id,
                    "in_flight_successor_pane_id": in_flight[0],
                },
            )

        # 5. Insert the new row.
        new_pane_id = str(uuid.uuid4())
        marker_token = idempotency_key or new_marker_token()
        now = _utc_now_rfc3339(clock)
        new_chain_depth = predecessor.chain_depth + 1
        # Reuse the predecessor's role / capability / label / launch_command
        # so the operator gets a like-for-like replacement. The label
        # uniqueness scope is per-container across non-terminal panes —
        # the predecessor is terminal (removed/failed) so its label is
        # free to be reused.
        # `launch_command_override`, if supplied, replaces the predecessor's
        # launch_command_ref for this recreate only.
        new_launch_ref = (
            launch_command_override if launch_command_override is not None
            else predecessor.launch_command_ref
        )
        new_row = ManagedPaneRow(
            id=new_pane_id,
            layout_id=predecessor.layout_id,
            container_id=predecessor.container_id,
            agent_id=None,
            role=predecessor.role,
            capability=predecessor.capability,
            label=predecessor.label,
            launch_command_ref=new_launch_ref,
            tmux_session_name=predecessor.tmux_session_name,
            tmux_pane_index=predecessor.tmux_pane_index,
            pending_marker_token=marker_token,
            state=ManagedState.CREATING,
            failed_stage=None,
            predecessor_id=predecessor.id,
            chain_depth=new_chain_depth,
            created_at=now,
            updated_at=now,
        )
        # Single-row insert — no explicit transaction needed (atomicity
        # is intrinsic to one statement). The per-container lock above
        # already serializes against other recreate / remove / create
        # against the same container. tx_lock guards the connection
        # against concurrent FEAT-009 worker mutations on the shared
        # ``worker_conn``.
        #
        # review #6: translate the partial-unique-index IntegrityError into
        # the closed-set conflict codes (mirrors create_layout) rather than
        # leaking a raw sqlite3.IntegrityError out of the M7 contract — e.g.
        # when an unrelated live pane (via create_layout or recovery) has
        # re-occupied the freed (tmux_session_name, tmux_pane_index)/label
        # slot between the in-flight check above and this insert.
        with tx_guard(tx_lock):
            try:
                insert_pane(conn, new_row)
            except sqlite3.IntegrityError as exc:
                err_text = str(exc)
                if "tmux_session_name" in err_text and "tmux_pane_index" in err_text:
                    raise ManagedSessionsError(
                        MANAGED_SESSION_NAME_CONFLICT,
                        details={
                            "container_id": new_row.container_id,
                            "tmux_session_name": new_row.tmux_session_name,
                        },
                    ) from exc
                if "container_id" in err_text and "label" in err_text:
                    raise ManagedSessionsError(
                        MANAGED_PANE_LABEL_CONFLICT,
                        details={
                            "container_id": new_row.container_id,
                            "label": new_row.label,
                        },
                    ) from exc
                raise

        # 6. Emit managed_pane_recreated.
        if event_emitter is not None:
            event_emitter(
                build_event(
                    PANE_RECREATED,
                    actor=actor,
                    layout_id=new_row.layout_id,
                    pane_id=new_pane_id,
                    sequence=0,
                    payload={
                        "predecessor_id": predecessor.id,
                        "chain_depth": new_chain_depth,
                    },
                )
            )
            event_emitter(
                build_event(
                    PANE_PENDING_MARKER_SET,
                    actor=actor,
                    pane_id=new_pane_id,
                    sequence=1,
                    payload={"marker_token": marker_token},
                )
            )

        return RecreatePaneResult(
            pane_id=new_pane_id,
            predecessor_id=predecessor.id,
            layout_id=predecessor.layout_id,
            chain_depth=new_chain_depth,
            state=ManagedState.CREATING,
        )


# ─── T045: promote_from_adopted stub (M8) ────────────────────────────────


@dataclass(frozen=True, slots=True)
class PromoteFromAdoptedStubResult:
    """Per FR-018 / state-machine.md §Promotion stub — MVP returns
    ``not_implemented``. The state-machine module's
    ``PROMOTE_FROM_ADOPTED`` constant is exposed for tests; the
    transition itself is gated off."""

    error_code: str  # always "not_implemented"
    details: dict[str, str]


def promote_from_adopted(agent_id: str) -> PromoteFromAdoptedStubResult:
    """MVP stub — always returns ``not_implemented``.

    Per spec §FR-018 and state-machine.md §Promotion stub, the
    ``promote_from_adopted`` transition is reserved for a later feature.
    The service entry point exists so the M8 contract surface is
    reachable (the handler layer translates this into the FEAT-011
    envelope shape with ``error.code = "not_implemented"`` and
    ``details = {"reserved_since": "FEAT-013"}``).
    """
    return PromoteFromAdoptedStubResult(
        error_code="not_implemented",
        details={"reserved_since": "FEAT-013"},
    )
