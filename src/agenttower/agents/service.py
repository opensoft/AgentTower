"""Daemon-side AgentService — orchestrator for the FEAT-006 socket methods.

Implements the validation order from data-model.md §7.3 (register_agent)
and §7.3a (set_role). Owns the per-(container, pane composite key)
register mutex and the per-``agent_id`` agent mutex; commits each call
in a single ``BEGIN IMMEDIATE`` SQLite transaction with rollback on
failure (FR-035). Audit rows (FR-014) are appended *after* COMMIT and
ONLY for actual role transitions (FR-027 — no audit on no-op writes).

Cross-subsystem ordering with FEAT-004 pane reconciliation is provided
by SQLite ``BEGIN IMMEDIATE`` semantics — the FEAT-006 mutex covers
register_agent against other register_agent calls only (FR-038 /
Clarifications session 2026-05-07-continued Q4).

**Audit-append failure invariant** (FR-014 hardening): every successful
COMMIT is followed by a JSONL audit append in a try/except. If the
append raises (disk full, fsync EIO, mode-broadening race), the role
change is already committed and cannot be rolled back; the failure is
emitted via the lifecycle logger as an ``audit_append_failed`` event
and the call still returns success. Persisting "audit pending" rows
in a same-DB table for replay is a deferred follow-up.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from ..state import agents as state_agents
from ..state.agents import AgentRecord
from ..tmux.parsers import sanitize_text
from . import audit as audit_mod
from . import permissions
from . import validation
from .errors import RegistrationError
from .identifiers import generate_agent_id, validate_agent_id_shape
from .mutex import AgentLockMap, PaneCompositeKey, RegisterLockMap


# Sentinel values for "field absent in the JSON envelope" — encodes the
# Clarifications Q1 wire contract: only-supplied-fields-overwrite. The
# CLI MUST omit unsupplied flags from ``params`` so absent dict keys
# read as "leave stored value unchanged" on idempotent re-registration.
_UNSET: Final[object] = object()


# Maximum agent_id PK collision retries (FR-001 / research R-001).
# Vanishingly unlikely at MVP scale (48 bits of entropy → ~16M agents
# before the first expected collision); 5 attempts is overwhelmingly
# conservative.
_AGENT_ID_RETRY_LIMIT: Final[int] = 5


# SQLite extended-errcode constants (sqlite3.h).  We disambiguate
# IntegrityError on the agent_id PRIMARY KEY (which we retry) from
# IntegrityError on any other UNIQUE constraint (e.g. the agents-table
# pane composite key — which we surface as internal_error) by inspecting
# ``exc.sqlite_extended_errcode`` rather than substring-matching the
# English error message (which can drift between SQLite versions).
_SQLITE_CONSTRAINT_PRIMARYKEY: Final[int] = 1555


# Pane composite-key string-field bounds, applied defensively in
# ``_coerce_pane_key``.  FEAT-004 already sanitizes these on the way
# IN to the panes table; the FEAT-006 service trusts the CLI for
# identity (FR-024) but still cannot let a same-uid peer (or future
# automation that bypasses the CLI) plant NUL/control bytes in the
# agents row that flow back through list_agents into TSV/JSON.
_PANE_FIELD_MAX_BYTES: Final[int] = 4096


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _check_schema_version(
    params: dict[str, Any], *, daemon_schema_version: int, method_name: str
) -> None:
    """Shared FR-040 forward-compat gate.

    Runs at the top of every FEAT-006 service method. Refuses with
    ``schema_version_newer`` when the daemon's schema is newer than
    what the calling CLI advertises, and with ``bad_request`` when the
    field is present but not an int (defensive — a buggy client
    sending ``"latest"`` or ``1.5`` would otherwise silently bypass
    the gate).
    """
    if "schema_version" not in params:
        return
    client_schema = params["schema_version"]
    if not isinstance(client_schema, int) or isinstance(client_schema, bool):
        raise RegistrationError(
            "bad_request",
            f"{method_name}: params.schema_version must be an integer",
        )
    if client_schema < daemon_schema_version:
        raise RegistrationError(
            "schema_version_newer",
            f"daemon schema_version={daemon_schema_version} > "
            f"client expected={client_schema}; upgrade the CLI",
        )


def _check_unknown_keys(
    params: dict[str, Any], allowed: frozenset[str], *, method_name: str
) -> None:
    """Reject any key in *params* not in the *allowed* closed set.

    Mirrors the ``unknown_filter`` gate ``list_agents`` enforces. Refuses
    with ``bad_request`` so a typo or stale-CLI extra field surfaces
    deterministically rather than being silently dropped.
    """
    unknown = sorted(set(params.keys()) - allowed)
    if unknown:
        raise RegistrationError(
            "bad_request",
            f"{method_name}: unknown params keys {unknown}; "
            f"allowed: {sorted(allowed)}",
        )


def _require_string(
    params: dict[str, Any], key: str, *, method_name: str
) -> str:
    """Read a required string field from *params* or raise ``bad_request``."""
    if key not in params:
        raise RegistrationError(
            "bad_request",
            f"{method_name}: params.{key} is required",
        )
    value = params[key]
    if not isinstance(value, str):
        raise RegistrationError(
            "bad_request",
            f"{method_name}: params.{key} must be a string",
        )
    return value


@dataclass
class AgentService:
    """Owns the FEAT-006 mutex registries; orchestrates each socket method.

    *connection_factory* MUST yield a ``sqlite3.Connection`` for the
    state database. The service opens fresh connections for each
    short-lived call so register_agent / list_agents / set_* can run on
    the daemon's accept-thread pool without sharing an SQLite cursor.

    *events_file* is the FEAT-001 ``events.jsonl`` path. May be ``None``
    in unit tests (audit append becomes a no-op). *schema_version* is
    the build's current schema version, used by the forward-compat
    check (edge case line 79; FR-040 ``schema_version_newer``).

    *lifecycle_logger* (optional) receives ``audit_append_failed`` events
    when the post-COMMIT JSONL audit append raises — see the module
    docstring's audit-append failure invariant.
    """

    connection_factory: Callable[[], sqlite3.Connection]
    register_locks: RegisterLockMap
    agent_locks: AgentLockMap
    events_file: Path | None
    schema_version: int
    lifecycle_logger: Any = None
    # FEAT-007 / US4: when set, register_agent honors an optional
    # ``attach_log`` envelope (FR-034 / FR-035 atomic two-table commit).
    log_service: Any = None

    def _emit_lifecycle(self, event: str, **kwargs: Any) -> None:
        """Best-effort emit a lifecycle event; swallow logger failures.

        Mirrors the pattern in :mod:`discovery.service`: the daemon must
        keep serving requests even if the structured log sink is
        misbehaving (FR-035).
        """
        logger = self.lifecycle_logger
        if logger is None:
            return
        try:
            logger.emit(event, **kwargs)
        except Exception:  # pragma: no cover — defensive
            pass

    # ------------------------------------------------------------------ #
    # register_agent (FR-007 / FR-008 / FR-010 / FR-015 / FR-018a / etc.)
    # ------------------------------------------------------------------ #

    # Closed set of keys ``register_agent`` accepts on the wire. Anything
    # outside this set is a forward-compat / typo signal and is refused
    # with ``bad_request`` rather than silently ignored — mirrors the
    # FR-026 ``unknown_filter`` gate that ``list_agents`` already enforces.
    #
    # ``confirm`` is intentionally NOT in this set: register-self has no
    # meaningful confirm (the master-safety boundary is unconditional
    # here per FR-010), so register_agent audit rows always record
    # ``confirm_provided: false``.  Allowing the wire field would let a
    # client spoof the audit value.
    _REGISTER_AGENT_ALLOWED_KEYS = frozenset(
        {
            "schema_version",
            "container_id",
            "pane_composite_key",
            "role",
            "capability",
            "label",
            "project_path",
            "parent_agent_id",
            # FEAT-007 / FR-035: when present, the daemon ALSO runs the
            # FEAT-007 attach pipeline atomically with the register call
            # (FR-034 fail-the-call). The nested object accepts an optional
            # ``log_path``; absent → canonical FR-005 default.
            "attach_log",
        }
    )

    def register_agent(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        # 0. Closed-key validation + forward-compat schema gate
        #    (FR-040 / FR-035 hygiene).
        _check_unknown_keys(
            params, self._REGISTER_AGENT_ALLOWED_KEYS, method_name="register_agent"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="register_agent",
        )

        # 1. Required identity inputs (FR-024 — daemon does not re-derive
        #    container identity; the CLI is responsible).
        container_id = params.get("container_id")
        pane_key_in = params.get("pane_composite_key")
        if not isinstance(container_id, str):
            raise RegistrationError(
                "bad_request",
                "params.container_id must be a string",
            )
        if not container_id:
            raise RegistrationError(
                "value_out_of_set",
                "params.container_id must be a non-empty string",
            )
        pane_key = _coerce_pane_key(pane_key_in)
        if pane_key[0] != container_id:
            raise RegistrationError(
                "value_out_of_set",
                "params.pane_composite_key.container_id must match params.container_id",
            )

        # 2. Optional mutable fields — supplied-vs-default wire contract
        #    (Clarifications Q1 / FR-007). Absent keys → ``_UNSET``.
        role_in = _opt(params, "role")
        capability_in = _opt(params, "capability")
        label_in = _opt(params, "label")
        project_path_in = _opt(params, "project_path")
        parent_in = _opt(params, "parent_agent_id")

        # 3. Closed-set field shape validation on present optional keys.
        if role_in is not _UNSET:
            validation.validate_role(role_in)
        if capability_in is not _UNSET:
            validation.validate_capability(capability_in)
        # 4. Free-text bounds + sanitization (FR-033 / FR-034).
        if label_in is not _UNSET:
            label_in = validation.validate_label(label_in)
        if project_path_in is not _UNSET and project_path_in != "":
            project_path_in = validation.validate_project_path(project_path_in)
        # 5. Parent shape (full agent_id form). ``None`` is allowed as
        #    "explicitly null parent" but only meaningful in error
        #    paths because re-registration with different --parent is
        #    rejected as parent_immutable (FR-018a).
        if parent_in is not _UNSET and parent_in is not None:
            validation.validate_parent_agent_id_shape(parent_in)

        # 6. Master-safety static rejection (FR-010): ``register-self
        #    --role master`` MUST be refused regardless of ``--confirm``.
        if role_in == "master":
            raise RegistrationError(
                "master_via_register_self_rejected",
                "register-self cannot assign role=master; register first, "
                "then run `agenttower set-role --role master --confirm`",
            )

        # 7. Swarm-parent shape pairing (FR-015 / FR-016).
        if role_in == "swarm" and (parent_in is _UNSET or parent_in is None):
            raise RegistrationError(
                "swarm_parent_required",
                "--role swarm requires --parent <agent-id>",
            )
        if (
            parent_in is not _UNSET
            and parent_in is not None
            and role_in is not _UNSET
            and role_in != "swarm"
        ):
            raise RegistrationError(
                "parent_role_mismatch",
                "--parent only valid with --role swarm",
            )

        # 8. Serialize concurrent register_agent against the same pane
        #    composite key (FR-038). Independent panes proceed in
        #    parallel (each gets its own per-key lock).
        with self.register_locks.for_key(pane_key):
            return self._register_agent_locked(
                container_id=container_id,
                pane_key=pane_key,
                role_in=role_in,
                capability_in=capability_in,
                label_in=label_in,
                project_path_in=project_path_in,
                parent_in=parent_in,
                socket_peer_uid=socket_peer_uid,
                attach_log_envelope=params.get("attach_log"),
                client_schema_version=params.get("schema_version"),
            )

    def _register_agent_locked(
        self,
        *,
        container_id: str,
        pane_key: PaneCompositeKey,
        role_in: object,
        capability_in: object,
        label_in: object,
        project_path_in: object,
        parent_in: object,
        socket_peer_uid: int,
        attach_log_envelope: Any = None,
        client_schema_version: Any = None,
    ) -> dict[str, Any]:
        """Execute the register_agent write inside a single BEGIN IMMEDIATE.

        Both paths (creation and re-registration) take their existence
        SELECT and parent-active validation INSIDE the same write
        transaction so the validate-then-write window cannot be raced
        by a concurrent ``set_role`` (different mutex domain) or by a
        FEAT-004 pane-reconciliation cascade. Audit rows are appended
        AFTER COMMIT, in a try/except that emits a lifecycle event on
        failure so the role transition is never silently lost.
        """
        conn = self.connection_factory()
        try:
            now_iso = _now_iso()

            audit_event: dict[str, Any] | None = None
            outcome: dict[str, Any]
            attach_log_outcome: dict[str, Any] | None = None
            deferred_attach_audit: dict[str, Any] | None = None

            conn.execute("BEGIN IMMEDIATE")
            try:
                self._validate_bound_pane_is_active(
                    conn,
                    pane_key=pane_key,
                )
                existing = state_agents.select_agent_by_pane_key(
                    conn, pane_key=pane_key
                )

                if existing is None:
                    # ===== Creation path =====
                    role = role_in if role_in is not _UNSET else "unknown"
                    capability = (
                        capability_in if capability_in is not _UNSET else "unknown"
                    )
                    label = label_in if label_in is not _UNSET else ""
                    project_path = (
                        project_path_in if project_path_in is not _UNSET else ""
                    )
                    parent_agent_id = parent_in if parent_in is not _UNSET else None
                    # FR-016: a non-null parent demands role=swarm. Closes
                    # the gap for "parent supplied but role omitted",
                    # where the argparse default "unknown" would otherwise
                    # silently persist alongside a parent_agent_id.
                    if parent_agent_id is not None and role != "swarm":
                        raise RegistrationError(
                            "parent_role_mismatch",
                            "--parent only valid with --role swarm",
                        )
                    # FR-017: parent existence/active/role=slave check —
                    # MUST run inside BEGIN IMMEDIATE so a concurrent
                    # FEAT-004 cascade cannot flip the parent inactive
                    # between the check and the INSERT.
                    if isinstance(parent_agent_id, str):
                        self._validate_parent_for_swarm(
                            conn, parent_agent_id=parent_agent_id
                        )
                    effective_perms_json = permissions.serialize_effective_permissions(
                        role
                    )
                    new_agent_id = self._insert_with_savepoint_retry(
                        conn,
                        pane_key=pane_key,
                        role=role,
                        capability=capability,
                        label=label,
                        project_path=project_path,
                        parent_agent_id=parent_agent_id,
                        effective_perms_json=effective_perms_json,
                        now_iso=now_iso,
                    )
                    final_agent_id = new_agent_id
                    created_or_reactivated = "created"
                    audit_event = {
                        "agent_id": new_agent_id,
                        "prior_role": None,
                        "new_role": role,
                    }
                else:
                    # ===== Re-registration / re-activation path =====
                    # (FR-007 / FR-008 / FR-018a)
                    if (
                        parent_in is not _UNSET
                        and parent_in != existing.parent_agent_id
                    ):
                        raise RegistrationError(
                            "parent_immutable",
                            "--parent is immutable after creation; re-registration "
                            "with a different --parent is rejected",
                        )
                    resolved_role = (
                        role_in if role_in is not _UNSET else existing.role
                    )
                    resolved_parent = (
                        parent_in
                        if parent_in is not _UNSET
                        else existing.parent_agent_id
                    )
                    if role_in is not _UNSET and resolved_role == "master":
                        # Even on re-registration, register-self never assigns master.
                        raise RegistrationError(
                            "master_via_register_self_rejected",
                            "register-self cannot assign role=master",
                        )
                    if resolved_parent is not None and resolved_role != "swarm":
                        raise RegistrationError(
                            "parent_role_mismatch",
                            "--parent only valid with --role swarm",
                        )
                    resolved_capability = (
                        capability_in
                        if capability_in is not _UNSET
                        else existing.capability
                    )
                    resolved_label = (
                        label_in if label_in is not _UNSET else existing.label
                    )
                    resolved_project = (
                        project_path_in
                        if project_path_in is not _UNSET
                        else existing.project_path
                    )
                    effective_perms_json = permissions.serialize_effective_permissions(
                        resolved_role
                    )
                    role_changed = resolved_role != existing.role
                    was_inactive = not existing.active
                    state_agents.update_agent_mutable_fields(
                        conn,
                        agent_id=existing.agent_id,
                        role=resolved_role,
                        capability=resolved_capability,
                        label=resolved_label,
                        project_path=resolved_project,
                        effective_permissions_json=effective_perms_json,
                        last_registered_at=now_iso,
                        active=True,
                    )
                    final_agent_id = existing.agent_id
                    created_or_reactivated = (
                        "reactivated" if was_inactive else "updated"
                    )
                    if role_changed:
                        audit_event = {
                            "agent_id": existing.agent_id,
                            "prior_role": existing.role,
                            "new_role": resolved_role,
                        }

                final_record = _select_agent_full_by_id(conn, agent_id=final_agent_id)

                if attach_log_envelope is not None:
                    if not isinstance(attach_log_envelope, dict):
                        raise RegistrationError(
                            "bad_request",
                            "params.attach_log must be an object",
                        )
                    if self.log_service is None:
                        raise RegistrationError(
                            "internal_error",
                            "log service is not wired into the daemon",
                        )
                    assert final_record is not None
                    container_record = self._select_active_container_for_attach(
                        conn, container_id=final_record.agent.container_id
                    )
                    attach_params: dict[str, Any] = {
                        "agent_id": final_record.agent.agent_id,
                    }
                    if "log_path" in attach_log_envelope:
                        attach_params["log_path"] = attach_log_envelope["log_path"]
                    if client_schema_version is not None:
                        attach_params["schema_version"] = client_schema_version
                    attach_result = self.log_service.attach_log_in_transaction(
                        conn,
                        params=attach_params,
                        agent_record=final_record.agent,
                        container_record=container_record,
                        socket_peer_uid=socket_peer_uid,
                        source="register_self",
                        defer_audit=True,
                    )
                    deferred_attach_audit = attach_result.pop(
                        "__deferred_audit__", None
                    )
                    attach_log_outcome = attach_result

                conn.execute("COMMIT")
            except RegistrationError:
                conn.execute("ROLLBACK")
                raise
            except Exception:
                conn.execute("ROLLBACK")
                raise

            assert final_record is not None  # invariant: just inserted/updated
            outcome = _agent_full_record_to_register_payload(
                final_record, created_or_reactivated=created_or_reactivated
            )

            # FR-035: append FEAT-006 audit row FIRST.
            if audit_event is not None:
                self._safe_append_audit(
                    method_name="register_agent",
                    socket_peer_uid=socket_peer_uid,
                    confirm_provided=False,
                    **audit_event,
                )
            # FR-035: append FEAT-007 audit row SECOND (deferred from
            # the LogService.attach_log call above).
            if deferred_attach_audit is not None:
                from ..logs import audit as logs_audit

                try:
                    logs_audit.append_log_attachment_change(
                        self.log_service.events_file,
                        **deferred_attach_audit,
                    )
                except Exception:  # pragma: no cover — defensive
                    self._emit_lifecycle(
                        "audit_append_failed",
                        method="register_agent.attach_log",
                        agent_id=final_record.agent.agent_id,
                    )
            if attach_log_outcome is not None:
                outcome["attach_log"] = attach_log_outcome
            return outcome
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _insert_with_savepoint_retry(
        self,
        conn: sqlite3.Connection,
        *,
        pane_key: PaneCompositeKey,
        role: str,
        capability: str,
        label: str,
        project_path: str,
        parent_agent_id: str | None,
        effective_perms_json: str,
        now_iso: str,
    ) -> str:
        """INSERT a fresh agent row inside the caller's BEGIN IMMEDIATE.

        Uses a SAVEPOINT per attempt so an ``agent_id`` PK collision can
        be rolled back without dropping the outer transaction. Real PK
        collisions are vanishingly rare at MVP scale (FR-001 / R-001);
        the retry loop just keeps the daemon alive on the impossible
        case. UNIQUE-constraint violations on the pane composite key
        (impossible because we hold the per-pane mutex AND we already
        SELECTed the row inside the tx) are surfaced as
        ``internal_error`` rather than retried.
        """
        last_exc: Exception | None = None
        for attempt in range(_AGENT_ID_RETRY_LIMIT):
            agent_id = generate_agent_id()
            savepoint = f"agent_insert_{attempt}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                state_agents.insert_agent(
                    conn,
                    agent_id=agent_id,
                    pane_key=pane_key,
                    role=role,
                    capability=capability,
                    label=label,
                    project_path=project_path,
                    parent_agent_id=parent_agent_id,
                    effective_permissions_json=effective_perms_json,
                    created_at=now_iso,
                    last_registered_at=now_iso,
                    active=True,
                )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                return agent_id
            except sqlite3.IntegrityError as exc:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                # Distinguish PK collision (retry with fresh id) from
                # UNIQUE on the pane composite key (a real bug — caller
                # ensures pane_key is not already bound) by inspecting
                # the SQLite extended errcode rather than the localized
                # English error text.
                if getattr(exc, "sqlite_errorcode", None) == _SQLITE_CONSTRAINT_PRIMARYKEY:
                    last_exc = exc
                    continue
                raise RegistrationError(
                    "internal_error",
                    f"agents insert failed: {exc}",
                ) from exc
            except Exception as exc:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise RegistrationError(
                    "internal_error",
                    f"agents insert failed: {exc}",
                ) from exc
        raise RegistrationError(
            "internal_error",
            f"agent_id PK collision retry budget exhausted ({_AGENT_ID_RETRY_LIMIT})",
        ) from last_exc

    def _cleanup_agent_row(self, agent_id: str) -> None:
        """FR-034 fail-the-call: delete the just-created agent row.

        Called after a register transaction has already committed and the
        downstream FEAT-007 attach raised. We open a fresh ``BEGIN
        IMMEDIATE`` and DELETE the row by primary key. Failures here are
        swallowed-and-logged because we are already on the error path
        and cannot meaningfully roll back further.
        """
        conn = self.connection_factory()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            conn.execute("COMMIT")
        except Exception:  # pragma: no cover — defensive
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            self._emit_lifecycle(
                "audit_append_failed",
                method="register_agent.cleanup",
                agent_id=agent_id,
                reason="cleanup-rollback failed",
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _safe_append_audit(
        self,
        *,
        method_name: str,
        agent_id: str,
        prior_role: str | None,
        new_role: str,
        confirm_provided: bool,
        socket_peer_uid: int,
    ) -> None:
        """Append an audit row, swallowing-and-logging any append failure.

        The role mutation is already committed by the caller. If the
        JSONL append raises (disk full, fsync EIO, mode-broadening
        race), we cannot roll back; emit ``audit_append_failed`` via
        the lifecycle logger so the gap is observable, and return
        normally so the caller still sees success. See the module
        docstring's audit-append failure invariant.
        """
        try:
            audit_mod.append_role_change(
                self.events_file,
                agent_id=agent_id,
                prior_role=prior_role,
                new_role=new_role,
                confirm_provided=confirm_provided,
                socket_peer_uid=socket_peer_uid,
            )
        except Exception as exc:
            self._emit_lifecycle(
                "audit_append_failed",
                method=method_name,
                agent_id=agent_id,
                prior_role=prior_role,
                new_role=new_role,
                error=type(exc).__name__,
                error_message=sanitize_text(str(exc), 512)[0],
            )

    def _validate_bound_pane_is_active(
        self,
        conn: sqlite3.Connection,
        *,
        pane_key: PaneCompositeKey,
    ) -> None:
        """Reject register_agent when the bound FEAT-004 pane/container is not active.

        This closes the FEAT-004 reconciliation race window for
        register-self: the client may have resolved a valid pane moments
        earlier, but by the time this BEGIN IMMEDIATE transaction starts
        the pane or its container may already be inactive. In that case,
        register-self must follow the same closed-set failure surface as
        the resolver miss path rather than creating/reactivating a ghost
        agent row.
        """
        state = state_agents.select_active_for_bound_pane(conn, pane_key=pane_key)
        if state != (True, True):
            raise RegistrationError(
                "pane_unknown_to_daemon",
                "bound pane is absent or inactive in the FEAT-004 registry",
            )

    def _select_active_container_for_attach(
        self, conn: sqlite3.Connection, *, container_id: str
    ) -> dict[str, Any]:
        """Fetch the FEAT-007 container fields on the caller's transaction."""
        row = conn.execute(
            """
            SELECT active, mounts_json, config_user
              FROM containers
             WHERE container_id = ?
            """,
            (container_id,),
        ).fetchone()
        if row is None or not bool(row[0]):
            raise RegistrationError(
                "agent_inactive",
                f"container {container_id!r} is inactive",
            )
        bench_user = row[2] or "root"
        return {
            "mounts_json": row[1] or "[]",
            "bench_user": bench_user,
            "tmux_present": True,
        }

    def _validate_parent_for_swarm(
        self, conn: sqlite3.Connection, *, parent_agent_id: str
    ) -> None:
        """FR-017 dynamic parent validation — exists, active, role=slave."""
        validate_agent_id_shape(parent_agent_id)
        parent = state_agents.select_agent_by_id(conn, agent_id=parent_agent_id)
        if parent is None:
            raise RegistrationError(
                "parent_not_found",
                f"parent agent {parent_agent_id} not found",
            )
        if not parent.active:
            raise RegistrationError(
                "parent_inactive",
                f"parent agent {parent_agent_id} is inactive",
            )
        if parent.role != "slave":
            raise RegistrationError(
                "parent_role_invalid",
                f"parent agent must have role=slave (got {parent.role})",
            )

    # ------------------------------------------------------------------ #
    # list_agents (FR-025 / FR-026 — read-only; no mutex; no Docker; no tmux)
    # ------------------------------------------------------------------ #

    # Closed set of filter keys ``list_agents`` accepts (FR-026).
    # ``schema_version`` is the FR-040 forward-compat hint and is
    # consumed by the shared preflight, not by the filter logic.
    _LIST_AGENTS_ALLOWED_KEYS = frozenset(
        {
            "schema_version",
            "role",
            "container_id",
            "active_only",
            "parent_agent_id",
        }
    )

    def list_agents(self, params: dict[str, Any]) -> dict[str, Any]:
        # FR-040 forward-compat gate (run on every FEAT-006 method).
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="list_agents",
        )
        # Validate filter keys against the closed set (FR-026). Keep the
        # historical ``unknown_filter`` code for filter-key violations
        # (rather than the generic ``bad_request``) — FR-026 and the
        # existing test surface lock that spelling.
        for key in params.keys():
            if key not in self._LIST_AGENTS_ALLOWED_KEYS:
                raise RegistrationError(
                    "unknown_filter",
                    f"unknown filter key {key!r}; allowed: "
                    f"{sorted(self._LIST_AGENTS_ALLOWED_KEYS - {'schema_version'})}",
                )

        role_filter = params.get("role")
        roles_normalized: list[str] | None = None
        if role_filter is not None:
            if isinstance(role_filter, str):
                validation.validate_role(role_filter)
                roles_normalized = [role_filter]
            elif isinstance(role_filter, list):
                roles_normalized = [validation.validate_role(r) for r in role_filter]
            else:
                raise RegistrationError(
                    "value_out_of_set",
                    "params.role must be a string or list of strings",
                )

        container_id = params.get("container_id")
        if container_id is not None:
            validation.validate_container_id_filter(container_id)

        active_only_param = params.get("active_only", False)
        if not isinstance(active_only_param, bool):
            raise RegistrationError(
                "value_out_of_set",
                "params.active_only must be a boolean",
            )

        parent_agent_id = params.get("parent_agent_id")
        if parent_agent_id is not None:
            validation.validate_parent_agent_id_shape(parent_agent_id)

        conn = self.connection_factory()
        try:
            rows = _list_agents_full(
                conn,
                role=roles_normalized,
                container_id=container_id,
                active_only=active_only_param,
                parent_agent_id=parent_agent_id,
            )
        finally:
            conn.close()

        return {
            "filter": {
                "role": roles_normalized,
                "container_id": container_id,
                "active_only": active_only_param,
                "parent_agent_id": parent_agent_id,
            },
            "agents": [_agent_full_record_to_dict(r) for r in rows],
        }

    # ------------------------------------------------------------------ #
    # set_role / set_label / set_capability  (US2 / FR-011 / FR-012 /
    # FR-013 / FR-014 / FR-027 / FR-031). Each method:
    #
    # 1. Runs the closed-set unknown-keys gate + schema_version preflight.
    # 2. Validates the required ``agent_id`` + the field-specific value.
    # 3. Acquires the per-agent_id mutex.
    # 4. Opens BEGIN IMMEDIATE; re-SELECTs the agent inside the tx so
    #    the no-op check, existence check, and active check all run
    #    against a snapshot a concurrent FEAT-004 cascade or another
    #    set_* call cannot race past.
    # 5. Audit append (set_role only) is wrapped in try/except + lifecycle
    #    log per the module-docstring invariant.
    # ------------------------------------------------------------------ #

    _SET_ROLE_ALLOWED_KEYS = frozenset(
        {"schema_version", "agent_id", "role", "confirm"}
    )
    _SET_LABEL_ALLOWED_KEYS = frozenset(
        {"schema_version", "agent_id", "label"}
    )
    _SET_CAPABILITY_ALLOWED_KEYS = frozenset(
        {"schema_version", "agent_id", "capability"}
    )

    def set_role(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        _check_unknown_keys(
            params, self._SET_ROLE_ALLOWED_KEYS, method_name="set_role"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="set_role",
        )
        agent_id = _require_string(params, "agent_id", method_name="set_role")
        validate_agent_id_shape(agent_id)
        new_role = _require_string(params, "role", method_name="set_role")
        validation.validate_role(new_role)
        confirm_raw = params.get("confirm", False)
        if not isinstance(confirm_raw, bool):
            raise RegistrationError(
                "bad_request",
                "set_role: params.confirm must be a boolean",
            )
        confirm = confirm_raw

        # FR-012: set-role --role swarm is rejected unconditionally.
        if new_role == "swarm":
            raise RegistrationError(
                "swarm_role_via_set_role_rejected",
                "set-role --role swarm is rejected; use "
                "`agenttower register-self --role swarm --parent <agent-id>` instead",
            )
        # FR-011: master promotion requires --confirm.
        if new_role == "master" and not confirm:
            raise RegistrationError(
                "master_confirm_required",
                "master role assignment requires --confirm",
            )

        with self.agent_locks.for_key(agent_id):
            conn = self.connection_factory()
            try:
                effective_perms_json = permissions.serialize_effective_permissions(
                    new_role
                )

                conn.execute("BEGIN IMMEDIATE")
                try:
                    # Atomic existence + active re-check inside the
                    # transaction. Treats a missing containers row as
                    # ``container_active = 0`` — without an active
                    # container backing the agent, role assignment
                    # (especially master promotion) MUST be refused.
                    state = state_agents.select_active_for_role_and_container(
                        conn, agent_id=agent_id
                    )
                    if state is None:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_not_found", f"agent {agent_id} not found"
                        )
                    agent_active, container_active = state
                    if not agent_active:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_inactive",
                            f"agent {agent_id} is inactive",
                        )
                    fresh = state_agents.select_agent_by_id(conn, agent_id=agent_id)
                    assert fresh is not None  # invariant: state is not None
                    prior_role = fresh.role
                    if new_role == "master" and container_active is not True:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_inactive",
                            f"agent {agent_id} or its container is inactive",
                        )
                    if prior_role == new_role:
                        # No-op short-circuit (FR-027) — same value, no
                        # audit row, no UPDATE. The check runs INSIDE
                        # BEGIN IMMEDIATE so a concurrent transition
                        # cannot land between the read and our return.
                        conn.execute("COMMIT")
                        return {
                            "agent_id": agent_id,
                            "field": "role",
                            "prior_value": prior_role,
                            "new_value": new_role,
                            "effective_permissions": fresh.effective_permissions,
                            "audit_appended": False,
                        }
                    state_agents.update_agent_role(
                        conn,
                        agent_id=agent_id,
                        role=new_role,
                        effective_permissions_json=effective_perms_json,
                    )
                    conn.execute("COMMIT")
                except RegistrationError:
                    raise
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

                # Audit row AFTER COMMIT (FR-014) — wrapped per the
                # module-docstring invariant.
                self._safe_append_audit(
                    method_name="set_role",
                    agent_id=agent_id,
                    prior_role=prior_role,
                    new_role=new_role,
                    confirm_provided=confirm,
                    socket_peer_uid=socket_peer_uid,
                )
                return {
                    "agent_id": agent_id,
                    "field": "role",
                    "prior_value": prior_role,
                    "new_value": new_role,
                    "effective_permissions": permissions.effective_permissions(new_role),
                    "audit_appended": True,
                }
            finally:
                conn.close()

    def set_label(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        _check_unknown_keys(
            params, self._SET_LABEL_ALLOWED_KEYS, method_name="set_label"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="set_label",
        )
        agent_id = _require_string(params, "agent_id", method_name="set_label")
        validate_agent_id_shape(agent_id)
        if "label" not in params:
            raise RegistrationError(
                "bad_request",
                "set_label: params.label is required",
            )
        new_label = validation.validate_label(params["label"])

        with self.agent_locks.for_key(agent_id):
            conn = self.connection_factory()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    fresh = state_agents.select_agent_by_id(conn, agent_id=agent_id)
                    if fresh is None:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_not_found", f"agent {agent_id} not found"
                        )
                    if not fresh.active:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_inactive", f"agent {agent_id} is inactive"
                        )
                    if fresh.label == new_label:
                        conn.execute("COMMIT")
                        return {
                            "agent_id": agent_id,
                            "field": "label",
                            "prior_value": fresh.label,
                            "new_value": new_label,
                            "audit_appended": False,
                        }
                    state_agents.update_agent_label(
                        conn, agent_id=agent_id, label=new_label
                    )
                    conn.execute("COMMIT")
                except RegistrationError:
                    raise
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                # set_label never appends an audit row (FR-014 only audits
                # role transitions).
                return {
                    "agent_id": agent_id,
                    "field": "label",
                    "prior_value": fresh.label,
                    "new_value": new_label,
                    "audit_appended": False,
                }
            finally:
                conn.close()

    def set_capability(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        _check_unknown_keys(
            params, self._SET_CAPABILITY_ALLOWED_KEYS, method_name="set_capability"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="set_capability",
        )
        agent_id = _require_string(params, "agent_id", method_name="set_capability")
        validate_agent_id_shape(agent_id)
        if "capability" not in params:
            raise RegistrationError(
                "bad_request",
                "set_capability: params.capability is required",
            )
        new_capability = params["capability"]
        validation.validate_capability(new_capability)

        with self.agent_locks.for_key(agent_id):
            conn = self.connection_factory()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    fresh = state_agents.select_agent_by_id(conn, agent_id=agent_id)
                    if fresh is None:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_not_found", f"agent {agent_id} not found"
                        )
                    if not fresh.active:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_inactive", f"agent {agent_id} is inactive"
                        )
                    if fresh.capability == new_capability:
                        conn.execute("COMMIT")
                        return {
                            "agent_id": agent_id,
                            "field": "capability",
                            "prior_value": fresh.capability,
                            "new_value": new_capability,
                            "audit_appended": False,
                        }
                    state_agents.update_agent_capability(
                        conn, agent_id=agent_id, capability=new_capability
                    )
                    conn.execute("COMMIT")
                except RegistrationError:
                    raise
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return {
                    "agent_id": agent_id,
                    "field": "capability",
                    "prior_value": fresh.capability,
                    "new_value": new_capability,
                    "audit_appended": False,
                }
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _opt(params: dict[str, Any], key: str) -> object:
    """Return ``params[key]`` if present, else the ``_UNSET`` sentinel.

    Encodes the Clarifications Q1 wire contract: "absent key" ≠ "explicit
    null". The CLI MUST omit unsupplied flags so the daemon can leave
    stored values unchanged on idempotent re-registration (FR-007).
    """
    return params[key] if key in params else _UNSET


