"""T030 / FR-014: canonical JSON envelope contract for ``config doctor --json``.

This complements ``test_doctor_render.py`` (which exercises the rendering of
specific ``DoctorReport``s) by locking the closed-set token enumerations and
the field-presence rules across every documented sub_code spelling.

In particular this file negative-locks ``not_in_container`` and
``no_containers_known`` (Clarifications 2026-05-06) — both synonyms must
NEVER appear in ``--json`` output regardless of which code path produced the
report.
"""

from __future__ import annotations

import json

import pytest

from agenttower.config_doctor.checks import CheckResult
from agenttower.config_doctor.render import render_json
from agenttower.config_doctor.runner import DoctorReport


def _row(
    code,
    status,
    *,
    source=None,
    details="",
    actionable=None,
    sub=None,
    cgroup_candidates=None,
    daemon_container_set_empty=None,
):
    return CheckResult(
        code=code,
        status=status,
        source=source,
        details=details,
        actionable_message=actionable,
        sub_code=sub,
        cgroup_candidates=cgroup_candidates,
        daemon_container_set_empty=daemon_container_set_empty,
    )


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeTopLevel:
    def test_top_level_keys(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass", source="host_default", details="x"),
                _row("socket_reachable", "pass", source="host_default", details="x"),
                _row("daemon_status", "pass", source="schema_check", details="x"),
                _row("container_identity", "info", details="host_context", sub="host_context"),
                _row("tmux_present", "info", details="not_in_tmux", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", details="not_in_tmux", sub="not_in_tmux"),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        assert set(envelope.keys()) == {"summary", "checks"}

    def test_summary_field_keys_and_order(self):
        """FR-014: ``summary`` field order is fixed."""
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "info"),
                _row("tmux_present", "info"),
                _row("tmux_pane_match", "info"),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        keys = list(envelope["summary"].keys())
        assert keys == ["exit_code", "total", "passed", "warned", "failed", "info"]


# ---------------------------------------------------------------------------
# Closed-set check codes
# ---------------------------------------------------------------------------


class TestCheckCodesClosedSet:
    def test_check_codes_are_the_closed_six(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "pass"),
                _row("tmux_present", "pass"),
                _row("tmux_pane_match", "pass"),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        assert set(envelope["checks"].keys()) == {
            "socket_resolved",
            "socket_reachable",
            "daemon_status",
            "container_identity",
            "tmux_present",
            "tmux_pane_match",
        }


# ---------------------------------------------------------------------------
# Status tokens are stable
# ---------------------------------------------------------------------------


class TestStatusTokensStable:
    @pytest.mark.parametrize("status", ["pass", "warn", "fail", "info"])
    def test_status_token_round_trips_verbatim(self, status):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", status),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "info"),
                _row("tmux_present", "info"),
                _row("tmux_pane_match", "info"),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        assert envelope["checks"]["socket_resolved"]["status"] == status

    def test_no_other_status_tokens_emitted(self):
        """The four-token closed set is exhaustive — no synonyms allowed."""
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "info"),
                _row("tmux_present", "info"),
                _row("tmux_pane_match", "info"),
            ),
            exit_code=0,
        )
        rendered = render_json(report)
        for synonym in ("ok", "skipped", "error", "warning", "success", "failure"):
            assert f'"status": "{synonym}"' not in rendered
            assert f'"status":"{synonym}"' not in rendered


# ---------------------------------------------------------------------------
# Optional keys omitted when value is None
# ---------------------------------------------------------------------------


