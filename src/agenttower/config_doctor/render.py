"""TSV and canonical JSON rendering for ``agenttower config doctor``.

FR-013: default output is one TSV row per check + a trailing ``summary`` line.
FR-014: ``--json`` emits exactly one canonical JSON object per invocation.
"""

from __future__ import annotations

import json
from typing import Any

from agenttower.config_doctor.checks import CheckResult
from agenttower.config_doctor.runner import DoctorReport


def render_tsv(report: DoctorReport) -> str:
    """Render the doctor report as TSV (FR-013).

    One row per check: ``<check>\\t<status>\\t<one-line-detail>``.
    Non-pass rows are followed by an indented ``actionable_message`` line.
    A trailing ``summary\\t<exit_code>\\t<n_pass>/<n_total> checks passed``
    line caps the output.
    """

    lines: list[str] = []
    n_pass = 0
    for row in report.checks:
        lines.append(f"{row.code}\t{row.status}\t{row.details}")
        if row.actionable_message:
            lines.append(f"    {row.actionable_message}")
        if row.status == "pass":
            n_pass += 1

    total = len(report.checks)
    lines.append(f"summary\t{report.exit_code}\t{n_pass}/{total} checks passed")
    return "\n".join(lines) + "\n"


def render_json(report: DoctorReport) -> str:
    """Render the doctor report as one canonical JSON object (FR-014)."""

    summary = _summarize(report)
    checks: dict[str, dict[str, Any]] = {}
    for row in report.checks:
        check_obj: dict[str, Any] = {
            "status": row.status,
            "details": row.details,
        }
        if row.source is not None:
            check_obj["source"] = row.source
        if row.sub_code is not None:
            check_obj["sub_code"] = row.sub_code
        if row.actionable_message is not None:
            check_obj["actionable_message"] = row.actionable_message
        if row.cgroup_candidates is not None:
            check_obj["cgroup_candidates"] = list(row.cgroup_candidates)
        if row.daemon_container_set_empty is not None:
            check_obj["daemon_container_set_empty"] = bool(row.daemon_container_set_empty)
        checks[row.code] = check_obj

    envelope = {
        "summary": summary,
        "checks": checks,
    }
    return json.dumps(envelope, ensure_ascii=False)


def _summarize(report: DoctorReport) -> dict[str, int]:
    n_pass = sum(1 for r in report.checks if r.status == "pass")
    n_warn = sum(1 for r in report.checks if r.status == "warn")
    n_fail = sum(1 for r in report.checks if r.status == "fail")
    n_info = sum(1 for r in report.checks if r.status == "info")
    return {
        "exit_code": int(report.exit_code),
        "total": len(report.checks),
        "passed": n_pass,
        "warned": n_warn,
        "failed": n_fail,
        "info": n_info,
    }


__all__ = ["render_json", "render_tsv"]