def _coerce_pane_key(value: Any) -> PaneCompositeKey:
    """Validate, coerce, and defensively sanitize the wire pane composite key.

    FR-024 trusts the CLI for identity, but the daemon still applies
    NUL/control-byte stripping + length caps on the string fields so a
    same-uid peer (or future automation that bypasses the official CLI)
    cannot plant control bytes in the agents row that flow back through
    list_agents into TSV/JSON.
    """
    if not isinstance(value, dict):
        raise RegistrationError(
            "bad_request",
            "params.pane_composite_key must be an object",
        )
    required = (
        "container_id",
        "tmux_socket_path",
        "tmux_session_name",
        "tmux_window_index",
        "tmux_pane_index",
        "tmux_pane_id",
    )
    for k in required:
        if k not in value:
            raise RegistrationError(
                "bad_request",
                f"params.pane_composite_key.{k} is required",
            )
    try:
        container_id = _sanitize_pane_field(str(value["container_id"]))
        tmux_socket_path = _sanitize_pane_field(str(value["tmux_socket_path"]))
        tmux_session_name = _sanitize_pane_field(str(value["tmux_session_name"]))
        tmux_pane_id = _sanitize_pane_field(str(value["tmux_pane_id"]))
        return (
            container_id,
            tmux_socket_path,
            tmux_session_name,
            int(value["tmux_window_index"]),
            int(value["tmux_pane_index"]),
            tmux_pane_id,
        )
    except (TypeError, ValueError) as exc:
        raise RegistrationError(
            "tmux_pane_malformed",
            f"params.pane_composite_key has malformed field: {exc}",
        ) from exc


