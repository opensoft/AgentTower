"""FEAT-011 T036/T037/T038 — ``app.scan.{containers, panes, status}`` handlers.

These three handlers expose the existing FEAT-003 / FEAT-004 discovery
services through the FEAT-011 envelope. They:

* Acquire the FR-030d/e gate via :class:`scans.ScanRegistry` — same-kind
  coalescing + 4-concurrent in-flight cap.
* For ``wait=true``: block on the registry's done event for up to 30 s
  (FR-030b). On timeout the response is a ``scan_timeout`` failure
  with ``details.scan_id``; the scan continues server-side and remains
  reachable via ``app.scan.status``.
* For ``wait=false``: kick the scan off on a daemon thread and return
  immediately with ``{scan_id, state: "running"}``.
* ``app.scan.status``: lookup by ``scan_id`` → returns ``{state,
  scan_kind, started_at, completed_at, result}`` per FR-030c, or
  ``scan_not_found`` for unknown / evicted ids.

All three are session-gated (FR-007). ``host_only`` (FR-042) is
enforced by ``gate_session_required`` shared with the other handlers.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

from . import envelope as _envelope
from . import scans as _scans
from . import sessions as _sessions
from .errors import (
    INTERNAL_ERROR,
    SCAN_NOT_FOUND,
    SCAN_TIMEOUT,
    VALIDATION_FAILED,
)

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext


_WAIT_TIMEOUT_SECONDS = 30.0  # FR-030b


def _result_to_dict(result: Any) -> dict[str, Any]:
    """Coerce a scan-worker result (dataclass / dict / object) → plain dict.

    The discovery services return frozen dataclasses (``ScanResult``,
    ``PaneScanResult``); we project them to a JSON-serializable dict
    suitable for the ``app.scan.status.result`` field.
    """
    if result is None:
        return {}
    if is_dataclass(result):
        return _coerce_to_jsonable(asdict(result))
    if isinstance(result, dict):
        return _coerce_to_jsonable(result)
    # Fallback: best-effort attribute scrape for plain objects.
    return _coerce_to_jsonable({
        k: getattr(result, k) for k in dir(result)
        if not k.startswith("_") and not callable(getattr(result, k))
    })


def _coerce_to_jsonable(obj: Any) -> Any:
    """Recursively convert tuples → lists and frozen dataclasses to dicts
    so the result can be JSON-serialized. Strings/numbers/None pass through."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _coerce_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_coerce_to_jsonable(v) for v in obj]
    if is_dataclass(obj):
        return _coerce_to_jsonable(asdict(obj))
    return str(obj)


def _run_scan_in_background(
    record: _scans.ScanRecord,
    scan_callable,
    registry: _scans.ScanRegistry,
) -> None:
    """Daemon-thread worker. Calls ``scan_callable()`` and updates the
    registry with the terminal state."""
    try:
        result = scan_callable()
    except Exception as exc:  # noqa: BLE001 — never propagate to caller
        registry.fail(
            record.scan_id,
            {"error": f"{type(exc).__name__}: {exc}"},
        )
        return
    registry.complete(record.scan_id, _result_to_dict(result))


def _kick_off_scan(
    record: _scans.ScanRecord,
    scan_callable,
    registry: _scans.ScanRegistry,
) -> None:
    """Spawn the daemon thread that runs the underlying scan."""
    thread = threading.Thread(
        target=_run_scan_in_background,
        args=(record, scan_callable, registry),
        name=f"app-scan-{record.scan_kind}-{record.scan_id[:8]}",
        daemon=True,
    )
    thread.start()


