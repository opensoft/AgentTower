"""PaneDiscoveryService: orchestrates one FEAT-004 pane scan.

Owns its own ``threading.Lock`` independent of the FEAT-003 container-scan
mutex (FR-017 / R-004). Enforces the FR-025 write order:

1. acquire pane-scan mutex
2. emit ``pane_scan_started`` lifecycle log line
3. load active container set + cascade set + per-container bench user
4. iterate containers: ``id -u``, socket listing, per-socket ``list-panes``
5. build the in-memory reconciliation set (pure ``reconcile`` function)
6. commit one ``BEGIN IMMEDIATE`` SQLite transaction (insert ``pane_scans``
   row + apply pane upserts/touch/inactivate)
7. append one ``pane_scan_degraded`` JSONL event when the scan is degraded
8. emit ``pane_scan_completed`` lifecycle log line
9. return the socket response

Healthy scans never write to ``events.jsonl`` (FR-025).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

try:
    import pwd as _pwd
except ImportError:  # pragma: no cover — POSIX only
    _pwd = None  # type: ignore[assignment]

from ..events import writer as events_writer
from ..socket_api import errors as _errors
from ..state import containers as state_containers
from ..state import panes as state_panes
from ..state.panes import (
    PaneCompositeKey,
    PaneReconcileWriteSet,
    PerScopeError,
)
from ..tmux import (
    FailedSocketScan,
    OkSocketScan,
    SocketScanOutcome,
    TmuxAdapter,
    TmuxError,
)
from .pane_reconcile import ContainerMeta, reconcile

_MAX_TEXT = 2048


class PostCommitSideEffectError(RuntimeError):
    """Raised after SQLite commit when a required audit write fails (R-015)."""


@dataclass(frozen=True)
class PaneScanResult:
    """Return value of :meth:`PaneDiscoveryService.scan` and ``scan_panes``."""

    scan_id: str
    started_at: str
    completed_at: str
    status: Literal["ok", "degraded"]
    containers_scanned: int
    sockets_scanned: int
    panes_seen: int
    panes_newly_active: int
    panes_reconciled_inactive: int
    containers_skipped_inactive: int
    containers_tmux_unavailable: int
    error_code: str | None
    error_message: str | None
    error_details: tuple[PerScopeError, ...] = field(default_factory=tuple)


def _bound(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = "".join(ch for ch in text if ch == "\t" or ch == "\n" or ord(ch) >= 32)
    return cleaned[:_MAX_TEXT]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _resolve_bench_user(
    config_user: str | None, env: Mapping[str, str]
) -> str | None:
    """Return the bench user for ``docker exec -u`` per FR-020.

    Order: ``containers.config_user`` (left-of-``:`` if present) → ``$USER``
    → ``pwd.getpwuid(os.getuid()).pw_name``. Returns ``None`` if all three
    paths are empty (caller raises ``bench_user_unresolved``).
    """
    if config_user:
        # Strip a `:uid` suffix if present (FR-020).
        head = config_user.split(":", 1)[0].strip()
        if head:
            return head
    user = env.get("USER")
    if user:
        return user
    if _pwd is not None:
        try:
            return _pwd.getpwuid(os.getuid()).pw_name or None
        except KeyError:
            return None
    return None


@dataclass
class _ContainerScanState:
    """Per-container working state inside one scan."""

    container_id: str
    container_name: str
    bench_user: str | None
    container_user_label: str
    is_inactive_cascade: bool = False
    sockets_scanned: int = 0
    failures: list[PerScopeError] = field(default_factory=list)
    socket_outcomes: dict[tuple[str, str], SocketScanOutcome] = field(default_factory=dict)
    tmux_unavailable: bool = False


class PaneDiscoveryService:
    """Owns the pane-scan mutex; runs scan-then-reconcile per FR-025."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        adapter: TmuxAdapter,
        list_connection_factory: Callable[[], sqlite3.Connection] | None = None,
        events_file: Path | None = None,
        lifecycle_logger: Any = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._conn = connection
        self._adapter = adapter
        self._list_connection_factory = list_connection_factory or self._default_list_factory
        self._events_file = events_file
        self._lifecycle_logger = lifecycle_logger
        self._env: dict[str, str] = dict(env if env is not None else os.environ)
        self._scan_mutex = threading.Lock()

    @property
    def scan_mutex(self) -> threading.Lock:
        return self._scan_mutex

    def _default_list_factory(self) -> sqlite3.Connection:
        row = self._conn.execute("PRAGMA database_list").fetchone()
        db_path = str(row[2]) if row is not None else ""
        if not db_path:
            raise ValueError("PaneDiscoveryService requires a file-backed SQLite connection")
        return sqlite3.connect(db_path)

    # -- list_panes (read-only; no mutex; no Docker; no tmux) -----------------

    def list_panes(
        self,
        *,
        active_only: bool = False,
        container_filter: str | None = None,
    ) -> list[state_panes.PaneRow]:
        conn = self._list_connection_factory()
        try:
            return state_panes.select_panes_for_listing(
                conn, active_only=active_only, container_filter=container_filter
            )
        finally:
            conn.close()

    # -- scan_panes (acquires mutex; runs subprocess + reconcile + commit) ----

    def scan(self) -> PaneScanResult:
        """Run one pane scan, serialized via the in-process pane mutex (FR-017)."""
        with self._scan_mutex:
            scan_id = str(uuid.uuid4())
            started_at = _now_iso()
            try:
                self._emit_lifecycle_strict(
                    "pane_scan_started", scan_id=scan_id
                )
            except Exception as exc:  # FR-025 pre-commit lifecycle failure.
                raise TmuxError(
                    code=_errors.INTERNAL_ERROR,
                    message=_bound(f"pane_scan_started emit failed: {exc}"),
                ) from exc
            try:
                return self._scan_locked(scan_id=scan_id, started_at=started_at)
            except TmuxError as exc:
                if exc.code == _errors.DOCKER_UNAVAILABLE:
                    self._handle_docker_unavailable(
                        scan_id=scan_id, started_at=started_at, message=exc.message
                    )
                raise

    # -- Internals ------------------------------------------------------------

    def _scan_locked(self, *, scan_id: str, started_at: str) -> PaneScanResult:
        active_rows = state_containers.select_active_containers_with_user(self._conn)
        cascade_ids = state_containers.select_inactive_container_ids_with_panes(self._conn)
        prior_panes = state_panes.select_all_panes(self._conn)

        per_container: list[_ContainerScanState] = []
        socket_results: dict[tuple[str, str], SocketScanOutcome] = {}
        tmux_unavailable: set[str] = set()
        all_failures: list[PerScopeError] = []
        containers_scanned = 0
        sockets_scanned = 0
        container_metadata: dict[str, ContainerMeta] = {}

        for container_id, name, config_user in active_rows:
            bench_user = _resolve_bench_user(config_user, self._env)
            if not bench_user:
                err = PerScopeError(
                    container_id=container_id,
                    tmux_socket_path=None,
                    error_code=_errors.BENCH_USER_UNRESOLVED,
                    error_message=_bound("bench user resolution returned empty"),
                )
                all_failures.append(err)
                tmux_unavailable.add(container_id)
                container_metadata[container_id] = ContainerMeta(
                    container_name=name, container_user=""
                )
                continue
            container_metadata[container_id] = ContainerMeta(
                container_name=name, container_user=bench_user
            )
            state = self._scan_one_container(
                container_id=container_id,
                container_name=name,
                bench_user=bench_user,
            )
            containers_scanned += 1
            sockets_scanned += state.sockets_scanned
            socket_results.update(state.socket_outcomes)
            all_failures.extend(state.failures)
            if state.tmux_unavailable:
                tmux_unavailable.add(container_id)

        write_set = reconcile(
            prior_panes=prior_panes,
            socket_results=socket_results,
            tmux_unavailable_containers=tmux_unavailable,
            inactive_cascade_containers=cascade_ids,
            container_metadata=container_metadata,
            now_iso=started_at,
        )

        # Truncation notes attach to the per-(container, socket) where the
        # truncated pane lives. Group them by composite scope.
        truncation_index = self._index_truncations(write_set, socket_results)

        error_details = self._merge_error_details(all_failures, truncation_index)
        truncated_any = any(notes for notes in truncation_index.values())
        status = (
            "degraded"
            if all_failures or truncated_any
            else "ok"
        )
        error_code = error_details[0].error_code if error_details else None
        error_message = self._partial_error_message(error_details, all_failures)

        completed_at = self._commit_scan(
            scan_id=scan_id,
            started_at=started_at,
            status=status,
            write_set=write_set,
            containers_scanned=containers_scanned,
            sockets_scanned=sockets_scanned,
            error_code=error_code,
            error_message=error_message,
            error_details=error_details,
        )

        if status == "degraded":
            self._emit_jsonl_degraded(
                scan_id=scan_id,
                error_code=error_code,
                error_message=error_message,
                error_details=error_details,
            )
        try:
            self._emit_lifecycle_strict(
                "pane_scan_completed",
                scan_id=scan_id,
                status=status,
                containers=containers_scanned,
                sockets=sockets_scanned,
                panes_seen=write_set.panes_seen,
                newly_active=write_set.panes_newly_active,
                inactivated=write_set.panes_reconciled_inactive,
                skipped_inactive=write_set.containers_skipped_inactive,
                tmux_unavailable=write_set.containers_tmux_unavailable,
                error=error_code or "",
            )
        except Exception as exc:
            # Post-commit lifecycle failure (FR-025 / R-015): SQLite row
            # already committed, NOT rolled back; daemon stays alive; the
            # socket method handler converts this to internal_error.
            raise PostCommitSideEffectError(
                f"pane_scan_completed emit failed: {exc}"
            ) from exc

        return PaneScanResult(
            scan_id=scan_id,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            containers_scanned=containers_scanned,
            sockets_scanned=sockets_scanned,
            panes_seen=write_set.panes_seen,
            panes_newly_active=write_set.panes_newly_active,
            panes_reconciled_inactive=write_set.panes_reconciled_inactive,
            containers_skipped_inactive=write_set.containers_skipped_inactive,
            containers_tmux_unavailable=write_set.containers_tmux_unavailable,
            error_code=error_code,
            error_message=error_message,
            error_details=tuple(error_details),
        )

    def _scan_one_container(
        self, *, container_id: str, container_name: str, bench_user: str
    ) -> _ContainerScanState:
        state = _ContainerScanState(
            container_id=container_id,
            container_name=container_name,
            bench_user=bench_user,
            container_user_label=bench_user,
        )

        try:
            uid = self._adapter.resolve_uid(
                container_id=container_id, bench_user=bench_user
            )
        except TmuxError as exc:
            if exc.code == _errors.DOCKER_UNAVAILABLE:
                # Whole-scan failure (FR-022, R-011); propagate upward so
                # the scan() wrapper writes the pane_scans row + JSONL event
                # with the proper envelope shape.
                raise
            state.failures.append(_per_scope_from_tmux_error(exc))
            state.tmux_unavailable = True
            return state

        try:
            listing = self._adapter.list_socket_dir(
                container_id=container_id, bench_user=bench_user, uid=uid
            )
        except TmuxError as exc:
            if exc.code == _errors.DOCKER_UNAVAILABLE:
                raise
            state.failures.append(_per_scope_from_tmux_error(exc))
            state.tmux_unavailable = True
            return state

        if not listing.sockets:
            # Empty socket dir → no per-socket scans, no panes; not an error.
            return state

        any_success = False
        for socket_name in listing.sockets:
            socket_path = f"/tmp/tmux-{uid}/{socket_name}"  # NOSONAR - intentional tmux socket path inside bench container.
            state.sockets_scanned += 1
            try:
                panes = self._adapter.list_panes(
                    container_id=container_id,
                    bench_user=bench_user,
                    socket_path=socket_path,
                )
            except TmuxError as exc:
                if exc.code == _errors.DOCKER_UNAVAILABLE:
                    raise
                err = _per_scope_from_tmux_error(exc, socket_path=socket_path)
                state.failures.append(err)
                if exc.code == _errors.OUTPUT_MALFORMED and exc.partial_panes:
                    any_success = True
                    state.socket_outcomes[(container_id, socket_path)] = OkSocketScan(
                        panes=tuple(exc.partial_panes)
                    )
                else:
                    state.socket_outcomes[(container_id, socket_path)] = FailedSocketScan(
                        error_code=err.error_code, error_message=err.error_message
                    )
                continue
            any_success = True
            state.socket_outcomes[(container_id, socket_path)] = OkSocketScan(
                panes=tuple(panes)
            )

        if not any_success and listing.sockets:
            state.tmux_unavailable = True

        return state

    def _commit_scan(
        self,
        *,
        scan_id: str,
        started_at: str,
        status: str,
        write_set: PaneReconcileWriteSet,
        containers_scanned: int,
        sockets_scanned: int,
        error_code: str | None,
        error_message: str | None,
        error_details: list[PerScopeError],
    ) -> str:
        details_payload = (
            None
            if not error_details
            else [_per_scope_to_dict(e) for e in error_details]
        )
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            state_panes.apply_pane_reconcile_writeset(
                self._conn, write_set=write_set, now_iso=started_at
            )
            completed_at = _now_iso()
            state_panes.insert_pane_scan(
                self._conn,
                scan_id=scan_id,
                started_at=started_at,
                completed_at=completed_at,
                status=status,
                containers_scanned=containers_scanned,
                sockets_scanned=sockets_scanned,
                panes_seen=write_set.panes_seen,
                panes_newly_active=write_set.panes_newly_active,
                panes_reconciled_inactive=write_set.panes_reconciled_inactive,
                containers_skipped_inactive=write_set.containers_skipped_inactive,
                containers_tmux_unavailable=write_set.containers_tmux_unavailable,
                error_code=error_code,
                error_message=error_message,
                error_details=details_payload,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return completed_at

    def _emit_jsonl_degraded(
        self,
        *,
        scan_id: str,
        error_code: str | None,
        error_message: str | None,
        error_details: list[PerScopeError],
    ) -> None:
        if self._events_file is None:
            return
        try:
            events_writer.append_event(
                self._events_file,
                {
                    "type": "pane_scan_degraded",
                    "payload": {
                        "scan_id": scan_id,
                        "error_code": error_code,
                        "error_message": error_message,
                        "error_details": [_per_scope_to_dict(e) for e in error_details],
                    },
                },
            )
        except OSError as exc:
            self._emit_lifecycle("pane_scan_jsonl_failed", scan_id=scan_id)
            raise PostCommitSideEffectError(
                f"pane scan degraded event append failed: {exc}"
            ) from exc

    def _emit_lifecycle(self, event: str, **kwargs: Any) -> None:
        """Best-effort emit; swallows logging errors. Use for non-gate events."""
        if self._lifecycle_logger is None:
            return
        try:
            sanitized = {
                k: _bound(str(v)) if v is not None else "" for k, v in kwargs.items()
            }
            self._lifecycle_logger.emit(event, **sanitized)
        except Exception:
            # Best-effort: never raise from here.
            pass

    def _emit_lifecycle_strict(self, event: str, **kwargs: Any) -> None:
        """Strict emit (FR-025): caller catches and converts to internal_error.

        Used for the pane_scan_started (pre-commit gate) and
        pane_scan_completed (post-commit gate) events. A failure here MUST
        escalate per FR-025; the caller wraps with the appropriate
        rollback/internal-error semantics.
        """
        if self._lifecycle_logger is None:
            return
        sanitized = {
            k: _bound(str(v)) if v is not None else "" for k, v in kwargs.items()
        }
        self._lifecycle_logger.emit(event, **sanitized)

    def _handle_docker_unavailable(
        self, *, scan_id: str, started_at: str, message: str
    ) -> None:
        """Whole-scan-failure persistence path (FR-022, R-011, contracts §3.4).

        When the SubprocessTmuxAdapter cannot resolve the docker binary,
        every per-container call would fail the same way. We persist a
        single pane_scans row with status='degraded', error_code=
        'docker_unavailable', append one pane_scan_degraded JSONL event,
        and emit pane_scan_completed. The caller re-raises so the socket
        method handler returns ok:false with docker_unavailable.
        """
        completed_at = _now_iso()
        bounded_message = _bound(message)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            state_panes.insert_pane_scan(
                self._conn,
                scan_id=scan_id,
                started_at=started_at,
                completed_at=completed_at,
                status="degraded",
                containers_scanned=0,
                sockets_scanned=0,
                panes_seen=0,
                panes_newly_active=0,
                panes_reconciled_inactive=0,
                containers_skipped_inactive=0,
                containers_tmux_unavailable=0,
                error_code=_errors.DOCKER_UNAVAILABLE,
                error_message=bounded_message,
                error_details=None,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            return
        self._emit_jsonl_degraded(
            scan_id=scan_id,
            error_code=_errors.DOCKER_UNAVAILABLE,
            error_message=bounded_message,
            error_details=[],
        )
        self._emit_lifecycle(
            "pane_scan_completed",
            scan_id=scan_id,
            status="degraded",
            containers=0,
            sockets=0,
            panes_seen=0,
            newly_active=0,
            inactivated=0,
            skipped_inactive=0,
            tmux_unavailable=0,
            error=_errors.DOCKER_UNAVAILABLE,
        )

    @staticmethod
    def _index_truncations(
        write_set: PaneReconcileWriteSet,
        socket_results: Mapping[tuple[str, str], SocketScanOutcome],
    ) -> dict[tuple[str, str], list]:
        """Group truncation notes by ``(container_id, tmux_socket_path)``."""
        out: dict[tuple[str, str], list] = {}
        for note in write_set.pane_truncations:
            key = (note.container_id, note.tmux_socket_path)
            out.setdefault(key, []).append(note)
        return out

    @staticmethod
    def _merge_error_details(
        failures: list[PerScopeError],
        truncation_index: Mapping[tuple[str, str], list],
    ) -> list[PerScopeError]:
        out: list[PerScopeError] = []
        for failure in failures:
            scope_key = (failure.container_id, failure.tmux_socket_path or "")
            extra_truncations = (
                tuple(truncation_index.get(scope_key, []))
                if failure.tmux_socket_path is not None
                else ()
            )
            if extra_truncations:
                out.append(
                    PerScopeError(
                        container_id=failure.container_id,
                        tmux_socket_path=failure.tmux_socket_path,
                        error_code=failure.error_code,
                        error_message=failure.error_message,
                        pane_truncations=extra_truncations,
                    )
                )
            else:
                out.append(failure)
        seen_scopes = {
            (e.container_id, e.tmux_socket_path or "") for e in out
        }
        for (container_id, socket_path), notes in truncation_index.items():
            if (container_id, socket_path) in seen_scopes:
                continue
            out.append(
                PerScopeError(
                    container_id=container_id,
                    tmux_socket_path=socket_path,
                    error_code=_errors.OUTPUT_MALFORMED,
                    error_message=_bound(
                        f"{len(notes)} pane field(s) truncated"
                    ),
                    pane_truncations=tuple(notes),
                )
            )
        return out

    @staticmethod
    def _partial_error_message(
        error_details: list[PerScopeError],
        failures: list[PerScopeError],
    ) -> str | None:
        if not error_details:
            return None
        if failures:
            first = failures[0]
            return _bound(first.error_message or first.error_code)
        return _bound("pane field(s) truncated")


def _per_scope_from_tmux_error(
    exc: TmuxError, *, socket_path: str | None = None
) -> PerScopeError:
    return PerScopeError(
        container_id=exc.container_id or "",
        tmux_socket_path=socket_path if socket_path is not None else exc.tmux_socket_path,
        error_code=exc.code,
        error_message=_bound(exc.message),
    )


def _per_scope_to_dict(err: PerScopeError) -> dict[str, Any]:
    out: dict[str, Any] = {
        "container_id": err.container_id,
        "error_code": err.error_code,
        "error_message": err.error_message,
    }
    if err.tmux_socket_path is not None:
        out["tmux_socket_path"] = err.tmux_socket_path
    if err.pane_truncations:
        out["pane_truncations"] = [
            {
                "tmux_pane_id": note.tmux_pane_id,
                "tmux_socket_path": note.tmux_socket_path,
                "container_id": note.container_id,
                "field": note.field,
                "original_len": note.original_len,
            }
            for note in err.pane_truncations
        ]
    return out