def _sanitize_pane_field(text: str) -> str:
    """Strip control bytes + cap length for pane composite-key strings."""
    bounded, _ = sanitize_text(text, _PANE_FIELD_MAX_BYTES)
    return bounded


# ---------------------------------------------------------------------------
# Joined SELECTs — surface ``container_name``, ``container_user``,
# ``pane_pid``, and ``cwd`` (= ``panes.pane_current_path``) on every
# wire payload alongside the agents-row columns. The contract
# (contracts/socket-api.md §2.1, §6.2 + cli.md C-CLI-602) requires
# these in both ``register_agent`` and ``list_agents`` responses.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AgentFullRecord:
    """An ``AgentRecord`` plus the four contract-required JOIN fields."""

    agent: AgentRecord
    container_name: str | None
    container_user: str | None
    pane_pid: int | None
    cwd: str | None


_JOINED_SELECT_TAIL = """
    LEFT JOIN containers ON containers.container_id = agents.container_id
    LEFT JOIN panes
      ON panes.container_id = agents.container_id
     AND panes.tmux_socket_path = agents.tmux_socket_path
     AND panes.tmux_session_name = agents.tmux_session_name
     AND panes.tmux_window_index = agents.tmux_window_index
     AND panes.tmux_pane_index = agents.tmux_pane_index
     AND panes.tmux_pane_id = agents.tmux_pane_id
"""

