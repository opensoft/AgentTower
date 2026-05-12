"""T027 — FEAT-009 ``--target`` resolver tests.

Covers Research §R-001 / Clarifications session 2 Q2:

* Valid ``agent_id`` shape → resolved as agent_id.
* Anything else → resolved as label.
* Multiple active label matches → ``target_label_ambiguous``.
* Zero matches in either form → ``agent_not_found`` (reused from
  FEAT-006/008 per Clarifications session 2 Q5).
* Mixed-case agent_id input is NOT lower-cased — it's treated as a
  label (consistent with FEAT-006's case-strict ``AGENT_ID_RE``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from agenttower.routing.errors import TargetResolveError
from agenttower.routing.target_resolver import AgentsLookup, resolve_target
from agenttower.state.agents import AgentRecord


# ──────────────────────────────────────────────────────────────────────
# FakeAgentsLookup: in-memory test double satisfying the Protocol
# ──────────────────────────────────────────────────────────────────────


@dataclass
class FakeAgentsLookup:
    """In-memory :class:`AgentsLookup` test double."""

    records: list[AgentRecord]

    def get_agent_by_id(self, agent_id: str) -> AgentRecord | None:
        for r in self.records:
            if r.agent_id == agent_id:
                return r
        return None

    def find_agents_by_label(
        self,
        label: str,
        *,
        only_active: bool = True,
    ) -> list[AgentRecord]:
        return [
            r for r in self.records
            if r.label == label and (not only_active or r.active)
        ]


# ──────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────


def _make_agent(
    *,
    agent_id: str = "agt_aaaaaa111111",
    role: str = "slave",
    label: str = "worker-1",
    active: bool = True,
) -> AgentRecord:
    return AgentRecord(
        agent_id=agent_id,
        container_id="c0123456789a",
        tmux_socket_path="/tmp/tmux-1000/default",
        tmux_session_name="agenttower",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id="%0",
        role=role,
        capability="implement",
        label=label,
        project_path="/workspace/proj",
        parent_agent_id=None,
        effective_permissions={},
        created_at="2026-05-12T00:00:00.000Z",
        last_registered_at="2026-05-12T00:00:00.000Z",
        last_seen_at="2026-05-12T00:00:00.000Z",
        active=active,
    )


_SLAVE = _make_agent(agent_id="agt_aaaaaa111111", label="worker-1", active=True)
_OTHER = _make_agent(agent_id="agt_bbbbbb222222", label="worker-2", active=True)


# ──────────────────────────────────────────────────────────────────────
# agent_id resolution (rule 1)
# ──────────────────────────────────────────────────────────────────────


def test_valid_agent_id_resolves() -> None:
    lookup = FakeAgentsLookup([_SLAVE])
    assert resolve_target("agt_aaaaaa111111", lookup) is _SLAVE


def test_valid_agent_id_shape_missing_record_raises_agent_not_found() -> None:
    lookup = FakeAgentsLookup([])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("agt_aaaaaa111111", lookup)
    assert info.value.code == "agent_not_found"


def test_valid_agent_id_returns_record_even_when_inactive() -> None:
    """The resolver returns inactive records (the permission gate is
    responsible for ``target_not_active``). This separation lets the
    operator see a 'rooted at deregistered agent' surface in the queue
    listing rather than a flat 'not found'."""
    inactive = replace(_SLAVE, active=False)
    lookup = FakeAgentsLookup([inactive])
    result = resolve_target("agt_aaaaaa111111", lookup)
    assert result is inactive
    assert result.active is False


# ──────────────────────────────────────────────────────────────────────
# Label resolution (rule 2)
# ──────────────────────────────────────────────────────────────────────


def test_unique_active_label_resolves() -> None:
    lookup = FakeAgentsLookup([_SLAVE])
    assert resolve_target("worker-1", lookup) is _SLAVE


def test_label_with_zero_active_matches_raises_agent_not_found() -> None:
    lookup = FakeAgentsLookup([_SLAVE])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("ghost", lookup)
    assert info.value.code == "agent_not_found"


def test_label_with_zero_active_matches_after_filtering_raises_agent_not_found() -> None:
    """An inactive agent shares the label; resolver filters to active
    only by default, so the lookup miss is ``agent_not_found``."""
    inactive_with_label = replace(_SLAVE, active=False)
    lookup = FakeAgentsLookup([inactive_with_label])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("worker-1", lookup)
    assert info.value.code == "agent_not_found"


def test_label_with_multiple_active_matches_raises_target_label_ambiguous() -> None:
    duplicate = _make_agent(agent_id="agt_dddddd444444", label="worker-1")
    lookup = FakeAgentsLookup([_SLAVE, duplicate])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("worker-1", lookup)
    assert info.value.code == "target_label_ambiguous"
    # Error message lists both agent_ids so the operator can disambiguate.
    msg = info.value.message
    assert "agt_aaaaaa111111" in msg
    assert "agt_dddddd444444" in msg


def test_label_match_returns_the_single_active_when_inactive_shares_label() -> None:
    """If one agent with a given label is inactive and one is active,
    the resolver returns the active one (only_active=True filter)."""
    inactive_duplicate = _make_agent(
        agent_id="agt_eeeeee555555", label="worker-1", active=False
    )
    lookup = FakeAgentsLookup([_SLAVE, inactive_duplicate])
    assert resolve_target("worker-1", lookup) is _SLAVE


# ──────────────────────────────────────────────────────────────────────
# Shape discrimination edge cases
# ──────────────────────────────────────────────────────────────────────


def test_input_not_matching_agent_id_shape_falls_through_to_label() -> None:
    """``agt_xxx`` with non-hex chars doesn't match AGENT_ID_RE; treated
    as a label."""
    weird_label_agent = _make_agent(agent_id="agt_aaaaaa111111", label="agt_NOTHEX")
    lookup = FakeAgentsLookup([weird_label_agent])
    # 'agt_NOTHEX' has uppercase + 'X' (not hex) → falls to label rule.
    assert resolve_target("agt_NOTHEX", lookup) is weird_label_agent


def test_mixed_case_agent_id_is_treated_as_label_not_agent_id() -> None:
    """FEAT-006 ``AGENT_ID_RE`` is case-strict; an uppercase form is
    NOT lowercased. It falls through to label resolution, which finds
    nothing → ``agent_not_found``."""
    lookup = FakeAgentsLookup([_SLAVE])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("AGT_AAAAAA111111", lookup)
    assert info.value.code == "agent_not_found"


def test_short_string_resembling_agent_id_treated_as_label() -> None:
    """``agt_abc123`` is shorter than the 12-hex requirement → label rule."""
    lookup = FakeAgentsLookup([_SLAVE])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("agt_abc123", lookup)
    assert info.value.code == "agent_not_found"


def test_long_string_resembling_agent_id_treated_as_label() -> None:
    """``agt_abc123def4567`` is longer than 12 hex → label rule."""
    lookup = FakeAgentsLookup([_SLAVE])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("agt_abc123def4567", lookup)
    assert info.value.code == "agent_not_found"


def test_empty_string_treated_as_label_raises_agent_not_found() -> None:
    lookup = FakeAgentsLookup([_SLAVE])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("", lookup)
    assert info.value.code == "agent_not_found"


# ──────────────────────────────────────────────────────────────────────
# Multiple slaves, distinct labels
# ──────────────────────────────────────────────────────────────────────


def test_resolves_correct_agent_when_multiple_distinct_labels_exist() -> None:
    lookup = FakeAgentsLookup([_SLAVE, _OTHER])
    assert resolve_target("worker-1", lookup) is _SLAVE
    assert resolve_target("worker-2", lookup) is _OTHER


def test_resolves_correct_agent_when_multiple_agent_ids_exist() -> None:
    lookup = FakeAgentsLookup([_SLAVE, _OTHER])
    assert resolve_target("agt_aaaaaa111111", lookup) is _SLAVE
    assert resolve_target("agt_bbbbbb222222", lookup) is _OTHER


def test_three_active_with_same_label_all_listed_in_error() -> None:
    """The ``target_label_ambiguous`` message lists every conflicting
    agent_id (alphabetically) so the operator can disambiguate."""
    duplicate1 = _make_agent(agent_id="agt_dddddd444444", label="worker-1")
    duplicate2 = _make_agent(agent_id="agt_eeeeee555555", label="worker-1")
    lookup = FakeAgentsLookup([_SLAVE, duplicate1, duplicate2])
    with pytest.raises(TargetResolveError) as info:
        resolve_target("worker-1", lookup)
    msg = info.value.message
    for aid in ("agt_aaaaaa111111", "agt_dddddd444444", "agt_eeeeee555555"):
        assert aid in msg


# ──────────────────────────────────────────────────────────────────────
# Resolver does NOT trim / normalize
# ──────────────────────────────────────────────────────────────────────


def test_whitespace_in_input_not_trimmed() -> None:
    """The resolver does NOT strip whitespace. A typo with leading/
    trailing space surfaces as ``agent_not_found`` (because the label
    lookup matches exact strings)."""
    lookup = FakeAgentsLookup([_SLAVE])
    with pytest.raises(TargetResolveError) as info:
        resolve_target(" worker-1", lookup)
    assert info.value.code == "agent_not_found"
