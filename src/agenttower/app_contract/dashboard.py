"""``app.dashboard`` handler — aggregate counts + recents + hints.

Implements FR-015, FR-016, FR-017, FR-018, FR-045.

Counts (FR-016):
    containers:      active | inactive | degraded_scan
    panes:           total | registered | unregistered
    agents:          total + by_role for the FEAT-006 closed set
    log_attachments: active | degraded | none
    events:          total
    queue:           by_state across the FEAT-009 closed set
    routes:          enabled | disabled

Recent rows (FR-017):
    Per surface: ``recent_limit`` rows (default 10, bound [1, 50]).
    Each row is a compact view-model from ``view_models.py``.

Side-effect-free (FR-045) — no scans triggered, no audit emitted.
No global lock (FR-018) — counts/recents are read sequentially and
slight inter-surface inconsistency is acceptable.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from agenttower.routing import skip_counter

from . import envelope, recommendations, view_models
from .errors import VALIDATION_FAILED
from .readiness import (
    Hint,
    emit_hints,
    probe_docker,
    probe_jsonl,
    probe_log_attachment_workers,
    probe_routing_worker,
    probe_sqlite,
    probe_tmux_discovery,
)
from .versioning import AGENT_ROLES, QUEUE_STATES

_log = logging.getLogger(__name__)

# FR-027 / SC-006 latency budget. Crossing this triggers a WARN log but
# the dashboard response is returned best-effort (FR-027 — no error
# envelope, no missing fields).
_LATENCY_BUDGET_MS: int = 500


def _test_only_injection_ms() -> int:
    """Test-only latency-injection hook (FEAT-014 T024 SC-006 / FR-027).

    Returns the millisecond sleep amount when the env var
    ``AGENTTOWER_TEST_INJECT_LATENCY_MS`` is set to a positive integer;
    ``0`` (no injection) otherwise.

    Production builds never set this env var — the env-var-gated sleep
    path is dead code in release. Integration tests use this to force
    ``app.dashboard`` past the SC-006 budget to exercise the FR-027
    WARN-log path without needing a real slow daemon.
    """
    val = os.environ.get("AGENTTOWER_TEST_INJECT_LATENCY_MS", "")
    if not val:
        return 0
    try:
        return max(0, int(val))
    except (ValueError, TypeError):
        return 0


def _test_only_forced_degraded_subsystems() -> set[str]:
    """Test-only readiness-probe override (FEAT-014 T024 SC-006 degraded
    waiver).

    Returns the set of subsystem names that should be forced to status
    ``degraded`` regardless of their actual probe result, parsed from
    ``AGENTTOWER_TEST_FORCE_DEGRADED_SUBSYSTEMS`` (comma-separated). Empty
    set when the env var is unset.

    Production builds never set this env var. Integration tests use this
    to seed a ``subsystem_degraded`` recommendation without needing a
    real Docker/tmux failure.
    """
    val = os.environ.get("AGENTTOWER_TEST_FORCE_DEGRADED_SUBSYSTEMS", "")
    if not val:
        return set()
    return {name.strip() for name in val.split(",") if name.strip()}

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext


_NO_PEER_UID: int = -1
_RECENT_LIMIT_DEFAULT = 10
_RECENT_LIMIT_MIN = 1
_RECENT_LIMIT_MAX = 50


def _coerce_recent_limit(
    value: Any,
) -> tuple[int | None, dict[str, Any] | None]:
    """Coerce optional ``recent_limit`` param. FR-017."""
    if value is None:
        return _RECENT_LIMIT_DEFAULT, None
    if isinstance(value, bool) or not isinstance(value, int):
        return None, envelope.failure(
            VALIDATION_FAILED,
            "recent_limit must be an integer",
            details={"field": "recent_limit", "reason": "must be an integer"},
        )
    if value < _RECENT_LIMIT_MIN or value > _RECENT_LIMIT_MAX:
        return None, envelope.failure(
            VALIDATION_FAILED,
            f"recent_limit must be in [{_RECENT_LIMIT_MIN}, {_RECENT_LIMIT_MAX}]",
            details={
                "field": "recent_limit",
                "reason": f"out of bounds [{_RECENT_LIMIT_MIN},{_RECENT_LIMIT_MAX}]",
            },
        )
    return value, None


# ─── Counts (FR-016) ──────────────────────────────────────────────────────


def _container_counts(ctx: "DaemonContext") -> dict[str, int]:
    """Containers by state. ``degraded_scan`` semantics per FR-016a."""
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return {"active": 0, "inactive": 0, "degraded_scan": 0}
    # FEAT-003 stores containers with an ``active`` boolean column. The
    # ``degraded_scan`` state defined by FR-016a (FEAT-003 saw container,
    # FEAT-004 pane discovery failed) is not yet tracked as a persisted
    # column at MVP; report 0 until upstream wiring lands. Active/inactive
    # come from the ``active`` column.
    try:
        rows = conn.execute(
            "SELECT active, COUNT(*) FROM containers GROUP BY active"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return {"active": 0, "inactive": 0, "degraded_scan": 0}
    active = 0
    inactive = 0
    for row in rows:
        if row[0]:
            active = int(row[1])
        else:
            inactive = int(row[1])
    return {"active": active, "inactive": inactive, "degraded_scan": 0}


def _pane_counts(ctx: "DaemonContext") -> dict[str, int]:
    """Panes total / registered / unregistered. A pane is "registered"
    iff it appears as the bound pane of an active agent."""
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return {"total": 0, "registered": 0, "unregistered": 0}
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM panes").fetchone()[0])
    except Exception:  # noqa: BLE001
        total = 0
    try:
        # Match each pane against an active agent via the composite key.
        registered = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM panes p
                WHERE EXISTS (
                    SELECT 1 FROM agents a
                    WHERE a.active = 1
                      AND a.container_id = p.container_id
                      AND a.tmux_pane_id = p.tmux_pane_id
                )
                """
            ).fetchone()[0]
        )
    except Exception:  # noqa: BLE001
        registered = 0
    return {
        "total": total,
        "registered": registered,
        "unregistered": max(total - registered, 0),
    }


