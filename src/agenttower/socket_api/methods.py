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
from typing import Any

from . import errors

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


# Dispatch table — the closed set of methods FEAT-002 advertises.
# Entries are replaced in-place by later phases; the keys never change.
DISPATCH: dict[str, Handler] = {
    "ping": _ping,
    "status": _status,
    "shutdown": _shutdown,
}
