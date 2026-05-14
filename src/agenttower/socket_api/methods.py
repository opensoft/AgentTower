"""Method implementations for the FEAT-002 local control API.

In US1 only ``ping`` is implemented; ``status`` and ``shutdown`` are
fleshed out by US2 / US4. The dispatch table is intentionally closed so
unknown methods always return :data:`errors.UNKNOWN_METHOD`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..tmux.parsers import sanitize_text

from . import errors

if TYPE_CHECKING:
    from ..discovery.pane_service import PaneDiscoveryService
    from ..discovery.service import DiscoveryService

# ``Handler`` returns the response envelope (already shaped via make_ok / make_error).
# ``peer_uid`` is the SO_PEERCRED-derived uid of the AF_UNIX peer, injected by
# the server out-of-band so it cannot be spoofed via the request body. Tests
# that invoke handlers directly may rely on the default sentinel ``-1``.
Handler = Callable[..., dict[str, Any]]


# Sentinel used when no peer-credential information is available
# (e.g. unit tests calling DISPATCH directly without a real socket).
_NO_PEER_UID = -1


@dataclass
class DaemonContext:
    """Runtime context shared between the server and method handlers."""

    pid: int
    start_time_utc: datetime
    socket_path: Path
    state_path: Path
    daemon_version: str
    schema_version: int | None = None
    shutdown_requested: threading.Event | None = None
    discovery_service: "DiscoveryService | None" = None
    pane_service: "PaneDiscoveryService | None" = None
    agent_service: Any = None
    log_service: Any = None
    events_file: Path | None = None
    lifecycle_logger: Any = None
    # FEAT-008 — populated at daemon boot once Phase 3 (US1) lands.
    # Until then they remain ``None`` and the status surface reports
    # ``running: false``. See ``data-model.md`` §7.
    events_reader: Any = None
    follow_session_registry: Any = None
    events_config: Any = None
    # FEAT-009 — populated at daemon boot (T048). Handlers return
    # ``internal_error`` if any is unwired (defensive — production wiring
    # is mandatory). The ``state_conn`` is the SQLite connection the
    # operator-pane liveness check (Group-A walk Q8) uses to look up
    # caller agents via :func:`agents.select_agent_by_id`.
    state_conn: Any = None
    queue_service: Any = None
    routing_flag_service: Any = None
    delivery_worker: Any = None
    queue_audit_writer: Any = None
    message_queue_dao: Any = None
    daemon_state_dao: Any = None


def _ping(ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID) -> dict[str, Any]:
    return errors.make_ok({})


def _status(ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    delta = (now - ctx.start_time_utc).total_seconds()
    uptime_seconds = max(0, int(delta))

    # FEAT-008 — events_reader / events_persistence fields per
    # data-model.md §7. The reader populates them via the
    # ``events_reader`` and ``follow_session_registry`` attributes on
    # the DaemonContext; until Phase 3 (US1) wires these, the fields
    # default to a not-running state. They remain forward-compatible
    # with future degraded-mode reporting (FR-029 / FR-040).
    if ctx.events_reader is None:
        events_reader = {
            "running": False,
            "last_cycle_started_at": None,
            "last_cycle_duration_ms": None,
            "active_attachments": 0,
            "attachments_in_failure": [],
        }
        events_persistence = {"degraded_sqlite": None, "degraded_jsonl": None}
    else:
        snapshot = ctx.events_reader.status_snapshot()
        is_running = (
            bool(ctx.events_reader.is_running())
            if hasattr(ctx.events_reader, "is_running")
            else True
        )
        events_reader = {
            "running": is_running,
            "last_cycle_started_at": snapshot.last_cycle_started_at,
            "last_cycle_duration_ms": snapshot.last_cycle_duration_ms,
            "active_attachments": snapshot.active_attachments,
            "attachments_in_failure": snapshot.attachments_in_failure,
        }
        events_persistence = {
            "degraded_sqlite": snapshot.degraded_sqlite,
            "degraded_jsonl": snapshot.degraded_jsonl,
        }

    # FEAT-009 — routing kill switch + queue audit persistence
    # health surface (plan §"Status surface").
    routing_block: dict[str, Any]
    routing_svc = getattr(ctx, "routing_flag_service", None)
    if routing_svc is None:
        routing_block = {
            "value": None,
            "last_updated_at": None,
            "last_updated_by": None,
        }
    else:
        try:
            value, last_at, last_by = routing_svc.read_full()
        except Exception:
            value, last_at, last_by = None, None, None
        routing_block = {
            "value": value,
            "last_updated_at": last_at,
            "last_updated_by": last_by,
        }

    audit_writer = getattr(ctx, "queue_audit_writer", None)
    queue_audit_block: dict[str, Any]
    if audit_writer is None:
        queue_audit_block = {
            "degraded": False,
            "pending_rows": 0,
            "last_failure_exc_class": None,
        }
    else:
        queue_audit_block = {
            "degraded": bool(audit_writer.degraded),
            "pending_rows": int(audit_writer.pending_count),
            "last_failure_exc_class": audit_writer.last_failure_exc_class,
        }

    return errors.make_ok(
        {
            "alive": True,
            "pid": ctx.pid,
            "start_time_utc": ctx.start_time_utc.isoformat(timespec="microseconds"),
            "uptime_seconds": uptime_seconds,
            "socket_path": str(ctx.socket_path),
            "state_path": str(ctx.state_path),
            "schema_version": ctx.schema_version,
            "daemon_version": ctx.daemon_version,
            "events_reader": events_reader,
            "events_persistence": events_persistence,
            "routing": routing_block,
            "queue_audit": queue_audit_block,
        }
    )


def _shutdown(ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID) -> dict[str, Any]:
    if ctx.shutdown_requested is not None:
        ctx.shutdown_requested.set()
    return errors.make_ok({"shutting_down": True})


def _scan_result_to_payload(result: Any) -> dict[str, Any]:
    return {
        "scan_id": result.scan_id,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "status": result.status,
        "matched_count": result.matched_count,
        "inactive_reconciled_count": result.inactive_reconciled_count,
        "ignored_count": result.ignored_count,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "error_details": [
            {
                "container_id": e.container_id,
                "error_code": e.code,
                "error_message": e.message,
            }
            for e in result.error_details
        ],
    }


def _scan_containers(ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID) -> dict[str, Any]:
    if ctx.discovery_service is None:
        return errors.make_error(
            errors.INTERNAL_ERROR, "discovery service unavailable"
        )
    # Lazy import keeps the module-level Protocol forward-ref intact.
    from ..docker.adapter import DockerError

    try:
        result = ctx.discovery_service.scan()
    except DockerError as exc:
        if exc.code in errors.CLOSED_CODE_SET:
            return errors.make_error(exc.code, exc.message)
        return errors.make_error(errors.INTERNAL_ERROR, _internal_error_message(str(exc), prefix="scan failed"))
    except Exception as exc:  # pragma: no cover — defensive
        return errors.make_error(errors.INTERNAL_ERROR, _internal_error_message(str(exc), prefix="scan failed"))
    return errors.make_ok(_scan_result_to_payload(result))


def _list_containers(ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID) -> dict[str, Any]:
    if ctx.discovery_service is None:
        return errors.make_error(
            errors.INTERNAL_ERROR, "discovery service unavailable"
        )
    active_only = params.get("active_only", False)
    if not isinstance(active_only, bool):
        return errors.make_error(
            errors.BAD_REQUEST, "params.active_only must be a boolean"
        )
    rows = ctx.discovery_service.list_containers(active_only=active_only)
    payload = {
        "filter": "active_only" if active_only else "all",
        "containers": [
            {
                "id": r.container_id,
                "name": r.name,
                "image": r.image,
                "status": r.status,
                "labels": r.labels,
                "mounts": r.mounts,
                "active": r.active,
                "first_seen_at": r.first_seen_at,
                "last_scanned_at": r.last_scanned_at,
                "config_user": r.config_user,
                "working_dir": r.working_dir,
            }
            for r in rows
        ],
    }
    return errors.make_ok(payload)


def _pane_scan_to_payload(result: Any) -> dict[str, Any]:
    """Marshal a ``PaneScanResult`` into the FEAT-004 socket envelope shape.

    The dataclass field ``panes_reconciled_inactive`` is renamed at this JSON
    boundary to the canonical wire field ``panes_reconciled_to_inactive``
    (data-model §6 note 5). This is the only renamed field; every other
    field name is preserved.
    """
    return {
        "scan_id": result.scan_id,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "status": result.status,
        "containers_scanned": result.containers_scanned,
        "sockets_scanned": result.sockets_scanned,
        "panes_seen": result.panes_seen,
        "panes_newly_active": result.panes_newly_active,
        "panes_reconciled_to_inactive": result.panes_reconciled_inactive,
        "containers_skipped_inactive": result.containers_skipped_inactive,
        "containers_tmux_unavailable": result.containers_tmux_unavailable,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "error_details": [_pane_scope_error_to_dict(e) for e in result.error_details],
    }


def _pane_scope_error_to_dict(err: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "container_id": err.container_id,
        "error_code": err.error_code,
        "error_message": err.error_message,
    }
    if err.tmux_socket_path is not None:
        out["tmux_socket_path"] = err.tmux_socket_path
    if err.pane_truncations:
        out["pane_truncations"] = [
            {
                "tmux_pane_id": note.tmux_pane_id,
                "field": note.field,
                "original_len": note.original_len,
            }
            for note in err.pane_truncations
        ]
    return out


def _pane_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "container_id": row.container_id,
        "container_name": row.container_name,
        "container_user": row.container_user,
        "tmux_socket_path": row.tmux_socket_path,
        "tmux_session_name": row.tmux_session_name,
        "tmux_window_index": row.tmux_window_index,
        "tmux_pane_index": row.tmux_pane_index,
        "tmux_pane_id": row.tmux_pane_id,
        "pane_pid": row.pane_pid,
        "pane_tty": row.pane_tty,
        "pane_current_command": row.pane_current_command,
        "pane_current_path": row.pane_current_path,
        "pane_title": row.pane_title,
        "pane_active": row.pane_active,
        "active": row.active,
        "first_seen_at": row.first_seen_at,
        "last_scanned_at": row.last_scanned_at,
    }


def _scan_panes(ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID) -> dict[str, Any]:
    if ctx.pane_service is None:
        return errors.make_error(errors.INTERNAL_ERROR, "pane service unavailable")
    from ..tmux.adapter import TmuxError  # local import: avoid cycles
    container_filter = params.get("container")
    if container_filter is not None and not isinstance(container_filter, str):
        return errors.make_error(
            errors.BAD_REQUEST, "params.container must be a string or null"
        )

    try:
        result = ctx.pane_service.scan_for_container(container_id=container_filter)
    except TmuxError as exc:
        if exc.code in errors.CLOSED_CODE_SET:
            return errors.make_error(exc.code, exc.message)
        return errors.make_error(errors.INTERNAL_ERROR, _internal_error_message(str(exc), prefix="pane scan failed"))
    except Exception as exc:  # pragma: no cover — defensive
        return errors.make_error(errors.INTERNAL_ERROR, _internal_error_message(str(exc), prefix="pane scan failed"))
    return errors.make_ok(_pane_scan_to_payload(result))


def _list_panes(ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID) -> dict[str, Any]:
    if ctx.pane_service is None:
        return errors.make_error(errors.INTERNAL_ERROR, "pane service unavailable")
    active_only = params.get("active_only", False)
    if not isinstance(active_only, bool):
        return errors.make_error(
            errors.BAD_REQUEST, "params.active_only must be a boolean"
        )
    container_filter = params.get("container", None)
    if container_filter is not None and not isinstance(container_filter, str):
        return errors.make_error(
            errors.BAD_REQUEST, "params.container must be a string or null"
        )
    rows = ctx.pane_service.list_panes(
        active_only=active_only, container_filter=container_filter
    )
    payload = {
        "filter": "active_only" if active_only else "all",
        "container_filter": container_filter,
        "panes": [_pane_row_to_dict(r) for r in rows],
    }
    return errors.make_ok(payload)


def _internal_error_message(message: str, *, prefix: str) -> str:
    bounded, _ = sanitize_text(message, 2048)
    if not bounded:
        return prefix
    return f"{prefix}: {bounded}"


# ---------------------------------------------------------------------------
# FEAT-006 — agent-registration handlers (FR-023).
#
# Each handler delegates to ``ctx.agent_service`` (an ``AgentService``
# instance wired by the daemon) and maps the agent-domain
# :class:`RegistrationError` into the FEAT-002 closed-set wire envelope.
# Schema-newer requests are refused via SCHEMA_VERSION_NEWER without
# touching state (FR-040, edge case line 79).
# ---------------------------------------------------------------------------


def _agent_service_or_error(ctx: DaemonContext) -> tuple[Any, dict[str, Any] | None]:
    """Return ``(service, None)`` or ``(None, error_envelope)``."""
    service = getattr(ctx, "agent_service", None)
    if service is None:
        return None, errors.make_error(
            errors.INTERNAL_ERROR, "agent service unavailable"
        )
    return service, None


def _dispatch_agent_method(
    ctx: DaemonContext,
    params: dict[str, Any],
    peer_uid: int,
    *,
    method_name: str,
    pass_uid: bool = False,
) -> dict[str, Any]:
    """Dispatch *method_name* on the wired ``AgentService``.

    Maps :class:`RegistrationError` to the closed-set wire envelope and
    every unexpected ``Exception`` to ``internal_error`` so the daemon
    stays alive (FR-035).

    *peer_uid* is the SO_PEERCRED-derived uid the server extracted from
    the accepted AF_UNIX connection. It is passed out-of-band so a
    request body cannot spoof it.
    """
    service, err = _agent_service_or_error(ctx)
    if err is not None:
        return err
    # Lazy import keeps this module's import graph independent of the
    # ``agents`` package (which depends on ``socket_api.errors``).
    from ..agents.errors import RegistrationError

    if not isinstance(params, dict):
        return errors.make_error(errors.BAD_REQUEST, "params must be an object")

    method = getattr(service, method_name)
    try:
        if pass_uid:
            result = method(params, socket_peer_uid=int(peer_uid))
        else:
            result = method(params)
    except RegistrationError as exc:
        # Defense in depth: bound the error message length and strip
        # control bytes even on the closed-code branch (the non-closed
        # branch already routes through ``_internal_error_message``).
        # A future contributor whose error message embeds raw user
        # input shouldn't be able to leak NUL/CR/LF onto the wire.
        bounded_message, _ = sanitize_text(exc.message, 2048) if exc.message else ("", 0)
        if exc.code in errors.CLOSED_CODE_SET:
            return errors.make_error(exc.code, bounded_message or exc.code)
        return errors.make_error(
            errors.INTERNAL_ERROR,
            _internal_error_message(exc.message, prefix=method_name),
        )
    except Exception as exc:  # pragma: no cover — defensive
        return errors.make_error(
            errors.INTERNAL_ERROR,
            _internal_error_message(str(exc), prefix=method_name),
        )
    return errors.make_ok(result)


def _register_agent(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_agent_method(
        ctx, params, peer_uid, method_name="register_agent", pass_uid=True
    )


def _list_agents(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_agent_method(ctx, params, peer_uid, method_name="list_agents")


def _set_role(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_agent_method(
        ctx, params, peer_uid, method_name="set_role", pass_uid=True
    )


def _set_label(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_agent_method(
        ctx, params, peer_uid, method_name="set_label", pass_uid=True
    )


def _set_capability(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_agent_method(
        ctx, params, peer_uid, method_name="set_capability", pass_uid=True
    )


# ---------------------------------------------------------------------------
# FEAT-007 dispatch (FR-031, FR-032, FR-033, FR-037a)
# ---------------------------------------------------------------------------


def _log_service_or_error(ctx: DaemonContext) -> tuple[Any, dict[str, Any] | None]:
    service = getattr(ctx, "log_service", None)
    if service is None:
        return None, errors.make_error(
            errors.INTERNAL_ERROR, "log service unavailable"
        )
    return service, None


def _dispatch_log_method(
    ctx: DaemonContext,
    params: dict[str, Any],
    peer_uid: int,
    *,
    method_name: str,
) -> dict[str, Any]:
    service, err = _log_service_or_error(ctx)
    if err is not None:
        return err
    from ..agents.errors import RegistrationError

    if not isinstance(params, dict):
        return errors.make_error(errors.BAD_REQUEST, "params must be an object")

    method = getattr(service, method_name)
    try:
        result = method(params, socket_peer_uid=int(peer_uid))
    except RegistrationError as exc:
        bounded_message, _ = sanitize_text(exc.message, 2048) if exc.message else ("", 0)
        if exc.code in errors.CLOSED_CODE_SET:
            return errors.make_error(exc.code, bounded_message or exc.code)
        return errors.make_error(
            errors.INTERNAL_ERROR,
            _internal_error_message(exc.message, prefix=method_name),
        )
    except Exception as exc:  # pragma: no cover — defensive
        return errors.make_error(
            errors.INTERNAL_ERROR,
            _internal_error_message(str(exc), prefix=method_name),
        )
    return errors.make_ok(result)


def _attach_log(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_log_method(ctx, params, peer_uid, method_name="attach_log")


def _detach_log(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_log_method(ctx, params, peer_uid, method_name="detach_log")


def _attach_log_status(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_log_method(
        ctx, params, peer_uid, method_name="attach_log_status"
    )


def _attach_log_preview(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    return _dispatch_log_method(
        ctx, params, peer_uid, method_name="attach_log_preview"
    )


# ---------------------------------------------------------------------------
# FEAT-008 — events.* methods (T037 / T038).
# ---------------------------------------------------------------------------


_EVENTS_VALID_TYPES = frozenset(
    {
        "activity", "waiting_for_input", "completed", "error",
        "test_failed", "test_passed", "manual_review_needed",
        "long_running", "pane_exited", "swarm_member_reported",
    }
)


def _events_config_value(ctx: DaemonContext, name: str, fallback: Any) -> Any:
    cfg = getattr(ctx, "events_config", None)
    if cfg is None:
        return fallback
    return getattr(cfg, name, fallback)


def _events_parse_iso_with_offset(
    value: str, *, field: str
) -> tuple[datetime | None, dict[str, Any] | None]:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None, errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"{field} must be ISO-8601 with an explicit offset",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"{field} must be ISO-8601 with an explicit offset",
        )
    return parsed.astimezone(timezone.utc), None


def _events_resolve_target(
    ctx: DaemonContext, target: str | None
) -> dict[str, Any] | None:
    """Return an error envelope iff ``target`` is set AND not in the
    FEAT-006 registry; otherwise None (the caller proceeds)."""
    if target is None:
        return None
    if ctx.agent_service is None:
        return errors.make_error(
            errors.INTERNAL_ERROR, "agent service unavailable"
        )
    # The FEAT-006 list_agents signature takes a positional dict ``params``
    # and returns a dict containing ``agents`` (a list of dicts).
    try:
        listing = ctx.agent_service.list_agents(
            {"schema_version": ctx.schema_version}
        )
    except Exception as exc:  # pragma: no cover — defensive
        return errors.make_error(
            errors.INTERNAL_ERROR, f"agent service failed: {exc}"
        )
    rows = (
        listing.get("agents", []) if isinstance(listing, dict) else []
    )
    found = any(
        (row.get("agent_id") if isinstance(row, dict) else getattr(row, "agent_id", None))
        == target
        for row in rows
    )
    if not found:
        # L2 — do NOT echo the operator-supplied target id back into
        # the error message. The client already knows what it sent;
        # echoing back enables enumeration / log-noise amplification.
        return errors.make_error(
            errors.AGENT_NOT_FOUND, "target agent not found"
        )
    return None


def _events_validate_filter(params: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the ``events.list`` filter shape; None means OK."""
    types = params.get("types") or []
    if not isinstance(types, list):
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID, "types must be a list"
        )
    for t in types:
        if not isinstance(t, str) or t not in _EVENTS_VALID_TYPES:
            return errors.make_error(
                errors.EVENTS_FILTER_INVALID,
                f"unknown event type: {t!r}",
            )
    since = params.get("since")
    until = params.get("until")
    if since is not None and not isinstance(since, str):
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID, "since must be an ISO-8601 string"
        )
    if until is not None and not isinstance(until, str):
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID, "until must be an ISO-8601 string"
        )
    since_dt = None
    until_dt = None
    if since is not None:
        since_dt, err = _events_parse_iso_with_offset(since, field="since")
        if err is not None:
            return err
    if until is not None:
        until_dt, err = _events_parse_iso_with_offset(until, field="until")
        if err is not None:
            return err
    if since_dt is not None and until_dt is not None and since_dt > until_dt:
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"since ({since}) must be <= until ({until})",
        )
    if "reverse" in params and not isinstance(params["reverse"], bool):
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"reverse must be a boolean; got {params['reverse']!r}",
        )
    limit = params.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            return errors.make_error(
                errors.EVENTS_FILTER_INVALID,
                f"limit must be a positive integer; got {limit!r}",
            )
    return None


