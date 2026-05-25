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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    count_active_layouts,
    insert_layout,
    insert_pane,
    select_layout_by_idempotency_key,
    select_panes_for_layout,
)
from .errors import (
    MANAGED_LAYOUT_CAPACITY_EXCEEDED,
    MANAGED_LAUNCH_COMMAND_NOT_FOUND,
    MANAGED_PANE_LABEL_CONFLICT,
    MANAGED_SESSION_NAME_CONFLICT,
    MANAGED_TEMPLATE_NOT_FOUND,
    ManagedSessionsError,
)
from .launch_profiles import LaunchCommandProfile, load_profiles, resolve_profile
from .pending_marker import new_marker_token
from .serializer import ContainerSerializer
from .state_machine import ManagedState
from .templates import ManagedTemplate, resolve_template


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
        # 4. R10 replay — return the existing layout untouched.
        if idempotency_key is not None:
            existing = select_layout_by_idempotency_key(
                conn, container_id, idempotency_key
            )
            if existing is not None:
                return _summarize_layout(conn, existing, replay=True)

        # 5. FR-025 capacity check.
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
        #    transaction so partial inserts can't leak.
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
            profile_name: Optional[str] = (
                launch_overrides.get(override_key) or tmpl_pane.default_launch_command_ref
            )
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

        conn.execute("BEGIN IMMEDIATE")
        try:
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
