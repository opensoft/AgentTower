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

from . import errors

if TYPE_CHECKING:
    from ..discovery.pane_service import PaneDiscoveryService
    from ..discovery.service import DiscoveryService

# ``Handler`` returns the response envelope (already shaped via make_ok / make_error).
Handler = Callable[["DaemonContext", dict[str, Any]], dict[str, Any]]


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
    events_file: Path | None = None
    lifecycle_logger: Any = None


def _ping(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
    return errors.make_ok({})


def _status(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    delta = (now - ctx.start_time_utc).total_seconds()
    uptime_seconds = max(0, int(delta))
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
        }
    )


def _shutdown(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
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


def _scan_containers(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
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
        return errors.make_error(errors.INTERNAL_ERROR, str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        return errors.make_error(errors.INTERNAL_ERROR, f"scan failed: {exc}")
    return errors.make_ok(_scan_result_to_payload(result))


def _list_containers(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
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


def _scan_panes(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
    if ctx.pane_service is None:
        return errors.make_error(errors.INTERNAL_ERROR, "pane service unavailable")
    from ..tmux.adapter import TmuxError  # local import: avoid cycles

    try:
        result = ctx.pane_service.scan()
    except TmuxError as exc:
        if exc.code in errors.CLOSED_CODE_SET:
            return errors.make_error(exc.code, exc.message)
        return errors.make_error(errors.INTERNAL_ERROR, str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        return errors.make_error(errors.INTERNAL_ERROR, f"pane scan failed: {exc}")
    return errors.make_ok(_pane_scan_to_payload(result))


def _list_panes(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
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


# Dispatch table — the closed set of methods FEAT-002 advertises plus
# FEAT-003's two and FEAT-004's two new entries. FEAT-002 keys retain
# insertion order (FR-022).
DISPATCH: dict[str, Handler] = {
    "ping": _ping,
    "status": _status,
    "shutdown": _shutdown,
    "scan_containers": _scan_containers,
    "list_containers": _list_containers,
    "scan_panes": _scan_panes,
    "list_panes": _list_panes,
}