def _event_row_to_payload(row: Any, *, include_jsonl_appended_at: bool = False) -> dict[str, Any]:
    """Render one ``EventRow`` into the FR-027 stable JSON shape."""
    payload = {
        "event_id": row.event_id,
        "event_type": row.event_type,
        "agent_id": row.agent_id,
        "attachment_id": row.attachment_id,
        "log_path": row.log_path,
        "byte_range_start": row.byte_range_start,
        "byte_range_end": row.byte_range_end,
        "line_offset_start": row.line_offset_start,
        "line_offset_end": row.line_offset_end,
        "observed_at": row.observed_at,
        "record_at": row.record_at,
        "excerpt": row.excerpt,
        "classifier_rule_id": row.classifier_rule_id,
        "debounce": {
            "window_id": row.debounce_window_id,
            "collapsed_count": row.debounce_collapsed_count,
            "window_started_at": row.debounce_window_started_at,
            "window_ended_at": row.debounce_window_ended_at,
        },
        "schema_version": row.schema_version,
    }
    if include_jsonl_appended_at:
        payload["jsonl_appended_at"] = row.jsonl_appended_at
    return payload


def _events_list(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    """``events.list`` — FR-030 / FR-035a per ``contracts/socket-events.md``
    C-EVT-001."""
    import sqlite3

    from ..events.dao import (
        CursorError,
        EventFilter,
        select_events,
    )
    from .. import events as events_pkg

    target = params.get("target")
    if target is not None and not isinstance(target, str):
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"target must be a string; got {type(target).__name__}",
        )

    err = _events_validate_filter(params)
    if err is not None:
        return err

    err = _events_resolve_target(ctx, target)
    if err is not None:
        return err

    default_page_size = int(
        _events_config_value(ctx, "default_page_size", events_pkg.DEFAULT_PAGE_SIZE)
    )
    max_page_size = int(
        _events_config_value(ctx, "max_page_size", events_pkg.MAX_PAGE_SIZE)
    )
    limit = int(params.get("limit") or default_page_size)
    if limit > max_page_size:
        limit = max_page_size
    cursor = params.get("cursor")
    reverse = params.get("reverse", False)
    types = tuple(params.get("types") or [])
    filter = EventFilter(
        target_agent_id=target,
        types=types,
        since_iso=params.get("since"),
        until_iso=params.get("until"),
    )

    conn = sqlite3.connect(str(ctx.state_path / "agenttower.sqlite3"))
    try:
        try:
            rows, next_cursor = select_events(
                conn, filter=filter, cursor=cursor, limit=limit, reverse=reverse
            )
        except CursorError as exc:
            return errors.make_error(errors.EVENTS_INVALID_CURSOR, str(exc))
    finally:
        conn.close()

    return errors.make_ok(
        {
            "events": [_event_row_to_payload(r) for r in rows],
            "next_cursor": next_cursor,
        }
    )


