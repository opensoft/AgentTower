"""Unit tests for doctor exit-code mapping — FR-018 (incl. Q5 layering)."""

from __future__ import annotations

import pytest

from agenttower.config_doctor.checks import CheckResult
from agenttower.config_doctor.runner import DoctorReport, _compute_exit_code


def _row(code, status, *, sub=None):
    return CheckResult(
        code=code,
        status=status,
        source=None,
        details="",
        actionable_message=None,
        sub_code=sub,
    )


def _build(rows):
    return rows


# ---------------------------------------------------------------------------
# Exit 0 — every required check pass/info
# ---------------------------------------------------------------------------


class TestExitZero:
    def test_all_pass(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "pass"),
            _row("daemon_status", "pass"),
            _row("container_identity", "pass", sub="unique_match"),
            _row("tmux_present", "pass"),
            _row("tmux_pane_match", "pass", sub="pane_match"),
        )
        assert _compute_exit_code(rows) == 0

    def test_required_pass_with_info_non_required(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "pass"),
            _row("daemon_status", "pass"),
            _row("container_identity", "info", sub="host_context"),
            _row("tmux_present", "info", sub="not_in_tmux"),
            _row("tmux_pane_match", "info", sub="not_in_tmux"),
        )
        assert _compute_exit_code(rows) == 0


# ---------------------------------------------------------------------------
# Exit 2 — socket_reachable fail
# ---------------------------------------------------------------------------


class TestExitTwo:
    @pytest.mark.parametrize("kind", ["socket_missing", "connection_refused", "connect_timeout"])
    def test_socket_reachable_failure_kinds(self, kind):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "fail", sub=kind),
            _row("daemon_status", "info", sub="daemon_unavailable"),
            _row("container_identity", "info", sub="daemon_unavailable"),
            _row("tmux_present", "info", sub="not_in_tmux"),
            _row("tmux_pane_match", "info", sub="daemon_unavailable"),
        )
        assert _compute_exit_code(rows) == 2

    def test_permission_denied_also_exit_2(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "fail", sub="permission_denied"),
            _row("daemon_status", "info", sub="daemon_unavailable"),
            _row("container_identity", "info", sub="daemon_unavailable"),
            _row("tmux_present", "info", sub="not_in_tmux"),
            _row("tmux_pane_match", "info", sub="daemon_unavailable"),
        )
        assert _compute_exit_code(rows) == 2


# ---------------------------------------------------------------------------
# Exit 3 — Q5 layering: daemon_status fail with daemon_error or schema_version_newer
# ---------------------------------------------------------------------------


class TestExitThreeLayering:
    def test_daemon_error_yields_exit_3(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "pass"),
            _row("daemon_status", "fail", sub="daemon_error"),
            _row("container_identity", "info", sub="daemon_unavailable"),
            _row("tmux_present", "info", sub="not_in_tmux"),
            _row("tmux_pane_match", "info", sub="daemon_unavailable"),
        )
        assert _compute_exit_code(rows) == 3

    def test_schema_version_newer_yields_exit_3(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "pass"),
            _row("daemon_status", "fail", sub="schema_version_newer"),
            _row("container_identity", "info", sub="daemon_unavailable"),
            _row("tmux_present", "info", sub="not_in_tmux"),
            _row("tmux_pane_match", "info", sub="daemon_unavailable"),
        )
        assert _compute_exit_code(rows) == 3

    def test_schema_version_older_warn_does_not_yield_exit_3(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "pass"),
            _row("daemon_status", "warn", sub="schema_version_older"),
            _row("container_identity", "pass", sub="unique_match"),
            _row("tmux_present", "pass"),
            _row("tmux_pane_match", "pass", sub="pane_match"),
        )
        assert _compute_exit_code(rows) == 0


# ---------------------------------------------------------------------------
# Exit 5 — degraded
# ---------------------------------------------------------------------------


class TestExitFive:
    def test_pane_unknown_yields_exit_5(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "pass"),
            _row("daemon_status", "pass"),
            _row("container_identity", "pass", sub="unique_match"),
            _row("tmux_present", "pass"),
            _row("tmux_pane_match", "fail", sub="pane_unknown_to_daemon"),
        )
        assert _compute_exit_code(rows) == 5

    def test_container_no_match_yields_exit_5(self):
        rows = (
            _row("socket_resolved", "pass"),
            _row("socket_reachable", "pass"),
            _row("daemon_status", "pass"),
            _row("container_identity", "fail", sub="no_match"),
            _row("tmux_present", "pass"),
            _row("tmux_pane_match", "pass", sub="pane_match"),
        )
        assert _compute_exit_code(rows) == 5


# ---------------------------------------------------------------------------
# Exit 4 — reserved, never produced
# ---------------------------------------------------------------------------


class TestExitFourReserved:
    def test_no_combination_yields_exit_4(self):
        # We try all combinations of statuses and assert exit 4 is never returned.
        for sr in ("pass", "fail"):
            for ds in ("pass", "warn", "fail", "info"):
                for ci in ("pass", "warn", "fail", "info"):
                    for tp in ("pass", "warn", "fail", "info"):
                        for tpm in ("pass", "warn", "fail", "info"):
                            rows = (
                                _row("socket_resolved", "pass"),
                                _row("socket_reachable", sr, sub="socket_missing" if sr == "fail" else None),
                                _row("daemon_status", ds, sub="daemon_error" if ds == "fail" else None),
                                _row("container_identity", ci, sub="no_match" if ci == "fail" else None),
                                _row("tmux_present", tp),
                                _row("tmux_pane_match", tpm),
                            )
                            assert _compute_exit_code(rows) != 4