_JOINED_PROJECTION = """
    agents.agent_id, agents.container_id,
    agents.tmux_socket_path, agents.tmux_session_name,
    agents.tmux_window_index, agents.tmux_pane_index, agents.tmux_pane_id,
    agents.role, agents.capability, agents.label, agents.project_path,
    agents.parent_agent_id, agents.effective_permissions,
    agents.created_at, agents.last_registered_at, agents.last_seen_at,
    agents.active,
    COALESCE(containers.name, panes.container_name) AS container_name,
    COALESCE(containers.config_user, panes.container_user) AS container_user,
    panes.pane_pid AS pane_pid,
    panes.pane_current_path AS cwd
"""


def _row_to_full_record(row: tuple) -> _AgentFullRecord:
    import json as _json

    agent = AgentRecord(
        agent_id=row[0],
        container_id=row[1],
        tmux_socket_path=row[2],
        tmux_session_name=row[3],
        tmux_window_index=int(row[4]),
        tmux_pane_index=int(row[5]),
        tmux_pane_id=row[6],
        role=row[7],
        capability=row[8],
        label=row[9],
        project_path=row[10],
        parent_agent_id=row[11],
        effective_permissions=_json.loads(row[12]),
        created_at=row[13],
        last_registered_at=row[14],
        last_seen_at=row[15],
        active=bool(row[16]),
    )
    return _AgentFullRecord(
        agent=agent,
        container_name=row[17],
        container_user=row[18],
        pane_pid=int(row[19]) if row[19] is not None else None,
        cwd=row[20],
    )


