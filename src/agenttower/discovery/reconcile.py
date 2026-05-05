"""Pure reconciliation function for FEAT-003 container scans.

Given the prior SQLite state and the result of the current scan, compute the
write set the SQLite layer must apply (in one transaction). No SQL, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..docker.adapter import InspectResult


@dataclass(frozen=True)
class ContainerUpsert:
    container_id: str
    name: str
    image: str
    status: str
    labels: dict[str, str]
    mounts: list[dict[str, Any]]
    inspect: dict[str, Any]
    config_user: str | None
    working_dir: str | None
    active: bool


@dataclass(frozen=True)
class ReconcileWriteSet:
    upserts: list[ContainerUpsert] = field(default_factory=list)
    touch_only: list[str] = field(default_factory=list)
    inactivate: list[str] = field(default_factory=list)
    matched_count: int = 0
    inactive_reconciled_count: int = 0


def _inspect_to_upsert(result: InspectResult, summary_status: str) -> ContainerUpsert:
    return ContainerUpsert(
        container_id=result.container_id,
        name=result.name or result.container_id,
        image=result.image,
        status=result.status or summary_status,
        labels=dict(result.labels),
        mounts=[
            {
                "source": m.source,
                "target": m.target,
                "type": m.type,
                "mode": m.mode,
                "rw": m.rw,
            }
            for m in result.mounts
        ],
        inspect=dict(result.inspect_blob),
        config_user=result.config_user,
        working_dir=result.working_dir,
        active=True,
    )


def reconcile(
    *,
    matching_summaries: Sequence[Any],
    successful_inspects: Mapping[str, InspectResult],
    failed_inspect_ids: Sequence[str],
    prior_active_ids: set[str],
    prior_known_ids: set[str],
) -> ReconcileWriteSet:
    """Compute the write set for a single scan.

    `matching_summaries` is the list of `ContainerSummary` objects whose names
    matched the rule (so callers can know summary-status when inspect lacked
    state info). The function returns:

    - `upserts`: full row writes for successfully-inspected matching candidates
    - `touch_only`: ids whose only change is `last_scanned_at` (FR-026 prior-record case)
    - `inactivate`: previously-active ids that are now absent from the scan
    - counters per FR-041 / FR-026
    """
    summary_status_by_id = {s.container_id: s.status for s in matching_summaries}

    upserts: list[ContainerUpsert] = []
    for cid, inspect in successful_inspects.items():
        upserts.append(_inspect_to_upsert(inspect, summary_status_by_id.get(cid, "")))

    touch_only: list[str] = []
    for cid in failed_inspect_ids:
        if cid in prior_known_ids:
            touch_only.append(cid)
        # else: no prior record → no write (FR-026)

    successful_ids = set(successful_inspects.keys())
    candidates_present = successful_ids | {c for c in failed_inspect_ids if c in prior_known_ids}
    inactivate = sorted(prior_active_ids - candidates_present)

    # FR-041: matched_count counts matching docker ps rows including failed inspects.
    matched_count = len(matching_summaries)
    inactive_reconciled_count = len(inactivate)

    return ReconcileWriteSet(
        upserts=upserts,
        touch_only=touch_only,
        inactivate=inactivate,
        matched_count=matched_count,
        inactive_reconciled_count=inactive_reconciled_count,
    )
