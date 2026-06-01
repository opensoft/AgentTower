"""FEAT-014 T016 — Unit tests for the recommendation engine.

Exercises ``agenttower.app_contract.recommendations`` (created by T019).

Maps to:

* FR-010 — fixed 7-code precedence list, evaluated top-to-bottom, first
  match wins: ``subsystem_degraded > no_containers > no_panes_discovered >
  unadopted_panes_present > blocked_queue_drain > no_routes_configured >
  all_clear``.
* FR-011 — per-code ``target`` rule (data-model.md §RecommendedNextAction).
* FR-024 — ``target.id`` opacity (no operator-readable display chars).
* SC-003 (a) — degraded subsystem wins over each of the 6 lower-priority
  conditions.
* SC-003 (b) — adjacent-pair first-match check (``no_containers`` beats
  ``no_panes_discovered``; ``unadopted_panes_present`` beats
  ``blocked_queue_drain``) — demonstrates the rule is *first-match*, not
  *top-of-list*.
* Research §SS — ``target.kind == "subsystem"`` ``target.id`` is exactly
  one of the FEAT-011 readiness-probe names, picked deterministically by
  probe order when multiple subsystems are degraded.
* Research §CC — determinism: same input → same output across calls.

Every assertion carries ``@pytest.mark.v1_1`` per the v1.1 marker rule.

Public API under test (``agenttower.app_contract.recommendations`` — see
T019; the canonical signatures live in that module's docstring +
``__all__``, this list is mirrored here for test-reader convenience):

  @dataclass(frozen=True, slots=True, kw_only=True)
  class RecommendationState:
      degraded_subsystems: tuple[str, ...] = ()
      container_count: int = 0
      first_active_container_id: str | None = None
      pane_count: int = 0
      first_unadopted_pane_id: str | None = None
      unadopted_pane_count: int = 0          # used by {N} template
      oldest_blocked_message_id: str | None = None
      blocked_queue_count: int = 0           # used by {N} template
      route_count: int = 0

  @dataclass(frozen=True, slots=True)
  class RecommendedNextAction:
      code: str
      title: str
      detail: str | None
      target: dict | None        # {"kind": str, "id": str} or None

  def compute_recommendation(state: RecommendationState) -> RecommendedNextAction:
      # Pure. Walks the 7-code precedence list; returns the first match.
      # `all_clear` is always returned as the floor when nothing else matches.

  PROBE_ORDER: tuple[str, ...]   # = versioning.SUBSYSTEM_NAMES alias.

If the production dataclass adds a field, update this mirror AND the
``recommendations`` module docstring's contract block in the same PR so
the two stay in sync (Copilot review feedback 2026-05-25 #3299740771).
"""

from __future__ import annotations

import pytest

from agenttower.app_contract.recommendations import (
    PROBE_ORDER,
    RecommendationState,
    RecommendedNextAction,
    compute_recommendation,
)


def _state(**overrides: object) -> RecommendationState:
    """Helper: build a state with defaults (everything zero / None) +
    targeted overrides."""
    return RecommendationState(**overrides)  # type: ignore[arg-type]


# ─── FR-010 fixture-per-code coverage (7 tests) ─────────────────────────────


@pytest.mark.v1_1
def test_code_subsystem_degraded() -> None:
    """Degraded subsystem present → ``subsystem_degraded`` regardless of
    every other surface state."""
    result = compute_recommendation(_state(degraded_subsystems=("docker",)))
    assert result.code == "subsystem_degraded"


@pytest.mark.v1_1
def test_code_no_containers() -> None:
    """No degraded subsystems, no containers → ``no_containers``."""
    result = compute_recommendation(_state())
    assert result.code == "no_containers"


@pytest.mark.v1_1
def test_code_no_panes_discovered() -> None:
    """At least one container, but no panes → ``no_panes_discovered``."""
    result = compute_recommendation(
        _state(container_count=1, first_active_container_id="c-1")
    )
    assert result.code == "no_panes_discovered"


@pytest.mark.v1_1
def test_code_unadopted_panes_present() -> None:
    """Panes exist with at least one unadopted → ``unadopted_panes_present``."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c-1",
            pane_count=3,
            first_unadopted_pane_id="p-1",
        )
    )
    assert result.code == "unadopted_panes_present"


@pytest.mark.v1_1
def test_code_blocked_queue_drain() -> None:
    """All panes adopted, but queue has blocked rows → ``blocked_queue_drain``."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c-1",
            pane_count=3,
            first_unadopted_pane_id=None,  # all adopted
            oldest_blocked_message_id="m-7",
        )
    )
    assert result.code == "blocked_queue_drain"