def _agent_counts(ctx: "DaemonContext") -> dict[str, Any]:
    """Total agents + per-role breakdown (FR-016)."""
    conn = getattr(ctx, "state_conn", None)
    by_role: dict[str, int] = {role: 0 for role in AGENT_ROLES}
    if conn is None:
        return {"total": 0, "by_role": by_role}
    try:
        rows = conn.execute("SELECT role, COUNT(*) FROM agents GROUP BY role").fetchall()
    except Exception:  # noqa: BLE001
        return {"total": 0, "by_role": by_role}
    total = 0
    for row in rows:
        role = (row[0] or "unknown")
        if role not in by_role:
            role = "unknown"
        by_role[role] = by_role.get(role, 0) + int(row[1])
        total += int(row[1])
    return {"total": total, "by_role": by_role}


def _log_attachment_counts(ctx: "DaemonContext") -> dict[str, int]:
    """Log attachments active | degraded | none.

    "none" is the count of registered agents that have NO active log
    attachment — a useful UX signal but distinct from a "rows in the
    log_attachments table" count.
    """
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return {"active": 0, "degraded": 0, "none": 0}
    try:
        active = int(
            conn.execute(
                "SELECT COUNT(*) FROM log_attachments WHERE status = 'active'"
            ).fetchone()[0]
        )
    except Exception:  # noqa: BLE001
        active = 0
    try:
        # FEAT-007 ``log_attachments.status`` closed set is
        # {active, superseded, stale, detached} — there is no
        # ``degraded`` literal. The dashboard's "degraded" bucket
        # maps to ``stale`` (attachment row exists but is no longer
        # receiving output). ``superseded`` rows are bookkeeping for
        # a newer active attachment; ``detached`` is "no attachment".
        degraded = int(
            conn.execute(
                "SELECT COUNT(*) FROM log_attachments WHERE status = 'stale'"
            ).fetchone()[0]
        )
    except Exception:  # noqa: BLE001
        degraded = 0
    try:
        agent_count = int(
            conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        )
    except Exception:  # noqa: BLE001
        agent_count = 0
    return {
        "active": active,
        "degraded": degraded,
        "none": max(agent_count - active - degraded, 0),
    }


