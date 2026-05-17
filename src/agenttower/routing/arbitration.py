"""FEAT-010 deterministic master arbitration (spec §FR-016..020).

One public function :func:`pick_master` returning an
:class:`ArbitrationResult` — either:

* :class:`MasterWon` — the arbitration winner, with the full
  :class:`AgentRecord` so the worker can use ``(agent_id, label, role,
  capability)`` as the resulting queue row's ``sender`` identity per
  FR-020.

* :class:`MasterSkip` — no winner, with one of the closed-set reason
  values from :data:`SKIP_REASONS_ARBITRATION`. The worker maps these
  to ``route_skipped(reason=...)`` per FR-018 + contracts/error-codes.md §2a.

The function is pure: no SQLite, no I/O. The caller (worker) is
responsible for taking the active-master snapshot via
``agents_service.list_active(role='master')`` at evaluation time per
FR-020 + research §R8.

Selection rules:
- ``master_rule='auto'`` → lex-lowest active master agent_id (FR-017).
  Implemented as ``sorted(active_masters, key=lambda a: a.agent_id)[0]``
  per Clarifications + tasks.md T035 — NOT ``min()`` (which uses an
  inconsistent comparison key path under some Python versions) and
  NOT a streaming-min (which is harder to reason about and to verify).
- ``master_rule='explicit'`` + active match → that master wins (FR-016).
- ``master_rule='explicit'`` + registered-but-inactive → skip with
  ``master_inactive``.
- ``master_rule='explicit'`` + no registry record → skip with
  ``master_not_found``.
- ``master_rule='auto'`` + zero active masters → skip with
  ``no_eligible_master``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable, Protocol

from agenttower.routing.route_errors import (
    MASTER_INACTIVE,
    MASTER_NOT_FOUND,
    NO_ELIGIBLE_MASTER,
    RouteMasterRuleInvalid,
)


# ──────────────────────────────────────────────────────────────────────
# Closed-set tokens
# ──────────────────────────────────────────────────────────────────────


MASTER_RULE_AUTO: Final[str] = "auto"
MASTER_RULE_EXPLICIT: Final[str] = "explicit"

MASTER_RULES: Final[frozenset[str]] = frozenset(
    {MASTER_RULE_AUTO, MASTER_RULE_EXPLICIT}
)
"""The two closed-set ``master_rule`` values from FR-007."""

SKIP_REASONS_ARBITRATION: Final[frozenset[str]] = frozenset(
    {NO_ELIGIBLE_MASTER, MASTER_INACTIVE, MASTER_NOT_FOUND}
)
"""The three arbitration-failure skip reasons emitted by :func:`pick_master`."""


# ──────────────────────────────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────────────────────────────


class _MasterCandidate(Protocol):
    """Minimal shape consumed by :func:`pick_master`.

    Production callers pass :class:`agenttower.state.agents.AgentRecord`;
    tests pass a thin dataclass. Defined as a Protocol so this module
    has no hard import of :mod:`agenttower.state` (keeps it pure-Python
    + trivially testable without spinning the registry stack).
    """

    agent_id: str
    role: str
    active: bool


@dataclass(frozen=True)
class MasterWon:
    """Arbitration produced a winner. The worker uses ``agent`` as the
    sender identity on the resulting queue row per FR-020."""

    agent: _MasterCandidate


@dataclass(frozen=True)
class MasterSkip:
    """Arbitration produced no winner. The worker emits
    ``route_skipped(reason=self.reason, winner_master_agent_id=None,
    target_agent_id=None, target_label=None)`` per Clarifications Q2
    and advances the cursor per FR-012."""

    reason: str  # one of SKIP_REASONS_ARBITRATION


ArbitrationResult = MasterWon | MasterSkip


# ──────────────────────────────────────────────────────────────────────
# Picker
# ──────────────────────────────────────────────────────────────────────


def pick_master(
    *,
    master_rule: str,
    master_value: str | None,
    active_masters: Iterable[_MasterCandidate],
) -> ArbitrationResult:
    """Resolve ``(master_rule, master_value, snapshot) → winner | skip``.

    Args:
        master_rule: ``'auto'`` or ``'explicit'`` per FR-007 +
            :data:`MASTER_RULES`.
        master_value: Required (and only meaningful) when
            ``master_rule='explicit'``; the ``agent_id`` of the explicit
            master. MUST be ``None`` when ``master_rule='auto'``.
        active_masters: Snapshot of currently-active agents with
            ``role='master'``, taken by the caller at evaluation time
            (FR-020). Order is unspecified — :func:`pick_master`
            applies its own deterministic sort.

    Returns:
        :class:`MasterWon` carrying the chosen :class:`AgentRecord`, OR
        :class:`MasterSkip` carrying one of the three arbitration
        skip reasons.

    Raises:
        RouteMasterRuleInvalid: When ``master_rule`` is not in
            :data:`MASTER_RULES`. (This is a programming/validation
            error, not a runtime skip — the routes service catches
            it at ``route add`` time.)
    """
    if master_rule not in MASTER_RULES:
        raise RouteMasterRuleInvalid(
            f"master_rule {master_rule!r} not in {sorted(MASTER_RULES)}"
        )

    # Materialize the snapshot once so we can iterate it twice.
    candidates: list[_MasterCandidate] = list(active_masters)

    if master_rule == MASTER_RULE_AUTO:
        return _pick_auto(candidates)

    # master_rule == MASTER_RULE_EXPLICIT
    if master_value is None:
        raise RouteMasterRuleInvalid(
            "master_rule='explicit' requires a non-NULL master_value"
        )
    return _pick_explicit(candidates, master_value)


def _pick_auto(
    candidates: list[_MasterCandidate],
) -> ArbitrationResult:
    """FR-017: lex-lowest active master agent_id wins.

    The caller supplies an ``active_masters`` snapshot pre-filtered to
    ``role='master' AND active=True``; this function defends in depth
    by re-checking those invariants and rejecting any candidate that
    fails.
    """
    eligible = [c for c in candidates if c.role == "master" and c.active]
    if not eligible:
        return MasterSkip(reason=NO_ELIGIBLE_MASTER)

    # T035 (tasks.md): explicit sorted-then-[0] pattern, NOT min().
    # The sort key is the bare agent_id string so ties are impossible
    # (agent_ids are UUIDv4-derived per FEAT-006 AGENT_ID_RE).
    winner = sorted(eligible, key=lambda a: a.agent_id)[0]
    return MasterWon(agent=winner)


def _pick_explicit(
    candidates: list[_MasterCandidate],
    master_value: str,
) -> ArbitrationResult:
    """FR-016: explicit master wins iff registered AND active.

    Skip reasons distinguish "the named agent exists but is not an
    active master" (``master_inactive``) from "no agent with that
    ``agent_id`` is in the registry at all" (``master_not_found``).
    The latter requires the caller to have included inactive +
    non-master agents in the snapshot — but the typical caller passes
    only the active-master subset, so we conservatively treat any
    miss as ``master_not_found``.

    Note: ``master_inactive`` is the more useful operator signal
    ("you named the right agent but it's down") but distinguishing
    it requires a registry lookup outside the snapshot. The worker
    is responsible for the secondary lookup when this returns
    ``master_not_found``; if the secondary lookup hits, the worker
    upgrades the reason to ``master_inactive`` before emitting the
    audit entry.
    """
    for candidate in candidates:
        if candidate.agent_id == master_value:
            if candidate.role == "master" and candidate.active:
                return MasterWon(agent=candidate)
            # Found but not eligible — distinguish from not_found.
            return MasterSkip(reason=MASTER_INACTIVE)
    return MasterSkip(reason=MASTER_NOT_FOUND)
