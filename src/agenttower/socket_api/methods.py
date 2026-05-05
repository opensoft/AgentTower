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
                "code": e.code,
                "message": e.message,
            }
            for e in result.error_details
        ],
    }


def _scan_containers(ctx: DaemonContext, params: dict[str, Any]) -> dict[str, Any]:
    if params:
        return errors.make_error(
            errors.BAD_REQUEST, "scan_containers does not accept params"
        )
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
    unexpected = set(params) - {"active_only"}
    if unexpected:
        first = min(unexpected)
        return errors.make_error(errors.BAD_REQUEST, f"unknown param: {first}")
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


# Dispatch table — the closed set of methods FEAT-002 advertises plus
# FEAT-003's two new entries. FEAT-002 keys retain insertion order (FR-022).
DISPATCH: dict[str, Handler] = {
    "ping": _ping,
    "status": _status,
    "shutdown": _shutdown,
    "scan_containers": _scan_containers,
    "list_containers": _list_containers,
}