def _event_count(ctx: "DaemonContext") -> int:
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return 0
    try:
        return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    except Exception:  # noqa: BLE001
        return 0


def _queue_counts(ctx: "DaemonContext") -> dict[str, int]:
    """Queue counts across the FEAT-009 closed state set."""
    by_state: dict[str, int] = {s: 0 for s in QUEUE_STATES}
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return by_state
    try:
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM message_queue GROUP BY state"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return by_state
    for row in rows:
        state = row[0] or ""
        if state in by_state:
            by_state[state] = int(row[1])
    return by_state


def _route_counts(ctx: "DaemonContext") -> dict[str, int]:
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return {"enabled": 0, "disabled": 0}
    try:
        enabled = int(
            conn.execute(
                "SELECT COUNT(*) FROM routes WHERE enabled = 1"
            ).fetchone()[0]
        )
        disabled = int(
            conn.execute(
                "SELECT COUNT(*) FROM routes WHERE enabled = 0"
            ).fetchone()[0]
        )
    except Exception:  # noqa: BLE001
        return {"enabled": 0, "disabled": 0}
    return {"enabled": enabled, "disabled": disabled}


# ─── v1.1 "first id" deterministic lookups (FEAT-014 T020) ───────────────
#
# T020 / Research §CC determinism: target.id values for the recommendation
# engine come from these deterministic-first-by-PK queries. Each helper
# follows FR-025's fail-soft pattern — broad except returns None so the
# recommendation engine sees the corresponding state field as null and
# routes around it (e.g., no_panes_discovered emits target=None).


def _first_active_container_id(ctx: "DaemonContext") -> str | None:
    """Deterministic first active container by primary-key order."""
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT container_id FROM containers "
            "WHERE active = 1 ORDER BY container_id LIMIT 1"
        ).fetchone()
    except Exception:  # noqa: BLE001 — FR-025 fallback
        return None
    return row[0] if row else None


def _first_unadopted_pane_id(ctx: "DaemonContext") -> str | None:
    """Deterministic first unadopted pane by primary-key order. A pane is
    unadopted iff no agent row exists for it (per the same agent→pane
    matching the v1.0 ``_pane_counts.registered`` query uses)."""
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT p.tmux_pane_id FROM panes p "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM agents a "
            "  WHERE a.container_id = p.container_id "
            "    AND a.tmux_pane_id = p.tmux_pane_id "
            "    AND a.active = 1"
            ") "
            "ORDER BY p.container_id, p.tmux_pane_id LIMIT 1"
        ).fetchone()
    except Exception:  # noqa: BLE001 — FR-025 fallback
        return None
    return row[0] if row else None


def _oldest_blocked_message_id(ctx: "DaemonContext") -> str | None:
    """Deterministic oldest blocked queue message by created_at."""
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT message_id FROM message_queue "
            "WHERE state = 'blocked' "
            "ORDER BY created_at ASC, message_id ASC LIMIT 1"
        ).fetchone()
    except Exception:  # noqa: BLE001 — FR-025 fallback
        return None
    return row[0] if row else None


# ─── v1.1 PaneState / AgentState aggregators (FEAT-014) ───────────────────


PANE_STATE_KEYS: tuple[str, ...] = (
    "discovered-and-unmanaged",
    "discovered-and-registered",
    "inactive-or-stale",
    "discovery-degraded",
)

AGENT_STATE_KEYS: tuple[str, ...] = (
    "active",
    "inactive",
    "partially_configured",
    "log-attached",
    "log-detached",
)


def _maybe_test_only_inject_latency() -> None:
    """Sleep for ``_test_only_injection_ms()`` ms if the env var is set.

    No-op in production (env var unset). Integration tests use this to
    push ``app.dashboard`` past the SC-006 budget for FR-027 testing.
    """
    inject_ms = _test_only_injection_ms()
    if inject_ms > 0:
        time.sleep(inject_ms / 1000.0)


