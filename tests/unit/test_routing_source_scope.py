"""T013 — FEAT-010 source-scope parser + match-function tests.

Covers ``agenttower.routing.source_scope``:

* :func:`parse_source_scope_value` for each closed-set kind, with the
  full shape contract (NULL value for ``any``, ``agt_*`` for
  ``agent_id``, ``role:<r>[,capability:<c>]`` for ``role``).
* :func:`parse_role_capability` (the Clarifications Q1 shared helper)
  for the grammar — accepted tokens, reserved-character rejection,
  optional capability filter.
* :func:`matches` for every match-decision branch.
"""

from __future__ import annotations

import pytest

from agenttower.routing import source_scope as ss
from agenttower.routing.route_errors import RouteSourceScopeInvalid


# ──────────────────────────────────────────────────────────────────────
# parse_source_scope_value — kind='any'
# ──────────────────────────────────────────────────────────────────────


def test_parse_any_with_null_value_returns_kind_any() -> None:
    parsed = ss.parse_source_scope_value(None, "any")
    assert parsed.kind == "any"
    assert parsed.agent_id is None
    assert parsed.role is None
    assert parsed.capability is None


def test_parse_any_with_non_null_value_rejects() -> None:
    with pytest.raises(RouteSourceScopeInvalid, match="requires source_scope_value=NULL"):
        ss.parse_source_scope_value("role:slave", "any")


# ──────────────────────────────────────────────────────────────────────
# parse_source_scope_value — kind='agent_id'
# ──────────────────────────────────────────────────────────────────────


def test_parse_agent_id_with_valid_id() -> None:
    parsed = ss.parse_source_scope_value("agt_a1b2c3d4e5f6", "agent_id")
    assert parsed.kind == "agent_id"
    assert parsed.agent_id == "agt_a1b2c3d4e5f6"
    assert parsed.role is None
    assert parsed.capability is None


@pytest.mark.parametrize(
    "bad_id",
    [
        "agt_NOTHEX12345A",  # uppercase
        "agt_a1b2c3d4e5",    # too short
        "agt_a1b2c3d4e5f67",  # too long
        "AGT_a1b2c3d4e5f6",  # wrong prefix case
        "noprefix",          # no prefix
    ],
)
def test_parse_agent_id_rejects_malformed(bad_id: str) -> None:
    with pytest.raises(RouteSourceScopeInvalid, match="must match agent_id pattern"):
        ss.parse_source_scope_value(bad_id, "agent_id")


def test_parse_agent_id_rejects_empty_string() -> None:
    """Empty string is treated as a missing value (caught before regex)."""
    with pytest.raises(RouteSourceScopeInvalid, match="requires a non-empty"):
        ss.parse_source_scope_value("", "agent_id")


def test_parse_agent_id_rejects_null_value() -> None:
    with pytest.raises(RouteSourceScopeInvalid, match="requires a non-empty"):
        ss.parse_source_scope_value(None, "agent_id")


# ──────────────────────────────────────────────────────────────────────
# parse_source_scope_value — kind='role'
# ──────────────────────────────────────────────────────────────────────


def test_parse_role_only() -> None:
    parsed = ss.parse_source_scope_value("role:slave", "role")
    assert parsed.kind == "role"
    assert parsed.role == "slave"
    assert parsed.capability is None
    assert parsed.agent_id is None


def test_parse_role_with_capability() -> None:
    parsed = ss.parse_source_scope_value("role:slave,capability:codex", "role")
    assert parsed.role == "slave"
    assert parsed.capability == "codex"


def test_parse_role_accepts_hyphen_and_underscore_tokens() -> None:
    parsed = ss.parse_source_scope_value(
        "role:bench-slave,capability:claude_code", "role"
    )
    assert parsed.role == "bench-slave"
    assert parsed.capability == "claude_code"


@pytest.mark.parametrize(
    "bad_value",
    [
        "slave",                               # missing role: prefix
        "role:",                               # empty role token
        "role:slave with spaces",              # whitespace in token
        "role:slave,extra:x",                  # unknown second key
        "role:slave,capability:",              # empty capability token
        "role:slave,capability:codex,x:y",     # three parts
        "role:slave:nested",                   # nested colon in role
    ],
)
def test_parse_role_rejects_malformed(bad_value: str) -> None:
    with pytest.raises(RouteSourceScopeInvalid):
        ss.parse_source_scope_value(bad_value, "role")


def test_parse_role_rejects_null_value() -> None:
    with pytest.raises(RouteSourceScopeInvalid, match="requires a non-empty"):
        ss.parse_source_scope_value(None, "role")


