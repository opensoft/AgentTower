"""Unit tests for render.py — FR-013 / FR-014 (TSV + canonical JSON)."""

from __future__ import annotations

import json

import pytest

from agenttower.config_doctor.checks import CheckResult
from agenttower.config_doctor.render import render_json, render_tsv
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


def _full_pass_report() -> DoctorReport:
    return DoctorReport(
        checks=(
            _row("socket_resolved", "pass", source="env_override", details="/tmp/sock (env_override)"),
            _row("socket_reachable", "pass", source="env_override", details="daemon_version=0.5.0 schema_version=3"),
            _row("daemon_status", "pass", source="schema_check", details="schema_version=3"),
            _row("container_identity", "pass", source="cgroup", details="unique_match: abc123 (py-bench)", sub="unique_match"),
            _row("tmux_present", "pass", source="env", details="socket=/tmp/tmux session=$0 pane=%0"),
            _row("tmux_pane_match", "pass", source="list_panes", details="pane_match: %0", sub="pane_match"),
        ),
        exit_code=0,
    )


# ---------------------------------------------------------------------------
# TSV (FR-013)
# ---------------------------------------------------------------------------


class TestRenderTsv:
    def test_six_rows_plus_summary(self):
        out = render_tsv(_full_pass_report())
        lines = out.rstrip("\n").split("\n")
        assert len(lines) == 7  # 6 checks + 1 summary
        assert lines[-1].startswith("summary\t0\t6/6 ")

    def test_tab_separated_three_columns(self):
        out = render_tsv(_full_pass_report())
        for line in out.rstrip("\n").split("\n")[:6]:
            cols = line.split("\t")
            assert len(cols) == 3

    def test_actionable_message_indented(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass", source="host_default", details="/x"),
                _row("socket_reachable", "fail", details="socket_missing", actionable="try ensure-daemon", sub="socket_missing"),
                _row("daemon_status", "info", details="daemon_unavailable", actionable="skipped", sub="daemon_unavailable"),
                _row("container_identity", "info", details="daemon_unavailable", actionable="skipped", sub="daemon_unavailable"),
                _row("tmux_present", "info", details="not_in_tmux", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", details="not_in_tmux", sub="not_in_tmux"),
            ),
            exit_code=2,
        )
        out = render_tsv(report)
        # Actionable line is indented with 4 spaces
        assert "    try ensure-daemon" in out
        assert "    skipped" in out

    def test_summary_line_format(self):
        report = _full_pass_report()
        out = render_tsv(report)
        last = out.rstrip("\n").split("\n")[-1]
        assert last == "summary\t0\t6/6 checks passed"


# ---------------------------------------------------------------------------
# JSON (FR-014, R-007)
# ---------------------------------------------------------------------------


class TestRenderJsonShape:
    def test_top_level_keys(self):
        out = json.loads(render_json(_full_pass_report()))
        assert set(out.keys()) == {"summary", "checks"}

    def test_summary_field_set_and_values(self):
        out = json.loads(render_json(_full_pass_report()))
        s = out["summary"]
        assert set(s.keys()) == {"exit_code", "total", "passed", "warned", "failed", "info"}
        assert s["exit_code"] == 0
        assert s["total"] == 6
        assert s["passed"] == 6
        assert s["warned"] == 0
        assert s["failed"] == 0
        assert s["info"] == 0

    def test_checks_keyed_by_closed_set_codes(self):
        out = json.loads(render_json(_full_pass_report()))
        assert set(out["checks"].keys()) == {
            "socket_resolved",
            "socket_reachable",
            "daemon_status",
            "container_identity",
            "tmux_present",
            "tmux_pane_match",
        }

    def test_status_tokens_closed(self):
        out = json.loads(render_json(_full_pass_report()))
        for v in out["checks"].values():
            assert v["status"] in {"pass", "warn", "fail", "info"}

    def test_optional_keys_omitted_when_none(self):
        out = json.loads(render_json(_full_pass_report()))
        # On pass rows, sub_code and actionable_message are not emitted
        for code in ("socket_resolved", "socket_reachable", "daemon_status", "tmux_present"):
            v = out["checks"][code]
            assert "actionable_message" not in v


# ---------------------------------------------------------------------------
# Q2/Q3/Q4 token-locking — `not_in_container` and `no_containers_known` MUST NOT appear
# ---------------------------------------------------------------------------


class TestDeadTokens:
    def test_not_in_container_never_emitted(self):
        out = render_json(_full_pass_report())
        assert "not_in_container" not in out

    def test_no_containers_known_never_emitted(self):
        out = render_json(_full_pass_report())
        assert "no_containers_known" not in out


# ---------------------------------------------------------------------------
# Q3 / Q4 structured qualifiers
# ---------------------------------------------------------------------------


class TestQualifiers:
    def test_cgroup_candidates_serialized_when_set(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass", source="host_default", details="/x"),
                _row("socket_reachable", "pass", source="host_default", details="ok"),
                _row("daemon_status", "pass", source="schema_check", details="ok"),
                _row(
                    "container_identity",
                    "fail",
                    details="multi_match",
                    sub="multi_match",
                    cgroup_candidates=("aaaa1111", "bbbb2222"),
                ),
                _row("tmux_present", "info", details="not_in_tmux", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", details="not_in_tmux", sub="not_in_tmux"),
            ),
            exit_code=5,
        )
        out = json.loads(render_json(report))
        assert out["checks"]["container_identity"]["cgroup_candidates"] == ["aaaa1111", "bbbb2222"]

    def test_daemon_container_set_empty_serialized_when_set(self):
        report = DoctorReport(
            checks=(
                _row("socket_resolved", "pass", source="host_default", details="/x"),
                _row("socket_reachable", "pass", source="host_default", details="ok"),
                _row("daemon_status", "pass", source="schema_check", details="ok"),
                _row(
                    "container_identity",
                    "fail",
                    details="no_match",
                    sub="no_match",
                    actionable="run scan",
                    daemon_container_set_empty=True,
                ),
                _row("tmux_present", "info", details="not_in_tmux", sub="not_in_tmux"),
                _row("tmux_pane_match", "info", details="not_in_tmux", sub="not_in_tmux"),
            ),
            exit_code=5,
        )
        out = json.loads(render_json(report))
        assert out["checks"]["container_identity"]["daemon_container_set_empty"] is True
