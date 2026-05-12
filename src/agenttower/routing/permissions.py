"""FEAT-009 permission gate.

Implements the six-step enqueue precedence (FR-019 / FR-020 after
Clarifications session 2 Q3) and the three-step delivery-time
target-only re-check (FR-025 / research §R-006).

Both functions are pure — they take dataclass / boolean inputs and
return a :class:`Decision`. No I/O, no agent-registry calls. The
service layer composes them with the registry lookup, the routing
flag, the FEAT-003 container service, and the FEAT-004 pane
resolution.

Enqueue precedence (FR-019, evaluated in this fixed order):

1. Routing flag is ``enabled`` → otherwise ``kill_switch_off``.
2. Sender has role ``master`` AND is currently ``active`` → otherwise
   ``sender_role_not_permitted``.
3. Target exists in the registry AND ``active=true`` → otherwise
   ``target_not_active``. (If the target is missing entirely, the
   resolver layer raised ``agent_not_found`` BEFORE this function ran
   and no queue row was created.)
4. Target role is ``slave`` or ``swarm`` → otherwise
   ``target_role_not_permitted``.
5. Target's container is in the active set → otherwise
   ``target_container_inactive``.
6. Target's pane is resolvable via FEAT-004 → otherwise
   ``target_pane_missing``.

Delivery-time re-check (FR-025 / R-006) repeats steps 1, 3, 5, 6 —
sender liveness and sender role are NOT re-checked (the FR-025
Assumption locks authorization at enqueue time).
"""

from __future__ import annotations

from dataclasses import dataclass

from agenttower.state.agents import AgentRecord


__all__ = [
    "Decision",
    "evaluate_enqueue_permissions",
    "recheck_target_only",
]


# Closed-set role names. Mirrors FR-021 / FR-022.
_PERMITTED_SENDER_ROLES: frozenset[str] = frozenset({"master"})
_PERMITTED_TARGET_ROLES: frozenset[str] = frozenset({"slave", "swarm"})


@dataclass(frozen=True)
class Decision:
    """Outcome of a permission evaluation.

    On ``ok=True``, the caller proceeds (enqueue or pre-paste step). On
    ``ok=False``, ``block_reason`` carries the closed-set reason from
    FR-017 and the caller transitions / creates the queue row in
    ``blocked``.

    The ``block_reason`` is ``None`` iff ``ok`` is ``True``; the type
    system can't express this but tests pin it.
    """

    ok: bool
    block_reason: str | None = None

    @classmethod
    def allow(cls) -> "Decision":
        return cls(ok=True, block_reason=None)

    @classmethod
    def block(cls, reason: str) -> "Decision":
        return cls(ok=False, block_reason=reason)


def evaluate_enqueue_permissions(
    sender: AgentRecord,
    target: AgentRecord,
    *,
    routing_enabled: bool,
    target_container_active: bool,
    target_pane_resolvable: bool,
) -> Decision:
    """Evaluate the six-step FR-019 precedence at enqueue time.

    Args:
        sender: Resolved :class:`AgentRecord` for the calling pane. The
            caller (queue service / socket dispatch) guarantees the
            pane resolved to an agent — host-side callers were already
            rejected with ``sender_not_in_pane`` at the dispatch layer.
        target: Resolved :class:`AgentRecord` for the ``--target``
            argument. ``agent_not_found`` and ``target_label_ambiguous``
            were already raised by :func:`routing.target_resolver.resolve_target`
            before this function runs; if the target reached here it
            exists in the registry.
        routing_enabled: Current value of the routing flag (read via
            :class:`routing.kill_switch.RoutingFlagService`).
        target_container_active: Whether the target's container appears
            in the FEAT-003 container service's active set.
        target_pane_resolvable: Whether the target's pane can be
            resolved by FEAT-004's pane discovery against the captured
            ``target_pane_id``.

    Returns:
        :class:`Decision` — ``ok=True`` if all six steps pass;
        ``ok=False`` with the FIRST failing step's ``block_reason``
        otherwise (FR-020 precedence guarantee).
    """
    # Step 1: routing flag
    if not routing_enabled:
        return Decision.block("kill_switch_off")
    # Step 2: sender role + active
    if sender.role not in _PERMITTED_SENDER_ROLES or not sender.active:
        return Decision.block("sender_role_not_permitted")
    # Step 3: target active
    if not target.active:
        return Decision.block("target_not_active")
    # Step 4: target role
    if target.role not in _PERMITTED_TARGET_ROLES:
        return Decision.block("target_role_not_permitted")
    # Step 5: container active
    if not target_container_active:
        return Decision.block("target_container_inactive")
    # Step 6: pane resolvable
    if not target_pane_resolvable:
        return Decision.block("target_pane_missing")
    return Decision.allow()


def recheck_target_only(
    target: AgentRecord,
    *,
    routing_enabled: bool,
    target_container_active: bool,
    target_pane_resolvable: bool,
) -> Decision:
    """Evaluate the three-step FR-025 / R-006 re-check at delivery time.

    Differs from :func:`evaluate_enqueue_permissions` in that:

    * Sender role and sender liveness are NOT re-checked (FR-025
      Assumption locks authorization at enqueue time — an in-flight
      message proceeds even if the sender's role is later demoted or
      the sender goes inactive).
    * Target role is NOT re-checked at delivery time per the same
      Assumption (re-checking role would race with operator-driven
      role changes; the spec's Edge Cases section locks this).

    The four conditions evaluated in order (matching R-006):

    1. Routing flag is still ``enabled`` → otherwise ``kill_switch_off``.
    2. Target is still ``active`` → otherwise ``target_not_active``.
    3. Target's container is still active → otherwise
       ``target_container_inactive``.
    4. Target's pane is still resolvable → otherwise
       ``target_pane_missing``.
    """
    if not routing_enabled:
        return Decision.block("kill_switch_off")
    if not target.active:
        return Decision.block("target_not_active")
    if not target_container_active:
        return Decision.block("target_container_inactive")
    if not target_pane_resolvable:
        return Decision.block("target_pane_missing")
    return Decision.allow()
