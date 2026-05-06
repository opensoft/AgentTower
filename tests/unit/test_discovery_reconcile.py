"""Unit tests for the pure FEAT-003 reconciliation function."""

from __future__ import annotations

from agenttower.discovery.reconcile import reconcile
from agenttower.docker.adapter import ContainerSummary, InspectResult


def _summary(cid: str, name: str = "py-bench") -> ContainerSummary:
    return ContainerSummary(container_id=cid, name=name, image="img", status="running")


def _inspect(cid: str) -> InspectResult:
    return InspectResult(
        container_id=cid,
        name="py-bench",
        image="img",
        status="running",
        labels={},
        mounts=[],
        config_user=None,
        working_dir=None,
        env_keys=[],
        inspect_blob={"config_user": None, "working_dir": None, "env_keys": [], "full_status": "running"},
    )


def test_insert_as_active_for_new_id() -> None:
    summaries = [_summary("a")]
    successes = {"a": _inspect("a")}
    ws = reconcile(
        matching_summaries=summaries,
        successful_inspects=successes,
        failed_inspect_ids=[],
        prior_active_ids=set(),
        prior_known_ids=set(),
    )
    assert [u.container_id for u in ws.upserts] == ["a"]
    assert ws.touch_only == []
    assert ws.inactivate == []
    assert ws.matched_count == 1
    assert ws.inactive_reconciled_count == 0


def test_update_and_keep_active_for_existing_id() -> None:
    ws = reconcile(
        matching_summaries=[_summary("a")],
        successful_inspects={"a": _inspect("a")},
        failed_inspect_ids=[],
        prior_active_ids={"a"},
        prior_known_ids={"a"},
    )
    assert [u.container_id for u in ws.upserts] == ["a"]
    assert ws.upserts[0].active is True
    assert ws.inactivate == []


def test_mark_inactive_when_previously_active_disappears() -> None:
    ws = reconcile(
        matching_summaries=[],
        successful_inspects={},
        failed_inspect_ids=[],
        prior_active_ids={"a"},
        prior_known_ids={"a"},
    )
    assert ws.inactivate == ["a"]
    assert ws.inactive_reconciled_count == 1
    assert ws.matched_count == 0


def test_inspect_failure_with_prior_record_touch_only() -> None:
    ws = reconcile(
        matching_summaries=[_summary("a")],
        successful_inspects={},
        failed_inspect_ids=["a"],
        prior_active_ids={"a"},
        prior_known_ids={"a"},
    )
    assert ws.upserts == []
    assert ws.touch_only == ["a"]
    assert ws.inactivate == []  # prior-record candidate stays in candidates_present
    assert ws.matched_count == 1


def test_inspect_failure_no_prior_record_no_write() -> None:
    ws = reconcile(
        matching_summaries=[_summary("a")],
        successful_inspects={},
        failed_inspect_ids=["a"],
        prior_active_ids=set(),
        prior_known_ids=set(),
    )
    assert ws.upserts == []
    assert ws.touch_only == []
    assert ws.inactivate == []
    assert ws.matched_count == 1  # FR-041: matched counts include failed inspect


def test_fr041_sum_invariant_for_healthy_scan() -> None:
    """FR-041: matched_count + ignored_count == |parseable docker ps rows|."""
    summaries = [_summary("a"), _summary("b")]
    ignored_count = 3  # caller computed
    parseable_total = len(summaries) + ignored_count

    ws = reconcile(
        matching_summaries=summaries,
        successful_inspects={"a": _inspect("a"), "b": _inspect("b")},
        failed_inspect_ids=[],
        prior_active_ids=set(),
        prior_known_ids=set(),
    )
    assert ws.matched_count + ignored_count == parseable_total


def test_matched_count_counts_alias_expanded_rows() -> None:
    summaries = [_summary("a", "py-bench"), _summary("a", "py-bench-alias")]
    ws = reconcile(
        matching_summaries=summaries,
        successful_inspects={"a": _inspect("a")},
        failed_inspect_ids=[],
        prior_active_ids=set(),
        prior_known_ids=set(),
    )
    assert ws.matched_count == 2
    assert [u.container_id for u in ws.upserts] == ["a"]