def _events_classifier_rules(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    """``events.classifier_rules`` — debug surface per C-EVT-005."""
    from ..events import classifier_rules as cr

    return errors.make_ok(
        {
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "event_type": r.event_type,
                    "priority": r.priority,
                }
                for r in cr.RULES
            ],
            "synthetic_rule_ids": list(cr.SYNTHETIC_RULE_IDS),
        }
    )


def _events_follow_session_registry_or_error(
    ctx: DaemonContext,
) -> tuple[Any, dict[str, Any] | None]:
    """Return ``(registry, None)`` or ``(None, error_envelope)``."""
    if ctx.follow_session_registry is None:
        return None, errors.make_error(
            errors.INTERNAL_ERROR, "follow session registry unavailable"
        )
    return ctx.follow_session_registry, None


def _events_follow_open(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    """``events.follow_open`` per C-EVT-002."""
    import sqlite3
    import time as _time

    from ..events.dao import EventFilter, select_events
    from .. import events as events_pkg

    target = params.get("target")
    if target is not None and not isinstance(target, str):
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"target must be a string; got {type(target).__name__}",
        )
    err = _events_validate_filter(params)
    if err is not None:
        return err
    err = _events_resolve_target(ctx, target)
    if err is not None:
        return err
    registry, err = _events_follow_session_registry_or_error(ctx)
    if err is not None:
        return err

    types = tuple(params.get("types") or [])
    since = params.get("since")

    # Compute live_starting_event_id = current max event_id at session-open
    # time; later events are "live."
    db_path = ctx.state_path / "agenttower.sqlite3"
    backlog_events: list[dict[str, Any]] = []
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events")
        live_starting = int(cur.fetchone()[0])
        if since is not None:
            backlog_rows, _ = select_events(
                conn,
                filter=EventFilter(
                    target_agent_id=target, types=types, since_iso=since
                ),
                cursor=None,
                limit=int(
                    _events_config_value(
                        ctx, "default_page_size", events_pkg.DEFAULT_PAGE_SIZE
                    )
                ),
                reverse=False,
            )
            backlog_events = [_event_row_to_payload(r) for r in backlog_rows]
    finally:
        conn.close()

    expires_at = _time.monotonic() + float(
        _events_config_value(
            ctx,
            "follow_session_idle_timeout_seconds",
            events_pkg.FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS,
        )
    )
    session = registry.open(
        target_agent_id=target,
        types=types,
        since_iso=since,
        live_starting_event_id=live_starting,
        expires_at_monotonic=expires_at,
    )
    return errors.make_ok(
        {
            "session_id": session.session_id,
            "backlog_events": backlog_events,
            "live_starting_event_id": live_starting,
        }
    )