# ──────────────────────────────────────────────────────────────────────
# parse_source_scope_value — unknown kind
# ──────────────────────────────────────────────────────────────────────


def test_parse_unknown_kind_rejects() -> None:
    with pytest.raises(RouteSourceScopeInvalid, match="not in"):
        ss.parse_source_scope_value(None, "tag")


# ──────────────────────────────────────────────────────────────────────
# parse_role_capability (shared helper — direct test)
# ──────────────────────────────────────────────────────────────────────


def test_parse_role_capability_returns_role_only() -> None:
    assert ss.parse_role_capability("role:swarm") == ("swarm", None)


def test_parse_role_capability_returns_role_and_cap() -> None:
    assert ss.parse_role_capability("role:slave,capability:codex") == (
        "slave",
        "codex",
    )


def test_parse_role_capability_raises_value_error_on_bad_input() -> None:
    """Shared helper raises a plain ``ValueError`` so each call site can
    wrap with its own domain-appropriate exception (per the
    docstring's contract)."""
    with pytest.raises(ValueError):
        ss.parse_role_capability("not-a-role")


# ──────────────────────────────────────────────────────────────────────
# matches — kind='any'
# ──────────────────────────────────────────────────────────────────────


def test_matches_any_returns_true_for_any_event() -> None:
    parsed = ss.parse_source_scope_value(None, "any")
    assert ss.matches(
        parsed,
        event_source_agent_id="agt_a1b2c3d4e5f6",
        event_source_role="slave",
        event_source_capability="codex",
    )


# ──────────────────────────────────────────────────────────────────────
# matches — kind='agent_id'
# ──────────────────────────────────────────────────────────────────────


def test_matches_agent_id_hit() -> None:
    parsed = ss.parse_source_scope_value("agt_a1b2c3d4e5f6", "agent_id")
    assert ss.matches(
        parsed,
        event_source_agent_id="agt_a1b2c3d4e5f6",
        event_source_role="slave",
        event_source_capability=None,
    )


def test_matches_agent_id_miss() -> None:
    parsed = ss.parse_source_scope_value("agt_a1b2c3d4e5f6", "agent_id")
    assert not ss.matches(
        parsed,
        event_source_agent_id="agt_111111111111",
        event_source_role="slave",
        event_source_capability=None,
    )


# ──────────────────────────────────────────────────────────────────────
# matches — kind='role'
# ──────────────────────────────────────────────────────────────────────


def test_matches_role_only_hits_when_role_matches() -> None:
    parsed = ss.parse_source_scope_value("role:slave", "role")
    assert ss.matches(
        parsed,
        event_source_agent_id="agt_x",
        event_source_role="slave",
        event_source_capability="anything",
    )


def test_matches_role_only_misses_when_role_differs() -> None:
    parsed = ss.parse_source_scope_value("role:slave", "role")
    assert not ss.matches(
        parsed,
        event_source_agent_id="agt_x",
        event_source_role="master",
        event_source_capability="anything",
    )


def test_matches_role_capability_hits_when_both_match() -> None:
    parsed = ss.parse_source_scope_value("role:slave,capability:codex", "role")
    assert ss.matches(
        parsed,
        event_source_agent_id="agt_x",
        event_source_role="slave",
        event_source_capability="codex",
    )


def test_matches_role_capability_misses_when_capability_differs() -> None:
    parsed = ss.parse_source_scope_value("role:slave,capability:codex", "role")
    assert not ss.matches(
        parsed,
        event_source_agent_id="agt_x",
        event_source_role="slave",
        event_source_capability="claude_code",
    )


def test_matches_role_capability_misses_when_event_has_null_capability() -> None:
    """If the route says ``capability:codex`` but the event has no
    capability, the match MUST fail — capability filter is strict
    when present on the route."""
    parsed = ss.parse_source_scope_value("role:slave,capability:codex", "role")
    assert not ss.matches(
        parsed,
        event_source_agent_id="agt_x",
        event_source_role="slave",
        event_source_capability=None,
    )


def test_matches_role_capability_absent_matches_any_capability() -> None:
    """When the route omits the capability filter, ANY capability
    (including None) on the event side matches."""
    parsed = ss.parse_source_scope_value("role:slave", "role")
    for cap in ("codex", "claude_code", "plan", None):
        assert ss.matches(
            parsed,
            event_source_agent_id="agt_x",
            event_source_role="slave",
            event_source_capability=cap,
        ), f"capability={cap!r} should match a capability-less route"