@pytest.mark.v1_1
def test_unadopted_panes_present_fires_when_count_positive_but_id_lookup_failed() -> None:
    """codex P2 #3298870848: gate on COUNT, not the id-lookup result.

    The dashboard handler builds ``RecommendationState`` from two queries:
    a count query (``_pane_counts``) AND a separate first-id query
    (``_first_unadopted_pane_id``) that can independently fail under
    FR-025 best-effort semantics. If the count succeeds (> 0) but the
    id-lookup returned ``None``, the recommendation MUST still fire
    ``unadopted_panes_present`` (with ``target=None``) — falling through
    to a lower-priority code would hide the real backlog the count just
    surfaced.
    """
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c-1",
            pane_count=3,
            first_unadopted_pane_id=None,  # id lookup failed
            unadopted_pane_count=2,        # but count says 2 unadopted
            route_count=1,                 # would otherwise be no_routes
        )
    )
    assert result.code == "unadopted_panes_present"
    assert result.target is None, (
        "id-lookup failed → emit recommendation WITHOUT target, not with "
        "a stale or fabricated target"
    )


@pytest.mark.v1_1
def test_blocked_queue_drain_fires_when_count_positive_but_id_lookup_failed() -> None:
    """codex P2 #3298870848 symmetric leg: ``blocked_queue_drain`` has the
    same gate-on-id-not-count bug as ``unadopted_panes_present``. Fix
    must be symmetric so a failed ``_oldest_blocked_message_id`` lookup
    doesn't hide a real backlog signaled by the count.
    """
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c-1",
            pane_count=3,
            first_unadopted_pane_id=None,         # all adopted
            unadopted_pane_count=0,
            oldest_blocked_message_id=None,       # id lookup failed
            blocked_queue_count=5,                # but count says 5 blocked
            route_count=1,                        # would otherwise be no_routes
        )
    )
    assert result.code == "blocked_queue_drain"
    assert result.target is None


@pytest.mark.v1_1
def test_code_no_routes_configured() -> None:
    """Containers + panes adopted + no blocked queue + no routes → ``no_routes_configured``."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c-1",
            pane_count=3,
            first_unadopted_pane_id=None,
            oldest_blocked_message_id=None,
            route_count=0,
        )
    )
    assert result.code == "no_routes_configured"


@pytest.mark.v1_1
def test_code_all_clear() -> None:
    """Healthy daemon, everything wired → ``all_clear``."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c-1",
            pane_count=3,
            first_unadopted_pane_id=None,
            oldest_blocked_message_id=None,
            route_count=2,
        )
    )
    assert result.code == "all_clear"


# ─── SC-003 (a) — degraded precedence over each lower-priority condition ────


@pytest.mark.v1_1
@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({}, id="degraded-vs-no-containers"),
        pytest.param(
            {"container_count": 1, "first_active_container_id": "c"},
            id="degraded-vs-no-panes",
        ),
        pytest.param(
            {
                "container_count": 1,
                "first_active_container_id": "c",
                "pane_count": 1,
                "first_unadopted_pane_id": "p",
            },
            id="degraded-vs-unadopted",
        ),
        pytest.param(
            {
                "container_count": 1,
                "first_active_container_id": "c",
                "pane_count": 1,
                "oldest_blocked_message_id": "m",
            },
            id="degraded-vs-blocked-queue",
        ),
        pytest.param(
            {
                "container_count": 1,
                "first_active_container_id": "c",
                "pane_count": 1,
                "route_count": 0,
            },
            id="degraded-vs-no-routes",
        ),
        pytest.param(
            {
                "container_count": 1,
                "first_active_container_id": "c",
                "pane_count": 1,
                "route_count": 5,
            },
            id="degraded-vs-all-clear",
        ),
    ],
)
def test_sc003a_subsystem_degraded_wins_over_each_lower_condition(
    extra: dict[str, object],
) -> None:
    """SC-003 (a): ``subsystem_degraded`` wins by precedence over each of the
    six other codes even when the lower-priority condition is also true."""
    result = compute_recommendation(
        _state(degraded_subsystems=("docker",), **extra)  # type: ignore[arg-type]
    )
    assert result.code == "subsystem_degraded"


# ─── SC-003 (b) — adjacent-pair first-match (not top-of-list) ──────────────


@pytest.mark.v1_1
def test_sc003b_no_containers_beats_no_panes_discovered() -> None:
    """SC-003 (b): when both ``no_containers`` and (vacuously)
    ``no_panes_discovered`` could match, the higher-precedence
    ``no_containers`` wins — demonstrates the rule is first-match top-down,
    not "always pick the first listed code"."""
    result = compute_recommendation(_state(container_count=0, pane_count=0))
    assert result.code == "no_containers"