def _select_agent_full_by_id(
    conn: sqlite3.Connection, *, agent_id: str
) -> _AgentFullRecord | None:
    sql = (
        "SELECT" + _JOINED_PROJECTION + "FROM agents"
        + _JOINED_SELECT_TAIL + "WHERE agents.agent_id = ?"
    )
    row = conn.execute(sql, (agent_id,)).fetchone()
    return _row_to_full_record(row) if row is not None else None


def _list_agents_full(
    conn: sqlite3.Connection,
    *,
    role: list[str] | None,
    container_id: str | None,
    active_only: bool,
    parent_agent_id: str | None,
) -> list[_AgentFullRecord]:
    """Mirror ``state_agents.list_agents`` with the contract JOIN fields."""
    where: list[str] = []
    params: list[Any] = []
    if active_only:
        where.append("agents.active = 1")
    if role:
        placeholders = ",".join("?" * len(role))
        where.append(f"agents.role IN ({placeholders})")
        params.extend(role)
    if container_id is not None:
        if len(container_id) == 64:
            where.append("agents.container_id = ?")
            params.append(container_id)
        else:
            # Index-friendly half-open range scan; mirrors the plain
            # state_agents.list_agents() helper. ``substr(...)`` would
            # defeat the agents_active_order index.
            where.append("agents.container_id >= ? AND agents.container_id < ?")
            params.append(container_id)
            params.append(state_agents._next_lex_prefix(container_id))
    if parent_agent_id is not None:
        where.append("agents.parent_agent_id = ?")
        params.append(parent_agent_id)
    where_clause = "WHERE " + " AND ".join(where) if where else ""
    order_by = (
        "ORDER BY agents.active DESC, agents.container_id ASC, "
        "agents.parent_agent_id ASC, agents.label ASC, agents.agent_id ASC"
    )
    sql = (
        "SELECT" + _JOINED_PROJECTION + "FROM agents"
        + _JOINED_SELECT_TAIL + where_clause + " " + order_by
    )
    return [_row_to_full_record(r) for r in conn.execute(sql, params).fetchall()]


