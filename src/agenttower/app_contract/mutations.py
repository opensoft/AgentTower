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
    LOG_ATTACH_BLOCKED,
    PANE_ALREADY_REGISTERED,
    PANE_NOT_FOUND,
    PERMISSION_DENIED,
    QUEUE_MESSAGE_NOT_FOUND,
    ROUTE_NOT_FOUND,
    ROUTING_DISABLED,
    STALE_OBJECT,
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
    return _envelope.internal_error_logged(
        "FEAT-006 register_agent (unmapped upstream code)", f"{code}: {message}"
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
    # The production daemon sets ``state_path`` to the state dir;
    # tests sometimes point it at the SQLite file. Use reads' helper
    # to coerce both shapes to the same file path.
    from . import reads as _reads

    db_path = _reads._resolve_state_db_path(ctx)
    if db_path is None:
        return _envelope.failure(
            INTERNAL_ERROR,
            "state_path unwired",
            details={},
        )
    conn = sqlite3.connect(str(db_path))
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
        return _envelope.internal_error_logged("agent_service.register_agent", exc)

    # 8. Project the post-state agent record → AgentViewModel.
    agent_payload = outcome.get("agent", outcome)
    agent_id = agent_payload.get("agent_id") if isinstance(agent_payload, dict) else None

    # Fetch the canonical row for the view model (including derived
    # fields). Use a fresh connection — register_agent has already
    # committed the row.
    conn = sqlite3.connect(str(db_path))
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


# ═══════════════════════════════════════════════════════════════════════
# US3 — Operator mutations (T060–T065)
# ═══════════════════════════════════════════════════════════════════════
#
# Each handler is a thin host-only façade over an upstream service:
#
#   * T060 ``app.agent.update``    → FEAT-006 ``AgentService.set_role`` /
#     ``set_label`` / ``set_capability`` (project_path: see note below).
#   * T061 ``app.log.attach``      → FEAT-007 ``LogService.attach_log``.
#   * T062 ``app.log.detach``      → FEAT-007 ``LogService.detach_log``
#     (success-idempotent per FR-029b).
#   * T063 ``app.send_input``      → FEAT-009 ``QueueService.send_input``
#     with the T011 per-session ``IdempotencyStore`` (FR-031a).
#   * T064 ``app.queue.{approve,delay,cancel}`` → FEAT-009
#     ``QueueService.{approve,delay,cancel}``.
#   * T065 ``app.route.{add,remove,update}`` → FEAT-010
#     ``RoutesService.{add_route,remove_route,enable_route/disable_route}``.
#
# Upstream-service-gap note (T060 project_path): FEAT-006 ships
# ``set_role`` / ``set_label`` / ``set_capability`` standalone service
# methods but NO ``set_project_path`` — the only path that mutates
# ``project_path`` upstream is ``register_agent`` re-registration. To keep
# ``app.agent.update`` a single atomic operator action without forcing a
# full re-registration round-trip, the ``project_path`` field is applied
# with a direct, single-column ``UPDATE agents`` here (guarded the same
# way the adopt handler guards its direct state-DB reads). A FEAT-006
# ``set_project_path`` service method is the proper follow-up.


_VALID_ROLES = ("master", "slave", "swarm", "test-runner", "shell", "unknown")
_CAPABILITY_MAX_LEN = 128
# M2: explicit cap on the serialized app.send_input payload (16 KiB).
# Well under the 64 KiB NDJSON request-line cap so the field-attributed
# validation_failed fires before the generic wire-level payload_too_large.
# Documented in contracts/app-methods.md.
_SEND_INPUT_PAYLOAD_MAX_BYTES = 16384


# ─── Per-session idempotency store registry (FR-031a) ────────────────────


# The T011 ``IdempotencyStore`` is per-session, but ``AppSession`` is a
# frozen dataclass with no store attribute, and there is no per-session
# store wiring yet. Until that wiring lands, keep a process-wide map from
# ``app_session_id`` → ``IdempotencyStore`` so dedupe is still scoped per
# session (FR-031a) and a session's store is garbage-collected when the
# session is dropped via ``drop_idempotency_store``. (Unwired-service gap
# noted in the T060–T065 handoff.)
import threading as _threading

from .idempotency import MAX_KEY_LENGTH as _IDEMP_MAX_KEY_LEN
from .idempotency import IdempotencyStore as _IdempotencyStore

_idempotency_stores: dict[int, _IdempotencyStore] = {}
_idempotency_stores_lock = _threading.Lock()


def _store_for_session(app_session_id: int) -> _IdempotencyStore:
    """Return the per-session ``IdempotencyStore``, creating it on first use."""
    with _idempotency_stores_lock:
        store = _idempotency_stores.get(app_session_id)
        if store is None:
            store = _IdempotencyStore()
            _idempotency_stores[app_session_id] = store
        return store


def drop_idempotency_store(app_session_id: int) -> None:
    """Test seam / session-eviction hook — drop a session's dedupe store."""
    with _idempotency_stores_lock:
        _idempotency_stores.pop(app_session_id, None)


# ─── Shared helpers ──────────────────────────────────────────────────────


def _state_db_or_error(ctx: "DaemonContext"):
    """Resolve the state-DB path. Returns ``(path, None)`` or ``(None, env)``."""
    from . import reads as _reads

    db_path = _reads._resolve_state_db_path(ctx)
    if db_path is None:
        return None, _envelope.failure(
            INTERNAL_ERROR, "state_path unwired", details={}
        )
    return db_path, None


def _agent_view_from_db(db_path, agent_id: str) -> dict[str, Any] | None:
    """Build a full ``AgentViewModel`` for ``agent_id`` from the state DB.

    Derives ``log_attached`` from the FEAT-007 ``log_attachments`` table
    (an ``active`` row for the agent). Returns ``None`` if the agent row
    does not exist.
    """
    from ..state import agents as state_agents

    conn = sqlite3.connect(str(db_path))
    try:
        record = state_agents.select_agent_by_id(conn, agent_id=agent_id)
        if record is None:
            return None
        log_attached = False
        try:
            row = conn.execute(
                "SELECT 1 FROM log_attachments "
                "WHERE agent_id = ? AND status = 'active'",
                (agent_id,),
            ).fetchone()
            log_attached = row is not None
        except sqlite3.OperationalError:
            log_attached = False
        return _vm.agent_view(
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
            log_attached=log_attached,
            pane_active=True,
        )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _map_registration_error_generic(
    code: str, message: str, *, agent_id: str
) -> dict[str, Any]:
    """Map a FEAT-006 ``RegistrationError`` from a set-* call → FEAT-011 env.

    Used by ``app.agent.update`` / ``app.log.{attach,detach}``. ``agent_id``
    is threaded into ``agent_not_found`` / ``log_attach_blocked`` details.
    """
    if code in ("agent_not_found", "agent_inactive"):
        return _envelope.failure(
            AGENT_NOT_FOUND, message, details={"agent_id": agent_id}
        )
    if code in ("container_inactive", "target_container_inactive"):
        return _envelope.failure(
            CONTAINER_INACTIVE, message, details={"container_id": ""}
        )
    if code in ("tmux_unavailable", "log_path_in_use", "pipe_pane_failed"):
        return _envelope.failure(
            LOG_ATTACH_BLOCKED,
            message,
            details={"agent_id": agent_id, "reason": code},
        )
    if code in (
        "value_out_of_set",
        "field_too_long",
        "project_path_invalid",
        "bad_request",
        "swarm_role_via_set_role_rejected",
        "master_confirm_required",
    ):
        return _envelope.failure(
            VALIDATION_FAILED, message, details={"field": "params", "reason": code}
        )
    return _envelope.internal_error_logged(
        "upstream agent/log service (unmapped code)", f"{code}: {message}"
    )


# ─── T060 — app.agent.update ─────────────────────────────────────────────


def app_agent_update(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.agent.update`` — role / capability / label / project_path update.

    FR-029 / FR-029a / FR-030a. Last-write-wins; NEVER returns
    ``stale_object``. Absent field = no change; empty string clears
    ``project_path`` / ``label`` only; empty string on ``role`` /
    ``capability`` → ``validation_failed`` with the per-field reason.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    agent_id = params.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "agent_id must be a non-empty string",
            details={"field": "agent_id", "reason": "missing or wrong type"},
        )

    agent_service = getattr(ctx, "agent_service", None)
    if agent_service is None or not hasattr(agent_service, "set_role"):
        return _envelope.failure(
            INTERNAL_ERROR, "daemon agent_service not wired", details={}
        )

    db_path, err = _state_db_or_error(ctx)
    if err:
        return err

    # FR-029a field-validation pass — runs BEFORE any mutation so an
    # invalid field rejects the whole call without partial application.
    has_role = "role" in params
    has_capability = "capability" in params
    has_label = "label" in params
    has_project = "project_path" in params

    role = params.get("role")
    capability = params.get("capability")
    project_path = params.get("project_path")

    if has_role:
        if not isinstance(role, str):
            return _envelope.failure(
                VALIDATION_FAILED,
                "role must be a string",
                details={"field": "role", "reason": "wrong type"},
            )
        if role == "":
            return _envelope.failure(
                VALIDATION_FAILED,
                "role is not clearable",
                details={
                    "field": "role",
                    "reason": "field is not clearable; provide a valid "
                    "value from the role closed set",
                },
            )
        if role not in _VALID_ROLES:
            return _envelope.failure(
                VALIDATION_FAILED,
                f"role must be one of {list(_VALID_ROLES)}",
                details={"field": "role", "reason": "not in role closed set"},
            )
    if has_capability:
        if not isinstance(capability, str):
            return _envelope.failure(
                VALIDATION_FAILED,
                "capability must be a string",
                details={"field": "capability", "reason": "wrong type"},
            )
        if capability == "":
            return _envelope.failure(
                VALIDATION_FAILED,
                "capability is not clearable",
                details={
                    "field": "capability",
                    "reason": "field is not clearable; provide a non-empty value",
                },
            )
    if has_label:
        label, label_err = _validate_label(params.get("label"))
        if label_err:
            return label_err
    else:
        label = None
    if has_project and project_path is not None and not isinstance(
        project_path, str
    ):
        return _envelope.failure(
            VALIDATION_FAILED,
            "project_path must be a string",
            details={"field": "project_path", "reason": "wrong type"},
        )

    # Apply each requested field. set_* methods are individually atomic;
    # last-write-wins (FR-030a) — no version guard.
    from ..agents.errors import RegistrationError

    applied_any = False
    try:
        if has_role:
            agent_service.set_role(
                {"agent_id": agent_id, "role": role, "confirm": True},
                socket_peer_uid=peer_uid,
            )
            applied_any = True
        if has_capability:
            agent_service.set_capability(
                {"agent_id": agent_id, "capability": capability},
                socket_peer_uid=peer_uid,
            )
            applied_any = True
        if has_label:
            agent_service.set_label(
                {"agent_id": agent_id, "label": label},
                socket_peer_uid=peer_uid,
            )
            applied_any = True
    except RegistrationError as exc:
        return _map_registration_error_generic(
            exc.code, exc.message, agent_id=agent_id
        )
    except Exception as exc:  # noqa: BLE001 — envelope-shape safety net
        return _envelope.internal_error_logged("agent update", exc)

    # project_path — direct single-column UPDATE (no FEAT-006 service
    # method exists; see the module gap note above). Empty string clears
    # the field per FR-029a.
    if has_project:
        from ..state import agents as state_agents

        conn = sqlite3.connect(str(db_path))
        try:
            existing = state_agents.select_agent_by_id(conn, agent_id=agent_id)
            if existing is None:
                return _envelope.failure(
                    AGENT_NOT_FOUND,
                    f"agent {agent_id!r} not found",
                    details={"agent_id": agent_id},
                )
            new_project = project_path if project_path is not None else ""
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE agents SET project_path = ? WHERE agent_id = ?",
                (new_project, agent_id),
            )
            conn.execute("COMMIT")
            applied_any = True
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return _envelope.internal_error_logged("project_path update", exc)
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    # Project the post-update row. If no field was supplied the call is a
    # no-op that still returns the current row (FR-030 post-state).
    agent_view = _agent_view_from_db(db_path, agent_id)
    if agent_view is None:
        return _envelope.failure(
            AGENT_NOT_FOUND,
            f"agent {agent_id!r} not found",
            details={"agent_id": agent_id},
        )

    if applied_any:
        _audit.emit_app_mutation(
            getattr(ctx, "events_file", None),
            event_type="agent_updated",
            payload={
                "agent_id": agent_id,
                "via": "app.agent.update",
                "fields": [
                    f
                    for f, present in (
                        ("role", has_role),
                        ("capability", has_capability),
                        ("label", has_label),
                        ("project_path", has_project),
                    )
                    if present
                ],
            },
            session=session,
        )

    return _envelope.success({"row": agent_view})


