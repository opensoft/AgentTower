"""Daemon-side LogService — orchestrator for the FEAT-007 socket methods.

Implements the validation order from data-model.md §7 (attach_log) and
§7-derived flows for detach_log / attach_log_status / attach_log_preview.
Owns the per-(agent_id) and per-(log_path) mutex registries; commits each
call in a single ``BEGIN IMMEDIATE`` SQLite transaction with rollback on
failure (FR-016).

Mirrors the FEAT-006 ``AgentService`` shape so the dispatch + lifecycle
patterns are uniform across the daemon.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agents.errors import RegistrationError
from ..agents.identifiers import validate_agent_id_shape
from ..agents.mutex import AgentLockMap
from ..socket_api import errors as socket_errors
from ..state import log_attachments as la_state
from ..state import log_offsets as lo_state
from . import audit as audit_mod
from . import lifecycle as lifecycle_mod
from . import path_validation
from .canonical_paths import (
    container_canonical_log_path_for,
    host_canonical_log_path_for,
)
from .docker_exec import DockerExecRunner, DockerExecResult
from .host_visibility import (
    HostVisibilityProof,
    LogPathNotHostVisible,
    prove_host_visible,
)
from .identifiers import (
    MAX_ATTACHMENT_ID_RETRIES,
    generate_attachment_id,
)
from .mutex import LogPathLockMap, acquire_in_order
from .path_validation import LogPathInvalid
from .pipe_pane import (
    PIPE_PANE_STDERR_PATTERNS,
    build_attach_argv,
    build_inspection_argv,
    build_toggle_off_argv,
    render_pipe_command_for_audit,
    sanitize_pipe_pane_stderr,
)
from .pipe_pane_state import (
    classify_pipe_target,
    parse_list_panes_output,
    sanitize_prior_pipe_target,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _check_schema_version(
    params: dict[str, Any], *, daemon_schema_version: int, method_name: str
) -> None:
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
    if key not in params:
        raise RegistrationError(
            "bad_request", f"{method_name}: params.{key} is required"
        )
    value = params[key]
    if not isinstance(value, str):
        raise RegistrationError(
            "bad_request", f"{method_name}: params.{key} must be a string"
        )
    return value


# ---------------------------------------------------------------------------
# Service.
# ---------------------------------------------------------------------------


@dataclass
class LogService:
    """FEAT-007 LogService — owns the attach/detach/status/preview pipeline.

    Mutexes:
    * :attr:`agent_locks` — per-``agent_id`` (REUSED from FEAT-006 per FR-040)
    * :attr:`log_path_locks` — per-``log_path`` (NEW per FR-041)

    External adapters:
    * :attr:`docker_exec_runner` — issues ``docker exec`` for FR-010 / FR-011 /
      FR-019 / FR-021c.

    Configuration:
    * :attr:`daemon_home` — host $HOME for canonical-path generation (FR-005)
      and daemon-owned-root rejection (FR-052).
    """

    connection_factory: Callable[[], sqlite3.Connection]
    agent_locks: AgentLockMap
    log_path_locks: LogPathLockMap
    events_file: Path | None
    schema_version: int
    daemon_home: Path
    docker_exec_runner: DockerExecRunner
    lifecycle_logger: Any = None

    # ------------------------------------------------------------------ #
    # attach_log (FR-001..FR-019, FR-021, FR-021d, FR-040..FR-044)
    # ------------------------------------------------------------------ #

    _ATTACH_ALLOWED_KEYS = frozenset(
        {"schema_version", "agent_id", "log_path"}
    )
    _DETACH_ALLOWED_KEYS = frozenset({"schema_version", "agent_id"})
    _STATUS_ALLOWED_KEYS = frozenset({"schema_version", "agent_id"})
    _PREVIEW_ALLOWED_KEYS = frozenset({"schema_version", "agent_id", "lines"})

    def attach_log(
        self,
        params: dict[str, Any],
        *,
        socket_peer_uid: int,
        source: str = "explicit",
        defer_audit: bool = False,
    ) -> dict[str, Any]:
        """Implement the attach_log socket method (data-model.md §7).

        When ``defer_audit=True`` the daemon-side audit append is SKIPPED
        and the staged payload is returned in the result under
        ``__deferred_audit__``. The caller (AgentService.register_agent
        with FR-035 ordering) is then responsible for appending both
        audit rows in the documented order. Standalone callers leave
        ``defer_audit=False`` and the audit append happens as usual.
        """
        _check_unknown_keys(
            params, self._ATTACH_ALLOWED_KEYS, method_name="attach_log"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="attach_log",
        )
        agent_id = _require_string(params, "agent_id", method_name="attach_log")
        validate_agent_id_shape(agent_id)

        # Resolve agent → bound container + pane (FR-001..FR-004).
        agent_record = self._resolve_active_agent(agent_id)
        container_record = self._resolve_active_container(agent_record.container_id)
        self._require_active_pane(agent_record)

        log_path_supplied, proof, host_path = self._resolve_attach_target(
            params,
            method_name="attach_log",
            agent_record=agent_record,
            container_record=container_record,
        )

        # FR-013 tmux availability check (cached on container row).
        if container_record.get("tmux_present") is False:
            raise RegistrationError(
                "tmux_unavailable",
                f"tmux is not available in container {agent_record.container_id!r}",
            )

        # FR-040 + FR-041 + FR-059: acquire per-agent lock first, then per-path
        # lock only when an explicit --log was supplied.
        agent_lock = self.agent_locks.for_key(agent_id)
        path_lock = self.log_path_locks.for_key(host_path) if log_path_supplied else None

        with acquire_in_order(agent_lock, path_lock):
            return self._attach_log_locked(
                agent_record=agent_record,
                container_record=container_record,
                proof=proof,
                host_path=host_path,
                source=source,
                socket_peer_uid=socket_peer_uid,
                explicit_log_supplied=log_path_supplied,
                defer_audit=defer_audit,
                conn=None,
                manage_transaction=True,
            )

    def attach_log_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        params: dict[str, Any],
        agent_record: Any,
        container_record: dict[str, Any],
        socket_peer_uid: int,
        source: str = "register_self",
        defer_audit: bool = True,
    ) -> dict[str, Any]:
        """Attach inside an existing caller-owned SQLite transaction."""
        _check_unknown_keys(
            params, self._ATTACH_ALLOWED_KEYS, method_name="attach_log"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="attach_log",
        )
        agent_id = _require_string(params, "agent_id", method_name="attach_log")
        validate_agent_id_shape(agent_id)
        if agent_id != agent_record.agent_id:
            raise RegistrationError(
                "bad_request",
                "attach_log: params.agent_id must match the active registration target",
            )
        log_path_supplied, proof, host_path = self._resolve_attach_target(
            params,
            method_name="attach_log",
            agent_record=agent_record,
            container_record=container_record,
        )
        if container_record.get("tmux_present") is False:
            raise RegistrationError(
                "tmux_unavailable",
                f"tmux is not available in container {agent_record.container_id!r}",
            )

        agent_lock = self.agent_locks.for_key(agent_id)
        path_lock = self.log_path_locks.for_key(host_path) if log_path_supplied else None
        with acquire_in_order(agent_lock, path_lock):
            return self._attach_log_locked(
                agent_record=agent_record,
                container_record=container_record,
                proof=proof,
                host_path=host_path,
                source=source,
                socket_peer_uid=socket_peer_uid,
                explicit_log_supplied=log_path_supplied,
                defer_audit=defer_audit,
                conn=conn,
                manage_transaction=False,
            )

    def _attach_log_locked(
        self,
        *,
        agent_record: Any,
        container_record: dict[str, Any],
        proof: HostVisibilityProof,
        host_path: str,
        source: str,
        socket_peer_uid: int,
        explicit_log_supplied: bool,
        defer_audit: bool = False,
        conn: sqlite3.Connection | None = None,
        manage_transaction: bool = True,
    ) -> dict[str, Any]:
        """Inner attach pipeline; runs under acquired locks."""
        deferred_audit: dict[str, Any] | None = None

        def _emit_or_defer_audit(**kwargs: Any) -> None:
            nonlocal deferred_audit
            if defer_audit:
                deferred_audit = dict(kwargs)
                return
            audit_mod.append_log_attachment_change(self.events_file, **kwargs)

        agent_id = agent_record.agent_id
        container_user = container_record["bench_user"]
        container_id = agent_record.container_id
        pane_short_form = self._pane_short_form(agent_record)

        owned_conn = conn is None
        if conn is None:
            conn = self.connection_factory()
        try:
            if manage_transaction:
                conn.execute("BEGIN IMMEDIATE")

            # Re-check: another agent owns this path active? (FR-009)
            existing_active_other = la_state.select_active_by_log_path(
                conn, log_path=host_path
            )
            if (
                existing_active_other is not None
                and existing_active_other.agent_id != agent_id
            ):
                # Don't roll back here — the ``except RegistrationError``
                # handler below already gates the rollback on
                # ``manage_transaction``. An unconditional rollback here
                # would tear down the outer ``AgentService`` transaction
                # when ``manage_transaction=False`` (register-self path)
                # and surface as ``sqlite3.OperationalError`` instead of
                # the closed-set ``log_path_in_use`` code.
                raise RegistrationError(
                    "log_path_in_use",
                    f"log_path {host_path!r} is owned by agent_id "
                    f"{existing_active_other.agent_id!r}",
                )

            # Re-check: existing row for this (agent, path)?
            existing = la_state.select_for_agent_path(
                conn, agent_id=agent_id, log_path=host_path
            )

            # Check: this agent's most-recent recoverable row at a different
            # path → supersede that row (FR-019). FR-019 applies regardless
            # of prior status — supersede from active/stale/detached. The
            # toggle-off path below keys on live pane state (not on the
            # prior row's status), so toggle-off is correctly skipped when
            # the prior was stale or detached (no live pipe).
            agent_recent = la_state.select_most_recent_for_agent(
                conn, agent_id=agent_id
            )
            supersede_target: la_state.LogAttachmentRecord | None = None
            if (
                agent_recent is not None
                and agent_recent.status in ("active", "stale", "detached")
                and agent_recent.log_path != host_path
            ):
                supersede_target = agent_recent

            # FR-008: pre-create the host log file at mode 0600 BEFORE issuing
            # any pipe-pane command. The bench-side `cat >> <file>` opens the
            # file in append mode under the bench user's umask, which would
            # otherwise create it at 0o644 and trip the FR-008 invariant.
            # Pre-creating ensures cat appends to an existing 0o600 file.
            self._ensure_log_dir_and_file(host_path)

            # FR-018: idempotent re-attach (same path, status=active).
            if existing is not None and existing.status == "active":
                # Defensive pipe-pane re-issue (idempotent under -o flag).
                self._issue_pipe_pane_attach(
                    container_user, container_id, pane_short_form,
                    proof.container_path,
                )
                if manage_transaction:
                    conn.execute("COMMIT")
                # When ``manage_transaction=True`` the COMMIT above released
                # the conn's snapshot, so a fresh connection is fine; when
                # ``False`` the caller's transaction is still open and the
                # offset row must be read on that same conn to see consistent
                # state. ``conn_for_offset`` carries that distinction.
                return self._render_attach_result(
                    existing, byte_offset=0, line_offset=0, is_new=False,
                    prior_status=existing.status,
                    extra_offset_load=True,
                    conn_for_offset=None if manage_transaction else conn,
                )

            # FR-011 pipe-state inspection.
            inspect_result = self._inspect_pipe_state(
                container_user, container_id, pane_short_form
            )
            pane_state = parse_list_panes_output(inspect_result.stdout)
            classification = classify_pipe_target(
                pane_state.pipe_command, proof.container_path
            )
            prior_pipe_target_audit: str | None = None

            # If a foreign pipe is active, toggle it off first.
            if pane_state.pipe_active and not classification.is_canonical:
                if classification.foreign_target:
                    prior_pipe_target_audit = sanitize_prior_pipe_target(
                        classification.foreign_target
                    )
                self._issue_pipe_pane_toggle_off(
                    container_user, container_id, pane_short_form
                )

            # If the pane is already piped to the canonical path, skip the
            # attach issuance (no-op — the daemon already won this state).
            # Otherwise issue the attach.
            if not (pane_state.pipe_active and classification.is_canonical):
                self._issue_pipe_pane_attach(
                    container_user, container_id, pane_short_form,
                    proof.container_path,
                )

            # SQLite mutations.
            now = _now_iso()
            pipe_command_audit = render_pipe_command_for_audit(
                container_user, container_id, pane_short_form, proof.container_path
            )

            # FR-019 supersede the prior row at a different path.
            new_attachment_id = self._allocate_attachment_id(conn)
            if supersede_target is not None:
                la_state.update_status(
                    conn,
                    attachment_id=supersede_target.attachment_id,
                    new_status="superseded",
                    last_status_at=now,
                    superseded_at=now,
                    superseded_by=new_attachment_id,
                )
                # FR-061: clear file-missing suppression for the prior path
                # because the row is leaving stale (if it was stale).
                lifecycle_mod.reset_suppression_for_path(
                    agent_id, supersede_target.log_path
                )

            # FR-021 (stale recovery) / FR-021d (detached recovery) — same path,
            # existing row → update in place.
            prior_status: str | None = None
            byte_offset_after = 0
            line_offset_after = 0
            if existing is not None and existing.status in ("stale", "detached"):
                prior_status = existing.status
                la_state.update_status(
                    conn,
                    attachment_id=existing.attachment_id,
                    new_status="active",
                    last_status_at=now,
                )
                # FR-021 file-consistency check.
                offset_row = lo_state.select(
                    conn, agent_id=agent_id, log_path=host_path
                )
                if offset_row is not None and prior_status == "stale":
                    file_intact = self._file_consistency_intact(
                        host_path, offset_row.file_inode, offset_row.file_size_seen
                    )
                    if not file_intact:
                        from . import host_fs as host_fs_mod

                        st = host_fs_mod.stat_log_file(host_path)
                        new_inode = st.inode if st is not None else None
                        new_size = st.size if st is not None else 0
                        lo_state.reset(
                            conn,
                            agent_id=agent_id,
                            log_path=host_path,
                            file_inode=new_inode,
                            file_size_seen=new_size,
                            timestamp=now,
                        )
                        # FR-046 lifecycle: rotation event in addition to audit.
                        lifecycle_mod.emit_log_rotation_detected(
                            self.lifecycle_logger,
                            agent_id=agent_id,
                            log_path=host_path,
                            prior_inode=offset_row.file_inode,
                            new_inode=new_inode,
                            prior_size=offset_row.file_size_seen,
                            new_size=new_size,
                        )
                        # FR-061: this is a fresh stream; clear file-missing
                        # suppression for this (agent, path).
                    else:
                        byte_offset_after = offset_row.byte_offset
                        line_offset_after = offset_row.line_offset
                elif offset_row is not None and prior_status == "detached":
                    # FR-021d: retain offsets byte-for-byte.
                    byte_offset_after = offset_row.byte_offset
                    line_offset_after = offset_row.line_offset
                lifecycle_mod.reset_suppression_for_path(agent_id, host_path)

                # Audit row for this status transition.
                _emit_or_defer_audit(
                    attachment_id=existing.attachment_id,
                    agent_id=agent_id,
                    prior_status=prior_status,
                    new_status="active",
                    prior_path=existing.log_path,
                    new_path=host_path,
                    prior_pipe_target=prior_pipe_target_audit,
                    source=source,
                    socket_peer_uid=socket_peer_uid,
                )
                if manage_transaction:
                    conn.execute("COMMIT")
                # Pass ``last_status_at=now`` so the JSON envelope reflects
                # the just-applied status transition (stale/detached → active)
                # rather than the pre-mutation timestamp from ``existing``.
                result = self._render_attach_result(
                    existing,
                    byte_offset=byte_offset_after,
                    line_offset=line_offset_after,
                    is_new=False,
                    prior_status=prior_status,
                    last_status_at=now,
                )
                if deferred_audit is not None:
                    result["__deferred_audit__"] = deferred_audit
                return result

            # Else: brand-new row OR superseded prior at different path.
            # (file already pre-created at the top of this function — FR-008.)
            new_record = la_state.LogAttachmentRecord(
                attachment_id=new_attachment_id,
                agent_id=agent_id,
                container_id=agent_record.container_id,
                tmux_socket_path=agent_record.tmux_socket_path,
                tmux_session_name=agent_record.tmux_session_name,
                tmux_window_index=agent_record.tmux_window_index,
                tmux_pane_index=agent_record.tmux_pane_index,
                tmux_pane_id=agent_record.tmux_pane_id,
                log_path=host_path,
                status="active",
                source=source,
                pipe_pane_command=pipe_command_audit,
                prior_pipe_target=prior_pipe_target_audit,
                attached_at=now,
                last_status_at=now,
                superseded_at=None,
                superseded_by=None,
                created_at=now,
            )
            la_state.insert(conn, new_record)
            lo_state.insert_initial(
                conn, agent_id=agent_id, log_path=host_path, timestamp=now
            )

            _emit_or_defer_audit(
                attachment_id=new_attachment_id,
                agent_id=agent_id,
                prior_status=(supersede_target.status if supersede_target else None),
                new_status="active",
                prior_path=(supersede_target.log_path if supersede_target else None),
                new_path=host_path,
                prior_pipe_target=prior_pipe_target_audit,
                source=source,
                socket_peer_uid=socket_peer_uid,
            )

            if manage_transaction:
                conn.execute("COMMIT")
            result = self._render_attach_result(
                new_record, byte_offset=0, line_offset=0, is_new=True,
                prior_status=(supersede_target.status if supersede_target else None),
            )
            if deferred_audit is not None:
                result["__deferred_audit__"] = deferred_audit
            return result
        except RegistrationError:
            if manage_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        except sqlite3.OperationalError as exc:
            if manage_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            # FR-042 SQLITE_BUSY → internal_error (no retry, no swallow).
            if "database is locked" in str(exc) or "busy" in str(exc).lower():
                raise RegistrationError(
                    "internal_error",
                    f"sqlite contention surfaced: {exc}",
                ) from exc
            raise RegistrationError("internal_error", str(exc)) from exc
        except Exception as exc:
            if manage_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise RegistrationError("internal_error", str(exc)) from exc
        finally:
            if owned_conn:
                conn.close()

    def _allocate_attachment_id(self, conn: sqlite3.Connection) -> str:
        """Generate a fresh attachment_id; bounded retry on PK collision."""
        for attempt in range(MAX_ATTACHMENT_ID_RETRIES):
            candidate = generate_attachment_id()
            cur = conn.execute(
                "SELECT 1 FROM log_attachments WHERE attachment_id = ?",
                (candidate,),
            )
            if cur.fetchone() is None:
                return candidate
        raise RegistrationError(
            "internal_error",
            f"attachment_id allocation exhausted {MAX_ATTACHMENT_ID_RETRIES} attempts",
        )

    # ------------------------------------------------------------------ #
    # detach_log (FR-021a..e)
    # ------------------------------------------------------------------ #

    def detach_log(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        _check_unknown_keys(
            params, self._DETACH_ALLOWED_KEYS, method_name="detach_log"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="detach_log",
        )
        agent_id = _require_string(params, "agent_id", method_name="detach_log")
        validate_agent_id_shape(agent_id)

        agent_record = self._resolve_active_agent(agent_id)
        container_record = self._resolve_active_container(agent_record.container_id)
        self._require_active_pane(agent_record)

        agent_lock = self.agent_locks.for_key(agent_id)
        with acquire_in_order(agent_lock, None):
            return self._detach_log_locked(
                agent_record=agent_record,
                container_record=container_record,
                socket_peer_uid=socket_peer_uid,
            )

    def _detach_log_locked(
        self, *, agent_record: Any, container_record: dict[str, Any], socket_peer_uid: int
    ) -> dict[str, Any]:
        agent_id = agent_record.agent_id
        container_user = container_record["bench_user"]
        container_id = agent_record.container_id
        pane_short_form = self._pane_short_form(agent_record)

        conn = self.connection_factory()
        try:
            conn.execute("BEGIN IMMEDIATE")

            existing = la_state.select_active_for_agent(conn, agent_id=agent_id)
            if existing is None:
                conn.execute("ROLLBACK")
                raise RegistrationError(
                    "attachment_not_found",
                    f"agent {agent_id!r} has no active log attachment",
                )

            # FR-021c: issue toggle-off; daemon swallows any pipe error here
            # under the FR-055 boundary — but for a live active row the pipe
            # SHOULD be running, so a failure here surfaces as pipe_pane_failed.
            result = self.docker_exec_runner.run(
                build_toggle_off_argv(container_user, container_id, pane_short_form)
            )
            if result.failure_kind is not None:
                conn.execute("ROLLBACK")
                raise RegistrationError(
                    result.failure_kind,
                    f"pipe-pane toggle-off: "
                    f"{sanitize_pipe_pane_stderr(result.stderr) or result.failure_kind}",
                )
            if result.returncode != 0 or _stderr_matches_pipe_pane_failure(
                result.stderr
            ):
                conn.execute("ROLLBACK")
                raise RegistrationError(
                    "pipe_pane_failed",
                    f"pipe-pane toggle-off failed: "
                    f"{sanitize_pipe_pane_stderr(result.stderr) or 'non-zero exit'}",
                )

            now = _now_iso()
            la_state.update_status(
                conn,
                attachment_id=existing.attachment_id,
                new_status="detached",
                last_status_at=now,
            )

            offset_row = lo_state.select(
                conn, agent_id=agent_id, log_path=existing.log_path
            )
            conn.execute("COMMIT")
            try:
                audit_mod.append_log_attachment_change(
                    self.events_file,
                    attachment_id=existing.attachment_id,
                    agent_id=agent_id,
                    prior_status="active",
                    new_status="detached",
                    prior_path=existing.log_path,
                    new_path=existing.log_path,
                    prior_pipe_target=None,
                    source="explicit",
                    socket_peer_uid=socket_peer_uid,
                )
            except Exception:  # pragma: no cover - defensive
                self._emit_lifecycle(
                    "audit_append_failed",
                    method="detach_log",
                    agent_id=agent_id,
                    attachment_id=existing.attachment_id,
                )
            return {
                "agent_id": agent_id,
                "attachment_id": existing.attachment_id,
                "log_path": existing.log_path,
                "status": "detached",
                "byte_offset": offset_row.byte_offset if offset_row else 0,
                "line_offset": offset_row.line_offset if offset_row else 0,
                "last_status_at": now,
            }
        except RegistrationError:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise RegistrationError("internal_error", str(exc)) from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # attach_log_status (FR-032)
    # ------------------------------------------------------------------ #

    def attach_log_status(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        _check_unknown_keys(
            params, self._STATUS_ALLOWED_KEYS, method_name="attach_log_status"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="attach_log_status",
        )
        agent_id = _require_string(
            params, "agent_id", method_name="attach_log_status"
        )
        validate_agent_id_shape(agent_id)

        # Universal read: only check agent_not_found; everything else is
        # status reporting.
        conn = self.connection_factory()
        try:
            cur = conn.execute(
                "SELECT 1 FROM agents WHERE agent_id = ?", (agent_id,)
            )
            if cur.fetchone() is None:
                raise RegistrationError(
                    "agent_not_found", f"agent {agent_id!r} not found"
                )
            attachment = la_state.select_most_recent_for_agent(
                conn, agent_id=agent_id
            )
            if attachment is None:
                return {
                    "agent_id": agent_id,
                    "attachment": None,
                    "offset": None,
                }
            offset = lo_state.select(
                conn, agent_id=agent_id, log_path=attachment.log_path
            )
            return {
                "agent_id": agent_id,
                "attachment": {
                    "attachment_id": attachment.attachment_id,
                    "log_path": attachment.log_path,
                    "status": attachment.status,
                    "source": attachment.source,
                    "attached_at": attachment.attached_at,
                    "last_status_at": attachment.last_status_at,
                    "superseded_at": attachment.superseded_at,
                    "superseded_by": attachment.superseded_by,
                },
                "offset": (
                    {
                        "byte_offset": offset.byte_offset,
                        "line_offset": offset.line_offset,
                        "last_event_offset": offset.last_event_offset,
                        "last_output_at": offset.last_output_at,
                        "file_inode": offset.file_inode,
                        "file_size_seen": offset.file_size_seen,
                    }
                    if offset
                    else None
                ),
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # attach_log_preview (FR-033)
    # ------------------------------------------------------------------ #

    def attach_log_preview(
        self, params: dict[str, Any], *, socket_peer_uid: int
    ) -> dict[str, Any]:
        from . import host_fs as host_fs_mod
        from . import redaction as redaction_mod

        _check_unknown_keys(
            params, self._PREVIEW_ALLOWED_KEYS, method_name="attach_log_preview"
        )
        _check_schema_version(
            params,
            daemon_schema_version=self.schema_version,
            method_name="attach_log_preview",
        )
        agent_id = _require_string(
            params, "agent_id", method_name="attach_log_preview"
        )
        validate_agent_id_shape(agent_id)

        if "lines" not in params:
            raise RegistrationError(
                "bad_request", "attach_log_preview: params.lines is required"
            )
        lines_in = params["lines"]
        if not isinstance(lines_in, int) or isinstance(lines_in, bool):
            raise RegistrationError(
                "bad_request", "attach_log_preview: params.lines must be an integer"
            )
        if lines_in < 1 or lines_in > 200:
            raise RegistrationError(
                "value_out_of_set",
                f"attach_log_preview: lines must be between 1 and 200; got {lines_in}",
            )

        conn = self.connection_factory()
        try:
            cur = conn.execute(
                "SELECT 1 FROM agents WHERE agent_id = ?", (agent_id,)
            )
            if cur.fetchone() is None:
                raise RegistrationError(
                    "agent_not_found", f"agent {agent_id!r} not found"
                )
            attachment = la_state.select_most_recent_for_agent(
                conn, agent_id=agent_id
            )
            if attachment is None or attachment.status == "superseded":
                raise RegistrationError(
                    "attachment_not_found",
                    f"no inspectable attachment for agent {agent_id!r}",
                )
        finally:
            conn.close()

        # File read happens outside the SQLite connection.
        if not host_fs_mod.file_exists(attachment.log_path):
            raise RegistrationError(
                "log_file_missing",
                f"host log file {attachment.log_path!r} does not exist",
            )
        try:
            raw_lines = host_fs_mod.read_tail_lines(attachment.log_path, lines_in)
        except FileNotFoundError as exc:
            raise RegistrationError("log_file_missing", str(exc)) from exc

        rendered = [redaction_mod.redact_one_line(line) for line in raw_lines]
        return {
            "agent_id": agent_id,
            "attachment_id": attachment.attachment_id,
            "log_path": attachment.log_path,
            "lines": rendered,
        }

    # ------------------------------------------------------------------ #
    # Helpers.
    # ------------------------------------------------------------------ #

    def _resolve_active_agent(self, agent_id: str) -> Any:
        """Resolve agent_id to an AgentRecord; raise per FR-001/FR-002."""
        from ..state import agents as agents_state

        conn = self.connection_factory()
        try:
            record = agents_state.select_agent_by_id(conn, agent_id=agent_id)
        finally:
            conn.close()
        if record is None:
            raise RegistrationError(
                "agent_not_found", f"agent {agent_id!r} not found"
            )
        if not record.active:
            raise RegistrationError(
                "agent_inactive", f"agent {agent_id!r} is inactive"
            )
        return record

    def _resolve_active_container(self, container_id: str) -> dict[str, Any]:
        """Return container row's relevant fields (mounts_json, bench_user, tmux_present)."""
        from ..state.bench_user import normalize_bench_user_for_exec

        conn = self.connection_factory()
        try:
            cur = conn.execute(
                """
                SELECT active, mounts_json, config_user, inspect_json
                  FROM containers WHERE container_id = ?
                """,
                (container_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            raise RegistrationError(
                "agent_inactive", f"container {container_id!r} not found"
            )
        active = bool(row[0])
        if not active:
            raise RegistrationError(
                "agent_inactive", f"container {container_id!r} is inactive"
            )
        # Docker ``Config.User`` may be ``user:uid`` (or whitespace/empty);
        # strip the ``:uid`` suffix and fall back to ``root`` so canonical
        # path construction and ``docker exec -u`` get a bare username.
        # Mirrors ``AgentService._select_active_container_for_attach`` and
        # ``logs.orphan_recovery._bench_containers``.
        bench_user = normalize_bench_user_for_exec(row[2])
        # We don't have a persisted tmux_present field on containers in this
        # build; derive a default of None (treat as available unless explicitly
        # known otherwise). Future FEAT-003 may persist this.
        return {
            "mounts_json": row[1] or "[]",
            "bench_user": bench_user,
            "tmux_present": True,
        }

    def _resolve_attach_target(
        self,
        params: dict[str, Any],
        *,
        method_name: str,
        agent_record: Any,
        container_record: dict[str, Any],
    ) -> tuple[bool, HostVisibilityProof, str]:
        """Resolve the requested/default attach target into proof + host path."""
        log_path_supplied = "log_path" in params
        requested_path: str
        if log_path_supplied:
            raw = params["log_path"]
            if not isinstance(raw, str):
                raise RegistrationError(
                    "bad_request", f"{method_name}: params.log_path must be a string"
                )
            try:
                requested_path = path_validation.validate_log_path(
                    raw, home=self.daemon_home
                )
            except LogPathInvalid as exc:
                raise RegistrationError("log_path_invalid", str(exc)) from exc
        else:
            requested_path = str(
                container_canonical_log_path_for(
                    container_record["bench_user"],
                    agent_record.container_id,
                    agent_record.agent_id,
                )
            )
        candidate_paths = [requested_path]
        if not log_path_supplied:
            candidate_paths.append(
                str(
                    host_canonical_log_path_for(
                        self.daemon_home,
                        agent_record.container_id,
                        agent_record.agent_id,
                    )
                )
            )
        proof: HostVisibilityProof | None = None
        last_exc: LogPathNotHostVisible | None = None
        for candidate in candidate_paths:
            try:
                proof = prove_host_visible(
                    container_record["mounts_json"],
                    candidate,
                    require_writable=True,
                )
                break
            except LogPathNotHostVisible as exc:
                last_exc = exc
        if proof is None:
            assert last_exc is not None
            if "max" in str(last_exc) and "FR-063" in str(last_exc):
                lifecycle_mod.emit_mounts_json_oversized(
                    self.lifecycle_logger,
                    container_id=agent_record.container_id,
                    observed_count=-1,
                    max_count=256,
                )
            raise RegistrationError("log_path_not_host_visible", str(last_exc)) from last_exc
        return log_path_supplied, proof, proof.host_path

    def _require_active_pane(self, agent_record: Any) -> None:
        """FR-003: bound pane MUST be active=1."""
        conn = self.connection_factory()
        try:
            cur = conn.execute(
                """
                SELECT active FROM panes
                 WHERE container_id = ? AND tmux_socket_path = ?
                   AND tmux_session_name = ? AND tmux_window_index = ?
                   AND tmux_pane_index = ? AND tmux_pane_id = ?
                """,
                (
                    agent_record.container_id,
                    agent_record.tmux_socket_path,
                    agent_record.tmux_session_name,
                    agent_record.tmux_window_index,
                    agent_record.tmux_pane_index,
                    agent_record.tmux_pane_id,
                ),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None or not bool(row[0]):
            raise RegistrationError(
                "pane_unknown_to_daemon",
                f"bound pane is not present in panes table",
            )

    def _pane_short_form(self, agent_record: Any) -> str:
        """FEAT-004 short pane form: ``<session>:<window>.<pane>``."""
        return (
            f"{agent_record.tmux_session_name}:"
            f"{agent_record.tmux_window_index}."
            f"{agent_record.tmux_pane_index}"
        )

    @staticmethod
    def _raise_docker_failure_if_present(
        result: DockerExecResult, *, op: str
    ) -> None:
        """If the runner surfaced a docker-level failure, raise its closed-set
        code rather than letting it masquerade as ``pipe_pane_failed`` in the
        downstream stderr-pattern check.
        """
        if result.failure_kind is not None:
            raise RegistrationError(
                result.failure_kind,
                f"{op}: {sanitize_pipe_pane_stderr(result.stderr) or result.failure_kind}",
            )

    def _inspect_pipe_state(
        self, container_user: str, container_id: str, pane_short_form: str
    ) -> DockerExecResult:
        result = self.docker_exec_runner.run(
            build_inspection_argv(container_user, container_id, pane_short_form)
        )
        # Distinguish docker-level failures (binary missing / timeout) from
        # tmux-level failures so clients see the actionable closed-set code.
        self._raise_docker_failure_if_present(result, op="tmux list-panes")
        # FR-055: tmux-level failures here surface as pipe_pane_failed.
        if result.returncode != 0 or _stderr_matches_pipe_pane_failure(
            result.stderr
        ):
            raise RegistrationError(
                "pipe_pane_failed",
                f"tmux list-panes failed: "
                f"{sanitize_pipe_pane_stderr(result.stderr) or 'non-zero exit'}",
            )
        return result

    def _issue_pipe_pane_attach(
        self,
        container_user: str,
        container_id: str,
        pane_short_form: str,
        container_side_log: str,
    ) -> None:
        result = self.docker_exec_runner.run(
            build_attach_argv(
                container_user, container_id, pane_short_form, container_side_log
            )
        )
        self._raise_docker_failure_if_present(result, op="tmux pipe-pane attach")
        if result.returncode != 0 or _stderr_matches_pipe_pane_failure(
            result.stderr
        ):
            # FR-055 + FR-012: refuse with pipe_pane_failed; no retry, no row.
            raise RegistrationError(
                "pipe_pane_failed",
                f"tmux pipe-pane attach failed: "
                f"{sanitize_pipe_pane_stderr(result.stderr) or 'non-zero exit'}",
            )

    def _issue_pipe_pane_toggle_off(
        self, container_user: str, container_id: str, pane_short_form: str
    ) -> None:
        result = self.docker_exec_runner.run(
            build_toggle_off_argv(container_user, container_id, pane_short_form)
        )
        self._raise_docker_failure_if_present(result, op="tmux pipe-pane toggle-off")
        if result.returncode != 0 or _stderr_matches_pipe_pane_failure(
            result.stderr
        ):
            raise RegistrationError(
                "pipe_pane_failed",
                f"tmux pipe-pane toggle-off failed: "
                f"{sanitize_pipe_pane_stderr(result.stderr) or 'non-zero exit'}",
            )

    def _ensure_log_dir_and_file(self, host_path: str) -> None:
        from . import host_fs as host_fs_mod

        try:
            host_fs_mod.ensure_log_directory_and_file(host_path)
        except OSError as exc:
            raise RegistrationError(
                "internal_error",
                f"failed to ensure host log file mode: {exc}",
            ) from exc

    def _emit_lifecycle(self, event: str, **kwargs: Any) -> None:
        if self.lifecycle_logger is None:
            return
        sanitized: dict[str, str] = {}
        for key, value in kwargs.items():
            text = str(value).replace("\x00", "")
            text = "".join(ch for ch in text if ord(ch) >= 32 or ch in ("\t",))
            sanitized[key] = text[:2048]
        try:
            self.lifecycle_logger.emit(event, **sanitized)
        except Exception:
            pass

    def _file_consistency_intact(
        self, host_path: str, stored_inode: str | None, stored_size_seen: int
    ) -> bool:
        """FR-021 file-consistency check: file present + inode match + size ≥ stored."""
        from . import host_fs as host_fs_mod

        st = host_fs_mod.stat_log_file(host_path)
        if st is None:
            return False
        if stored_inode is None:
            # Never observed — treat as fresh stream (reset).
            return False
        if st.inode != stored_inode:
            return False
        if st.size < stored_size_seen:
            return False
        return True

    def _render_attach_result(
        self,
        record: la_state.LogAttachmentRecord,
        *,
        byte_offset: int,
        line_offset: int,
        is_new: bool,
        prior_status: str | None,
        extra_offset_load: bool = False,
        conn_for_offset: sqlite3.Connection | None = None,
        last_status_at: str | None = None,
    ) -> dict[str, Any]:
        # If we don't have offsets in hand and this is an idempotent re-issue,
        # load them. When the caller is already inside an open transaction
        # (e.g. ``register-self --attach-log`` driving the inner-flow with
        # ``manage_transaction=False``), reuse their connection so the
        # offset read sees the same SQLite snapshot — opening a fresh
        # connection here could miss uncommitted writes from the same
        # transaction.
        if extra_offset_load:
            if conn_for_offset is not None:
                offset = lo_state.select(
                    conn_for_offset,
                    agent_id=record.agent_id,
                    log_path=record.log_path,
                )
            else:
                conn = self.connection_factory()
                try:
                    offset = lo_state.select(
                        conn, agent_id=record.agent_id, log_path=record.log_path
                    )
                finally:
                    conn.close()
            if offset is not None:
                byte_offset = offset.byte_offset
                line_offset = offset.line_offset
        # ``record`` is the pre-mutation snapshot; for status transitions
        # (stale/detached → active) the caller passes the post-mutation
        # ``last_status_at`` so the JSON envelope reflects current state.
        rendered_last_status_at = (
            last_status_at if last_status_at is not None else record.last_status_at
        )
        return {
            "agent_id": record.agent_id,
            "attachment_id": record.attachment_id,
            "log_path": record.log_path,
            "source": record.source,
            "status": "active",
            "byte_offset": byte_offset,
            "line_offset": line_offset,
            "attached_at": record.attached_at,
            "last_status_at": rendered_last_status_at,
            "is_new": is_new,
            "prior_status": prior_status,
        }


def _stderr_matches_pipe_pane_failure(stderr: str) -> bool:
    """Return True if any FR-012 stderr pattern appears in ``stderr``."""
    cleaned = (stderr or "").lower()
    return any(p.lower() in cleaned for p in PIPE_PANE_STDERR_PATTERNS)
