"""DiscoveryService: orchestrates a single FEAT-003 container scan."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..docker.adapter import DockerAdapter, DockerError, ScanResult, PerContainerError
from ..events import writer as events_writer
from ..socket_api import errors as _errors
from ..state import containers as state_containers
from .matching import MatchingRule, default_rule
from .reconcile import ReconcileWriteSet, reconcile

_MAX_TEXT = 2048


def _bound(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = "".join(ch for ch in text if ch == "\t" or ch == "\n" or ord(ch) >= 32)
    return cleaned[:_MAX_TEXT]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class DiscoveryService:
    """Owns the scan mutex, scans Docker, reconciles SQLite, emits audit events.

    The lock is in-process and recreated per daemon process (FR-035). The
    caller (one of the socket method handlers) supplies the open SQLite
    connection; the service is otherwise self-contained.
    """

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        adapter: DockerAdapter,
        rule_provider: Callable[[], MatchingRule] | None = None,
        events_file: Path | None = None,
        lifecycle_logger: Any = None,
    ) -> None:
        self._conn = connection
        self._adapter = adapter
        self._rule_provider = rule_provider or default_rule
        self._events_file = events_file
        self._lifecycle_logger = lifecycle_logger
        self._scan_mutex = threading.Lock()

    @property
    def scan_mutex(self) -> threading.Lock:
        return self._scan_mutex

    def list_containers(self, *, active_only: bool = False) -> list[state_containers.ContainerRow]:
        """Return persisted container rows without acquiring the scan mutex."""
        return state_containers.select_containers(self._conn, active_only=active_only)

    # -- Public API -----------------------------------------------------------

    def scan(self) -> ScanResult:
        """Run one container scan, serialized via the in-process mutex (FR-023)."""
        from ..config import ConfigInvalidError  # local import avoids cycles

        with self._scan_mutex:
            scan_id = str(uuid.uuid4())
            started_at = _now_iso()
            self._emit_lifecycle("scan_started", scan_id=scan_id)

            # Step 1 — load matching rule (may raise ConfigInvalidError → degraded).
            try:
                rule = self._rule_provider()
            except ConfigInvalidError as exc:
                completed_at = _now_iso()
                result = ScanResult(
                    scan_id=scan_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    status="degraded",
                    matched_count=0,
                    inactive_reconciled_count=0,
                    ignored_count=0,
                    error_code=_errors.CONFIG_INVALID,
                    error_message=_bound(exc.message),
                )
                self._persist_whole_failure(result)
                self._emit_lifecycle(
                    "scan_completed",
                    scan_id=scan_id,
                    status="degraded",
                    matched=0,
                    inactive=0,
                    ignored=0,
                    error=_errors.CONFIG_INVALID,
                )
                raise DockerError(
                    code=_errors.CONFIG_INVALID, message=_bound(exc.message)
                ) from None

            # Step 2 — list_running.
            try:
                summaries = list(self._adapter.list_running())
            except DockerError as exc:
                completed_at = _now_iso()
                result = ScanResult(
                    scan_id=scan_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    status="degraded",
                    matched_count=0,
                    inactive_reconciled_count=0,
                    ignored_count=0,
                    error_code=exc.code,
                    error_message=_bound(exc.message),
                )
                self._persist_whole_failure(result)
                self._emit_lifecycle(
                    "scan_completed",
                    scan_id=scan_id,
                    status="degraded",
                    matched=0,
                    inactive=0,
                    ignored=0,
                    error=exc.code,
                )
                raise

            # Step 3 — apply matching rule. FR-041: counters are per-scan and
            # `matched + ignored == |parseable docker ps rows|`.
            matching = [s for s in summaries if rule.matches(s.name)]
            ignored_count = len(summaries) - len(matching)
            matching_ids_in_order = [s.container_id for s in matching]
            unique_ids: list[str] = []
            seen: set[str] = set()
            for cid in matching_ids_in_order:
                if cid not in seen:
                    seen.add(cid)
                    unique_ids.append(cid)

            # Step 4 — inspect matching candidates.
            successes: dict[str, Any] = {}
            failures: list[PerContainerError] = []
            if unique_ids:
                try:
                    succ, fails = self._adapter.inspect(unique_ids)
                    successes = dict(succ)
                    failures = list(fails)
                except DockerError as exc:
                    completed_at = _now_iso()
                    result = ScanResult(
                        scan_id=scan_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="degraded",
                        matched_count=len(unique_ids),
                        inactive_reconciled_count=0,
                        ignored_count=ignored_count,
                        error_code=exc.code,
                        error_message=_bound(exc.message),
                    )
                    self._persist_whole_failure(result)
                    self._emit_lifecycle(
                        "scan_completed",
                        scan_id=scan_id,
                        status="degraded",
                        matched=len(unique_ids),
                        inactive=0,
                        ignored=ignored_count,
                        error=exc.code,
                    )
                    raise

            # Step 5 — reconcile + commit (one transaction per FR-042).
            prior_active = state_containers.select_active_container_ids(self._conn)
            prior_known = state_containers.select_known_container_ids(self._conn)
            failed_ids = [f.container_id for f in failures if f.container_id in {s.container_id for s in matching}]
            write_set = reconcile(
                matching_summaries=matching,
                successful_inspects=successes,
                failed_inspect_ids=failed_ids,
                prior_active_ids=prior_active,
                prior_known_ids=prior_known,
            )

            now_iso = _now_iso()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._apply_write_set(write_set, now_iso=now_iso)
                # Determine status + degraded details (FR-037, FR-044).
                degraded = bool(failures)
                error_code: str | None = None
                error_message: str | None = None
                error_details: list[PerContainerError] = []
                if degraded:
                    # First per-container error in docker ps order (FR-044).
                    by_id_first_failure: list[PerContainerError] = []
                    for cid in matching_ids_in_order:
                        for f in failures:
                            if f.container_id == cid and f not in by_id_first_failure:
                                by_id_first_failure.append(f)
                                break
                    error_details = by_id_first_failure
                    if error_details:
                        error_code = error_details[0].code
                        error_message = _bound(
                            f"{len(error_details)} of {len(unique_ids)} candidates failed inspect"
                        )

                completed_at = _now_iso()
                state_containers.insert_container_scan(
                    self._conn,
                    scan_id=scan_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    status="degraded" if degraded else "ok",
                    matched_count=write_set.matched_count,
                    inactive_reconciled_count=write_set.inactive_reconciled_count,
                    ignored_count=ignored_count,
                    error_code=error_code,
                    error_message=error_message,
                    error_details=[
                        {"container_id": e.container_id, "code": e.code, "message": _bound(e.message)}
                        for e in error_details
                    ]
                    if error_details
                    else None,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

            # Step 6 — degraded JSONL event after commit (FR-019, FR-043).
            if degraded:
                self._emit_jsonl_degraded(
                    scan_id=scan_id,
                    error_code=error_code,
                    error_message=error_message,
                    error_details=error_details,
                )
            self._emit_lifecycle(
                "scan_completed",
                scan_id=scan_id,
                status="degraded" if degraded else "ok",
                matched=write_set.matched_count,
                inactive=write_set.inactive_reconciled_count,
                ignored=ignored_count,
                error=error_code,
            )

            return ScanResult(
                scan_id=scan_id,
                started_at=started_at,
                completed_at=completed_at,
                status="degraded" if degraded else "ok",
                matched_count=write_set.matched_count,
                inactive_reconciled_count=write_set.inactive_reconciled_count,
                ignored_count=ignored_count,
                error_code=error_code,
                error_message=error_message,
                error_details=tuple(error_details),
            )

    # -- Internals -----------------------------------------------------------

    def _apply_write_set(self, write_set: ReconcileWriteSet, *, now_iso: str) -> None:
        for upsert in write_set.upserts:
            state_containers.upsert_container(
                self._conn,
                container_id=upsert.container_id,
                name=upsert.name,
                image=upsert.image,
                status=upsert.status,
                labels=upsert.labels,
                mounts=upsert.mounts,
                inspect=upsert.inspect,
                config_user=upsert.config_user,
                working_dir=upsert.working_dir,
                active=upsert.active,
                now_iso=now_iso,
            )
        if write_set.touch_only:
            state_containers.touch_last_scanned(
                self._conn,
                container_ids=write_set.touch_only,
                now_iso=now_iso,
            )
        if write_set.inactivate:
            state_containers.mark_inactive(
                self._conn,
                container_ids=write_set.inactivate,
                now_iso=now_iso,
            )

    def _persist_whole_failure(self, result: ScanResult) -> None:
        """Whole-scan failure path: write the scan row, append JSONL, no row writes."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            state_containers.insert_container_scan(
                self._conn,
                scan_id=result.scan_id,
                started_at=result.started_at,
                completed_at=result.completed_at,
                status=result.status,
                matched_count=result.matched_count,
                inactive_reconciled_count=result.inactive_reconciled_count,
                ignored_count=result.ignored_count,
                error_code=result.error_code,
                error_message=result.error_message,
                error_details=None,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._emit_jsonl_degraded(
            scan_id=result.scan_id,
            error_code=result.error_code,
            error_message=result.error_message,
            error_details=[],
        )

    def _emit_jsonl_degraded(
        self,
        *,
        scan_id: str,
        error_code: str | None,
        error_message: str | None,
        error_details: list[PerContainerError],
    ) -> None:
        if self._events_file is None:
            return
        try:
            events_writer.append_event(
                self._events_file,
                {
                    "type": "container_scan_degraded",
                    "payload": {
                        "scan_id": scan_id,
                        "error_code": error_code,
                        "error_message": error_message,
                        "error_details": [
                            {
                                "container_id": e.container_id,
                                "code": e.code,
                                "message": _bound(e.message),
                            }
                            for e in error_details
                        ],
                    },
                },
            )
        except OSError:
            self._emit_lifecycle("scan_jsonl_failed", scan_id=scan_id)

    def _emit_lifecycle(self, event: str, **kwargs: Any) -> None:
        if self._lifecycle_logger is None:
            return
        try:
            sanitized = {k: _bound(str(v)) if v is not None else "" for k, v in kwargs.items()}
            self._lifecycle_logger.emit(event, **sanitized)
        except Exception:
            # Lifecycle logging is best-effort; never raise from here.
            pass