@pytest.mark.v1_1
def test_sc003b_unadopted_panes_present_beats_blocked_queue_drain() -> None:
    """SC-003 (b): unadopted-panes wins over blocked-queue when both are true."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c-1",
            pane_count=3,
            first_unadopted_pane_id="p-1",
            oldest_blocked_message_id="m-7",  # would otherwise match blocked_queue_drain
        )
    )
    assert result.code == "unadopted_panes_present"


# ─── FR-011 — per-code target rule (data-model.md §RecommendedNextAction) ───


@pytest.mark.v1_1
def test_target_subsystem_degraded_when_attributable() -> None:
    """FR-011 + Research §SS: ``subsystem_degraded`` with an identifiable
    subsystem emits ``target = {kind: "subsystem", id: <probe-name>}``."""
    result = compute_recommendation(_state(degraded_subsystems=("tmux_discovery",)))
    assert result.target == {"kind": "subsystem", "id": "tmux_discovery"}


@pytest.mark.v1_1
def test_target_no_containers_is_null() -> None:
    """data-model.md §RecommendedNextAction: ``no_containers`` has
    ``target: null``."""
    result = compute_recommendation(_state())
    assert result.code == "no_containers"
    assert result.target is None


@pytest.mark.v1_1
def test_target_no_panes_discovered_points_at_first_active_container() -> None:
    """data-model.md: ``no_panes_discovered`` target is the first active
    container (deterministic per Research §CC)."""
    result = compute_recommendation(
        _state(container_count=2, first_active_container_id="ctr-7")
    )
    assert result.target == {"kind": "container", "id": "ctr-7"}


@pytest.mark.v1_1
def test_target_unadopted_panes_points_at_first_unadopted_pane() -> None:
    """data-model.md: ``unadopted_panes_present`` target is the first
    unadopted pane (deterministic)."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c",
            pane_count=3,
            first_unadopted_pane_id="pane-1234",
        )
    )
    assert result.target == {"kind": "pane", "id": "pane-1234"}


@pytest.mark.v1_1
def test_target_blocked_queue_points_at_oldest_blocked_message() -> None:
    """data-model.md: ``blocked_queue_drain`` target is the oldest blocked
    queue message id (deterministic)."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c",
            pane_count=1,
            oldest_blocked_message_id="msg-deadbeef",
        )
    )
    assert result.target == {"kind": "message", "id": "msg-deadbeef"}


@pytest.mark.v1_1
def test_target_no_routes_configured_is_null() -> None:
    """data-model.md: ``no_routes_configured`` has ``target: null``."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c",
            pane_count=1,
            route_count=0,
        )
    )
    assert result.code == "no_routes_configured"
    assert result.target is None


@pytest.mark.v1_1
def test_target_all_clear_is_null() -> None:
    """data-model.md: ``all_clear`` has ``target: null``."""
    result = compute_recommendation(
        _state(
            container_count=1,
            first_active_container_id="c",
            pane_count=1,
            route_count=1,
        )
    )
    assert result.code == "all_clear"
    assert result.target is None


# ─── Research §SS — subsystem target.id format + ordering ──────────────────


@pytest.mark.v1_1
def test_subsystem_target_id_matches_probe_order_on_multiple_degraded() -> None:
    """Research §SS: when multiple subsystems are degraded, ``target.id``
    is the **first one in PROBE_ORDER**. The function must NOT depend on
    the order the caller passed ``degraded_subsystems`` in."""
    # Pass them out of probe order — function should still pick the
    # first-in-PROBE_ORDER one.
    result = compute_recommendation(
        _state(degraded_subsystems=("jsonl", "docker", "tmux_discovery"))
    )
    assert result.target is not None
    assert result.target["kind"] == "subsystem"
    # PROBE_ORDER: docker, tmux_discovery, sqlite, jsonl, routing_worker, log_attachment_workers
    assert result.target["id"] == "docker"


@pytest.mark.v1_1
def test_subsystem_target_id_is_one_of_closed_set() -> None:
    """Research §SS: ``target.id`` for ``subsystem`` kind MUST be one of the
    6 FEAT-011 readiness-probe names (closed set)."""
    for probe in PROBE_ORDER:
        result = compute_recommendation(_state(degraded_subsystems=(probe,)))
        assert result.target == {"kind": "subsystem", "id": probe}


@pytest.mark.v1_1
def test_subsystem_degraded_unattributed_yields_null_target_template() -> None:
    """recommendations.py ``first_probe is None`` fall-through (Research §SS
    aggregate-failure case): when ``degraded_subsystems`` is non-empty but
    holds only names absent from ``PROBE_ORDER`` (e.g. an aggregator-caught
    failure surfaced under a synthetic name), the engine emits
    ``subsystem_degraded`` with ``target=None`` and the FIXED null-target
    template from closed-sets-v1_1.md — NOT a ``{subsystem_name}``
    substitution of the literal ``"unknown"`` (which is not a member of the
    closed set; swarm finding). Guards against a regression that raised
    ``StopIteration``, indexed ``[0]``, fabricated a target, or re-introduced
    the non-closed-set ``"unknown"`` prose."""
    result = compute_recommendation(
        _state(degraded_subsystems=("not_a_probe", "also_unknown"))
    )
    assert result.code == "subsystem_degraded"
    assert result.target is None
    assert result.title == "Subsystem health degraded"
    assert result.detail is not None
    assert "could not be attributed" in result.detail
    # Must NOT leak the non-closed-set literal "unknown" onto the wire.
    assert "unknown" not in result.title.lower()
    assert "unknown" not in result.detail.lower()


