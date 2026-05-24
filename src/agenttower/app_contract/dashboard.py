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

from typing import TYPE_CHECKING, Any

from . import envelope, view_models
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

    FR-019 caveat: the ``dar == v1.0 counts.panes.registered`` invariant
    only holds when every registered pane is on an active container. A
    registered pane on an inactive container goes to ``inactive-or-stale``
    by the priority rule, which lowers ``dar`` below v1.0 ``registered``.
    The US1 acceptance fixture (only active containers) is consistent.
    Tracked for a future spec clarification round.
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
    """Handler for ``app.dashboard`` (FR-007, FR-015..FR-018, FR-042, FR-045)."""
    # FR-042 + FR-007: combined host-only + session-token gate.
    from .sessions import gate_session_required  # lazy (circular avoidance)

    gate = gate_session_required(params, peer_uid)
    if isinstance(gate, dict):
        return gate
    # gate is an AppSession; app.dashboard is side-effect-free (FR-045)
    # so we don't bind it for audit attribution.

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

    # Recents.
    recents = {
        "events": _recent_events(ctx, recent_limit),
        "queue": _recent_queue(ctx, recent_limit),
        "routes": _recent_routes(ctx, recent_limit),
    }

    return envelope.success({
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
            "routes": route_counts,
        },
        "recent": recents,
        "hints": [h.to_dict() for h in hints],
    })


__all__ = [
    "app_dashboard",
]