def _events_follow_next(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    """``events.follow_next`` per C-EVT-003 — long-poll."""
    import math
    import sqlite3
    import time as _time

    from ..events.dao import EventFilter, select_events
    from .. import events as events_pkg

    session_id = params.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return errors.make_error(
            errors.EVENTS_SESSION_UNKNOWN, "session_id is required"
        )
    registry, err = _events_follow_session_registry_or_error(ctx)
    if err is not None:
        return err
    session = registry.get(session_id)
    if session is None:
        # CRIT-4 — register the bad lookup against the sliding-window
        # rate limiter. Generic message either way (no enumeration
        # signal); the limiter just prevents thread-pool exhaustion
        # under brute-force.
        registry.is_rate_limited(now_monotonic=_time.monotonic())
        return errors.make_error(
            errors.EVENTS_SESSION_UNKNOWN, "unknown follow session"
        )
    now_mono = _time.monotonic()
    if session.expires_at_monotonic < now_mono:
        registry.close(session_id)
        return errors.make_error(
            errors.EVENTS_SESSION_EXPIRED,
            f"follow session {session_id} expired",
        )

    # C4 (review MEDIUM) — clamp ``max_wait_seconds`` to the documented
    # server-side budget. The CLI passes ``max_wait_seconds=1.0`` so
    # SIGINT response stays bounded; bench-container scripts may pass
    # higher values. We cap at FOLLOW_LONG_POLL_MAX_SECONDS so a single
    # follower cannot hold a connection longer than the server-side
    # documented limit, regardless of the client's read_timeout.
    default_page_size = int(
        _events_config_value(ctx, "default_page_size", events_pkg.DEFAULT_PAGE_SIZE)
    )
    follow_idle_timeout = float(
        _events_config_value(
            ctx,
            "follow_session_idle_timeout_seconds",
            events_pkg.FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS,
        )
    )
    follow_long_poll_max = float(
        _events_config_value(
            ctx,
            "follow_long_poll_max_seconds",
            events_pkg.FOLLOW_LONG_POLL_MAX_SECONDS,
        )
    )
    raw_max_wait = params.get("max_wait_seconds")
    if raw_max_wait is None:
        max_wait = follow_long_poll_max
    elif (
        not isinstance(raw_max_wait, (int, float))
        or isinstance(raw_max_wait, bool)
    ):
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"max_wait_seconds must be a positive number; got {raw_max_wait!r}",
        )
    else:
        max_wait = float(raw_max_wait)
    if not math.isfinite(max_wait) or max_wait <= 0:
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"max_wait_seconds must be a positive number; got {raw_max_wait!r}",
        )
    max_wait = min(max_wait, follow_long_poll_max)
    deadline = now_mono + max_wait

    db_path = ctx.state_path / "agenttower.sqlite3"

    while True:
        conn = sqlite3.connect(str(db_path))
        try:
            # Compute the lower bound for "new events": last_emitted (if
            # we've seen anything) or live_starting (first call).
            lower_bound = max(
                session.last_emitted_event_id, session.live_starting_event_id
            )
            cursor_token = None
            if lower_bound > 0:
                from ..events.dao import encode_cursor

                cursor_token = encode_cursor(lower_bound, reverse=False)
            rows, _ = select_events(
                conn,
                filter=EventFilter(
                    target_agent_id=session.target_agent_id,
                    types=tuple(session.type_filter),
                ),
                cursor=cursor_token,
                limit=default_page_size,
                reverse=False,
            )
        finally:
            conn.close()

        if rows:
            session.last_emitted_event_id = rows[-1].event_id
            registry.refresh_expiration(
                session_id,
                new_expires_at_monotonic=_time.monotonic() + follow_idle_timeout,
            )
            return errors.make_ok(
                {
                    "events": [_event_row_to_payload(r) for r in rows],
                    "session_open": True,
                }
            )

        # No new events. Wait for either: (a) a notify from the reader
        # post-commit (Plan §"Follow long-poll model"), or (b) a short
        # periodic poll budget so direct DB writes (admin tools, tests)
        # are also discovered. The poll granularity is 250 ms — short
        # enough to keep latency well under SC-002's 1 s target while
        # avoiding hot-spinning the DAO.
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        poll_interval = min(0.25, remaining)
        with session.condition:
            session.condition.wait(timeout=poll_interval)
        # Re-check session existence (in case it was closed during wait).
        if registry.get(session_id) is None:
            return errors.make_ok({"events": [], "session_open": False})

    registry.refresh_expiration(
        session_id,
        new_expires_at_monotonic=_time.monotonic() + follow_idle_timeout,
    )
    return errors.make_ok({"events": [], "session_open": True})


