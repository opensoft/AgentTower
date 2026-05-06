"""DiscoveryService: orchestrates a single FEAT-003 container scan."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..docker.adapter import (
    ContainerSummary,
    DockerAdapter,
    DockerError,
    InspectResult,
    PerContainerError,
    ScanResult,
)
from ..events import writer as events_writer
from ..socket_api import errors as _errors
from ..state import containers as state_containers
from .matching import MatchingRule, default_rule
from .reconcile import ReconcileWriteSet, reconcile

_MAX_TEXT = 2048


class PostCommitSideEffectError(RuntimeError):
    """Raised after SQLite commit when a required audit write fails."""


def _bound(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = "".join(ch for ch in text if ch == "\t" or ch == "\n" or ord(ch) >= 32)
    return cleaned[:_MAX_TEXT]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _unique_in_order(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _ordered_error_details(
    failures: Sequence[PerContainerError], matching_ids_in_order: Sequence[str]
) -> list[PerContainerError]:
    ordered: list[PerContainerError] = []
    for container_id in matching_ids_in_order:
        for failure in failures:
            if failure.container_id == container_id and failure not in ordered:
                ordered.append(failure)
                break
    for failure in failures:
        if failure not in ordered:
            ordered.append(failure)
    return ordered


def _partial_error_message(
    error_details: Sequence[PerContainerError], unique_ids: Sequence[str]
) -> str | None:
    if not error_details:
        return None
    return _bound(f"{len(error_details)} of {len(unique_ids)} candidates failed inspect")


def _error_details_payload(
    error_details: Sequence[PerContainerError],
) -> list[dict[str, str]] | None:
    if not error_details:
        return None
    return [
        {
            "container_id": e.container_id,
            "error_code": e.code,
            "error_message": _bound(e.message),
        }
        for e in error_details
    ]


def _read_connection_factory(conn: sqlite3.Connection) -> Callable[[], sqlite3.Connection]:
    row = conn.execute("PRAGMA database_list").fetchone()
    db_path = str(row[2]) if row is not None else ""
    if not db_path:
        raise ValueError("DiscoveryService requires a file-backed SQLite connection")
    return lambda: sqlite3.connect(db_path)


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
        list_connection_factory: Callable[[], sqlite3.Connection] | None = None,
        events_file: Path | None = None,
        lifecycle_logger: Any = None,
    ) -> None:
        self._conn = connection
        self._adapter = adapter
        self._rule_provider = rule_provider or default_rule
        self._list_connection_factory = list_connection_factory or _read_connection_factory(
            connection
        )
        self._events_file = events_file
        self._lifecycle_logger = lifecycle_logger
        self._scan_mutex = threading.Lock()

    @property
    def scan_mutex(self) -> threading.Lock:
        return self._scan_mutex

    def list_containers(self, *, active_only: bool = False) -> list[state_containers.ContainerRow]:
        """Return persisted container rows without acquiring the scan mutex."""
        conn = self._list_connection_factory()
        try:
            return state_containers.select_containers(conn, active_only=active_only)
        finally:
            conn.close()

    # -- Public API -----------------------------------------------------------

    def scan(self) -> ScanResult:
        """Run one container scan, serialized via the in-process mutex (FR-023)."""
        with self._scan_mutex:
            scan_id = str(uuid.uuid4())
            started_at = _now_iso()
            self._emit_lifecycle("scan_started", scan_id=scan_id)
            return self._scan_locked(scan_id=scan_id, started_at=started_at)

    # -- Internals -----------------------------------------------------------

    def _scan_locked(self, *, scan_id: str, started_at: str) -> ScanResult:
        rule = self._load_rule_or_fail(scan_id=scan_id, started_at=started_at)
        summaries = self._list_running_or_fail(scan_id=scan_id, started_at=started_at)
        matching = [summary for summary in summaries if rule.matches(summary.name)]
        ignored_count = len(summaries) - len(matching)
        matching_ids_in_order = [summary.container_id for summary in matching]
        unique_ids = _unique_in_order(matching_ids_in_order)
        successes, failures = self._inspect_or_fail(
            scan_id=scan_id,
            started_at=started_at,
            unique_ids=unique_ids,
            ignored_count=ignored_count,
        )
        return self._persist_reconciled_scan(
            scan_id=scan_id,
            started_at=started_at,
            matching=matching,
            matching_ids_in_order=matching_ids_in_order,
            unique_ids=unique_ids,
            successes=successes,
            failures=failures,
            ignored_count=ignored_count,
        )

    def _load_rule_or_fail(self, *, scan_id: str, started_at: str) -> MatchingRule:
        from ..config import ConfigInvalidError  # local import avoids cycles

        try:
            return self._rule_provider()
        except ConfigInvalidError as exc:
            message = _bound(exc.message)
            self._record_whole_failure(
                scan_id=scan_id,
                started_at=started_at,
                matched_count=0,
                ignored_count=0,
                code=_errors.CONFIG_INVALID,
                message=message,
            )
            raise DockerError(code=_errors.CONFIG_INVALID, message=message) from None

    def _list_running_or_fail(
        self, *, scan_id: str, started_at: str
    ) -> list[ContainerSummary]:
        try:
            return list(self._adapter.list_running())
        except DockerError as exc:
            self._record_whole_failure(
                scan_id=scan_id,
                started_at=started_at,
                matched_count=0,
                ignored_count=0,
                code=exc.code,
                message=_bound(exc.message),
            )
            raise

    def _inspect_or_fail(
        self,
        *,
        scan_id: str,
        started_at: str,
        unique_ids: Sequence[str],
        ignored_count: int,
    ) -> tuple[dict[str, InspectResult], list[PerContainerError]]:
        if not unique_ids:
            return {}, []
        try:
            successes, failures = self._adapter.inspect(unique_ids)
        except DockerError as exc:
            self._record_whole_failure(
                scan_id=scan_id,
                started_at=started_at,
                matched_count=len(unique_ids),
                ignored_count=ignored_count,
                code=exc.code,
                message=_bound(exc.message),
            )
            raise
        return dict(successes), list(failures)

    def _record_whole_failure(
        self,
        *,
        scan_id: str,
        started_at: str,
        matched_count: int,
        ignored_count: int,
        code: str,
        message: str,
    ) -> None:
        result = ScanResult(
            scan_id=scan_id,
            started_at=started_at,
            completed_at=_now_iso(),
            status="degraded",
            matched_count=matched_count,
            inactive_reconciled_count=0,
            ignored_count=ignored_count,
            error_code=code,
            error_message=message,
        )
        self._persist_whole_failure(result)
        self._emit_lifecycle(
            "scan_completed",
            scan_id=scan_id,
            status="degraded",
            matched=matched_count,
            inactive=0,
            ignored=ignored_count,
            error=code,
        )

    def _persist_reconciled_scan(
        self,
        *,
        scan_id: str,
        started_at: str,
        matching: Sequence[ContainerSummary],
        matching_ids_in_order: Sequence[str],
        unique_ids: Sequence[str],
        successes: Mapping[str, InspectResult],
        failures: Sequence[PerContainerError],
        ignored_count: int,
    ) -> ScanResult:
        write_set = self._build_write_set(matching, successes, failures)
        error_details = _ordered_error_details(failures, matching_ids_in_order)
        error_code = error_details[0].code if error_details else None
        error_message = _partial_error_message(error_details, unique_ids)
        completed_at = self._commit_reconciled_scan(
            scan_id=scan_id,
            started_at=started_at,
            write_set=write_set,
            ignored_count=ignored_count,
            error_code=error_code,
            error_message=error_message,
            error_details=error_details,
        )
        self._after_scan_commit(
            scan_id=scan_id,
            write_set=write_set,
            ignored_count=ignored_count,
            error_code=error_code,
            error_message=error_message,
            error_details=error_details,
        )
        return ScanResult(
            scan_id=scan_id,
            started_at=started_at,
            completed_at=completed_at,
            status="degraded" if error_details else "ok",
            matched_count=write_set.matched_count,
            inactive_reconciled_count=write_set.inactive_reconciled_count,
            ignored_count=ignored_count,
            error_code=error_code,
            error_message=error_message,
            error_details=tuple(error_details),
        )

    def _build_write_set(
        self,
        matching: Sequence[ContainerSummary],
        successes: Mapping[str, InspectResult],
        failures: Sequence[PerContainerError],
    ) -> ReconcileWriteSet:
        prior_active = state_containers.select_active_container_ids(self._conn)
        prior_known = state_containers.select_known_container_ids(self._conn)
        matching_ids = {summary.container_id for summary in matching}
        failed_ids = [f.container_id for f in failures if f.container_id in matching_ids]
        return reconcile(
            matching_summaries=matching,
            successful_inspects=successes,
            failed_inspect_ids=failed_ids,
            prior_active_ids=prior_active,
            prior_known_ids=prior_known,
        )

    def _commit_reconciled_scan(
        self,
        *,
        scan_id: str,
        started_at: str,
        write_set: ReconcileWriteSet,
        ignored_count: int,
        error_code: str | None,
        error_message: str | None,
        error_details: Sequence[PerContainerError],
    ) -> str:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._apply_write_set(write_set, now_iso=_now_iso())
            completed_at = _now_iso()
            state_containers.insert_container_scan(
                self._conn,
                scan_id=scan_id,
                started_at=started_at,
                completed_at=completed_at,
                status="degraded" if error_details else "ok",
                matched_count=write_set.matched_count,
                inactive_reconciled_count=write_set.inactive_reconciled_count,
                ignored_count=ignored_count,
                error_code=error_code,
                error_message=error_message,
                error_details=_error_details_payload(error_details),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return completed_at

    def _after_scan_commit(
        self,
        *,
        scan_id: str,
        write_set: ReconcileWriteSet,
        ignored_count: int,
        error_code: str | None,
        error_message: str | None,
        error_details: Sequence[PerContainerError],
    ) -> None:
        if error_details:
            self._emit_jsonl_degraded(
                scan_id=scan_id,
                error_code=error_code,
                error_message=error_message,
                error_details=list(error_details),
            )
        self._emit_lifecycle(
            "scan_completed",
            scan_id=scan_id,
            status="degraded" if error_details else "ok",
            matched=write_set.matched_count,
            inactive=write_set.inactive_reconciled_count,
            ignored=ignored_count,
            error=error_code,
        )

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
                                "error_code": e.code,
                                "error_message": _bound(e.message),
                            }
                            for e in error_details
                        ],
                    },
                },
            )
        except OSError:
            self._emit_lifecycle("scan_jsonl_failed", scan_id=scan_id)
            raise PostCommitSideEffectError(
                "container scan degraded event append failed"
            ) from None

    def _emit_lifecycle(self, event: str, **kwargs: Any) -> None:
        if self._lifecycle_logger is None:
            return
        try:
            sanitized = {k: _bound(str(v)) if v is not None else "" for k, v in kwargs.items()}
            self._lifecycle_logger.emit(event, **sanitized)
        except Exception:
            # Lifecycle logging is best-effort; never raise from here.
            pass
