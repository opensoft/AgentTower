"""FEAT-011 US4 (T067) — one fixture per v1.0 dashboard hint code.

Story 4 ("degraded & unavailable states") requires that every closed-set
v1.0 hint, when its triggering condition holds, appears in the dashboard
output with the documented ``severity`` and ``target`` shape (FR-014a).

The closed v1.0 hint set (6 codes):

    docker_unavailable_hint   — action_required
    start_bench_container     — action_required
    check_container_filter    — reserved placeholder (not emitted at MVP)
    register_first_agent      — info
    attach_logs               — info
    enable_first_route        — info

At v1.0 no hint carries a ``target`` — every ``Hint`` is constructed
with ``target=None``, so ``Hint.to_dict()`` omits the ``target`` key.
The "correct target shape" for v1.0 is therefore **absent**; these
tests assert that explicitly so a future hint that starts carrying a
``target`` is caught.

This file drives ``emit_hints`` directly: one fixture (a tailored
``(rows, counts)`` state) per hint code so each trigger is exercised in
isolation. ``emit_hints`` is the exact helper ``app.dashboard`` calls
(``dashboard.py`` reuses it), so this is a faithful dashboard-hint test.

Self-contained: no cross-file fixture imports.
"""

from __future__ import annotations

import pytest

from agenttower.app_contract.readiness import Hint, SubsystemRow, emit_hints
from agenttower.app_contract.versioning import (
    HINT_SEVERITY_ACTION_REQUIRED,
    HINT_SEVERITY_INFO,
    SUBSYSTEM_NAMES,
    SUBSYSTEM_STATUS_OK,
    SUBSYSTEM_STATUS_UNAVAILABLE,
)


# ─── Helpers ─────────────────────────────────────────────────────────────


def _all_ok_rows() -> list[SubsystemRow]:
    """All six subsystems probing ok."""
    return [
        SubsystemRow(name=n, status=SUBSYSTEM_STATUS_OK, reason="")
        for n in SUBSYSTEM_NAMES
    ]


def _docker_unavailable_rows() -> list[SubsystemRow]:
    """Five subsystems ok, docker unavailable."""
    rows = _all_ok_rows()
    rows[0] = SubsystemRow(
        name="docker", status=SUBSYSTEM_STATUS_UNAVAILABLE, reason="unwired"
    )
    return rows


def _emit(rows, **counts) -> dict[str, Hint]:
    """Run emit_hints with sane count defaults and return {code: Hint}."""
    defaults = dict(
        container_count=0,
        pane_count=0,
        agent_count=0,
        route_count_enabled=0,
        log_attachment_count=0,
    )
    defaults.update(counts)
    hints = emit_hints(None, rows, **defaults)
    return {h.code: h for h in hints}


def _assert_v1_target_shape(hint: Hint) -> None:
    """Every v1.0 hint omits ``target`` — assert the documented shape."""
    assert hint.target is None
    assert "target" not in hint.to_dict()


# ─── docker_unavailable_hint ─────────────────────────────────────────────


def test_docker_unavailable_hint_fixture() -> None:
    """Fixture: docker subsystem unavailable → docker_unavailable_hint."""
    by_code = _emit(_docker_unavailable_rows(), container_count=0)
    assert "docker_unavailable_hint" in by_code
    hint = by_code["docker_unavailable_hint"]
    assert hint.severity == HINT_SEVERITY_ACTION_REQUIRED
    _assert_v1_target_shape(hint)


# ─── start_bench_container ───────────────────────────────────────────────


def test_start_bench_container_hint_fixture() -> None:
    """Fixture: docker ok but zero containers → start_bench_container."""
    by_code = _emit(_all_ok_rows(), container_count=0)
    assert "start_bench_container" in by_code
    hint = by_code["start_bench_container"]
    assert hint.severity == HINT_SEVERITY_ACTION_REQUIRED
    _assert_v1_target_shape(hint)
    # docker is ok here, so the docker hint must NOT also fire.
    assert "docker_unavailable_hint" not in by_code


# ─── check_container_filter (reserved placeholder) ───────────────────────


def test_check_container_filter_hint_reserved_not_emitted() -> None:
    """``check_container_filter`` is a registered v1.0 hint code but is a
    documented placeholder — MVP has no telemetry to distinguish
    "containers exist but didn't match the filter" from "no containers".
    No state ``emit_hints`` can be given triggers it; this test pins
    that intentional non-emission so a future wiring is a conscious
    change."""
    # Even with a fully-provisioned-looking system, the code never appears.
    for container_count in (0, 1, 5):
        by_code = _emit(
            _all_ok_rows(),
            container_count=container_count,
            pane_count=container_count,
            agent_count=container_count,
        )
        assert "check_container_filter" not in by_code


# ─── register_first_agent ────────────────────────────────────────────────


def test_register_first_agent_hint_fixture() -> None:
    """Fixture: containers + panes discovered but no agents registered."""
    by_code = _emit(
        _all_ok_rows(), container_count=2, pane_count=3, agent_count=0
    )
    assert "register_first_agent" in by_code
    hint = by_code["register_first_agent"]
    assert hint.severity == HINT_SEVERITY_INFO
    _assert_v1_target_shape(hint)


# ─── attach_logs ─────────────────────────────────────────────────────────


def test_attach_logs_hint_fixture() -> None:
    """Fixture: agents exist but no log attachments."""
    by_code = _emit(
        _all_ok_rows(),
        container_count=2,
        pane_count=3,
        agent_count=1,
        log_attachment_count=0,
        route_count_enabled=1,  # suppress enable_first_route noise
    )
    assert "attach_logs" in by_code
    hint = by_code["attach_logs"]
    assert hint.severity == HINT_SEVERITY_INFO
    _assert_v1_target_shape(hint)


# ─── enable_first_route ──────────────────────────────────────────────────


def test_enable_first_route_hint_fixture() -> None:
    """Fixture: agents exist but no enabled routes."""
    by_code = _emit(
        _all_ok_rows(),
        container_count=2,
        pane_count=3,
        agent_count=1,
        log_attachment_count=1,  # suppress attach_logs noise
        route_count_enabled=0,
    )
    assert "enable_first_route" in by_code
    hint = by_code["enable_first_route"]
    assert hint.severity == HINT_SEVERITY_INFO
    _assert_v1_target_shape(hint)


# ─── cross-cut: every emitted hint is v1.0-shaped ────────────────────────


@pytest.mark.parametrize(
    "rows, counts",
    [
        (_docker_unavailable_rows(), {}),
        (_all_ok_rows(), {"container_count": 0}),
        (_all_ok_rows(), {"container_count": 2, "pane_count": 3}),
        (
            _all_ok_rows(),
            {"container_count": 2, "pane_count": 3, "agent_count": 1},
        ),
    ],
)
def test_every_emitted_hint_has_v1_envelope_shape(rows, counts) -> None:
    """Every hint emitted from any state has code+severity+message and
    omits ``target`` (the v1.0 closed-set shape, FR-014a)."""
    hints = emit_hints(
        None,
        rows,
        container_count=counts.get("container_count", 0),
        pane_count=counts.get("pane_count", 0),
        agent_count=counts.get("agent_count", 0),
        route_count_enabled=counts.get("route_count_enabled", 0),
        log_attachment_count=counts.get("log_attachment_count", 0),
    )
    for hint in hints:
        d = hint.to_dict()
        assert set(d.keys()) == {"code", "severity", "message"}
        assert d["severity"] in {
            HINT_SEVERITY_INFO,
            HINT_SEVERITY_ACTION_REQUIRED,
        }
        assert isinstance(d["message"], str) and d["message"]