def _scan_dispatch(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int,
    *,
    scan_kind: str,
    scan_service_attr: str,
) -> dict[str, Any]:
    """Shared body for ``app.scan.containers`` and ``app.scan.panes``.

    ``scan_service_attr`` names the attribute on ``DaemonContext`` that
    holds the underlying discovery service (``discovery_service`` for
    containers, ``pane_service`` for panes). If the service is unwired
    the handler returns ``internal_error`` — production daemon wiring
    is mandatory.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session  # gate failure envelope

    wait = bool(params.get("wait", True))

    service = getattr(ctx, scan_service_attr, None)
    if service is None or not hasattr(service, "scan"):
        return _envelope.failure(
            INTERNAL_ERROR,
            f"daemon {scan_service_attr} service not wired; cannot run scan",
            details={},
        )

    registry = _scans.get_registry()
    try:
        record, coalesced = registry.start(
            scan_kind=scan_kind,
            issued_by_app_session_id=session.app_session_id,
        )
    except _scans.ScanCapExceeded:
        return _envelope.failure(
            VALIDATION_FAILED,
            f"too many scans in flight ({_scans.MAX_IN_FLIGHT} concurrent)",
            details={"field": "scan_kind", "reason": "too_many_scans_in_flight"},
        )

    # Only the **first** caller kicks off the worker. Coalesced callers
    # ride on the existing scan's done event.
    if not coalesced:
        _kick_off_scan(record, service.scan, registry)

    if not wait:
        return _envelope.success({
            "scan_id": record.scan_id,
            "state": record.state,
        })

    # wait=true (FR-030b): block on the done event up to 30 s.
    completed = record.done.wait(timeout=_WAIT_TIMEOUT_SECONDS)
    if not completed:
        return _envelope.failure(
            SCAN_TIMEOUT,
            f"scan exceeded {int(_WAIT_TIMEOUT_SECONDS)} s wall-clock; "
            f"continues server-side; poll app.scan.status({record.scan_id})",
            details={"scan_id": record.scan_id},
        )
    final = registry.lookup(record.scan_id)
    if final is None:
        # Vanishing edge case — record evicted between wait+lookup.
        # Treat as internal_error rather than scan_not_found, since
        # the caller just observed the scan complete.
        return _envelope.failure(
            INTERNAL_ERROR,
            "scan record evicted between wait and lookup",
            details={},
        )
    return _envelope.success({
        "scan_id": final.scan_id,
        "state": final.state,
        "result": final.result if final.result is not None else {},
    })


# ─── Handlers wired into APP_DISPATCH ────────────────────────────────────


def app_scan_containers(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.scan.containers`` (FR-030, FR-030b, FR-030c, FR-030d/e)."""
    return _scan_dispatch(
        ctx,
        params,
        peer_uid,
        scan_kind=_scans.KIND_CONTAINERS,
        scan_service_attr="discovery_service",
    )


def app_scan_panes(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.scan.panes`` (FR-030, FR-030b, FR-030c, FR-030d/e)."""
    return _scan_dispatch(
        ctx,
        params,
        peer_uid,
        scan_kind=_scans.KIND_PANES,
        scan_service_attr="pane_service",
    )


def app_scan_status(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.scan.status`` (FR-030c).

    Lookup a previously-issued scan by id. Returns ``{state, scan_kind,
    started_at, completed_at, result}`` per FR-030c, or ``scan_not_found``
    when the id is unknown or has been evicted.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    scan_id = params.get("scan_id") if isinstance(params, dict) else None
    if not isinstance(scan_id, str) or not scan_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "scan_id must be a non-empty string",
            details={"field": "scan_id", "reason": "missing or wrong type"},
        )

    record = _scans.get_registry().lookup(scan_id)
    if record is None:
        return _envelope.failure(
            SCAN_NOT_FOUND,
            f"scan_id not in registry (unknown or evicted past the "
            f"{_scans.MAX_RECORDS}-record cap)",
            details={"scan_id": scan_id},
        )

    return _envelope.success({
        "state": record.state,
        "scan_kind": record.scan_kind,
        "started_at": record.started_at_ms,
        "completed_at": record.completed_at_ms,
        "result": record.result,
    })


__all__ = [
    "app_scan_containers",
    "app_scan_panes",
    "app_scan_status",
]