# ─── T061 / T062 — app.log.attach / app.log.detach ───────────────────────


def _log_service_or_error(ctx: "DaemonContext"):
    """Return ``(log_service, None)`` or ``(None, error_envelope)``."""
    svc = getattr(ctx, "log_service", None)
    if svc is None or not hasattr(svc, "attach_log"):
        return None, _envelope.failure(
            INTERNAL_ERROR, "daemon log_service not wired", details={}
        )
    return svc, None


def app_log_attach(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.log.attach`` — attach the FEAT-007 log pipe for an agent."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    agent_id = params.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "agent_id must be a non-empty string",
            details={"field": "agent_id", "reason": "missing or wrong type"},
        )

    log_service, err = _log_service_or_error(ctx)
    if err:
        return err
    db_path, err = _state_db_or_error(ctx)
    if err:
        return err

    from ..agents.errors import RegistrationError

    try:
        log_service.attach_log(
            {"agent_id": agent_id}, socket_peer_uid=peer_uid, source="explicit"
        )
    except RegistrationError as exc:
        return _map_registration_error_generic(
            exc.code, exc.message, agent_id=agent_id
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("log_service.attach_log", exc)

    agent_view = _agent_view_from_db(db_path, agent_id)
    if agent_view is None:
        return _envelope.failure(
            AGENT_NOT_FOUND,
            f"agent {agent_id!r} not found",
            details={"agent_id": agent_id},
        )

    _audit.emit_app_mutation(
        getattr(ctx, "events_file", None),
        event_type="log_attachment_changed",
        payload={
            "agent_id": agent_id,
            "new_status": "active",
            "via": "app.log.attach",
        },
        session=session,
    )
    return _envelope.success({"row": agent_view})


def app_log_detach(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.log.detach`` — detach the FEAT-007 log pipe (FR-029b).

    Success-idempotent: detaching a never-attached log returns a success
    envelope carrying the agent view with ``log_attached: false`` — the
    upstream ``attachment_not_found`` code is swallowed here. The only
    failure code is ``agent_not_found``.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    agent_id = params.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "agent_id must be a non-empty string",
            details={"field": "agent_id", "reason": "missing or wrong type"},
        )

    log_service, err = _log_service_or_error(ctx)
    if err:
        return err
    db_path, err = _state_db_or_error(ctx)
    if err:
        return err

    from ..agents.errors import RegistrationError

    detached = False
    try:
        log_service.detach_log({"agent_id": agent_id}, socket_peer_uid=peer_uid)
        detached = True
    except RegistrationError as exc:
        # FR-029b: "no active attachment" is NOT an error — return success
        # with log_attached:false. Everything else maps normally.
        if exc.code == "attachment_not_found":
            detached = False
        else:
            return _map_registration_error_generic(
                exc.code, exc.message, agent_id=agent_id
            )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("log_service.detach_log", exc)

    agent_view = _agent_view_from_db(db_path, agent_id)
    if agent_view is None:
        return _envelope.failure(
            AGENT_NOT_FOUND,
            f"agent {agent_id!r} not found",
            details={"agent_id": agent_id},
        )

    # Only a real detach (a previously-attached log) emits an audit row.
    if detached:
        _audit.emit_app_mutation(
            getattr(ctx, "events_file", None),
            event_type="log_attachment_changed",
            payload={
                "agent_id": agent_id,
                "new_status": "detached",
                "via": "app.log.detach",
            },
            session=session,
        )
    return _envelope.success({"row": agent_view})


# ─── T063 — app.send_input ───────────────────────────────────────────────


def _queue_view_from_row(row: Any) -> dict[str, Any]:
    """Project a FEAT-009 ``QueueRow`` (or dict) → ``QueueViewModel``."""
    return _vm.queue_view(
        {
            "message_id": getattr(row, "message_id", None),
            "state": getattr(row, "state", ""),
            "block_reason": getattr(row, "block_reason", None),
            "failure_reason": getattr(row, "failure_reason", None),
            "sender_agent_id": getattr(row, "sender_agent_id", None),
            "target_agent_id": getattr(row, "target_agent_id", None),
            "payload_preview": "",
            "enqueued_at": getattr(row, "enqueued_at", None),
            "last_updated_at": getattr(row, "last_updated_at", None),
        }
    )


def _host_operator_sender():
    """Synthetic ``AgentRecord`` for the host operator (M4).

    ``app.send_input`` originates from the host control panel, not a
    bench-container pane, so no real ``agents`` row exists to act as
    the FEAT-009 sender. This record attributes the queue row's
    ``sender_agent_id`` to the ``HOST_OPERATOR_SENTINEL`` literal (kept
    disjoint from real ``agt_<hex>`` ids by construction) and carries
    ``role="master"`` so the FEAT-009 permission gate treats the
    operator as a permitted sender — ``master`` is the sole member of
    ``routing.permissions._PERMITTED_SENDER_ROLES``.
    """
    from ..agents.identifiers import HOST_OPERATOR_SENTINEL
    from ..state.agents import AgentRecord

    return AgentRecord(
        agent_id=HOST_OPERATOR_SENTINEL,
        container_id="",
        tmux_socket_path="",
        tmux_session_name="",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id="",
        role="master",
        capability="",
        label="host-operator",
        project_path="",
        parent_agent_id=None,
        effective_permissions={},
        created_at="",
        last_registered_at="",
        last_seen_at=None,
        active=True,
    )


def app_send_input(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.send_input`` — route a payload to a target agent (FR-031/031a).

    Honors the FEAT-009 per-message permission gate (→ ``permission_denied``)
    and global kill switch (→ ``routing_disabled``). Optional
    ``idempotency_key`` deduplicates per-session retries (FR-031a).
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    target_agent_id = params.get("target_agent_id")
    if not isinstance(target_agent_id, str) or not target_agent_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "target_agent_id must be a non-empty string",
            details={"field": "target_agent_id", "reason": "missing or wrong type"},
        )

    payload = params.get("payload")
    if not isinstance(payload, dict):
        return _envelope.failure(
            VALIDATION_FAILED,
            "payload must be a JSON object",
            details={"field": "payload", "reason": "missing or wrong type"},
        )

    idempotency_key = params.get("idempotency_key")
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str):
            return _envelope.failure(
                VALIDATION_FAILED,
                "idempotency_key must be a string when provided",
                details={"field": "idempotency_key", "reason": "wrong type"},
            )
        if len(idempotency_key) > _IDEMP_MAX_KEY_LEN:
            return _envelope.failure(
                VALIDATION_FAILED,
                f"idempotency_key exceeds {_IDEMP_MAX_KEY_LEN} chars",
                details={"field": "idempotency_key", "reason": "too long"},
            )

    queue_service = getattr(ctx, "queue_service", None)
    if queue_service is None or not hasattr(queue_service, "send_input"):
        return _envelope.failure(
            INTERNAL_ERROR, "daemon queue_service not wired", details={}
        )

    # FR-031a: dedupe — replay the recorded response on a key hit.
    store = _store_for_session(session.app_session_id)
    if idempotency_key is not None:
        hit = store.lookup(idempotency_key)
        if hit is not None:
            recorded = hit.deduplicated_response
            result = dict(recorded.get("result", {}))
            result["deduplicated"] = True
            return {
                "ok": recorded.get("ok", True),
                "app_contract_version": recorded.get(
                    "app_contract_version", _envelope.success()[
                        "app_contract_version"
                    ]
                ),
                "result": result,
            }

    # Resolve the target up-front so a bad target → agent_not_found.
    from ..routing.errors import QueueServiceError, TargetResolveError

    try:
        target_resolved = queue_service.resolve_target_agent_id(target_agent_id)
    except TargetResolveError as exc:
        return _envelope.failure(
            AGENT_NOT_FOUND,
            f"target_agent_id {target_agent_id!r}: {exc.message}",
            details={"agent_id": target_agent_id},
        )
    except QueueServiceError as exc:
        return _envelope.internal_error_logged(
            "target resolution", f"{exc.code}: {exc.message}"
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("target resolution", exc)

    # M4: the host operator is not a bench agent — there is no sender
    # pane. FEAT-009 ``send_input`` requires an ``AgentRecord`` sender;
    # build a synthetic host-operator record so (a) the queue row's
    # ``sender_agent_id`` is correctly attributed to the host operator
    # rather than mis-attributed to the target's own row, and (b) the
    # FEAT-009 permission gate evaluates the operator as a permitted
    # sender. Target existence was already validated by
    # ``resolve_target_agent_id`` above.
    sender_record = _host_operator_sender()

    import json as _json

    try:
        body_bytes = _json.dumps(payload, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        return _envelope.failure(
            VALIDATION_FAILED,
            "payload is not JSON-serializable",
            details={"field": "payload", "reason": "not serializable"},
        )
    # M2: explicit field-attributed cap on the serialized payload, so an
    # oversized body fails as validation_failed(field="payload") rather
    # than riding the incidental 64 KiB NDJSON line cap.
    if len(body_bytes) > _SEND_INPUT_PAYLOAD_MAX_BYTES:
        return _envelope.failure(
            VALIDATION_FAILED,
            f"payload exceeds the {_SEND_INPUT_PAYLOAD_MAX_BYTES}-byte "
            f"app.send_input limit when serialized",
            details={"field": "payload", "reason": "too large"},
        )

    try:
        outcome = queue_service.send_input(
            sender=sender_record,
            target_input=target_agent_id,
            body_bytes=body_bytes,
            wait=False,
        )
    except QueueServiceError as exc:
        if exc.code == "routing_disabled":
            return _envelope.failure(
                ROUTING_DISABLED, exc.message, details={}
            )
        if exc.code in ("sender_role_not_permitted", "target_not_active"):
            return _envelope.failure(
                PERMISSION_DENIED,
                exc.message,
                details={"reason": "feat009_permission_gate"},
            )
        if exc.code in ("agent_not_found", "target_label_ambiguous"):
            return _envelope.failure(
                AGENT_NOT_FOUND,
                exc.message,
                details={"agent_id": target_agent_id},
            )
        return _envelope.internal_error_logged(
            "send_input", f"{exc.code}: {exc.message}"
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("send_input", exc)

    row = getattr(outcome, "row", outcome)
    state = getattr(row, "state", "")
    block_reason = getattr(row, "block_reason", None)

    # FEAT-009 ``send_input`` does not raise on a permission/kill-switch
    # refusal — it lands the row ``blocked`` with a ``block_reason``. Map
    # the closed-set block reasons to FEAT-011 codes (FR-031, SC-038).
    if state == "blocked" and block_reason == "kill_switch_off":
        return _envelope.failure(
            ROUTING_DISABLED,
            "FEAT-009 global routing kill switch is off",
            details={},
        )
    if state == "blocked" and block_reason == "sender_role_not_permitted":
        return _envelope.failure(
            PERMISSION_DENIED,
            "FEAT-009 per-message permission gate refused the send",
            details={"reason": "feat009_permission_gate"},
        )

    message_id = getattr(row, "message_id", None)
    env = _envelope.success(
        {
            "message_id": message_id,
            "state": state,
            "deduplicated": False,
        }
    )

    _audit.emit_app_mutation(
        getattr(ctx, "events_file", None),
        event_type="queue_message_enqueued",
        payload={
            "message_id": message_id,
            "target_agent_id": target_resolved,
            "state": state,
            "via": "app.send_input",
        },
        session=session,
    )

    # FR-031a: record the response so a retry with the same key replays it.
    if idempotency_key is not None and message_id is not None:
        store.record(
            idempotency_key,
            message_id,
            env,
            getattr(session, "connection_started_at_ms", 0),
        )

    return env


# ─── T064 — app.queue.approve / delay / cancel ───────────────────────────


def _queue_service_or_error(ctx: "DaemonContext"):
    """Return ``(queue_service, None)`` or ``(None, error_envelope)``."""
    svc = getattr(ctx, "queue_service", None)
    if svc is None or not hasattr(svc, "approve"):
        return None, _envelope.failure(
            INTERNAL_ERROR, "daemon queue_service not wired", details={}
        )
    return svc, None


def _map_queue_action_error(
    code: str, message: str, *, message_id: str
) -> dict[str, Any]:
    """Map a FEAT-009 ``QueueServiceError`` from approve/delay/cancel."""
    if code == "message_id_not_found":
        return _envelope.failure(
            QUEUE_MESSAGE_NOT_FOUND, message, details={"message_id": message_id}
        )
    # Terminal-state guard (FR-030a) — the ONLY mutation surface allowed
    # to return ``stale_object``.
    if code in (
        "terminal_state_cannot_change",
        "approval_not_applicable",
        "delay_not_applicable",
        "delivery_in_progress",
    ):
        return _envelope.failure(
            STALE_OBJECT,
            message,
            details={},
        )
    if code == "routing_disabled":
        return _envelope.failure(ROUTING_DISABLED, message, details={})
    return _envelope.internal_error_logged(
        "queue action (unmapped upstream code)", f"{code}: {message}"
    )


def _queue_action(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int,
    *,
    action: str,
    audit_event_type: str,
) -> dict[str, Any]:
    """Shared body for ``app.queue.{approve,delay,cancel}``."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    message_id = params.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "message_id must be a non-empty string",
            details={"field": "message_id", "reason": "missing or wrong type"},
        )

    # delay carries a required relative delay; approve/cancel do not need
    # extra fields (cancel.reason is optional and informational).
    if action == "delay":
        delay_ms = params.get("delay_ms")
        if isinstance(delay_ms, bool) or not isinstance(delay_ms, int) or delay_ms < 0:
            return _envelope.failure(
                VALIDATION_FAILED,
                "delay_ms must be a non-negative integer",
                details={"field": "delay_ms", "reason": "missing or wrong type"},
            )

    queue_service, err = _queue_service_or_error(ctx)
    if err:
        return err

    from ..agents.identifiers import HOST_OPERATOR_SENTINEL
    from ..routing.errors import QueueServiceError

    try:
        method_fn = getattr(queue_service, action)
        row = method_fn(message_id, operator=HOST_OPERATOR_SENTINEL)
    except QueueServiceError as exc:
        return _map_queue_action_error(
            exc.code, exc.message, message_id=message_id
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged(f"queue.{action}", exc)

    queue_view = _queue_view_from_row(row)
    _audit.emit_app_mutation(
        getattr(ctx, "events_file", None),
        event_type=audit_event_type,
        payload={
            "message_id": message_id,
            "state": queue_view.get("state"),
            "via": f"app.queue.{action}",
        },
        session=session,
    )
    return _envelope.success({"row": queue_view})


def app_queue_approve(
    ctx: "DaemonContext", params: dict[str, Any], peer_uid: int = -1
) -> dict[str, Any]:
    """``app.queue.approve`` — ``blocked`` row → ``queued`` (FR-030a guard)."""
    return _queue_action(
        ctx, params, peer_uid,
        action="approve", audit_event_type="queue_message_approved",
    )


def app_queue_delay(
    ctx: "DaemonContext", params: dict[str, Any], peer_uid: int = -1
) -> dict[str, Any]:
    """``app.queue.delay`` — ``queued`` row → ``blocked`` (operator_delayed)."""
    return _queue_action(
        ctx, params, peer_uid,
        action="delay", audit_event_type="queue_message_delayed",
    )


def app_queue_cancel(
    ctx: "DaemonContext", params: dict[str, Any], peer_uid: int = -1
) -> dict[str, Any]:
    """``app.queue.cancel`` — non-terminal row → ``canceled``."""
    return _queue_action(
        ctx, params, peer_uid,
        action="cancel", audit_event_type="queue_message_canceled",
    )


# ─── T065 — app.route.add / remove / update ──────────────────────────────


def _routes_service_or_error(ctx: "DaemonContext"):
    """Return ``(routes_service, None)`` or ``(None, error_envelope)``."""
    svc = getattr(ctx, "routes_service", None)
    if svc is None or not hasattr(svc, "add_route"):
        return None, _envelope.failure(
            INTERNAL_ERROR, "daemon routes_service not wired", details={}
        )
    return svc, None


def _route_view_from_row(row: Any) -> dict[str, Any]:
    """Project a FEAT-010 ``RouteRow`` → ``RouteViewModel``."""
    return _vm.route_view(
        {
            "route_id": getattr(row, "route_id", None),
            "enabled": getattr(row, "enabled", False),
            "event_type": getattr(row, "event_type", ""),
            "source_scope_kind": getattr(row, "source_scope_kind", ""),
            "source_scope_value": getattr(row, "source_scope_value", None),
            "target_rule": getattr(row, "target_rule", ""),
            "target_value": getattr(row, "target_value", None),
            "master_rule": getattr(row, "master_rule", ""),
            "master_value": getattr(row, "master_value", None),
            "template": getattr(row, "template", ""),
            "last_consumed_event_id": getattr(row, "last_consumed_event_id", 0),
            "created_at": getattr(row, "created_at", None),
            "updated_at": getattr(row, "updated_at", None),
        }
    )


def app_route_add(
    ctx: "DaemonContext", params: dict[str, Any], peer_uid: int = -1
) -> dict[str, Any]:
    """``app.route.add`` — create a FEAT-010 route (FR-032)."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    event_type = params.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        return _envelope.failure(
            VALIDATION_FAILED,
            "event_type must be a non-empty string",
            details={"field": "event_type", "reason": "missing or wrong type"},
        )
    template_string = params.get("template")
    if not isinstance(template_string, str):
        return _envelope.failure(
            VALIDATION_FAILED,
            "template must be a string",
            details={"field": "template", "reason": "missing or wrong type"},
        )

    source_scope = params.get("source_scope") or {}
    target = params.get("target") or {}
    master = params.get("master") or {}
    if not isinstance(source_scope, dict):
        return _envelope.failure(
            VALIDATION_FAILED,
            "source_scope must be an object",
            details={"field": "source_scope", "reason": "wrong type"},
        )
    if not isinstance(target, dict):
        return _envelope.failure(
            VALIDATION_FAILED,
            "target must be an object",
            details={"field": "target", "reason": "wrong type"},
        )
    if not isinstance(master, dict):
        return _envelope.failure(
            VALIDATION_FAILED,
            "master must be an object",
            details={"field": "master", "reason": "wrong type"},
        )

    routes_service, err = _routes_service_or_error(ctx)
    if err:
        return err

    from ..routing.route_errors import RouteError

    try:
        row = routes_service.add_route(
            event_type=event_type,
            source_scope_kind=source_scope.get("kind", "any"),
            source_scope_value=source_scope.get("value"),
            target_rule=target.get("rule", ""),
            target_value=target.get("value"),
            master_rule=master.get("rule", "auto"),
            master_value=master.get("value"),
            template_string=template_string,
            created_by_agent_id=None,
        )
    except RouteError as exc:
        # All FEAT-010 add-route validation failures are client input
        # errors → validation_failed with the upstream code as reason.
        return _envelope.failure(
            VALIDATION_FAILED,
            str(exc),
            details={"field": "params", "reason": getattr(exc, "code", "route_error")},
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("routes_service.add_route", exc)

    route_view = _route_view_from_row(row)
    _audit.emit_app_mutation(
        getattr(ctx, "events_file", None),
        event_type="route_created",
        payload={"route_id": route_view.get("route_id"), "via": "app.route.add"},
        session=session,
    )
    return _envelope.success({"row": route_view})


def app_route_remove(
    ctx: "DaemonContext", params: dict[str, Any], peer_uid: int = -1
) -> dict[str, Any]:
    """``app.route.remove`` — hard-delete a FEAT-010 route (FR-032)."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    route_id = params.get("route_id")
    if not isinstance(route_id, str) or not route_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "route_id must be a non-empty string",
            details={"field": "route_id", "reason": "missing or wrong type"},
        )

    routes_service, err = _routes_service_or_error(ctx)
    if err:
        return err

    from ..routing.route_errors import RouteError, RouteIdNotFound

    # Capture the pre-delete row so the response can carry the post-state
    # entity (FR-030) — the route is gone after remove_route.
    pre_row = None
    try:
        pre_row, _runtime = routes_service.show_route(route_id)
    except RouteIdNotFound:
        return _envelope.failure(
            ROUTE_NOT_FOUND,
            f"no route with route_id={route_id!r}",
            details={"route_id": route_id},
        )
    except RouteError:
        pre_row = None
    except Exception:  # noqa: BLE001
        pre_row = None

    try:
        routes_service.remove_route(route_id, deleted_by_agent_id=None)
    except RouteIdNotFound:
        return _envelope.failure(
            ROUTE_NOT_FOUND,
            f"no route with route_id={route_id!r}",
            details={"route_id": route_id},
        )
    except RouteError as exc:
        return _envelope.failure(
            VALIDATION_FAILED,
            str(exc),
            details={"field": "params", "reason": getattr(exc, "code", "route_error")},
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("routes_service.remove_route", exc)

    route_view = (
        _route_view_from_row(pre_row)
        if pre_row is not None
        else {"route_id": route_id}
    )
    _audit.emit_app_mutation(
        getattr(ctx, "events_file", None),
        event_type="route_deleted",
        payload={"route_id": route_id, "via": "app.route.remove"},
        session=session,
    )
    return _envelope.success({"row": route_view})


def app_route_update(
    ctx: "DaemonContext", params: dict[str, Any], peer_uid: int = -1
) -> dict[str, Any]:
    """``app.route.update`` — enable/disable only (FR-029, FR-030a, FR-032).

    Accepts ONLY ``{route_id, enabled}``. Any other field → ``validation_failed``.
    Last-write-wins; never ``stale_object``.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session
    if not isinstance(params, dict):
        params = {}

    route_id = params.get("route_id")
    if not isinstance(route_id, str) or not route_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "route_id must be a non-empty string",
            details={"field": "route_id", "reason": "missing or wrong type"},
        )
    enabled = params.get("enabled")
    if not isinstance(enabled, bool):
        return _envelope.failure(
            VALIDATION_FAILED,
            "enabled must be a boolean",
            details={"field": "enabled", "reason": "missing or wrong type"},
        )

    # FEAT-010 routes are immutable except for the enabled flag — reject
    # any extra field rather than silently ignoring it.
    extra = set(params.keys()) - {"route_id", "enabled", "app_session_token"}
    if extra:
        offender = sorted(extra)[0]
        return _envelope.failure(
            VALIDATION_FAILED,
            f"app.route.update accepts only route_id + enabled; "
            f"unexpected field {offender!r}",
            details={"field": offender, "reason": "field not accepted"},
        )

    routes_service, err = _routes_service_or_error(ctx)
    if err:
        return err

    from ..routing.route_errors import RouteError, RouteIdNotFound

    try:
        if enabled:
            routes_service.enable_route(route_id, updated_by_agent_id=None)
        else:
            routes_service.disable_route(route_id, updated_by_agent_id=None)
    except RouteIdNotFound:
        return _envelope.failure(
            ROUTE_NOT_FOUND,
            f"no route with route_id={route_id!r}",
            details={"route_id": route_id},
        )
    except RouteError as exc:
        return _envelope.failure(
            VALIDATION_FAILED,
            str(exc),
            details={"field": "params", "reason": getattr(exc, "code", "route_error")},
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("routes_service route update", exc)

    # Project the post-update row (FR-030).
    try:
        row, _runtime = routes_service.show_route(route_id)
    except RouteIdNotFound:
        return _envelope.failure(
            ROUTE_NOT_FOUND,
            f"no route with route_id={route_id!r}",
            details={"route_id": route_id},
        )
    except Exception as exc:  # noqa: BLE001
        return _envelope.internal_error_logged("routes_service.show_route", exc)

    route_view = _route_view_from_row(row)
    _audit.emit_app_mutation(
        getattr(ctx, "events_file", None),
        event_type="route_updated",
        payload={
            "route_id": route_id,
            "enabled": enabled,
            "via": "app.route.update",
        },
        session=session,
    )
    return _envelope.success({"row": route_view})


__all__ = [
    "app_agent_register_from_pane",
    "app_agent_update",
    "app_log_attach",
    "app_log_detach",
    "app_send_input",
    "app_queue_approve",
    "app_queue_delay",
    "app_queue_cancel",
    "app_route_add",
    "app_route_remove",
    "app_route_update",
    "drop_idempotency_store",
]