# ─── FR-024 — target.id opacity (no operator-readable display chars) ────────


@pytest.mark.v1_1
def test_fr024_target_id_has_no_display_chars_for_subsystem() -> None:
    """FR-024: ``target.id`` opacity. The subsystem probe names are closed-
    set strings without spaces, slashes, or container-label punctuation —
    they're opaque internal identifiers, never operator-display strings."""
    for probe in PROBE_ORDER:
        result = compute_recommendation(_state(degraded_subsystems=(probe,)))
        assert result.target is not None
        target_id = result.target["id"]
        assert " " not in target_id, f"{probe}: unexpected space in target.id"
        assert "/" not in target_id, f"{probe}: unexpected slash in target.id"
        assert "\\" not in target_id, f"{probe}: unexpected backslash"


# ─── Research §CC — determinism: same input → same output ──────────────────


@pytest.mark.v1_1
def test_determinism_repeated_calls_same_input_same_output() -> None:
    """Research §CC: two consecutive calls with identical state produce
    identical RecommendedNextAction objects (same code, title, detail,
    target). No per-call randomness."""
    state = _state(
        degraded_subsystems=(),
        container_count=1,
        first_active_container_id="c",
        pane_count=2,
        first_unadopted_pane_id="p-1",
    )
    a = compute_recommendation(state)
    b = compute_recommendation(state)
    assert a == b
    assert a.code == "unadopted_panes_present"
    assert a.target == {"kind": "pane", "id": "p-1"}


@pytest.mark.v1_1
def test_determinism_across_subsystem_order_variants() -> None:
    """Determinism extends to insensitivity to caller-supplied list order:
    swapping the order of ``degraded_subsystems`` does NOT change the
    resulting recommendation (PROBE_ORDER is canonical)."""
    a = compute_recommendation(
        _state(degraded_subsystems=("jsonl", "docker"))
    )
    b = compute_recommendation(
        _state(degraded_subsystems=("docker", "jsonl"))
    )
    assert a == b
    assert a.target == {"kind": "subsystem", "id": "docker"}


# ─── FR-011 wire shape — RecommendedNextAction fields ──────────────────────


@pytest.mark.v1_1
def test_return_type_is_recommended_next_action_with_required_fields() -> None:
    """FR-011: the return type carries ``code``, ``title``, ``detail``,
    ``target`` — all four fields populated (target may be None)."""
    result = compute_recommendation(_state())
    assert isinstance(result, RecommendedNextAction)
    assert isinstance(result.code, str) and result.code
    assert isinstance(result.title, str) and result.title
    assert result.detail is None or isinstance(result.detail, str)
    assert result.target is None or isinstance(result.target, dict)


# The two {N}-templated codes (unadopted_panes_present / blocked_queue_drain)
# are the ONLY ones whose title/detail length is variable, so the cap tests
# below exercise them with a large count (swarm finding).
_BIG_N = 10**9
_VARIABLE_LENGTH_STATES = (
    _state(
        container_count=1,
        first_active_container_id="c",
        pane_count=3,
        first_unadopted_pane_id="p",
        unadopted_pane_count=_BIG_N,
    ),
    _state(
        container_count=1,
        first_active_container_id="c",
        pane_count=1,
        oldest_blocked_message_id="m",
        blocked_queue_count=_BIG_N,
    ),
)


@pytest.mark.v1_1
def test_title_size_cap_128_chars() -> None:
    """FR-011: ``title`` ≤ 128 chars."""
    for state in (
        _state(),
        _state(degraded_subsystems=("docker",)),
        _state(container_count=1, first_active_container_id="c"),
        *_VARIABLE_LENGTH_STATES,
    ):
        result = compute_recommendation(state)
        assert len(result.title) <= 128


@pytest.mark.v1_1
def test_detail_size_cap_512_chars() -> None:
    """FR-011: ``detail`` ≤ 512 chars (or None)."""
    for state in (
        _state(),
        _state(degraded_subsystems=("routing_worker",)),
        _state(container_count=1, first_active_container_id="c"),
        *_VARIABLE_LENGTH_STATES,
    ):
        result = compute_recommendation(state)
        if result.detail is not None:
            assert len(result.detail) <= 512
