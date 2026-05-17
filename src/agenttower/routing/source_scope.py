"""FEAT-010 source-scope parser and match function.

Spec hooks:
- FR-001: ``source_scope_value`` shape per ``source_scope_kind``
- FR-010: per-cycle event-matching rule
- Clarifications Q1: role+capability grammar is symmetric between
  ``source_scope_kind=role`` and ``target_rule=role``

The parser handles three closed-set kinds:

* ``any`` — value MUST be NULL; matches every event regardless of source
* ``agent_id`` — value MUST be an ``agt_<12-hex>`` agent_id; matches
  events whose ``source_agent_id`` equals the value exactly
* ``role`` — value MUST parse as ``role:<role>[,capability:<cap>]``;
  matches events whose ``source_role`` equals the role AND (when
  capability is present) whose ``source_capability`` equals the
  capability

The shared :func:`parse_role_capability` helper is the single source
of truth for the ``role:<r>[,capability:<c>]`` grammar — both this
module and :mod:`agenttower.routing.target_resolver` use it (the
target side will start importing it when ``target_rule=role`` ships
in the routing worker, per Clarifications Q1 + research §R3).

All functions are pure: no SQLite, no I/O, no logging. Tested
independently of the daemon in
``tests/unit/test_routing_source_scope.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from agenttower.agents import AGENT_ID_RE
from agenttower.routing.route_errors import RouteSourceScopeInvalid


# ──────────────────────────────────────────────────────────────────────
# Closed-set tokens
# ──────────────────────────────────────────────────────────────────────


SOURCE_SCOPE_KIND_ANY: Final[str] = "any"
SOURCE_SCOPE_KIND_AGENT_ID: Final[str] = "agent_id"
SOURCE_SCOPE_KIND_ROLE: Final[str] = "role"

SOURCE_SCOPE_KINDS: Final[frozenset[str]] = frozenset(
    {SOURCE_SCOPE_KIND_ANY, SOURCE_SCOPE_KIND_AGENT_ID, SOURCE_SCOPE_KIND_ROLE}
)
"""The three closed-set ``source_scope_kind`` values from FR-001."""

# Role + capability token grammar (Clarifications Q1):
# tokens are ``[A-Za-z0-9_-]+``; ``:`` and ``,`` are reserved separators.
# See contracts/cli-routes.md §9 for the rationale.
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]+$")


# ──────────────────────────────────────────────────────────────────────
# Parsed-value dataclass
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedSourceScope:
    """The parsed shape of a ``routes.source_scope_*`` pair.

    Exactly one of ``agent_id`` / ``role`` is non-None when ``kind`` is
    ``agent_id`` / ``role`` respectively; both are None when
    ``kind='any'``. ``capability`` is non-None only when ``kind='role'``
    AND the operator supplied a capability filter.
    """

    kind: str  # one of SOURCE_SCOPE_KINDS
    agent_id: str | None = None
    role: str | None = None
    capability: str | None = None


# ──────────────────────────────────────────────────────────────────────
# Shared role+capability parser (Clarifications Q1 / research §R3)
# ──────────────────────────────────────────────────────────────────────


def parse_role_capability(raw: str) -> tuple[str, str | None]:
    """Parse ``role:<role>[,capability:<cap>]`` into ``(role, capability)``.

    Shared between :func:`parse_source_scope_value` (when
    ``kind='role'``) and :mod:`agenttower.routing.target_resolver`'s
    ``target_rule=role`` path (Clarifications Q1: one grammar, one
    parser, one validator).

    Token grammar: role and capability are ``[A-Za-z0-9_-]+``; ``:``
    and ``,`` are reserved separators that MUST NOT appear inside
    tokens (contracts/cli-routes.md §9). Whitespace is NOT permitted
    anywhere in the value.

    Args:
        raw: The verbatim value string (e.g., ``"role:slave"`` or
            ``"role:slave,capability:codex"``).

    Returns:
        ``(role, capability)`` where ``capability`` is ``None`` when
        the operator did NOT supply a capability filter.

    Raises:
        ValueError: When the input does not match the grammar. Callers
            should translate this into the domain-appropriate exception
            (:class:`RouteSourceScopeInvalid` for source-side,
            ``RouteTargetRuleInvalid`` for target-side).
    """
    if not isinstance(raw, str) or not raw:
        raise ValueError("value must be a non-empty string")

    parts = raw.split(",")
    if len(parts) > 2:
        raise ValueError(
            f"too many comma-separated parts in {raw!r}; "
            "expected role:<role> or role:<role>,capability:<cap>"
        )

    role_part = parts[0]
    if not role_part.startswith("role:"):
        raise ValueError(
            f"first part {role_part!r} must start with 'role:'"
        )
    role = role_part[len("role:"):]
    if not _TOKEN_RE.fullmatch(role):
        raise ValueError(
            f"role token {role!r} must match {_TOKEN_RE.pattern}"
        )

    capability: str | None = None
    if len(parts) == 2:
        cap_part = parts[1]
        if not cap_part.startswith("capability:"):
            raise ValueError(
                f"second part {cap_part!r} must start with 'capability:'"
            )
        capability = cap_part[len("capability:"):]
        if not _TOKEN_RE.fullmatch(capability):
            raise ValueError(
                f"capability token {capability!r} must match "
                f"{_TOKEN_RE.pattern}"
            )

    return role, capability


# ──────────────────────────────────────────────────────────────────────
# Top-level parser
# ──────────────────────────────────────────────────────────────────────


def parse_source_scope_value(
    raw: str | None, kind: str
) -> ParsedSourceScope:
    """Parse a ``(source_scope_value, source_scope_kind)`` pair.

    The shape contract per FR-001:
    - ``kind='any'`` → value MUST be ``None``; returns ParsedSourceScope
      with all optional fields ``None``.
    - ``kind='agent_id'`` → value MUST match :data:`AGENT_ID_RE`; returns
      ParsedSourceScope with ``agent_id`` populated.
    - ``kind='role'`` → value MUST parse via
      :func:`parse_role_capability`; returns ParsedSourceScope with
      ``role`` (and optionally ``capability``) populated.

    Raises:
        RouteSourceScopeInvalid: When ``kind`` is not in
            :data:`SOURCE_SCOPE_KINDS`, OR when ``raw`` violates the
            shape contract for the given kind.
    """
    if kind not in SOURCE_SCOPE_KINDS:
        raise RouteSourceScopeInvalid(
            f"source_scope_kind {kind!r} not in {sorted(SOURCE_SCOPE_KINDS)}"
        )

    if kind == SOURCE_SCOPE_KIND_ANY:
        if raw is not None:
            raise RouteSourceScopeInvalid(
                f"source_scope_kind='any' requires source_scope_value=NULL; "
                f"got {raw!r}"
            )
        return ParsedSourceScope(kind=kind)

    if raw is None or not isinstance(raw, str) or not raw:
        raise RouteSourceScopeInvalid(
            f"source_scope_kind={kind!r} requires a non-empty "
            f"source_scope_value"
        )

    if kind == SOURCE_SCOPE_KIND_AGENT_ID:
        if not AGENT_ID_RE.match(raw):
            raise RouteSourceScopeInvalid(
                f"source_scope_value {raw!r} must match agent_id "
                f"pattern {AGENT_ID_RE.pattern}"
            )
        return ParsedSourceScope(kind=kind, agent_id=raw)

    # kind == SOURCE_SCOPE_KIND_ROLE
    try:
        role, capability = parse_role_capability(raw)
    except ValueError as exc:
        raise RouteSourceScopeInvalid(
            f"source_scope_value {raw!r} (kind='role') is malformed: {exc}"
        ) from None
    return ParsedSourceScope(kind=kind, role=role, capability=capability)


# ──────────────────────────────────────────────────────────────────────
# Match function (consumed by routing worker per FR-010)
# ──────────────────────────────────────────────────────────────────────


def matches(
    parsed: ParsedSourceScope,
    *,
    event_source_agent_id: str,
    event_source_role: str,
    event_source_capability: str | None,
) -> bool:
    """Return True iff an event with the given source identity matches
    the parsed source scope (FR-010).

    Match rules:
    - ``kind='any'`` → always True
    - ``kind='agent_id'`` → True iff ``event_source_agent_id ==
      parsed.agent_id``
    - ``kind='role'`` → True iff ``event_source_role == parsed.role``
      AND (when ``parsed.capability`` is non-None) ``event_source_capability
      == parsed.capability``. Capability-absence on the route side
      means "any capability" — including ``None`` capability on the
      event side.

    Args:
        parsed: A :class:`ParsedSourceScope` from
            :func:`parse_source_scope_value`.
        event_source_agent_id: The event's source agent_id (always
            present on FEAT-008 event rows).
        event_source_role: The event's source role from the FEAT-006
            registry lookup at evaluation time.
        event_source_capability: The event's source capability, or
            ``None`` when the registry record has no capability set.
    """
    if parsed.kind == SOURCE_SCOPE_KIND_ANY:
        return True
    if parsed.kind == SOURCE_SCOPE_KIND_AGENT_ID:
        return event_source_agent_id == parsed.agent_id
    # kind == SOURCE_SCOPE_KIND_ROLE
    if event_source_role != parsed.role:
        return False
    if parsed.capability is None:
        return True  # capability-absence matches any capability
    return event_source_capability == parsed.capability