def _agent_full_record_to_dict(full: _AgentFullRecord) -> dict[str, Any]:
    """Marshal an ``_AgentFullRecord`` into the wire JSON shape.

    Surfaces the four contract-required JOIN fields
    (``container_name``, ``container_user``, ``pane_pid``, ``cwd``)
    alongside the agents-row columns. JOIN fields default to ``None``
    when the bound containers/panes row was reaped (FEAT-003 / FEAT-004
    reconciliation).
    """
    record = full.agent
    return {
        "agent_id": record.agent_id,
        "container_id": record.container_id,
        "container_name": full.container_name,
        "container_user": full.container_user,
        "tmux_socket_path": record.tmux_socket_path,
        "tmux_session_name": record.tmux_session_name,
        "tmux_window_index": record.tmux_window_index,
        "tmux_pane_index": record.tmux_pane_index,
        "tmux_pane_id": record.tmux_pane_id,
        "pane_pid": full.pane_pid,
        "cwd": full.cwd,
        "role": record.role,
        "capability": record.capability,
        "label": record.label,
        "project_path": record.project_path,
        "parent_agent_id": record.parent_agent_id,
        "effective_permissions": record.effective_permissions,
        "created_at": record.created_at,
        "last_registered_at": record.last_registered_at,
        "last_seen_at": record.last_seen_at,
        "active": record.active,
    }


def _agent_full_record_to_register_payload(
    full: _AgentFullRecord, *, created_or_reactivated: str
) -> dict[str, Any]:
    payload = _agent_full_record_to_dict(full)
    payload["created_or_reactivated"] = created_or_reactivated
    return payload
