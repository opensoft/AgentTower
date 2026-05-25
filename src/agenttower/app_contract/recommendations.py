"""FEAT-014 T019 — Recommendation engine for ``app.dashboard``.

Pure function ``compute_recommendation(state)`` that walks the FR-010
7-code precedence list top-to-bottom and returns the first match. Used
by ``app_contract/dashboard.py`` (T020) to populate
``recommended_next_action`` + ``recommended_next_action_refreshed_at``
in the v1.1 success envelope.

Public 4-symbol surface (per data-model.md §RecommendedNextAction
§Compute API + tasks.md T019 contract):

* :class:`RecommendationState` — pure input dataclass.
* :class:`RecommendedNextAction` — pure output dataclass.
* :data:`PROBE_ORDER` — alias for ``versioning.SUBSYSTEM_NAMES``.
* :func:`compute_recommendation` — non-optional return; ``all_clear`` is
  the floor that always matches when no higher-precedence condition
  fires. The compute-failure null pathway lives in the **dashboard
  handler's** try/except (T020) per FR-021 / Research §FE, NOT inside
  this function.

Precedence (FR-010, first-match wins):

1. ``subsystem_degraded`` — any subsystem is degraded.
2. ``no_containers`` — daemon sees no bench containers.
3. ``no_panes_discovered`` — containers exist but no panes.
4. ``unadopted_panes_present`` — panes exist with ≥1 unadopted.
5. ``blocked_queue_drain`` — queue has blocked rows.
6. ``no_routes_configured`` — route catalog is empty.
7. ``all_clear`` — floor.

Title / detail templates are the canonical strings from
``contracts/closed-sets-v1_1.md`` §Per-code title/detail Templates.
Integer substitution (``{N}``) happens here at compute time per the
substitution rule in that section.

Determinism (Research §CC): the function is pure (no I/O, no per-call
randomness). Two callers passing equal ``RecommendationState`` instances
receive equal ``RecommendedNextAction`` outputs. Caller-supplied list
order on ``degraded_subsystems`` is normalized internally via
:data:`PROBE_ORDER` so two callers passing differently-ordered tuples
produce the same ``target.id`` for ``subsystem_degraded``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from . import versioning


# ─── Module constants ───────────────────────────────────────────────────────

#: Re-export alias for the FEAT-011 readiness probe order (Research §SS).
#: Strictly an alias — NOT a free-floating duplicate.
PROBE_ORDER: Final[tuple[str, ...]] = versioning.SUBSYSTEM_NAMES


# ─── Public dataclasses ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationState:
    """Pure input struct for :func:`compute_recommendation`.

    All fields are keyword-only with sensible defaults so tests can
    construct sparse instances. The dashboard handler (T020) builds this
    struct from the same SQLite row sources the v1.0 count helpers use.
    """

    degraded_subsystems: tuple[str, ...] = ()
    container_count: int = 0
    first_active_container_id: str | None = None
    pane_count: int = 0
    first_unadopted_pane_id: str | None = None
    unadopted_pane_count: int = 0
    oldest_blocked_message_id: str | None = None
    blocked_queue_count: int = 0
    route_count: int = 0


@dataclass(frozen=True)
class RecommendedNextAction:
    """Pure output struct matching the FR-011 wire shape.

    ``target`` is either ``{"kind": <closed-set-str>, "id": <opaque-str>}``
    or ``None`` per data-model.md §RecommendedNextAction per-code target
    rule.
    """

    code: str
    title: str
    detail: str | None
    target: dict | None


# ─── Title / detail templates (closed-sets-v1_1.md §Per-code Templates) ────


def _subsystem_degraded_title(subsystem_name: str) -> str:
    return f"Subsystem degraded: {subsystem_name}"


def _subsystem_degraded_detail(subsystem_name: str) -> str:
    return (
        f"The {subsystem_name} subsystem is reporting degraded health. "
        "Inspect daemon readiness or the relevant subsystem before "
        "relying on other dashboard signals."
    )


_NO_CONTAINERS_TITLE: Final[str] = "No bench containers"
_NO_CONTAINERS_DETAIL: Final[str] = (
    "The daemon does not see any bench containers. Start a container "
    "(or check Docker connectivity)."
)

_NO_PANES_TITLE: Final[str] = "No panes discovered"
_NO_PANES_DETAIL: Final[str] = (
    "Containers exist but no tmux panes were discovered. Check tmux "
    "discovery health and the container's bench user."
)

_UNADOPTED_TITLE: Final[str] = "Unadopted panes need attention"


def _unadopted_detail(n: int) -> str:
    return (
        f"{n} pane(s) are discovered but not yet registered with an agent. "
        "Adopt them to enable routing."
    )


_BLOCKED_QUEUE_TITLE: Final[str] = "Blocked queue rows"


def _blocked_queue_detail(n: int) -> str:
    return (
        f"{n} queue row(s) are blocked and need operator action "
        "(approve, delay, or cancel)."
    )


_NO_ROUTES_TITLE: Final[str] = "No routes configured"
_NO_ROUTES_DETAIL: Final[str] = (
    "The route catalog is empty. Configure at least one route to enable "
    "arbitration."
)

_ALL_CLEAR_TITLE: Final[str] = "All clear"


# ─── compute_recommendation ─────────────────────────────────────────────────


def compute_recommendation(state: RecommendationState) -> RecommendedNextAction:
    """Walk the FR-010 7-code precedence list; return the first match.

    Never returns ``None`` — ``all_clear`` is the floor.
    """
    # 1. subsystem_degraded
    if state.degraded_subsystems:
        # Canonical ordering via PROBE_ORDER (Research §CC determinism +
        # Research §SS deterministic-first-by-probe-order).
        degraded_set = set(state.degraded_subsystems)
        first_probe = next(
            (probe for probe in PROBE_ORDER if probe in degraded_set),
            None,
        )
        if first_probe is None:
            # Caller passed only non-PROBE_ORDER subsystem names; emit
            # the code with target=None (Research §SS aggregate-failure
            # case). Title/detail use a generic substitution.
            return RecommendedNextAction(
                code="subsystem_degraded",
                title=_subsystem_degraded_title("unknown"),
                detail=_subsystem_degraded_detail("unknown"),
                target=None,
            )
        return RecommendedNextAction(
            code="subsystem_degraded",
            title=_subsystem_degraded_title(first_probe),
            detail=_subsystem_degraded_detail(first_probe),
            target={"kind": "subsystem", "id": first_probe},
        )

    # 2. no_containers
    if state.container_count == 0:
        return RecommendedNextAction(
            code="no_containers",
            title=_NO_CONTAINERS_TITLE,
            detail=_NO_CONTAINERS_DETAIL,
            target=None,
        )

    # 3. no_panes_discovered
    if state.pane_count == 0:
        target: dict | None
        if state.first_active_container_id is not None:
            target = {"kind": "container", "id": state.first_active_container_id}
        else:
            target = None
        return RecommendedNextAction(
            code="no_panes_discovered",
            title=_NO_PANES_TITLE,
            detail=_NO_PANES_DETAIL,
            target=target,
        )

    # 4. unadopted_panes_present
    if state.first_unadopted_pane_id is not None:
        # Use the explicit count if supplied; default to 1 (the known
        # first id) so templated prose is never "0 pane(s)".
        n = state.unadopted_pane_count if state.unadopted_pane_count > 0 else 1
        return RecommendedNextAction(
            code="unadopted_panes_present",
            title=_UNADOPTED_TITLE,
            detail=_unadopted_detail(n),
            target={"kind": "pane", "id": state.first_unadopted_pane_id},
        )

    # 5. blocked_queue_drain
    if state.oldest_blocked_message_id is not None:
        n = state.blocked_queue_count if state.blocked_queue_count > 0 else 1
        return RecommendedNextAction(
            code="blocked_queue_drain",
            title=_BLOCKED_QUEUE_TITLE,
            detail=_blocked_queue_detail(n),
            target={"kind": "message", "id": state.oldest_blocked_message_id},
        )

    # 6. no_routes_configured
    if state.route_count == 0:
        return RecommendedNextAction(
            code="no_routes_configured",
            title=_NO_ROUTES_TITLE,
            detail=_NO_ROUTES_DETAIL,
            target=None,
        )

    # 7. all_clear (floor)
    return RecommendedNextAction(
        code="all_clear",
        title=_ALL_CLEAR_TITLE,
        detail=None,
        target=None,
    )


__all__ = [
    "PROBE_ORDER",
    "RecommendationState",
    "RecommendedNextAction",
    "compute_recommendation",
]
