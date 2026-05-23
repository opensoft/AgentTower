"""FEAT-011 contract version constants and closed-set enumerations.

Implements:
- FR-010 / FR-035: ``app_contract_version`` is a string ``MAJOR.MINOR``.
- FR-036: major-mismatch detection helper.
- FR-039: ``capability_flags = {}`` at v1.0.
- Closed-set enums backing FR-012 (readiness state, subsystem status),
  FR-013 (subsystem names), FR-014a (hint severity, hint codes),
  FR-016 + FR-016a (container state), FR-021a (state_priority, role_priority),
  FR-030c (scan state, scan kind), FR-044 (mutation origin).

Every closed set is additive across minors per FR-035.
"""

from __future__ import annotations

from typing import Final


# ─── Contract version (FR-010, FR-035) ────────────────────────────────────

APP_CONTRACT_VERSION: Final[str] = "1.0"
APP_CONTRACT_MAJOR: Final[int] = 1
APP_CONTRACT_MINOR: Final[int] = 0

SUPPORTED_MINOR_RANGE: Final[dict[str, str]] = {
    "min": "1.0",
    "max": "1.0",
}

# Capability flags at v1.0 (FR-039). Always present in app.hello;
# always empty at v1.0 because every FEAT-011 method is required.
# Future minors append named boolean flags here additively.
CAPABILITY_FLAGS_V1_0: Final[dict[str, bool]] = {}


def parse_major_minor(version: str) -> tuple[int, int]:
    """Parse a ``MAJOR.MINOR`` string into ``(major, minor)``.

    Raises ValueError if the string does not match the expected shape.
    """
    parts = version.split(".")
    if len(parts) != 2:
        raise ValueError(f"app_contract_version must be MAJOR.MINOR, got {version!r}")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(
            f"app_contract_version must be integer components, got {version!r}"
        ) from exc


def is_major_compatible(client_major: int) -> bool:
    """Return True if a client declaring ``client_major`` can speak this daemon.

    Per FR-035 / FR-036, only matching major versions are compatible.
    """
    return client_major == APP_CONTRACT_MAJOR


# ─── Readiness closed sets (FR-012, FR-013) ───────────────────────────────

READINESS_STATE_OK: Final[str] = "ready"
READINESS_STATE_DEGRADED: Final[str] = "degraded"
READINESS_STATE_UNAVAILABLE: Final[str] = "unavailable"

READINESS_STATES: Final[frozenset[str]] = frozenset({
    READINESS_STATE_OK,
    READINESS_STATE_DEGRADED,
    READINESS_STATE_UNAVAILABLE,
})

SUBSYSTEM_STATUS_OK: Final[str] = "ok"
SUBSYSTEM_STATUS_DEGRADED: Final[str] = "degraded"
SUBSYSTEM_STATUS_UNAVAILABLE: Final[str] = "unavailable"

SUBSYSTEM_STATUSES: Final[frozenset[str]] = frozenset({
    SUBSYSTEM_STATUS_OK,
    SUBSYSTEM_STATUS_DEGRADED,
    SUBSYSTEM_STATUS_UNAVAILABLE,
})

# FR-013: required subsystems at v1.0, in the order they appear in app.readiness.
SUBSYSTEM_NAMES: Final[tuple[str, ...]] = (
    "docker",
    "tmux_discovery",
    "sqlite",
    "jsonl",
    "routing_worker",
    "log_attachment_workers",
)


# ─── Hint closed sets (FR-014a) ───────────────────────────────────────────

HINT_SEVERITY_INFO: Final[str] = "info"
HINT_SEVERITY_WARNING: Final[str] = "warning"
HINT_SEVERITY_ACTION_REQUIRED: Final[str] = "action_required"

HINT_SEVERITIES: Final[frozenset[str]] = frozenset({
    HINT_SEVERITY_INFO,
    HINT_SEVERITY_WARNING,
    HINT_SEVERITY_ACTION_REQUIRED,
})

# FR-014a: closed v1.0 hint code registry.
HINT_CODES: Final[frozenset[str]] = frozenset({
    "start_bench_container",
    "check_container_filter",
    "register_first_agent",
    "attach_logs",
    "enable_first_route",
    "docker_unavailable_hint",
})


# ─── Container state (FR-016, FR-016a) ────────────────────────────────────

CONTAINER_STATE_ACTIVE: Final[str] = "active"
CONTAINER_STATE_INACTIVE: Final[str] = "inactive"
CONTAINER_STATE_DEGRADED_SCAN: Final[str] = "degraded_scan"

CONTAINER_STATES: Final[frozenset[str]] = frozenset({
    CONTAINER_STATE_ACTIVE,
    CONTAINER_STATE_INACTIVE,
    CONTAINER_STATE_DEGRADED_SCAN,
})