def _events_follow_close(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    """``events.follow_close`` per C-EVT-004."""
    import time as _time

    session_id = params.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return errors.make_error(
            errors.EVENTS_SESSION_UNKNOWN, "session_id is required"
        )
    registry, err = _events_follow_session_registry_or_error(ctx)
    if err is not None:
        return err
    closed = registry.close(session_id)
    if not closed:
        # CRIT-4 — register the bad lookup. Generic message; same
        # rationale as ``_events_follow_next``.
        registry.is_rate_limited(now_monotonic=_time.monotonic())
        return errors.make_error(
            errors.EVENTS_SESSION_UNKNOWN, "unknown follow session"
        )
    return errors.make_ok({})


# ---------------------------------------------------------------------------
# FEAT-009 — queue + routing dispatchers (T049).
#
# Eight new methods, all routed through ``QueueService`` /
# ``RoutingFlagService`` on the daemon context. Each handler enforces
# its caller-context gate at the dispatch boundary per Research §R-005
# and Group-A walk Q8.
#
# Wire-level ``caller_pane`` shape:
# * Absent or ``null`` → host-origin caller (FEAT-002 thin client running
#   on the daemon host). Combined with the SO_PEERCRED uid match this
#   discriminates host from bench-container origin (R-005).
# * Object with at least ``{"agent_id": "agt_<12-hex>"}`` → bench-container
#   thin client. The agent_id is the caller's own registered agent_id;
#   the daemon trusts the same-uid peer to populate it (matches FEAT-006
#   ``register_agent``'s trust model — FR-024).
#
# Mapping table (handler → caller-context gate):
#
# | Method              | Gate                                                    |
# |---------------------|---------------------------------------------------------|
# | queue.send_input    | caller_pane is not None (sender_not_in_pane)            |
# | queue.list          | none (FR-029 — queue read works under kill switch)     |
# | queue.approve       | if caller_pane: liveness (operator_pane_inactive)       |
# | queue.delay         | if caller_pane: liveness (operator_pane_inactive)       |
# | queue.cancel        | if caller_pane: liveness (operator_pane_inactive)       |
# | routing.enable      | caller_pane is None AND peer_uid==os.getuid()          |
# | routing.disable     | caller_pane is None AND peer_uid==os.getuid()          |
# | routing.status      | none                                                   |
# ---------------------------------------------------------------------------


def _routing_services_or_error(
    ctx: DaemonContext,
) -> tuple[Any, Any, dict[str, Any] | None]:
    """Return ``(queue_service, routing_flag_service, None)`` or
    ``(None, None, error_envelope)`` if either service is unwired."""
    queue = getattr(ctx, "queue_service", None)
    routing = getattr(ctx, "routing_flag_service", None)
    if queue is None or routing is None:
        return None, None, errors.make_error(
            errors.INTERNAL_ERROR, "routing services unavailable"
        )
    return queue, routing, None


def _parse_caller_pane(params: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pluck the optional ``caller_pane`` block out of ``params``.

    Returns ``(caller_pane_or_None, error_or_None)``. ``caller_pane`` is
    either a dict carrying at minimum ``agent_id``, or ``None`` for
    host-origin callers (absent / null in params).
    """
    raw = params.get("caller_pane") if isinstance(params, dict) else None
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, errors.make_error(
            errors.BAD_REQUEST, "params.caller_pane must be an object or null"
        )
    return raw, None


def _resolve_caller_agent(
    ctx: DaemonContext, caller_pane: dict[str, Any] | None,
) -> tuple[Any, dict[str, Any] | None]:
    """Resolve the caller's ``AgentRecord`` from the ``caller_pane``.

    For bench-container callers the wire carries ``caller_pane.agent_id``;
    we trust it (same-uid peer, FR-024) and verify the row exists +
    ``active=true``. Returns the record on success, an error envelope
    on miss / inactive.
    """
    if caller_pane is None:
        return None, None
    agent_id = caller_pane.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return None, errors.make_error(
            errors.BAD_REQUEST,
            "params.caller_pane.agent_id must be a non-empty string",
        )
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return None, errors.make_error(
            errors.INTERNAL_ERROR, "agent registry unavailable"
        )
    # Lazy import keeps the FEAT-009 dispatch module independent of the
    # state package's import graph for FEAT-001..004 boot paths.
    from ..state.agents import select_agent_by_id

    record = select_agent_by_id(conn, agent_id=agent_id)
    if record is None or not record.active:
        return None, errors.make_error(
            errors.OPERATOR_PANE_INACTIVE,
            "caller pane resolves to inactive or deregistered agent",
        )
    return record, None


def _queue_error_to_envelope(exc: Exception, *, method: str) -> dict[str, Any]:
    """Map a FEAT-009 service / target / liveness exception to the
    FEAT-002 closed-set error envelope.

    Only the closed-set codes pass through verbatim; anything else
    surfaces as ``internal_error`` so the daemon stays alive (FR-035).
    """
    from ..routing.errors import (
        OperatorPaneInactive,
        QueueServiceError,
        TargetResolveError,
    )

    if isinstance(exc, (QueueServiceError, TargetResolveError, OperatorPaneInactive)):
        code = exc.code
        if code in errors.CLOSED_CODE_SET:
            bounded, _ = sanitize_text(exc.message or code, 2048)
            return errors.make_error(code, bounded or code)
    return errors.make_error(
        errors.INTERNAL_ERROR,
        _internal_error_message(str(exc), prefix=method),
    )


def _queue_row_to_payload(row: Any, *, excerpt: str = "") -> dict[str, Any]:
    """Render a :class:`routing.dao.QueueRow` into the wire shape from
    ``contracts/queue-row-schema.md`` (FR-011).

    ``excerpt`` is the rendered preview (FR-047b). The caller computes it
    from the envelope body and passes it in; this helper does not read
    the body itself to keep the dispatcher's hot path clean.
    """
    return {
        "message_id": row.message_id,
        "state": row.state,
        "block_reason": row.block_reason,
        "failure_reason": row.failure_reason,
        "sender": {
            "agent_id": row.sender_agent_id,
            "label": row.sender_label,
            "role": row.sender_role,
            "capability": row.sender_capability,
        },
        "target": {
            "agent_id": row.target_agent_id,
            "label": row.target_label,
            "role": row.target_role,
            "capability": row.target_capability,
        },
        "envelope_size_bytes": row.envelope_size_bytes,
        "envelope_body_sha256": row.envelope_body_sha256,
        "enqueued_at": row.enqueued_at,
        "delivery_attempt_started_at": row.delivery_attempt_started_at,
        "delivered_at": row.delivered_at,
        "failed_at": row.failed_at,
        "canceled_at": row.canceled_at,
        "last_updated_at": row.last_updated_at,
        "operator_action": row.operator_action,
        "operator_action_at": row.operator_action_at,
        "operator_action_by": row.operator_action_by,
        "excerpt": excerpt,
    }


def _queue_send_input(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    """``queue.send_input`` — enqueue a row from a bench-container master.

    Caller-context gate (R-005): ``caller_pane is not None`` (else
    ``sender_not_in_pane``). The resolved sender record is passed to
    :meth:`QueueService.send_input`; permission checks (role / liveness)
    happen inside the service layer.
    """
    queue_service, _routing, err = _routing_services_or_error(ctx)
    if err is not None:
        return err
    if not isinstance(params, dict):
        return errors.make_error(errors.BAD_REQUEST, "params must be an object")
    caller_pane, err = _parse_caller_pane(params)
    if err is not None:
        return err
    if caller_pane is None:
        return errors.make_error(
            errors.SENDER_NOT_IN_PANE,
            "send-input requires a bench-container caller; host-origin callers are refused",
        )
    sender, err = _resolve_caller_agent(ctx, caller_pane)
    if err is not None:
        # _resolve_caller_agent returns operator_pane_inactive; remap to
        # sender_role_not_permitted for the send-input surface
        # (FR-021/023: an inactive sender is "not in a permitted role").
        if err.get("error", {}).get("code") == errors.OPERATOR_PANE_INACTIVE:
            return errors.make_error(
                errors.SENDER_ROLE_NOT_PERMITTED,
                "sender pane resolves to inactive or deregistered agent",
            )
        return err
    target = params.get("target")
    if not isinstance(target, str) or not target:
        return errors.make_error(
            errors.BAD_REQUEST, "params.target must be a non-empty string"
        )
    body_b64 = params.get("body_bytes")
    if not isinstance(body_b64, str):
        return errors.make_error(
            errors.BAD_REQUEST, "params.body_bytes must be a base64 string"
        )
    import base64
    try:
        body_bytes = base64.b64decode(body_b64, validate=True)
    except (ValueError, TypeError) as exc:
        return errors.make_error(
            errors.BAD_REQUEST, f"params.body_bytes is not valid base64: {exc}"
        )
    wait = params.get("wait", True)
    if not isinstance(wait, bool):
        return errors.make_error(
            errors.BAD_REQUEST, "params.wait must be a boolean"
        )
    wait_timeout = params.get("wait_timeout_seconds")
    if wait_timeout is not None:
        if not isinstance(wait_timeout, (int, float)) or wait_timeout < 0 or wait_timeout > 300:
            return errors.make_error(
                errors.BAD_REQUEST,
                "params.wait_timeout_seconds must be a number in [0.0, 300.0]",
            )
    try:
        result = queue_service.send_input(
            sender=sender,
            target_input=target,
            body_bytes=body_bytes,
            wait=wait,
            wait_timeout=float(wait_timeout) if wait_timeout is not None else None,
        )
    except Exception as exc:
        return _queue_error_to_envelope(exc, method="queue.send_input")
    # Compute the FR-047b excerpt from the body we already have in
    # memory — avoids a redundant SQLite BLOB read and ensures the
    # `--json` shape carries the documented `excerpt` field.
    from ..routing.excerpt import render_excerpt
    excerpt = render_excerpt(body_bytes)
    payload = _queue_row_to_payload(result.row, excerpt=excerpt)
    payload["waited_to_terminal"] = result.waited_to_terminal
    return errors.make_ok(payload)


def _queue_list(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    """``queue.list`` — list rows with filters. No origin restriction.

    ``--target`` and ``--sender`` accept either an ``agt_<12-hex>``
    agent_id OR a label (Research §R-001); we route both through
    ``target_resolver.resolve_target`` so labels work and ambiguous
    labels surface as ``target_label_ambiguous``. ``--since`` is
    validated via ``parse_since`` (FR-012b); malformed values surface
    as ``since_invalid_format``. The rendered rows include the FR-047b
    excerpt by reading the persisted body BLOB once per row.
    """
    queue_service, _routing, err = _routing_services_or_error(ctx)
    if err is not None:
        return err
    if not isinstance(params, dict):
        return errors.make_error(errors.BAD_REQUEST, "params must be an object")
    from ..routing.dao import QueueListFilter
    from ..routing.excerpt import render_excerpt
    from ..routing.target_resolver import resolve_target
    from ..routing.errors import (
        SINCE_INVALID_FORMAT,
        TargetResolveError,
    )
    from ..routing.timestamps import parse_since

    state = params.get("state")
    target_in = params.get("target")
    sender_in = params.get("sender")
    since = params.get("since")
    limit = params.get("limit", 100)
    if limit is not None and (not isinstance(limit, int) or limit < 1 or limit > 1000):
        return errors.make_error(
            errors.BAD_REQUEST, "params.limit must be an integer in [1, 1000]"
        )

    # Resolve target/sender filters via the same resolver send_input
    # uses, so labels work + ambiguous labels surface verbatim.
    target_agent_id: str | None = None
    sender_agent_id: str | None = None
    agents_lookup = getattr(queue_service, "_agents", None)
    if target_in is not None and isinstance(target_in, str) and target_in:
        if agents_lookup is not None:
            try:
                target_agent_id = resolve_target(target_in, agents_lookup).agent_id
            except TargetResolveError as exc:
                return _queue_error_to_envelope(exc, method="queue.list")
        else:
            target_agent_id = target_in
    if sender_in is not None and isinstance(sender_in, str) and sender_in:
        if agents_lookup is not None:
            try:
                sender_agent_id = resolve_target(sender_in, agents_lookup).agent_id
            except TargetResolveError as exc:
                return _queue_error_to_envelope(exc, method="queue.list")
        else:
            sender_agent_id = sender_in

    # Validate `since` format. ``parse_since`` accepts both the
    # canonical ms-form and the seconds form per FR-012b.
    since_value: str | None = None
    if since is not None:
        if not isinstance(since, str):
            return errors.make_error(
                errors.BAD_REQUEST, "params.since must be a string"
            )
        try:
            parse_since(since)
        except (ValueError, TypeError) as exc:
            return errors.make_error(
                SINCE_INVALID_FORMAT,
                f"params.since must parse as canonical ISO-8601 ms UTC: {exc}",
            )
        since_value = since

    filters = QueueListFilter(
        state=state if isinstance(state, str) else None,
        target_agent_id=target_agent_id,
        sender_agent_id=sender_agent_id,
        since=since_value,
        limit=limit if isinstance(limit, int) else 100,
    )
    try:
        rows = queue_service.list_rows(filters)
    except Exception as exc:
        return _queue_error_to_envelope(exc, method="queue.list")

    # Render each row with its FR-047b excerpt. One BLOB read per row
    # — acceptable for MVP list sizes (default limit 100, max 1000).
    dao = getattr(queue_service, "_dao", None)
    payloads: list[dict[str, Any]] = []
    for r in rows:
        excerpt = ""
        if dao is not None:
            try:
                body = dao.read_envelope_bytes(r.message_id)
                excerpt = render_excerpt(body)
            except Exception:
                # Best-effort excerpt: never fail listing on a stale row.
                excerpt = ""
        payloads.append(_queue_row_to_payload(r, excerpt=excerpt))
    return errors.make_ok({"rows": payloads, "next_cursor": None})


def _resolve_operator_identity(
    ctx: DaemonContext, params: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    """Group-A walk Q8: for operator-action handlers, resolve the
    ``operator_action_by`` string.

    * ``caller_pane is None`` → host-origin → ``HOST_OPERATOR_SENTINEL``.
    * ``caller_pane is not None`` → resolve agent_id; if missing /
      inactive, return ``operator_pane_inactive`` envelope.
    """
    caller_pane, err = _parse_caller_pane(params)
    if err is not None:
        return None, err
    if caller_pane is None:
        # Lazy import to keep dispatch module independent of agents pkg.
        from ..agents.identifiers import HOST_OPERATOR_SENTINEL
        return HOST_OPERATOR_SENTINEL, None
    record, err = _resolve_caller_agent(ctx, caller_pane)
    if err is not None:
        return None, err
    return record.agent_id, None


def _queue_operator_action(
    ctx: DaemonContext,
    params: dict[str, Any],
    *,
    method: str,
    service_method_name: str,
) -> dict[str, Any]:
    """Shared body for ``queue.approve`` / ``queue.delay`` / ``queue.cancel``."""
    queue_service, _routing, err = _routing_services_or_error(ctx)
    if err is not None:
        return err
    if not isinstance(params, dict):
        return errors.make_error(errors.BAD_REQUEST, "params must be an object")
    message_id = params.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        return errors.make_error(
            errors.BAD_REQUEST, "params.message_id must be a non-empty string"
        )
    operator, err = _resolve_operator_identity(ctx, params)
    if err is not None:
        return err
    try:
        method_fn = getattr(queue_service, service_method_name)
        row = method_fn(message_id, operator=operator)
    except Exception as exc:
        return _queue_error_to_envelope(exc, method=method)
    return errors.make_ok(_queue_row_to_payload(row))


def _queue_approve(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    return _queue_operator_action(
        ctx, params, method="queue.approve", service_method_name="approve",
    )


def _queue_delay(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    return _queue_operator_action(
        ctx, params, method="queue.delay", service_method_name="delay",
    )


def _queue_cancel(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    return _queue_operator_action(
        ctx, params, method="queue.cancel", service_method_name="cancel",
    )


def _routing_host_only_gate(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int,
) -> dict[str, Any] | None:
    """Enforce the routing-toggle host-only gate (R-005 / Q2): caller
    pane absent AND peer uid matches the daemon process uid.

    Fail-closed: if ``peer_uid`` is the ``_NO_PEER_UID`` sentinel
    (SO_PEERCRED unavailable or the call bypassed the socket boundary),
    the gate REFUSES the toggle. A host-only security gate that allows
    on "no credentials" is bypassable on non-Linux / failed-cred paths,
    so we treat "no peer credentials" as the same as a non-host caller.

    Returns ``None`` on success or an error envelope on refusal.
    """
    caller_pane, err = _parse_caller_pane(params)
    if err is not None:
        return err
    if caller_pane is not None:
        return errors.make_error(
            errors.ROUTING_TOGGLE_HOST_ONLY,
            "routing toggle is host-only; bench-container callers refused",
        )
    if peer_uid == _NO_PEER_UID:
        return errors.make_error(
            errors.ROUTING_TOGGLE_HOST_ONLY,
            "routing toggle requires verifiable peer credentials; "
            "SO_PEERCRED returned no uid",
        )
    import os
    daemon_uid = os.getuid()
    if peer_uid != daemon_uid:
        return errors.make_error(
            errors.ROUTING_TOGGLE_HOST_ONLY,
            "routing toggle requires daemon-host uid",
        )
    return None


def _routing_toggle(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int, *, value: str,
) -> dict[str, Any]:
    """Shared body for ``routing.enable`` (value=``enabled``) and
    ``routing.disable`` (value=``disabled``)."""
    _queue, routing, err = _routing_services_or_error(ctx)
    if err is not None:
        return err
    gate_err = _routing_host_only_gate(ctx, params, peer_uid)
    if gate_err is not None:
        return gate_err
    from ..agents.identifiers import HOST_OPERATOR_SENTINEL
    from ..routing.timestamps import now_iso_ms_utc

    ts = now_iso_ms_utc()
    try:
        result = (
            routing.enable(operator=HOST_OPERATOR_SENTINEL, ts=ts)
            if value == "enabled"
            else routing.disable(operator=HOST_OPERATOR_SENTINEL, ts=ts)
        )
    except Exception as exc:
        return errors.make_error(
            errors.INTERNAL_ERROR,
            _internal_error_message(str(exc), prefix=f"routing.{value}"),
        )
    if result.changed and getattr(ctx, "queue_audit_writer", None) is not None:
        try:
            ctx.queue_audit_writer.append_routing_toggled(
                previous_value=result.previous_value,
                current_value=result.current_value,
                operator=result.last_updated_by,
                observed_at=result.last_updated_at,
            )
        except Exception:
            # Audit-emit failure must not fail the toggle; the audit
            # writer's degraded-mode buffer handles JSONL faults. SQLite
            # faults still surface through ``agenttower status``.
            pass
    return errors.make_ok(
        {
            "previous_value": result.previous_value,
            "current_value": result.current_value,
            "changed": result.changed,
            "last_updated_at": result.last_updated_at,
            "last_updated_by": result.last_updated_by,
        }
    )


def _routing_enable(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    return _routing_toggle(ctx, params, peer_uid, value="enabled")


def _routing_disable(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    return _routing_toggle(ctx, params, peer_uid, value="disabled")


def _routing_status(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    """``routing.status`` — read the kill-switch flag. No origin gate."""
    _queue, routing, err = _routing_services_or_error(ctx)
    if err is not None:
        return err
    try:
        value, last_at, last_by = routing.read_full()
    except Exception as exc:
        return errors.make_error(
            errors.INTERNAL_ERROR,
            _internal_error_message(str(exc), prefix="routing.status"),
        )
    return errors.make_ok(
        {"value": value, "last_updated_at": last_at, "last_updated_by": last_by}
    )


# Dispatch table — the closed set of methods FEAT-002 advertises plus
# FEAT-003's two, FEAT-004's two, FEAT-006's five, FEAT-007's four,
# FEAT-008's events.* surface, and FEAT-009's eight queue/routing methods.
# FEAT-002 keys retain insertion order (FR-022).
DISPATCH: dict[str, Handler] = {
    "ping": _ping,
    "status": _status,
    "shutdown": _shutdown,
    "scan_containers": _scan_containers,
    "list_containers": _list_containers,
    "scan_panes": _scan_panes,
    "list_panes": _list_panes,
    "register_agent": _register_agent,
    "list_agents": _list_agents,
    "set_role": _set_role,
    "set_label": _set_label,
    "set_capability": _set_capability,
    "attach_log": _attach_log,
    "detach_log": _detach_log,
    "attach_log_status": _attach_log_status,
    "attach_log_preview": _attach_log_preview,
    "events.list": _events_list,
    "events.follow_open": _events_follow_open,
    "events.follow_next": _events_follow_next,
    "events.follow_close": _events_follow_close,
    "events.classifier_rules": _events_classifier_rules,
    "queue.send_input": _queue_send_input,
    "queue.list": _queue_list,
    "queue.approve": _queue_approve,
    "queue.delay": _queue_delay,
    "queue.cancel": _queue_cancel,
    "routing.enable": _routing_enable,
    "routing.disable": _routing_disable,
    "routing.status": _routing_status,
}
