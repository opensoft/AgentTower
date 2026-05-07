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
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from ..state import agents as state_agents
from ..state.agents import AgentRecord
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
# 96 bits of entropy makes accidental collisions vanishingly unlikely;
# 5 attempts is overwhelmingly conservative.
_AGENT_ID_RETRY_LIMIT: Final[int] = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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
    """

    connection_factory: Callable[[], sqlite3.Connection]
    register_locks: RegisterLockMap
    agent_locks: AgentLockMap
    events_file: Path | None
    schema_version: int

    # ------------------------------------------------------------------ #
    # register_agent (FR-007 / FR-008 / FR-010 / FR-015 / FR-018a / etc.)
    # ------------------------------------------------------------------ #

    def register_agent(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        # 1. Forward-compat schema check (edge case line 79). The CLI
        #    sends a ``schema_version`` hint mirroring FEAT-005; we
        #    refuse without writing if the daemon's schema is newer
        #    than the CLI build expects. (Symmetric direction is
        #    handled at the CLI side.)
        client_schema = params.get("schema_version")
        if isinstance(client_schema, int) and client_schema < self.schema_version:
            # Daemon schema newer than CLI's — refuse with closed-set code.
            raise RegistrationError(
                "schema_version_newer",
                f"daemon schema_version={self.schema_version} > "
                f"client expected={client_schema}; upgrade the CLI",
            )

        # 2. Required identity inputs (FR-024 — daemon does not re-derive
        #    container identity; the CLI is responsible).
        container_id = params.get("container_id")
        pane_key_in = params.get("pane_composite_key")
        if not isinstance(container_id, str) or not container_id:
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

        # 3. Optional mutable fields — supplied-vs-default wire contract
        #    (Clarifications Q1 / FR-007). Absent keys → ``_UNSET``.
        role_in = _opt(params, "role")
        capability_in = _opt(params, "capability")
        label_in = _opt(params, "label")
        project_path_in = _opt(params, "project_path")
        parent_in = _opt(params, "parent_agent_id")
        confirm_in = bool(params.get("confirm", False))

        # 4. Closed-set field shape validation on present optional keys.
        if role_in is not _UNSET:
            validation.validate_role(role_in)
        if capability_in is not _UNSET:
            validation.validate_capability(capability_in)
        # 5. Free-text bounds + sanitization (FR-033 / FR-034).
        if label_in is not _UNSET:
            label_in = validation.validate_label(label_in)
        if project_path_in is not _UNSET and project_path_in != "":
            project_path_in = validation.validate_project_path(project_path_in)
        # 6. Parent shape (full agent_id form). ``None`` is allowed as
        #    "explicitly null parent" but only meaningful in error
        #    paths because re-registration with different --parent is
        #    rejected as parent_immutable (FR-018a).
        if parent_in is not _UNSET and parent_in is not None:
            validation.validate_parent_agent_id_shape(parent_in)

        # 7. Master-safety static rejection (FR-010): ``register-self
        #    --role master`` MUST be refused regardless of ``--confirm``.
        if role_in == "master":
            raise RegistrationError(
                "master_via_register_self_rejected",
                "register-self cannot assign role=master; register first, "
                "then run `agenttower set-role --role master --confirm`",
            )

        # 8. Swarm-parent shape pairing (FR-015 / FR-016).
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

        # 9. Serialize concurrent register_agent against the same pane
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
                confirm_in=confirm_in,
                socket_peer_uid=socket_peer_uid,
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
        confirm_in: bool,
        socket_peer_uid: int,
    ) -> dict[str, Any]:
        conn = self.connection_factory()
        try:
            existing = state_agents.select_agent_by_pane_key(conn, pane_key=pane_key)
            now_iso = _now_iso()

            if existing is None:
                # Creation path. Apply argparse-style defaults for any
                # mutable field that is _UNSET on the wire (the CLI
                # supplies them on first registration only — research
                # R-002).
                role = role_in if role_in is not _UNSET else "unknown"
                capability = capability_in if capability_in is not _UNSET else "unknown"
                label = label_in if label_in is not _UNSET else ""
                project_path = (
                    project_path_in if project_path_in is not _UNSET else ""
                )
                parent_agent_id = parent_in if parent_in is not _UNSET else None
                # FR-016: a non-null parent demands role=swarm. The
                # pre-flight only catches the case where ``role_in`` was
                # explicitly supplied and != "swarm"; here we close the
                # gap for "parent supplied but role omitted", where the
                # argparse default "unknown" would otherwise silently
                # persist alongside a parent_agent_id.
                if parent_agent_id is not None and role != "swarm":
                    raise RegistrationError(
                        "parent_role_mismatch",
                        "--parent only valid with --role swarm",
                    )
                # Validate parent dynamic preconditions before any write
                # (FR-017): exists, active, role=slave.
                if isinstance(parent_agent_id, str):
                    self._validate_parent_for_swarm(
                        conn, parent_agent_id=parent_agent_id
                    )
                effective_perms_json = permissions.serialize_effective_permissions(role)
                new_agent_id = self._insert_with_retry(
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
                # Audit row for the creation transition (Clarifications Q4).
                audit_mod.append_role_change(
                    self.events_file,
                    agent_id=new_agent_id,
                    prior_role=None,
                    new_role=role,
                    confirm_provided=confirm_in,
                    socket_peer_uid=socket_peer_uid,
                )
                created_or_reactivated = "created"
                final_record = state_agents.select_agent_by_id(
                    conn, agent_id=new_agent_id
                )
            else:
                # Re-registration / re-activation path (FR-007 / FR-008 /
                # FR-018a). Resolve mutable fields per Q1
                # (only-supplied-fields-overwrite).
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
                if resolved_role == "master":
                    # Even on re-registration, register-self never assigns master.
                    raise RegistrationError(
                        "master_via_register_self_rejected",
                        "register-self cannot assign role=master",
                    )
                resolved_capability = (
                    capability_in if capability_in is not _UNSET else existing.capability
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
                conn.execute("BEGIN IMMEDIATE")
                try:
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
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                if role_changed:
                    audit_mod.append_role_change(
                        self.events_file,
                        agent_id=existing.agent_id,
                        prior_role=existing.role,
                        new_role=resolved_role,
                        confirm_provided=confirm_in,
                        socket_peer_uid=socket_peer_uid,
                    )
                created_or_reactivated = (
                    "reactivated" if was_inactive else "updated"
                )
                final_record = state_agents.select_agent_by_id(
                    conn, agent_id=existing.agent_id
                )

            assert final_record is not None  # invariant: just inserted/updated
            return _agent_record_to_register_payload(
                final_record, created_or_reactivated=created_or_reactivated
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _insert_with_retry(
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
        """INSERT a fresh agent row with ``_AGENT_ID_RETRY_LIMIT`` PK retries.

        96 bits of entropy makes a collision vanishingly unlikely; the
        retry loop keeps the daemon alive on the impossible case.
        Exhausted retries surface as ``internal_error`` (FR-035).
        """
        last_exc: Exception | None = None
        for _attempt in range(_AGENT_ID_RETRY_LIMIT):
            agent_id = generate_agent_id()
            try:
                conn.execute("BEGIN IMMEDIATE")
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
                conn.execute("COMMIT")
                return agent_id
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK")
                # PK clash → retry with a fresh agent_id. UNIQUE on the
                # pane composite key would be a different bug — caller
                # ensures pane_key is not already bound (we did the SELECT
                # under the per-pane mutex).
                if "agent_id" in str(exc) or "PRIMARY KEY" in str(exc):
                    last_exc = exc
                    continue
                # Any other integrity error (e.g., UNIQUE on the pane
                # composite key) is surfaced as internal_error so the
                # daemon stays alive.
                raise RegistrationError(
                    "internal_error",
                    f"agents insert failed: {exc}",
                ) from exc
            except Exception as exc:
                conn.execute("ROLLBACK")
                raise RegistrationError(
                    "internal_error",
                    f"agents insert failed: {exc}",
                ) from exc
        raise RegistrationError(
            "internal_error",
            f"agent_id PK collision retry budget exhausted ({_AGENT_ID_RETRY_LIMIT})",
        ) from last_exc

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

    def list_agents(self, params: dict[str, Any]) -> dict[str, Any]:
        # Validate filter keys against the closed set (FR-026).
        allowed = {"role", "container_id", "active_only", "parent_agent_id"}
        for key in params.keys():
            if key not in allowed:
                raise RegistrationError(
                    "unknown_filter",
                    f"unknown filter key {key!r}; allowed: {sorted(allowed)}",
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
            rows = state_agents.list_agents(
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
            "agents": [_agent_record_to_full_dict(r) for r in rows],
        }

    # ------------------------------------------------------------------ #
    # set_role / set_label / set_capability — Phase 4 (US2). Stubs here
    # preserve the dispatch wiring contract in T010 — actual bodies land
    # in T053..T055.
    # ------------------------------------------------------------------ #

    def set_role(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        return self._set_role_impl(params, socket_peer_uid=socket_peer_uid)

    def set_label(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        return self._set_label_impl(params, socket_peer_uid=socket_peer_uid)

    def set_capability(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        return self._set_capability_impl(params, socket_peer_uid=socket_peer_uid)

    # ------------------------------------------------------------------ #
    # set_role implementation (US2 / FR-011 / FR-012 / FR-013 / FR-014)
    # ------------------------------------------------------------------ #

    def _set_role_impl(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        agent_id = params.get("agent_id")
        if not isinstance(agent_id, str):
            raise RegistrationError(
                "value_out_of_set",
                "params.agent_id must be a string",
            )
        validate_agent_id_shape(agent_id)
        new_role = params.get("role")
        validation.validate_role(new_role)
        confirm = bool(params.get("confirm", False))

        # FR-012: set-role --role swarm is rejected (swarm role can only
        # be assigned via register-self --role swarm --parent <id>).
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
                existing = state_agents.select_agent_by_id(conn, agent_id=agent_id)
                if existing is None:
                    raise RegistrationError(
                        "agent_not_found",
                        f"agent {agent_id} not found",
                    )
                # No-op short-circuit (FR-027) — same value, no audit row.
                if existing.role == new_role:
                    return {
                        "agent_id": agent_id,
                        "field": "role",
                        "prior_value": existing.role,
                        "new_value": new_role,
                        "effective_permissions": existing.effective_permissions,
                        "audit_appended": False,
                    }

                effective_perms_json = permissions.serialize_effective_permissions(
                    new_role
                )
                # FR-011 atomic re-check inside BEGIN IMMEDIATE
                # (Clarifications session 2026-05-07-continued Q3).
                conn.execute("BEGIN IMMEDIATE")
                try:
                    state = state_agents.select_active_for_role_and_container(
                        conn, agent_id=agent_id
                    )
                    if state is None:
                        # Race: agent disappeared between SELECT and BEGIN.
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_not_found", f"agent {agent_id} not found"
                        )
                    agent_active, container_active = state
                    if not agent_active or container_active is False:
                        conn.execute("ROLLBACK")
                        raise RegistrationError(
                            "agent_inactive",
                            f"agent {agent_id} or its container is inactive",
                        )
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
                # Append the audit row AFTER COMMIT (FR-014).
                audit_mod.append_role_change(
                    self.events_file,
                    agent_id=agent_id,
                    prior_role=existing.role,
                    new_role=new_role,
                    confirm_provided=confirm,
                    socket_peer_uid=socket_peer_uid,
                )
                return {
                    "agent_id": agent_id,
                    "field": "role",
                    "prior_value": existing.role,
                    "new_value": new_role,
                    "effective_permissions": permissions.effective_permissions(new_role),
                    "audit_appended": True,
                }
            finally:
                conn.close()

    # ------------------------------------------------------------------ #
    # set_label implementation (US2 / FR-027 / FR-031)
    # ------------------------------------------------------------------ #

    def _set_label_impl(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        agent_id = params.get("agent_id")
        if not isinstance(agent_id, str):
            raise RegistrationError(
                "value_out_of_set",
                "params.agent_id must be a string",
            )
        validate_agent_id_shape(agent_id)
        new_label = params.get("label")
        new_label = validation.validate_label(new_label)

        with self.agent_locks.for_key(agent_id):
            conn = self.connection_factory()
            try:
                existing = state_agents.select_agent_by_id(conn, agent_id=agent_id)
                if existing is None:
                    raise RegistrationError(
                        "agent_not_found", f"agent {agent_id} not found"
                    )
                if not existing.active:
                    raise RegistrationError(
                        "agent_inactive", f"agent {agent_id} is inactive"
                    )
                if existing.label == new_label:
                    return {
                        "agent_id": agent_id,
                        "field": "label",
                        "prior_value": existing.label,
                        "new_value": new_label,
                        "effective_permissions": existing.effective_permissions,
                        "audit_appended": False,
                    }
                conn.execute("BEGIN IMMEDIATE")
                try:
                    state_agents.update_agent_label(
                        conn, agent_id=agent_id, label=new_label
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return {
                    "agent_id": agent_id,
                    "field": "label",
                    "prior_value": existing.label,
                    "new_value": new_label,
                    "effective_permissions": existing.effective_permissions,
                    "audit_appended": False,
                }
            finally:
                conn.close()

    # ------------------------------------------------------------------ #
    # set_capability implementation (US2 / FR-027 / FR-031)
    # ------------------------------------------------------------------ #

    def _set_capability_impl(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        agent_id = params.get("agent_id")
        if not isinstance(agent_id, str):
            raise RegistrationError(
                "value_out_of_set",
                "params.agent_id must be a string",
            )
        validate_agent_id_shape(agent_id)
        new_capability = params.get("capability")
        validation.validate_capability(new_capability)

        with self.agent_locks.for_key(agent_id):
            conn = self.connection_factory()
            try:
                existing = state_agents.select_agent_by_id(conn, agent_id=agent_id)
                if existing is None:
                    raise RegistrationError(
                        "agent_not_found", f"agent {agent_id} not found"
                    )
                if not existing.active:
                    raise RegistrationError(
                        "agent_inactive", f"agent {agent_id} is inactive"
                    )
                if existing.capability == new_capability:
                    return {
                        "agent_id": agent_id,
                        "field": "capability",
                        "prior_value": existing.capability,
                        "new_value": new_capability,
                        "effective_permissions": existing.effective_permissions,
                        "audit_appended": False,
                    }
                conn.execute("BEGIN IMMEDIATE")
                try:
                    state_agents.update_agent_capability(
                        conn, agent_id=agent_id, capability=new_capability
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return {
                    "agent_id": agent_id,
                    "field": "capability",
                    "prior_value": existing.capability,
                    "new_value": new_capability,
                    "effective_permissions": existing.effective_permissions,
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
    """Validate and coerce the wire ``pane_composite_key`` object."""
    if not isinstance(value, dict):
        raise RegistrationError(
            "value_out_of_set",
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
                "value_out_of_set",
                f"params.pane_composite_key.{k} is required",
            )
    try:
        return (
            str(value["container_id"]),
            str(value["tmux_socket_path"]),
            str(value["tmux_session_name"]),
            int(value["tmux_window_index"]),
            int(value["tmux_pane_index"]),
            str(value["tmux_pane_id"]),
        )
    except (TypeError, ValueError) as exc:
        raise RegistrationError(
            "tmux_pane_malformed",
            f"params.pane_composite_key has malformed field: {exc}",
        ) from exc


def _agent_record_to_full_dict(record: AgentRecord) -> dict[str, Any]:
    """Marshal an ``AgentRecord`` into the wire JSON shape (data-model §6.2)."""
    return {
        "agent_id": record.agent_id,
        "container_id": record.container_id,
        "tmux_socket_path": record.tmux_socket_path,
        "tmux_session_name": record.tmux_session_name,
        "tmux_window_index": record.tmux_window_index,
        "tmux_pane_index": record.tmux_pane_index,
        "tmux_pane_id": record.tmux_pane_id,
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


def _agent_record_to_register_payload(
    record: AgentRecord, *, created_or_reactivated: str
) -> dict[str, Any]:
    payload = _agent_record_to_full_dict(record)
    payload["created_or_reactivated"] = created_or_reactivated
    return payload