class TestOptionalKeysOmitted:
    def test_actionable_message_omitted_when_none(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "pass"),
                _row("tmux_present", "pass"),
                _row("tmux_pane_match", "pass"),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        for code in envelope["checks"]:
            check = envelope["checks"][code]
            assert "actionable_message" not in check
            assert "sub_code" not in check

    def test_source_present_on_pass_rows(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass", source="env_override"),
                _row("socket_reachable", "pass", source="env_override"),
                _row("daemon_status", "pass", source="schema_check"),
                _row("container_identity", "info"),
                _row("tmux_present", "info"),
                _row("tmux_pane_match", "info"),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        assert envelope["checks"]["socket_resolved"]["source"] == "env_override"
        assert envelope["checks"]["socket_reachable"]["source"] == "env_override"
        assert envelope["checks"]["daemon_status"]["source"] == "schema_check"

    def test_actionable_and_sub_code_present_on_fail_rows(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row(
                    "socket_reachable",
                    "fail",
                    sub="socket_missing",
                    actionable="run ensure-daemon",
                ),
                _row("daemon_status", "info", sub="daemon_unavailable"),
                _row("container_identity", "info", sub="daemon_unavailable"),
                _row("tmux_present", "info", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", sub="not_in_tmux"),
            ),
            exit_code=2,
        )
        envelope = json.loads(render_json(report))
        sr = envelope["checks"]["socket_reachable"]
        assert sr["sub_code"] == "socket_missing"
        assert sr["actionable_message"] == "run ensure-daemon"


# ---------------------------------------------------------------------------
# Negative locks for dead synonyms (Clarifications 2026-05-06)
# ---------------------------------------------------------------------------


class TestDeadSynonymsNeverEmitted:
    def test_not_in_container_is_dead(self):
        """``not_in_container`` is a dead synonym; only ``host_context``
        is emitted by ``container_identity``. CHK034 negative lock."""
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "info", sub="host_context"),
                _row("tmux_present", "info", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", sub="not_in_tmux"),
            ),
            exit_code=0,
        )
        rendered = render_json(report)
        assert "not_in_container" not in rendered
        assert "host_context" in rendered  # positive control

    def test_no_containers_known_is_dead(self):
        """``no_containers_known`` is a dead synonym (Clarifications 2026-05-06).
        The empty-``list_containers`` case is signalled via
        ``daemon_container_set_empty=true`` on a ``no_match`` / ``no_candidate``
        row, not via a new sub_code."""
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row(
                    "container_identity",
                    "fail",
                    sub="no_match",
                    daemon_container_set_empty=True,
                ),
                _row("tmux_present", "info", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", sub="not_in_tmux"),
            ),
            exit_code=5,
        )
        rendered = render_json(report)
        assert "no_containers_known" not in rendered
        envelope = json.loads(rendered)
        ci = envelope["checks"]["container_identity"]
        assert ci["sub_code"] == "no_match"
        assert ci["daemon_container_set_empty"] is True


# ---------------------------------------------------------------------------
# Closed-set sub_code enumerations
# ---------------------------------------------------------------------------

CONTAINER_IDENTITY_SUBCODES = (
    "unique_match",
    "host_context",
    "multi_match",
    "no_match",
    "no_candidate",
    "output_malformed",
    "daemon_unavailable",
)

TMUX_PANE_MATCH_SUBCODES = (
    "pane_match",
    "pane_unknown_to_daemon",
    "pane_ambiguous",
    "not_in_tmux",
    "daemon_unavailable",
)

SOCKET_REACHABLE_SUBCODES = (
    "socket_missing",
    "socket_not_unix",
    "connection_refused",
    "permission_denied",
    "connect_timeout",
    "protocol_error",
)


class TestSubCodeEnumerations:
    @pytest.mark.parametrize("sub", CONTAINER_IDENTITY_SUBCODES)
    def test_container_identity_sub_codes_round_trip(self, sub):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "info", sub=sub),
                _row("tmux_present", "info"),
                _row("tmux_pane_match", "info"),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        assert envelope["checks"]["container_identity"]["sub_code"] == sub

    @pytest.mark.parametrize("sub", TMUX_PANE_MATCH_SUBCODES)
    def test_tmux_pane_match_sub_codes_round_trip(self, sub):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "info"),
                _row("tmux_present", "info"),
                _row("tmux_pane_match", "info", sub=sub),
            ),
            exit_code=0,
        )
        envelope = json.loads(render_json(report))
        assert envelope["checks"]["tmux_pane_match"]["sub_code"] == sub

    @pytest.mark.parametrize("sub", SOCKET_REACHABLE_SUBCODES)
    def test_socket_reachable_sub_codes_round_trip(self, sub):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "fail", sub=sub),
                _row("daemon_status", "info", sub="daemon_unavailable"),
                _row("container_identity", "info", sub="daemon_unavailable"),
                _row("tmux_present", "info", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", sub="not_in_tmux"),
            ),
            exit_code=2,
        )
        envelope = json.loads(render_json(report))
        assert envelope["checks"]["socket_reachable"]["sub_code"] == sub


# ---------------------------------------------------------------------------
# summary.exit_code matches the DoctorReport.exit_code
# ---------------------------------------------------------------------------


class TestSummaryExitCode:
    @pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 5])
    def test_summary_exit_code_round_trips(self, exit_code):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass"),
                _row("socket_reachable", "pass"),
                _row("daemon_status", "pass"),
                _row("container_identity", "info"),
                _row("tmux_present", "info"),
                _row("tmux_pane_match", "info"),
            ),
            exit_code=exit_code,  # type: ignore[arg-type]
        )
        envelope = json.loads(render_json(report))
        assert envelope["summary"]["exit_code"] == exit_code