def _compute_pane_state_buckets(ctx: "DaemonContext") -> dict[str, int]:
    """v1.1 — PaneState buckets per data-model.md §PaneState (FEAT-014 FR-001..FR-002).

    4-key closed set with Research §PB priority order
    (degraded > stale > registered > unmanaged):

    * ``discovery-degraded`` — container in ``degraded_scan`` state. Always
      ``0`` at v1.1 MVP because FR-016a's ``degraded_scan`` is not yet a
      persisted column on the ``containers`` row (same caveat as
      ``_container_counts``). FR-003 mandates the key be present at ``0``.
    * ``inactive-or-stale`` — pane whose container row has ``active = 0``.
      The "``last_seen_at`` predates the most recent successful scan" half
      of the spec's definition (Clarifications Q1) is not implementable
      until upstream scan-timestamp wiring lands; v1.1 returns the
      container-inactive contribution only.
    * ``discovered-and-registered`` — pane with active agent AND active
      container (FR-019 cross-check; partially_configured agents still
      count here per the FR-019 carve-out — bucket determined by
      ``agents.active = 1``, not by role/capability/label completeness).
    * ``discovered-and-unmanaged`` — remaining panes (active container,
      no active agent).

    FR-025 fallback: returns all-zero if the SQLite accessor fails.

    FR-019 (post-R3 loosened invariant): ``dar <= v1.0 counts.panes.registered``,
    with the gap equal to the count of panes whose registered agent is on
    an inactive or ``degraded_scan`` container. Those panes are routed to
    ``inactive-or-stale`` / ``discovery-degraded`` by Research §PB priority,
    not to ``discovered-and-registered``. The US1 acceptance fixture (only
    active containers) trivially has zero gap, so ``dar == registered``
    holds there. The contradiction with the previous strict-equality FR-019
    wording is resolved in Clarifications §Session 2026-05-25-r3 Q1.
    """
    zeros = {k: 0 for k in PANE_STATE_KEYS}
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return zeros
    try:
        # inactive-or-stale: panes on containers with active=0 (container half
        # of Clarifications Q1; last_seen_at half deferred to upstream wiring).
        ios = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM panes p
                JOIN containers c ON c.container_id = p.container_id
                WHERE c.active = 0
                """
            ).fetchone()[0]
        )
        # discovered-and-registered: pane on active container with active agent.
        dar = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM panes p
                JOIN containers c ON c.container_id = p.container_id
                WHERE c.active = 1
                  AND EXISTS (
                      SELECT 1 FROM agents a
                      WHERE a.active = 1
                        AND a.container_id = p.container_id
                        AND a.tmux_pane_id = p.tmux_pane_id
                  )
                """
            ).fetchone()[0]
        )
        total = int(conn.execute("SELECT COUNT(*) FROM panes").fetchone()[0])
        # discovered-and-unmanaged = remainder (total - ios - dar - dd=0).
        dau = max(total - ios - dar, 0)
        return {
            "discovered-and-unmanaged": dau,
            "discovered-and-registered": dar,
            "inactive-or-stale": ios,
            "discovery-degraded": 0,
        }
    except Exception:  # noqa: BLE001 — FR-025 aggregator-failure fallback
        return zeros