# ─── Agent role and role_priority (FEAT-006 + FR-021a) ────────────────────

AGENT_ROLES: Final[tuple[str, ...]] = (
    "master",
    "slave",
    "swarm",
    "test-runner",
    "shell",
    "unknown",
)

# FR-021a normative integer mapping for default agent ordering.
ROLE_PRIORITY: Final[dict[str, int]] = {
    "master": 1,
    "slave": 2,
    "swarm": 3,
    "test-runner": 4,
    "shell": 5,
    "unknown": 6,
}


# ─── Queue state and state_priority (FEAT-009 + FR-021a) ──────────────────

# The shipped FEAT-009 ``message_queue.state`` CHECK set (state/schema.py).
# Round-5 (2026-05-20) correction: the earlier
# ``pending/in_flight/expired/cancelled`` vocabulary did not match
# FEAT-009. There is no ``pending`` (it is ``queued``), no ``in_flight``
# state (in-flight is a derived ``queued`` row with
# ``delivery_attempt_started_at`` set), and no ``expired`` state;
# ``canceled`` is the FEAT-009 single-``l`` spelling.
QUEUE_STATES: Final[tuple[str, ...]] = (
    "queued",
    "blocked",
    "delivered",
    "canceled",
    "failed",
)

# FR-021a normative integer mapping for default queue ordering.
# Operational-first: live (queued) + operator-decision (blocked) sort
# ahead of terminal rows; among terminal rows failed < delivered <
# canceled.
STATE_PRIORITY: Final[dict[str, int]] = {
    "queued": 1,
    "blocked": 2,
    "failed": 3,
    "delivered": 4,
    "canceled": 5,
}


# ─── Scan state and kind (FR-030c) ────────────────────────────────────────

SCAN_STATE_RUNNING: Final[str] = "running"
SCAN_STATE_COMPLETED: Final[str] = "completed"
SCAN_STATE_FAILED: Final[str] = "failed"

# v1.0 closed set is exactly these three. `expired` is intentionally absent
# (FR-030c, Clarifications session 2026-05-19 round 3).
SCAN_STATES: Final[frozenset[str]] = frozenset({
    SCAN_STATE_RUNNING,
    SCAN_STATE_COMPLETED,
    SCAN_STATE_FAILED,
})

SCAN_KIND_CONTAINERS: Final[str] = "containers"
SCAN_KIND_PANES: Final[str] = "panes"

SCAN_KINDS: Final[frozenset[str]] = frozenset({
    SCAN_KIND_CONTAINERS,
    SCAN_KIND_PANES,
})


# ─── Mutation origin (FR-044) ─────────────────────────────────────────────

# Extended FEAT-008 origin set: app.* mutations carry origin="app".
MUTATION_ORIGINS: Final[frozenset[str]] = frozenset({
    "cli",
    "app",
    "route",
    "system",
})

ORIGIN_APP: Final[str] = "app"


__all__ = [
    "APP_CONTRACT_VERSION",
    "APP_CONTRACT_MAJOR",
    "APP_CONTRACT_MINOR",
    "SUPPORTED_MINOR_RANGE",
    "CAPABILITY_FLAGS_V1_0",
    "parse_major_minor",
    "is_major_compatible",
    "READINESS_STATE_OK",
    "READINESS_STATE_DEGRADED",
    "READINESS_STATE_UNAVAILABLE",
    "READINESS_STATES",
    "SUBSYSTEM_STATUS_OK",
    "SUBSYSTEM_STATUS_DEGRADED",
    "SUBSYSTEM_STATUS_UNAVAILABLE",
    "SUBSYSTEM_STATUSES",
    "SUBSYSTEM_NAMES",
    "HINT_SEVERITY_INFO",
    "HINT_SEVERITY_WARNING",
    "HINT_SEVERITY_ACTION_REQUIRED",
    "HINT_SEVERITIES",
    "HINT_CODES",
    "CONTAINER_STATE_ACTIVE",
    "CONTAINER_STATE_INACTIVE",
    "CONTAINER_STATE_DEGRADED_SCAN",
    "CONTAINER_STATES",
    "AGENT_ROLES",
    "ROLE_PRIORITY",
    "QUEUE_STATES",
    "STATE_PRIORITY",
    "SCAN_STATE_RUNNING",
    "SCAN_STATE_COMPLETED",
    "SCAN_STATE_FAILED",
    "SCAN_STATES",
    "SCAN_KIND_CONTAINERS",
    "SCAN_KIND_PANES",
    "SCAN_KINDS",
    "MUTATION_ORIGINS",
    "ORIGIN_APP",
]
