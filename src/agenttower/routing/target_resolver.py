"""FEAT-009 ``--target`` resolver.

Per Clarifications session 2 Q2 + research §R-001: the ``--target``
argument (used by ``send-input`` and by ``queue`` filters) accepts
either an ``agent_id`` (shape ``agt_<12-hex>`` per the FEAT-006
``AGENT_ID_RE``) or a label.

Resolution algorithm:

1. If the input string matches :data:`agenttower.agents.AGENT_ID_RE`,
   look it up by ``agent_id`` against the FEAT-006 registry.
   * Match → return the :class:`AgentRecord`.
   * No match → raise :class:`TargetResolveError` with code
     ``agent_not_found`` (reused from FEAT-006 / FEAT-008 per
     Clarifications session 2 Q5).
2. Otherwise, look up by label (only_active=True so a stale
   deregistered agent doesn't shadow the current owner of a label).
   * Exactly one active match → return the :class:`AgentRecord`.
   * Zero active matches → ``agent_not_found``.
   * Two or more active matches → :class:`TargetResolveError` with
     code ``target_label_ambiguous`` (the only failure mode that
     distinguishes "you named the wrong thing" from "there are two
     possible right things"; CLI exit code 6).
"""

from __future__ import annotations

from typing import Protocol

from agenttower.agents import AGENT_ID_RE
from agenttower.routing.errors import (
    AGENT_NOT_FOUND,
    TARGET_LABEL_AMBIGUOUS,
    TargetResolveError,
)
from agenttower.state.agents import AgentRecord


__all__ = ["AgentsLookup", "resolve_target"]


class AgentsLookup(Protocol):
    """Read-only registry surface consumed by :func:`resolve_target`.

    Allows testing without instantiating the full FEAT-006
    :class:`AgentsService` and its SQLite dependency. The production
    implementation is satisfied by a thin adapter around
    ``AgentsService.list_agents`` / direct DAO reads.
    """

    def get_agent_by_id(self, agent_id: str) -> AgentRecord | None:
        """Return the :class:`AgentRecord` matching ``agent_id`` (regardless
        of active state) or ``None`` if absent.

        The resolver returns the record on hit so callers (the permission
        gate) can inspect ``active``; an inactive agent surfaces as
        ``target_not_active`` at the permissions step, not at resolution.
        """

    def find_agents_by_label(
        self,
        label: str,
        *,
        only_active: bool = True,
    ) -> list[AgentRecord]:
        """Return every :class:`AgentRecord` whose ``label`` equals
        ``label``. When ``only_active=True``, deregistered or inactive
        agents are filtered out — this is the resolver's default
        because a deregistered agent shouldn't shadow the current owner
        of a re-used label.
        """


def resolve_target(input_str: str, registry: AgentsLookup) -> AgentRecord:
    """Resolve a ``--target`` argument to an :class:`AgentRecord`.

    Args:
        input_str: The verbatim CLI / socket argument. NOT trimmed,
            normalized, or lowercased — operators get exactly what they
            type.
        registry: :class:`AgentsLookup` adapter.

    Returns:
        The resolved :class:`AgentRecord`.

    Raises:
        :class:`TargetResolveError` with:
          * ``code='agent_not_found'`` if the input is a well-formed
            agent_id that doesn't exist, OR a label that matches zero
            active agents.
          * ``code='target_label_ambiguous'`` if a label matches two or
            more active agents.

    Note: the resolver returns ``AgentRecord`` regardless of
    ``record.active``. Liveness is the permission gate's responsibility
    (FR-019 step 3 → ``target_not_active``). Mixing the two would
    conflate "you named nothing" (a CLI typo) with "you named something
    that's gone" (an operator-driven deregistration) — operator
    remediation differs.
    """
    if AGENT_ID_RE.match(input_str):
        record = registry.get_agent_by_id(input_str)
        if record is None:
            raise TargetResolveError(
                AGENT_NOT_FOUND,
                f"no agent registered with id {input_str!r}",
            )
        return record

    matches = registry.find_agents_by_label(input_str, only_active=True)
    if len(matches) == 0:
        raise TargetResolveError(
            AGENT_NOT_FOUND,
            f"no active agent with id or label {input_str!r}",
        )
    if len(matches) > 1:
        ids = ", ".join(sorted(m.agent_id for m in matches))
        raise TargetResolveError(
            TARGET_LABEL_AMBIGUOUS,
            f"label {input_str!r} matches multiple active agents: {ids}",
        )
    return matches[0]