def _compute_agent_state_buckets(ctx: "DaemonContext") -> dict[str, int]:
    """v1.1 — AgentState buckets per data-model.md §AgentState (FEAT-014 FR-004..FR-006, FR-020).

    5-key set, two orthogonal partitions:

    * **Configuration partition** (strict — FR-020):
      ``active`` + ``inactive`` + ``partially_configured`` == total agents
        - ``partially_configured`` — Clarifications Q2 — any of ``role``,
          ``capability``, ``label`` missing/empty/``unknown``.
        - ``active`` — fully configured AND container.active=1.
        - ``inactive`` — fully configured AND container.active=0.
    * **Log-state partition** (orthogonal — FR-006):
      ``log-attached`` + ``log-detached`` == total agents
        - ``log-attached`` — ``log_attachments.status='active'`` row exists.
        - ``log-detached`` — no active log attachment.

    Sum of all five MAY exceed total agents (FR-006 documented overlap).

    FR-025 fallback: returns all-zero if the SQLite accessor fails.
    """
    zeros = {k: 0 for k in AGENT_STATE_KEYS}
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return zeros
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0])
        # partially_configured (Clarifications Q2): any of role/capability/label
        # missing/empty/unknown. The agents schema CHECK-constrains role and
        # capability to closed sets that include 'unknown' (no empty string
        # possible at the DB level); `label` defaults to '' and may be empty.
        partially_configured = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM agents
                WHERE role = 'unknown'
                   OR capability = 'unknown'
                   OR label = ''
                """
            ).fetchone()[0]
        )
        # active: fully configured AND on active container.
        active = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM agents a
                JOIN containers c ON c.container_id = a.container_id
                WHERE c.active = 1
                  AND a.role != 'unknown'
                  AND a.capability != 'unknown'
                  AND a.label != ''
                """
            ).fetchone()[0]
        )
        # inactive = total - active - partially_configured (strict partition).
        inactive = max(total - active - partially_configured, 0)
        # Log-state partition: orthogonal to configuration partition.
        log_attached = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM agents a
                WHERE EXISTS (
                    SELECT 1 FROM log_attachments la
                    WHERE la.agent_id = a.agent_id AND la.status = 'active'
                )
                """
            ).fetchone()[0]
        )
        log_detached = max(total - log_attached, 0)
        return {
            "active": active,
            "inactive": inactive,
            "partially_configured": partially_configured,
            "log-attached": log_attached,
            "log-detached": log_detached,
        }
    except Exception:  # noqa: BLE001 — FR-025 aggregator-failure fallback
        return zeros


# ─── Recents (FR-017) ─────────────────────────────────────────────────────


def _recent_events(ctx: "DaemonContext", limit: int) -> list[dict[str, Any]]:
    """Recent FEAT-008 ``events`` rows for the dashboard recents block.

    Column note: the FEAT-008 ``events`` table (state/schema.py) has
    ``observed_at`` (not ``created_at``) and has **no** ``origin``
    column. We map ``observed_at`` → the view model's ``created_at``
    and pass ``origin=""`` since events carry no origin attribution.
    """
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT event_id, event_type, agent_id, observed_at "
            "FROM events ORDER BY event_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [view_models.compact_event(
        {"event_id": r[0], "event_type": r[1], "origin": "",
         "agent_id": r[2], "created_at": r[3]}
    ) for r in rows]


def _recent_queue(ctx: "DaemonContext", limit: int) -> list[dict[str, Any]]:
    """Recent FEAT-009 ``message_queue`` rows for the dashboard recents.

    Column note: the FEAT-009 ``message_queue`` table (state/schema.py)
    has ``enqueued_at`` (not ``created_at``) and **no** ``origin``
    column. We map ``enqueued_at`` → the view model's ``created_at``
    and pass ``origin=""``.
    """
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT message_id, state, target_agent_id, enqueued_at "
            "FROM message_queue ORDER BY enqueued_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [view_models.compact_queue(
        {"message_id": r[0], "state": r[1], "origin": "",
         "target_agent_id": r[2], "created_at": r[3]}
    ) for r in rows]


def _recent_routes(ctx: "DaemonContext", limit: int) -> list[dict[str, Any]]:
    conn = getattr(ctx, "state_conn", None)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT route_id, enabled, created_at "
            "FROM routes ORDER BY created_at DESC, route_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [view_models.compact_route(
        {"route_id": r[0], "enabled": bool(r[1]), "created_at": r[2]}
    ) for r in rows]


# ─── Handler ──────────────────────────────────────────────────────────────


def app_dashboard(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    """Handler for ``app.dashboard`` (FR-007, FR-015..FR-018, FR-042, FR-045).

    FEAT-014 FR-027 / SC-006: end-to-end latency is measured around the
    full handler body. Exceeding ``_LATENCY_BUDGET_MS`` (500 ms) triggers
    a WARN log with the event name ``app_dashboard_latency_exceeded``
    and the actual measured latency in milliseconds; the response is
    still returned best-effort (no error envelope, no missing fields).
    """
    # FR-042 + FR-007: combined host-only + session-token gate.
    from .sessions import gate_session_required  # lazy (circular avoidance)

    # FR-027 / SC-006 latency measurement spans the full handler body
    # (after the host-only + session-token gate so we don't measure
    # rejected-call paths). Wall-clock-equivalent monotonic ms; see
    # Research §TS / §CW for the clock-source convention.
    _t0 = time.monotonic_ns()

    gate = gate_session_required(params, peer_uid)
    if isinstance(gate, dict):
        return gate
    # gate is an AppSession; app.dashboard is side-effect-free (FR-045)
    # so we don't bind it for audit attribution.

    try:
        return _app_dashboard_body(ctx, params)
    finally:
        # FR-027 budget-miss best-effort: emit a single WARN line when the
        # SC-006 latency budget is exceeded. The response is already on its
        # way to the caller; this log is purely operator-visible telemetry.
        _latency_ms = (time.monotonic_ns() - _t0) // 1_000_000
        if _latency_ms > _LATENCY_BUDGET_MS:
            _log.warning(
                "app_dashboard_latency_exceeded latency_ms=%d budget_ms=%d",
                _latency_ms,
                _LATENCY_BUDGET_MS,
            )


def _app_dashboard_body(
    ctx: "DaemonContext", params: dict[str, Any]
) -> dict[str, Any]:
    """Inner body of :func:`app_dashboard`, extracted so the latency
    measurement in the outer function can use a clean try/finally
    pattern around the entire response-assembly path."""
    if not isinstance(params, dict):
        params = {}

    recent_limit, err = _coerce_recent_limit(params.get("recent_limit"))
    if err is not None:
        return err
    assert recent_limit is not None  # narrowed by _coerce_recent_limit

    # Counts across all 7 surfaces. FR-018: read sequentially with no
    # global lock; slight inter-surface inconsistency is acceptable.
    container_counts = _container_counts(ctx)
    pane_counts = _pane_counts(ctx)
    agent_counts = _agent_counts(ctx)
    log_attachment_counts = _log_attachment_counts(ctx)
    queue_counts = _queue_counts(ctx)
    route_counts = _route_counts(ctx)
    event_total = _event_count(ctx)
    # FEAT-014 v1.1 — additive PaneState / AgentState buckets (FR-001, FR-004).
    # by_state lives alongside the v1.0 counts dicts, not replacing them.
    # FEAT-014 T024 / FR-027 test-only latency injection: integration tests
    # set the env var to force the dashboard past the SC-006 budget. No-op
    # in production (env var is never set in release builds).
    _maybe_test_only_inject_latency()
    pane_state_buckets = _compute_pane_state_buckets(ctx)
    agent_state_buckets = _compute_agent_state_buckets(ctx)

    # Hints: reuse the readiness emission helper. We probe subsystems
    # again here because the dashboard is independently callable; the
    # cost is small (FR-045 says probes are cheap and side-effect-free).
    subsystem_rows = [
        probe_docker(ctx),
        probe_tmux_discovery(ctx),
        probe_sqlite(ctx),
        probe_jsonl(ctx),
        probe_routing_worker(ctx),
        probe_log_attachment_workers(ctx),
    ]
    # FEAT-014 T024 SC-006 degraded waiver — test-only hook for forcing
    # probes into the degraded state via env var. No-op in production.
    _forced_degraded = _test_only_forced_degraded_subsystems()
    if _forced_degraded:
        subsystem_rows = [
            dataclasses.replace(
                row, status="degraded", reason="test-only forced degraded"
            )
            if row.name in _forced_degraded
            else row
            for row in subsystem_rows
        ]
    hints = emit_hints(
        ctx,
        subsystem_rows,
        container_count=container_counts["active"] + container_counts["inactive"]
        + container_counts["degraded_scan"],
        pane_count=pane_counts["total"],
        agent_count=agent_counts["total"],
        route_count_enabled=route_counts["enabled"],
        log_attachment_count=log_attachment_counts["active"],
    )

    # FEAT-014 T020 — v1.1 recommendation engine wiring. Two sub-steps:
    # (1) Build a RecommendationState from the same row sources the
    #     count helpers + readiness probes already consumed.
    # (2) Call recommendations.compute_recommendation inside a try/except
    #     boundary per FR-021 / Research §FE — on success populate both
    #     wire fields; on exception set BOTH to None (paired-null) and
    #     emit a WARN log with the stable event name. The rest of the
    #     v1.1 payload is unaffected either way.
    rec_state = recommendations.RecommendationState(
        degraded_subsystems=tuple(
            row.name for row in subsystem_rows if row.status != "ok"
        ),
        container_count=(
            container_counts["active"]
            + container_counts["inactive"]
            + container_counts["degraded_scan"]
        ),
        first_active_container_id=_first_active_container_id(ctx),
        pane_count=pane_counts["total"],
        first_unadopted_pane_id=_first_unadopted_pane_id(ctx),
        unadopted_pane_count=pane_counts["unregistered"],
        oldest_blocked_message_id=_oldest_blocked_message_id(ctx),
        blocked_queue_count=queue_counts.get("blocked", 0),
        route_count=route_counts["enabled"] + route_counts["disabled"],
    )
    rec_action: dict | None
    rec_refreshed_at: str | None
    try:
        rec = recommendations.compute_recommendation(rec_state)
        rec_action = {
            "code": rec.code,
            "title": rec.title,
            "detail": rec.detail,
            "target": rec.target,
        }
        # Wall-clock ISO-8601 UTC ms per Research §TS (NOT the monotonic
        # clock T013's skip counter uses for window arithmetic). Capture
        # `now` once so the seconds and millisecond components come from
        # the same point in time (fixes L-T020-CLOCK from the post-T020
        # analyze: a millisecond-boundary tick between two separate
        # datetime.now() calls could otherwise mismatch the components).
        _now = datetime.now(timezone.utc)
        rec_refreshed_at = (
            f"{_now.strftime('%Y-%m-%dT%H:%M:%S')}."
            f"{_now.microsecond // 1000:03d}Z"
        )
    except Exception:  # noqa: BLE001 — FR-021 / Research §FE compute-failure isolation
        _log.warning(
            "app_dashboard_recommendation_compute_failed",
            exc_info=True,
        )
        rec_action = None
        rec_refreshed_at = None

    # Recents.
    recents = {
        "events": _recent_events(ctx, recent_limit),
        "queue": _recent_queue(ctx, recent_limit),
        "routes": _recent_routes(ctx, recent_limit),
    }

    return envelope.success({
        "recommended_next_action": rec_action,
        "recommended_next_action_refreshed_at": rec_refreshed_at,
        "counts": {
            "containers": container_counts,
            # FEAT-014 v1.1 — panes and agents gain a `by_state` sub-dict
            # alongside the v1.0 fields. v1.0 readers ignore the new key;
            # v1.1 readers consume it (additive-minor per FR-014, FR-012).
            "panes": {**pane_counts, "by_state": pane_state_buckets},
            "agents": {**agent_counts, "by_state": agent_state_buckets},
            "log_attachments": log_attachment_counts,
            "events": {"total": event_total},
            "queue": queue_counts,
            # FEAT-014 T015 — v1.1 additive route-skip telemetry. v1.0
            # readers ignore the new keys (FR-012); v1.1 readers consume
            # them per FR-007 / FR-008.
            "routes": {
                **route_counts,
                "recently_skipped_count": skip_counter.count_in_window(
                    time.monotonic_ns() // 1_000_000
                ),
                "recently_skipped_window_ms": skip_counter.WINDOW_MS,
            },
        },
        "recent": recents,
        "hints": [h.to_dict() for h in hints],
    })


__all__ = [
    "app_dashboard",
]
