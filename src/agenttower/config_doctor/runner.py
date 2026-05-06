"""``agenttower config doctor`` orchestrator (R-006, FR-012, FR-018, FR-027).

Runs the closed-set six checks in fixed order on every invocation. Per
Clarifications 2026-05-06, every check produces a ``CheckResult`` row even
when an upstream gate has failed (the dependent check then skips its
round-trip and emits ``status=info`` with sub-code ``daemon_unavailable``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from agenttower.config_doctor import runtime_detect
from agenttower.config_doctor.checks import (
    CheckCode,
    CheckResult,
    check_container_identity,
    check_daemon_status,
    check_socket_reachable,
    check_socket_resolved,
    check_tmux_pane_match,
    check_tmux_present,
)
from agenttower.config_doctor.socket_resolve import (
    SocketPathInvalid,
    resolve_socket_path,
)
from agenttower.paths import Paths
from agenttower.socket_api.client import (
    DaemonError,
    DaemonUnavailable,
    send_request,
)


CHECK_ORDER: tuple[CheckCode, ...] = (
    "socket_resolved",
    "socket_reachable",
    "daemon_status",
    "container_identity",
    "tmux_present",
    "tmux_pane_match",
)
"""FR-012: fixed check order. Tests assert this tuple verbatim."""

REQUIRED_CHECKS: frozenset[CheckCode] = frozenset(
    {"socket_resolved", "socket_reachable", "daemon_status"}
)
"""R-006: required-for-non-degraded set."""


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[CheckResult, ...]
    exit_code: Literal[0, 1, 2, 3, 4, 5]


def run_doctor(
    env: Mapping[str, str],
    host_paths: Paths,
) -> DoctorReport:
    """Run all six checks in fixed order; return aggregated :class:`DoctorReport`.

    Pre-flight :class:`SocketPathInvalid` is raised by the resolver and is
    NOT trapped here; the caller (cli.py) catches it and emits FR-002 stderr
    + exit `1` BEFORE calling :func:`run_doctor`.
    """

    runtime_context = runtime_detect.detect()
    resolved = resolve_socket_path(env, host_paths, runtime_context)

    socket_resolved = check_socket_resolved(resolved)

    socket_reachable, status_payload = check_socket_reachable(resolved)
    socket_reachable_ok = socket_reachable.status == "pass"

    daemon_status = check_daemon_status(status_payload, socket_reachable_ok)

    list_containers_payload: dict[str, Any] | None = None
    if socket_reachable_ok and daemon_status.status in ("pass", "warn"):
        list_containers_payload = _safe_call(resolved.path, "list_containers")

    container_identity = check_container_identity(
        env=env,
        runtime_context=runtime_context,
        list_containers_payload=list_containers_payload,
        socket_reachable_ok=socket_reachable_ok and daemon_status.status in ("pass", "warn"),
    )

    tmux_present, parsed_tmux = check_tmux_present(env)

    list_panes_payload: dict[str, Any] | None = None
    if socket_reachable_ok and daemon_status.status in ("pass", "warn") and tmux_present.status == "pass":
        list_panes_payload = _safe_call(resolved.path, "list_panes")

    tmux_pane_match = check_tmux_pane_match(
        parsed=parsed_tmux,
        list_panes_payload=list_panes_payload,
        socket_reachable_ok=socket_reachable_ok and daemon_status.status in ("pass", "warn"),
    )

    rows: tuple[CheckResult, ...] = (
        socket_resolved,
        socket_reachable,
        daemon_status,
        container_identity,
        tmux_present,
        tmux_pane_match,
    )
    exit_code = _compute_exit_code(rows)
    return DoctorReport(checks=rows, exit_code=exit_code)


def _safe_call(socket_path, method: str) -> dict[str, Any] | None:
    """Best-effort send_request that swallows transport/semantic errors.

    The doctor's per-check functions decide what to do with the result; if
    the call fails here, we return ``None`` and the dependent check emits
    ``daemon_unavailable`` (data-model §6).
    """

    try:
        return send_request(
            socket_path, method, connect_timeout=1.0, read_timeout=1.0
        )
    except (DaemonUnavailable, DaemonError):
        return None


def _compute_exit_code(rows: tuple[CheckResult, ...]) -> Literal[0, 1, 2, 3, 4, 5]:
    """R-006 exit-code mapping (FR-018, post-clarify Q5 layering).

    * ``0`` — every required check is ``pass`` or ``info``.
    * ``2`` — ``socket_reachable`` is ``fail`` with sub-code in
      ``{socket_missing, connection_refused, connect_timeout}``.
    * ``3`` — ``socket_reachable`` is ``pass`` AND ``daemon_status`` is
      ``fail`` with sub-code ``daemon_error`` or ``schema_version_newer``
      (Clarifications 2026-05-06).
    * ``5`` — round-trip ok and required checks pass, but a non-required
      check is ``fail``.
    * ``1`` is reserved for pre-flight (handled by cli.py before
      :func:`run_doctor`); ``4`` is reserved per FEAT-002.
    """

    by_code = {row.code: row for row in rows}
    socket_reachable = by_code["socket_reachable"]
    daemon_status = by_code["daemon_status"]

    if socket_reachable.status == "fail":
        if socket_reachable.sub_code in {"socket_missing", "connection_refused", "connect_timeout"}:
            return 2
        # socket_not_unix / permission_denied / protocol_error map to exit 2
        # as well per FR-018 — the round-trip cannot be performed.
        return 2

    if daemon_status.status == "fail":
        # Both daemon_error and schema_version_newer produce exit 3 per
        # Clarifications 2026-05-06.
        return 3

    # Required checks all pass/warn/info now. Look at non-required.
    if any(
        row.status == "fail"
        for row in rows
        if row.code not in REQUIRED_CHECKS
    ):
        return 5
    return 0


__all__ = ["CHECK_ORDER", "REQUIRED_CHECKS", "DoctorReport", "run_doctor"]
