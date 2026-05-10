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
        events_reader = {
            "running": True,
            "last_cycle_started_at": snapshot.last_cycle_started_at,
            "last_cycle_duration_ms": snapshot.last_cycle_duration_ms,
            "active_attachments": snapshot.active_attachments,
            "attachments_in_failure": snapshot.attachments_in_failure,
        }
        events_persistence = {
            "degraded_sqlite": snapshot.degraded_sqlite,
            "degraded_jsonl": snapshot.degraded_jsonl,
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
        return errors.make_error(
            errors.AGENT_NOT_FOUND,
            f"no agent registered with id {target}",
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
    if since is not None and until is not None and since > until:
        return errors.make_error(
            errors.EVENTS_FILTER_INVALID,
            f"since ({since}) must be <= until ({until})",
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

    limit = int(params.get("limit") or events_pkg.DEFAULT_PAGE_SIZE)
    if limit > events_pkg.MAX_PAGE_SIZE:
        limit = events_pkg.MAX_PAGE_SIZE
    cursor = params.get("cursor")
    reverse = bool(params.get("reverse", False))
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
                limit=events_pkg.DEFAULT_PAGE_SIZE,
                reverse=False,
            )
            backlog_events = [_event_row_to_payload(r) for r in backlog_rows]
    finally:
        conn.close()

    expires_at = _time.monotonic() + events_pkg.FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS
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
        return errors.make_error(
            errors.EVENTS_SESSION_UNKNOWN,
            f"unknown follow session: {session_id}",
        )
    now_mono = _time.monotonic()
    if session.expires_at_monotonic < now_mono:
        registry.close(session_id)
        return errors.make_error(
            errors.EVENTS_SESSION_EXPIRED,
            f"follow session {session_id} expired",
        )

    max_wait = float(
        params.get("max_wait_seconds")
        or events_pkg.FOLLOW_LONG_POLL_MAX_SECONDS
    )
    max_wait = min(max_wait, events_pkg.FOLLOW_LONG_POLL_MAX_SECONDS)
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
                limit=events_pkg.DEFAULT_PAGE_SIZE,
                reverse=False,
            )
        finally:
            conn.close()

        if rows:
            session.last_emitted_event_id = rows[-1].event_id
            registry.refresh_expiration(
                session_id,
                new_expires_at_monotonic=_time.monotonic()
                + events_pkg.FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS,
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
        new_expires_at_monotonic=_time.monotonic()
        + events_pkg.FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS,
    )
    return errors.make_ok({"events": [], "session_open": True})


def _events_follow_close(
    ctx: DaemonContext, params: dict[str, Any], peer_uid: int = _NO_PEER_UID
) -> dict[str, Any]:
    """``events.follow_close`` per C-EVT-004."""
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
        return errors.make_error(
            errors.EVENTS_SESSION_UNKNOWN,
            f"unknown follow session: {session_id}",
        )
    return errors.make_ok({})


# Dispatch table — the closed set of methods FEAT-002 advertises plus
# FEAT-003's two, FEAT-004's two, FEAT-006's five, FEAT-007's four,
# and FEAT-008's events.* surface.
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
}
