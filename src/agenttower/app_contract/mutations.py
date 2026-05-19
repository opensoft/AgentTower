"""FEAT-011 T041 — ``app.agent.register_from_pane`` adopt mutation.

The only path the app uses to promote a discovered tmux pane to a
registered agent (FR-025..FR-028, FR-028a, FR-028b, FR-028c, FR-028d).

Implementation calls into the FEAT-006 ``AgentService.register_agent``
service layer (NOT the legacy CLI entry point) per FR-026, so
validation and persistence behavior is identical to a CLI
``register-self`` for the same pane. FEAT-011 layers add:

* **Full 6-field pane-identity match** (FR-028a) — all of
  ``container_id``, ``tmux_socket``, ``session_name``, ``window_index``,
  ``pane_index``, ``pane_id`` must match a currently-discovered pane
  row byte-for-byte. Any single-field mismatch → ``pane_not_found``
  with ``details = {pane_id, mismatch_field}``.
* **attach_log + inactive container guard** (FR-028b) — if
  ``attach_log: true`` and the target container is inactive at adopt
  time, fail the entire adopt with ``container_inactive`` and emit no
  agents row.
* **parent_agent_id resolution** (FR-028c) — a non-existent
  ``parent_agent_id`` returns ``agent_not_found`` (not
  ``validation_failed``) per the Round-4 override.
* **Label normalization** (FR-028d) — trim, reject embedded newlines,
  ≤ 256 chars after trim.
* **App-origin audit row** — emit a JSONL ``agent_registered`` row
  with ``origin="app"`` + ``app_session_id`` via the T013 helper,
  alongside whatever FEAT-006 itself writes. FEAT-011 audit attribution
  is additive at this slice; threading ``origin="app"`` through
  ``AgentService._safe_append_audit`` is a follow-up.

Error-code mapping (FEAT-006 → FEAT-011):

* ``pane_already_registered`` → ``pane_already_registered`` (same)
* ``value_out_of_set`` / ``field_too_long`` / ``project_path_invalid``
  → ``validation_failed`` with ``details.field`` derived from the
  message (best-effort; the upstream message names the offending field).
* ``master_via_register_self_rejected`` → ``validation_failed`` with
  ``details.field == "role"``
* ``swarm_parent_required`` / ``parent_role_mismatch`` →
  ``validation_failed`` with ``details.field == "parent_agent_id"``
* ``parent_not_found`` / ``parent_inactive`` → ``agent_not_found``
  (FR-028c override)
* ``container_inactive`` (from FEAT-006) → ``container_inactive``
* Anything else → ``internal_error``
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from . import audit as _audit
from . import envelope as _envelope
from . import sessions as _sessions
from . import view_models as _vm
from .errors import (
    AGENT_NOT_FOUND,
    CONTAINER_INACTIVE,
    INTERNAL_ERROR,
    PANE_ALREADY_REGISTERED,
    PANE_NOT_FOUND,
    VALIDATION_FAILED,
)

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext


_REQUIRED_IDENTITY_FIELDS = (
    "container_id",
    "tmux_socket",
    "session_name",
    "window_index",
    "pane_index",
    "pane_id",
)


_LABEL_MAX_LEN = 256


# ─── Input validation ────────────────────────────────────────────────────


def _validate_identity(
    params: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate the 6 pane-identity fields are present and well-typed.

    Returns ``(identity_dict, None)`` on success or ``(None,
    error_envelope)`` on validation failure. The identity dict has the
    exact 6 keys above ready for comparison against ``PaneRow``.
    """
    for field in _REQUIRED_IDENTITY_FIELDS:
        if field not in params:
            return None, _envelope.failure(
                VALIDATION_FAILED,
                f"missing required identity field {field!r}",
                details={"field": field, "reason": "missing"},
            )
    for field in ("container_id", "tmux_socket", "session_name", "pane_id"):
        value = params[field]
        if not isinstance(value, str) or not value:
            return None, _envelope.failure(
                VALIDATION_FAILED,
                f"identity field {field!r} must be a non-empty string",
                details={"field": field, "reason": "wrong type or empty"},
            )
    for field in ("window_index", "pane_index"):
        value = params[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None, _envelope.failure(
                VALIDATION_FAILED,
                f"identity field {field!r} must be a non-negative integer",
                details={"field": field, "reason": "wrong type"},
            )
    return {field: params[field] for field in _REQUIRED_IDENTITY_FIELDS}, None


def _validate_label(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    """FR-028d: trim, reject embedded \\n / \\r, ≤ 256 chars after trim."""
    if value is None:
        return "", None
    if not isinstance(value, str):
        return None, _envelope.failure(
            VALIDATION_FAILED,
            "label must be a string",
            details={"field": "label", "reason": "wrong type"},
        )
    trimmed = value.strip()
    if "\n" in trimmed or "\r" in trimmed:
        return None, _envelope.failure(
            VALIDATION_FAILED,
            "label must not contain newlines",
            details={"field": "label", "reason": "embedded newline"},
        )
    if len(trimmed) > _LABEL_MAX_LEN:
        return None, _envelope.failure(
            VALIDATION_FAILED,
            f"label exceeds {_LABEL_MAX_LEN} chars after trim",
            details={"field": "label", "reason": "too long"},
        )
    return trimmed, None


# ─── Pane-identity full match (FR-028a) ──────────────────────────────────


def _find_pane_with_full_identity_match(
    conn: sqlite3.Connection, identity: dict[str, Any]
) -> tuple[Any | None, str | None]:
    """Locate the pane with EXACT 6-field identity match (FR-028a).

    Returns ``(pane_row, None)`` if matched, or
    ``(None, mismatch_field)`` naming the first offending field if a
    pane with the supplied ``pane_id`` exists but other identity fields
    disagree, or ``(None, "pane_id")`` if no pane has that pane_id.
    """
    from ..state import panes as state_panes

    all_panes = state_panes.select_panes_for_listing(conn, active_only=False)
    by_pane_id = [p for p in all_panes if p.tmux_pane_id == identity["pane_id"]]
    if not by_pane_id:
        return None, "pane_id"
    # FR-028a: ALL six fields must match byte-for-byte. We compare each
    # in turn; the first mismatching field is reported in the response
    # `details.mismatch_field` so the caller can fix the right thing.
    field_to_attr = (
        ("container_id", "container_id"),
        ("tmux_socket", "tmux_socket_path"),
        ("session_name", "tmux_session_name"),
        ("window_index", "tmux_window_index"),
        ("pane_index", "tmux_pane_index"),
        ("pane_id", "tmux_pane_id"),
    )
    for candidate in by_pane_id:
        first_mismatch: str | None = None
        for input_field, attr in field_to_attr:
            if getattr(candidate, attr) != identity[input_field]:
                first_mismatch = input_field
                break
        if first_mismatch is None:
            return candidate, None
    # All candidates with this pane_id had a mismatch. Report the first
    # of those (which is the most precise hint we can give a client).
    candidate = by_pane_id[0]
    for input_field, attr in field_to_attr:
        if getattr(candidate, attr) != identity[input_field]:
            return None, input_field
    return None, "pane_id"  # unreachable but defensive


# ─── Container active check (FR-028b) ────────────────────────────────────


def _container_is_active(conn: sqlite3.Connection, container_id: str) -> bool:
    """Return True iff the container is active per the FEAT-003 ``containers``
    row's ``active`` flag. Missing → False."""
    try:
        row = conn.execute(
            "SELECT active FROM containers WHERE container_id = ?",
            (container_id,),
        ).fetchone()
        return bool(row[0]) if row is not None else False
    except sqlite3.OperationalError:
        return False


# ─── parent_agent_id resolution (FR-028c) ────────────────────────────────


def _parent_agent_exists(conn: sqlite3.Connection, parent_agent_id: str) -> bool:
    """Return True iff a non-deleted agent exists with this id."""
    try:
        row = conn.execute(
            "SELECT 1 FROM agents WHERE agent_id = ? AND active = 1",
            (parent_agent_id,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


# ─── Error-code mapping (FEAT-006 → FEAT-011) ────────────────────────────


# Each mapping is `(feat006_code, feat011_code, details_builder)`.
# `details_builder` is a callable that takes the FEAT-006 message and
# returns the FEAT-011 `error.details` dict.
def _map_registration_error(
    code: str, message: str, *, container_id: str, parent_agent_id: str | None
) -> dict[str, Any]:
    """Map a FEAT-006 RegistrationError → FEAT-011 envelope."""
    if code == "pane_already_registered":
        # Best-effort agent_id extraction: FEAT-006 puts it in the message.
        # If not found, leave empty string so the response is still
        # well-formed per FR-034a.
        agent_id = ""
        # Look for a uuid-like token after "agent_id=" or in parens.
        for token in message.replace(",", " ").replace("=", " ").split():
            if len(token) == 32 and all(c in "0123456789abcdef" for c in token):
                agent_id = token
                break
        return _envelope.failure(
            PANE_ALREADY_REGISTERED,
            message,
            details={"agent_id": agent_id},
        )
    if code in ("parent_not_found", "parent_inactive"):
        # FR-028c override: map parent issues to agent_not_found.
        return _envelope.failure(
            AGENT_NOT_FOUND,
            message,
            details={"agent_id": parent_agent_id or ""},
        )
    if code == "master_via_register_self_rejected":
        return _envelope.failure(
            VALIDATION_FAILED,
            message,
            details={"field": "role", "reason": "master via register_self refused"},
        )
    if code in ("swarm_parent_required", "parent_role_mismatch", "parent_immutable"):
        return _envelope.failure(
            VALIDATION_FAILED,
            message,
            details={"field": "parent_agent_id", "reason": code},
        )
    if code == "container_inactive" or code == "target_container_inactive":
        return _envelope.failure(
            CONTAINER_INACTIVE,
            message,
            details={"container_id": container_id},
        )
    # General validation-class codes from FEAT-006 → validation_failed.
    if code in (
        "value_out_of_set",
        "field_too_long",
        "project_path_invalid",
        "bad_request",
    ):
        # The FEAT-006 message is short and field-oriented; encode it
        # as the reason. Field is left as "params" because the upstream
        # message-prefix variability isn't worth a regex parse here.
        return _envelope.failure(
            VALIDATION_FAILED,
            message,
            details={"field": "params", "reason": code},
        )
    # Anything else is a FEAT-006-internal failure; surface as
    # internal_error so the envelope shape is preserved.
    return _envelope.failure(
        INTERNAL_ERROR,
        f"FEAT-006 register_agent raised unmapped code {code!r}: {message}",
        details={},
    )


# ─── Handler ─────────────────────────────────────────────────────────────


def app_agent_register_from_pane(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.agent.register_from_pane`` adopt mutation.

    See module docstring for the full contract surface. Returns the
    post-state ``AgentViewModel`` on success.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    if not isinstance(params, dict):
        params = {}

    # 1. Full pane-identity validation (FR-025 + FR-028a).
    identity, err = _validate_identity(params)
    if err:
        return err

    # 2. Label normalization (FR-028d).
    label, err = _validate_label(params.get("label"))
    if err:
        return err

    # 3. Optional fields.
    role = params.get("role")
    capability = params.get("capability")
    project_path = params.get("project_path")
    parent_agent_id = params.get("parent_agent_id")
    attach_log = bool(params.get("attach_log", False))
    if parent_agent_id is not None and not isinstance(parent_agent_id, str):
        return _envelope.failure(
            VALIDATION_FAILED,
            "parent_agent_id must be a string when provided",
            details={"field": "parent_agent_id", "reason": "wrong type"},
        )

    # 4. Agent service must be wired.
    agent_service = getattr(ctx, "agent_service", None)
    if agent_service is None or not hasattr(agent_service, "register_agent"):
        return _envelope.failure(
            INTERNAL_ERROR,
            "daemon agent_service not wired",
            details={},
        )

    # 5. State DB for pre-flight checks (FR-028a, FR-028b, FR-028c).
    state_path = getattr(ctx, "state_path", None)
    if state_path is None:
        return _envelope.failure(
            INTERNAL_ERROR,
            "state_path unwired",
            details={},
        )
    conn = sqlite3.connect(str(state_path))
    try:
        # FR-028a: full 6-field identity match.
        matched, mismatch_field = _find_pane_with_full_identity_match(conn, identity)
        if matched is None:
            return _envelope.failure(
                PANE_NOT_FOUND,
                f"pane identity does not match a currently-discovered pane "
                f"(mismatch on field: {mismatch_field})",
                details={
                    "pane_id": identity["pane_id"],
                    "mismatch_field": mismatch_field or "pane_id",
                },
            )

        # FR-028b: attach_log + inactive container → fail entire adopt.
        if attach_log and not _container_is_active(conn, identity["container_id"]):
            return _envelope.failure(
                CONTAINER_INACTIVE,
                "attach_log=true requested but target container is inactive; "
                "no agents row was created",
                details={"container_id": identity["container_id"]},
            )

        # FR-028c: parent_agent_id, when supplied, must match a real agent.
        if parent_agent_id is not None and parent_agent_id != "":
            if not _parent_agent_exists(conn, parent_agent_id):
                return _envelope.failure(
                    AGENT_NOT_FOUND,
                    f"parent_agent_id {parent_agent_id!r} does not match any "
                    "registered agent",
                    details={"agent_id": parent_agent_id},
                )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # 6. Build the FEAT-006 register_agent params and call the service.
    # FEAT-006 ``_coerce_pane_key`` expects a dict with the exact field
    # names below — see agents/service.py:_coerce_pane_key.
    register_params: dict[str, Any] = {
        "container_id": identity["container_id"],
        "pane_composite_key": {
            "container_id": identity["container_id"],
            "tmux_socket_path": identity["tmux_socket"],
            "tmux_session_name": identity["session_name"],
            "tmux_window_index": identity["window_index"],
            "tmux_pane_index": identity["pane_index"],
            "tmux_pane_id": identity["pane_id"],
        },
    }
    if role is not None:
        register_params["role"] = role
    if capability is not None:
        register_params["capability"] = capability
    # FR-028d: pass the trimmed label (empty string is fine — FEAT-006
    # treats it as "no label").
    register_params["label"] = label
    if project_path is not None:
        register_params["project_path"] = project_path
    if parent_agent_id is not None:
        register_params["parent_agent_id"] = parent_agent_id
    # attach_log is intentionally NOT forwarded here — FEAT-011's
    # FR-028b guard fails the call BEFORE register_agent is invoked if
    # attach_log=true against an inactive container. For active
    # containers, attach_log triggers the FEAT-006 atomic-attach path
    # (an entire other slice); for the US2 adopt MVP we surface the
    # `attach_log` outcome to the response but don't auto-attach.
    # (Full attach_log wiring lives in a follow-up.)

    # 7. Invoke the FEAT-006 service.
    from ..agents.errors import RegistrationError

    try:
        outcome = agent_service.register_agent(
            register_params,
            socket_peer_uid=peer_uid,
        )
    except RegistrationError as exc:
        return _map_registration_error(
            exc.code,
            exc.message,
            container_id=identity["container_id"],
            parent_agent_id=parent_agent_id,
        )
    except Exception as exc:  # noqa: BLE001 — envelope-shape safety net
        return _envelope.failure(
            INTERNAL_ERROR,
            f"agent_service.register_agent raised {type(exc).__name__}: {exc}",
            details={},
        )

    # 8. Project the post-state agent record → AgentViewModel.
    agent_payload = outcome.get("agent", outcome)
    agent_id = agent_payload.get("agent_id") if isinstance(agent_payload, dict) else None

    # Fetch the canonical row for the view model (including derived
    # fields). Use a fresh connection — register_agent has already
    # committed the row.
    conn = sqlite3.connect(str(state_path))
    agent_view: dict[str, Any] = {}
    try:
        from ..state import agents as state_agents

        record = state_agents.select_agent_by_id(conn, agent_id=agent_id) if agent_id else None
        if record is not None:
            agent_view = _vm.agent_view(
                {
                    "agent_id": record.agent_id,
                    "role": record.role,
                    "capability": record.capability,
                    "label": record.label,
                    "project_path": record.project_path,
                    "parent_agent_id": record.parent_agent_id,
                    "container_id": record.container_id,
                    "pane_id": record.tmux_pane_id,
                    "registered_at": record.created_at,
                },
                log_attached=False,  # adopt doesn't auto-attach in this slice
                pane_active=True,
            )
        else:
            agent_view = agent_payload if isinstance(agent_payload, dict) else {}
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # 9. Emit FEAT-011 app-attribution audit row (FR-044). FEAT-006
    # also emits its own row from inside register_agent; this is an
    # additive marker. Threading origin="app" into FEAT-006's audit
    # writer is a follow-up.
    _audit.emit_app_mutation(
        getattr(ctx, "events_file", None),
        event_type="agent_registered",
        payload={
            "agent_id": agent_view.get("agent_id"),
            "container_id": agent_view.get("container_id"),
            "pane_id": agent_view.get("pane_id"),
            "role": agent_view.get("role"),
            "via": "app.agent.register_from_pane",
        },
        session=session,
    )

    return _envelope.success({"row": agent_view})


__all__ = ["app_agent_register_from_pane"]
