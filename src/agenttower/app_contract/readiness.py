"""``app.readiness`` handler + 6 subsystem probes + hint emission.

Implements FR-012, FR-013, FR-014, FR-014a, FR-045. Side-effect-free
per FR-045 (no scans triggered, no audit rows written).

Subsystems probed (FR-013):
    docker, tmux_discovery, sqlite, jsonl, routing_worker, log_attachment_workers

State aggregation (FR-012):
    every subsystem ok        → "ready"
    any subsystem unavailable  → "degraded" (or "unavailable" if all unavailable)
    any subsystem degraded     → "degraded"

The host-only gate (FR-042) applies to ``app.readiness``.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import envelope
from .versioning import (
    HINT_SEVERITY_ACTION_REQUIRED,
    HINT_SEVERITY_INFO,
    READINESS_STATE_DEGRADED,
    READINESS_STATE_OK as _READINESS_READY,
    READINESS_STATE_UNAVAILABLE,
    SUBSYSTEM_NAMES,
    SUBSYSTEM_STATUS_DEGRADED,
    SUBSYSTEM_STATUS_OK,
    SUBSYSTEM_STATUS_UNAVAILABLE,
)

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext


_NO_PEER_UID: int = -1


@dataclass(frozen=True)
class SubsystemRow:
    """Internal probe result. Serialized to FR-012 row shape by ``app_readiness``."""

    name: str
    status: str
    reason: str
    hint: str | None = None


@dataclass(frozen=True)
class Hint:
    """Top-level dashboard / readiness hint per FR-014a."""

    code: str
    severity: str
    message: str
    target: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.target is not None:
            d["target"] = self.target
        return d


# ─── Subsystem probes (FR-013, FR-045) ────────────────────────────────────


def probe_docker(ctx: "DaemonContext") -> SubsystemRow:
    """Docker reachability via the discovery service.

    Returns:
        - ``ok``           if the discovery service is wired and the most
          recent container scan completed without an error.
        - ``degraded``     if wired but the most recent scan errored.
        - ``unavailable``  if the service is unwired (boot still
          incomplete) or a probe call raises.
    """
    svc = getattr(ctx, "discovery_service", None)
    if svc is None:
        return SubsystemRow(
            name="docker",
            status=SUBSYSTEM_STATUS_UNAVAILABLE,
            reason="container discovery service not wired",
            hint=None,
        )
    try:
        # list_containers() is the cheapest read; failure here implies
        # Docker isn't reachable.
        svc.list_containers(active_only=False)
    except Exception as exc:  # noqa: BLE001 — side-effect-free probe
        return SubsystemRow(
            name="docker",
            status=SUBSYSTEM_STATUS_UNAVAILABLE,
            reason=f"docker unavailable: {type(exc).__name__}",
            hint=None,
        )
    return SubsystemRow(name="docker", status=SUBSYSTEM_STATUS_OK, reason="")


def probe_tmux_discovery(ctx: "DaemonContext") -> SubsystemRow:
    """tmux discovery service reachability.

    Tmux discovery runs inside bench containers; if no containers are
    up, the service is still ``ok`` (we report ``ok`` whenever the
    service is wired). A separate hint surfaces the empty-containers
    state at the dashboard level.
    """
    svc = getattr(ctx, "pane_service", None)
    if svc is None:
        return SubsystemRow(
            name="tmux_discovery",
            status=SUBSYSTEM_STATUS_UNAVAILABLE,
            reason="pane discovery service not wired",
            hint=None,
        )
    return SubsystemRow(name="tmux_discovery", status=SUBSYSTEM_STATUS_OK, reason="")


def probe_sqlite(ctx: "DaemonContext") -> SubsystemRow:
    """SQLite reachability — issues a trivial SELECT."""
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return SubsystemRow(
            name="sqlite",
            status=SUBSYSTEM_STATUS_UNAVAILABLE,
            reason="state connection not wired",
            hint=None,
        )
    try:
        conn.execute("SELECT 1").fetchone()
    except Exception as exc:  # noqa: BLE001
        return SubsystemRow(
            name="sqlite",
            status=SUBSYSTEM_STATUS_DEGRADED,
            reason=f"sqlite probe failed: {type(exc).__name__}",
            hint=None,
        )
    return SubsystemRow(name="sqlite", status=SUBSYSTEM_STATUS_OK, reason="")


def probe_jsonl(ctx: "DaemonContext") -> SubsystemRow:
    """JSONL audit-stream reachability via path stat + write permission.

    Checks both that the parent directory exists / is writable AND that
    the events file itself (if present) is writable. A read-only events
    file would silently swallow audit emissions otherwise.
    """
    events_file = getattr(ctx, "events_file", None)
    if events_file is None:
        return SubsystemRow(
            name="jsonl",
            status=SUBSYSTEM_STATUS_UNAVAILABLE,
            reason="events_file not wired",
            hint=None,
        )
    p = Path(events_file)
    parent = p.parent
    try:
        if not parent.exists():
            return SubsystemRow(
                name="jsonl",
                status=SUBSYSTEM_STATUS_UNAVAILABLE,
                reason=f"events_file parent {parent} does not exist",
                hint=None,
            )
        if not os.access(parent, os.W_OK):
            return SubsystemRow(
                name="jsonl",
                status=SUBSYSTEM_STATUS_DEGRADED,
                reason=f"events_file parent {parent} is not writable",
                hint=None,
            )
        # If the file exists, ensure we can stat AND write to it; if it
        # doesn't, the writer creates on first append, which is acceptable
        # because the parent directory writability check above covers
        # the create-on-write path.
        if p.exists():
            p.stat()
            if not os.access(p, os.W_OK):
                return SubsystemRow(
                    name="jsonl",
                    status=SUBSYSTEM_STATUS_DEGRADED,
                    reason=f"events_file {p} is not writable",
                    hint=None,
                )
    except Exception as exc:  # noqa: BLE001
        return SubsystemRow(
            name="jsonl",
            status=SUBSYSTEM_STATUS_DEGRADED,
            reason=f"jsonl probe failed: {type(exc).__name__}",
            hint=None,
        )
    return SubsystemRow(name="jsonl", status=SUBSYSTEM_STATUS_OK, reason="")


def probe_routing_worker(ctx: "DaemonContext") -> SubsystemRow:
    """FEAT-009 routing/delivery worker liveness."""
    worker = getattr(ctx, "delivery_worker", None)
    if worker is None:
        return SubsystemRow(
            name="routing_worker",
            status=SUBSYSTEM_STATUS_UNAVAILABLE,
            reason="delivery worker not wired",
            hint=None,
        )
    thread = getattr(worker, "thread", None)
    if isinstance(thread, threading.Thread) and not thread.is_alive():
        return SubsystemRow(
            name="routing_worker",
            status=SUBSYSTEM_STATUS_DEGRADED,
            reason="delivery worker thread is not alive",
            hint=None,
        )
    return SubsystemRow(name="routing_worker", status=SUBSYSTEM_STATUS_OK, reason="")


def probe_log_attachment_workers(ctx: "DaemonContext") -> SubsystemRow:
    """FEAT-007 log attachment workers liveness."""
    svc = getattr(ctx, "log_service", None)
    if svc is None:
        return SubsystemRow(
            name="log_attachment_workers",
            status=SUBSYSTEM_STATUS_UNAVAILABLE,
            reason="log service not wired",
            hint=None,
        )
    return SubsystemRow(
        name="log_attachment_workers", status=SUBSYSTEM_STATUS_OK, reason=""
    )


_PROBE_REGISTRY = {
    "docker": probe_docker,
    "tmux_discovery": probe_tmux_discovery,
    "sqlite": probe_sqlite,
    "jsonl": probe_jsonl,
    "routing_worker": probe_routing_worker,
    "log_attachment_workers": probe_log_attachment_workers,
}


# ─── State aggregation (FR-012, FR-014) ───────────────────────────────────


def aggregate_state(rows: list[SubsystemRow]) -> str:
    """Compute the top-level ``state`` from per-subsystem statuses.

    Rules (FR-012, FR-014):
        - If every required subsystem is ``ok`` → ``ready``.
        - If every required subsystem is ``unavailable`` → ``unavailable``.
        - Otherwise → ``degraded``.

    "No bench containers discovered" is NOT a degraded state per FR-014;
    that condition produces a hint while readiness stays ``ready``.
    """
    statuses = {row.status for row in rows}
    if statuses == {SUBSYSTEM_STATUS_OK}:
        return _READINESS_READY
    if statuses == {SUBSYSTEM_STATUS_UNAVAILABLE}:
        return READINESS_STATE_UNAVAILABLE
    return READINESS_STATE_DEGRADED


# ─── Hint emission (FR-014a) ──────────────────────────────────────────────


def emit_hints(
    ctx: "DaemonContext",
    rows: list[SubsystemRow],
    *,
    container_count: int,
    pane_count: int,
    agent_count: int,
    route_count_enabled: int,
    log_attachment_count: int,
) -> list[Hint]:
    """Compute the closed-set v1.0 hints from current state.

    Per FR-014a, each emitted hint uses a registered code and a
    documented severity. Hints are bias-toward-action — they suggest
    next steps the operator can take to make the system more useful.
    """
    hints: list[Hint] = []
    by_name = {row.name: row for row in rows}

    # docker_unavailable_hint: docker is the load-bearing subsystem for
    # container/pane discovery; if it's unavailable, surface that prominently.
    docker_row = by_name.get("docker")
    if docker_row is not None and docker_row.status == SUBSYSTEM_STATUS_UNAVAILABLE:
        hints.append(
            Hint(
                code="docker_unavailable_hint",
                severity=HINT_SEVERITY_ACTION_REQUIRED,
                message="Docker is not reachable from the daemon — start the docker service or check permissions.",
            )
        )

    # start_bench_container: zero containers discovered. Action-required only
    # if docker IS available (otherwise the docker_unavailable_hint covers it).
    if container_count == 0 and (
        docker_row is None or docker_row.status == SUBSYSTEM_STATUS_OK
    ):
        hints.append(
            Hint(
                code="start_bench_container",
                severity=HINT_SEVERITY_ACTION_REQUIRED,
                message="No bench containers discovered — start one to begin.",
            )
        )

    # check_container_filter: containers running on the host but the
    # discovery service found zero matches. We don't have visibility into
    # "containers exist but didn't match the filter" at this layer, so
    # this hint is reserved for future signal wiring.
    # (Intentionally not emitted at MVP — placeholder for future telemetry.)

    # register_first_agent: containers + panes discovered but no agents
    # registered yet — operator needs to adopt panes.
    if container_count > 0 and pane_count > 0 and agent_count == 0:
        hints.append(
            Hint(
                code="register_first_agent",
                severity=HINT_SEVERITY_INFO,
                message="Panes discovered but no agents registered yet — adopt a pane to start.",
            )
        )

    # attach_logs: agents exist but none have log attachments. Informational
    # — logs are useful for arbitration/audit but not required.
    if agent_count > 0 and log_attachment_count == 0:
        hints.append(
            Hint(
                code="attach_logs",
                severity=HINT_SEVERITY_INFO,
                message="No log attachments — attach a log to capture pane output for audit.",
            )
        )

    # enable_first_route: agents exist but no enabled routes — useful for
    # multi-agent workflows.
    if agent_count > 0 and route_count_enabled == 0:
        hints.append(
            Hint(
                code="enable_first_route",
                severity=HINT_SEVERITY_INFO,
                message="No routes enabled — add a route to forward events between agents.",
            )
        )

    return hints


# ─── Handler ──────────────────────────────────────────────────────────────


def app_readiness(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    """Handler for ``app.readiness`` (FR-007, FR-012..FR-014a, FR-042, FR-045)."""
    # FR-042 + FR-007: combined host-only + session-token gate.
    from .sessions import gate_session_required  # lazy (circular avoidance)

    gate = gate_session_required(params, peer_uid)
    if isinstance(gate, dict):
        return gate
    # gate is an AppSession; we don't need to bind it here because
    # app.readiness is side-effect-free (FR-045) — no audit emission.

    # Run all probes in fixed order (FR-013).
    rows: list[SubsystemRow] = [
        _PROBE_REGISTRY[name](ctx) for name in SUBSYSTEM_NAMES
    ]
    top_state = aggregate_state(rows)

    # Compute the counts needed for hint emission. These are small and
    # cheap; full dashboard counts live in dashboard.py.
    counts = _summary_counts(ctx)
    hints = emit_hints(
        ctx,
        rows,
        container_count=counts["containers"],
        pane_count=counts["panes"],
        agent_count=counts["agents"],
        route_count_enabled=counts["routes_enabled"],
        log_attachment_count=counts["log_attachments"],
    )

    return envelope.success({
        "state": top_state,
        "subsystems": [
            {
                "name": row.name,
                "status": row.status,
                "reason": row.reason,
                "hint": row.hint,
            }
            for row in rows
        ],
        "hints": [h.to_dict() for h in hints],
    })


def _summary_counts(ctx: "DaemonContext") -> dict[str, int]:
    """Cheap top-line counts for hint emission. Failures degrade to 0.

    ``containers`` counts only ACTIVE containers — the "no containers"
    hint must fire when nothing is running, even if stale inactive rows
    linger in the table.
    """
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return {
            "containers": 0,
            "panes": 0,
            "agents": 0,
            "routes_enabled": 0,
            "log_attachments": 0,
        }
    try:
        containers = conn.execute(
            "SELECT COUNT(*) FROM containers WHERE active = 1"
        ).fetchone()[0]
    except Exception:  # noqa: BLE001
        containers = 0
    try:
        panes = conn.execute("SELECT COUNT(*) FROM panes").fetchone()[0]
    except Exception:  # noqa: BLE001
        panes = 0
    try:
        agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    except Exception:  # noqa: BLE001
        agents = 0
    try:
        routes_enabled = conn.execute(
            "SELECT COUNT(*) FROM routes WHERE enabled = 1"
        ).fetchone()[0]
    except Exception:  # noqa: BLE001
        routes_enabled = 0
    try:
        log_attachments = conn.execute(
            "SELECT COUNT(*) FROM log_attachments WHERE status = 'active'"
        ).fetchone()[0]
    except Exception:  # noqa: BLE001
        log_attachments = 0
    return {
        "containers": int(containers),
        "panes": int(panes),
        "agents": int(agents),
        "routes_enabled": int(routes_enabled),
        "log_attachments": int(log_attachments),
    }


__all__ = [
    "SubsystemRow",
    "Hint",
    "probe_docker",
    "probe_tmux_discovery",
    "probe_sqlite",
    "probe_jsonl",
    "probe_routing_worker",
    "probe_log_attachment_workers",
    "aggregate_state",
    "emit_hints",
    "app_readiness",
]
