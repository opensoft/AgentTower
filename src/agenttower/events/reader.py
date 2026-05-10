"""FEAT-008 events reader.

The ``EventsReader`` runs as a single thread inside the daemon
(plan §"Plan summary"). For each ``log_attachments`` row in
``status='active'`` it:

1. Calls FEAT-007's ``reader_cycle_offset_recovery`` exactly once
   per cycle BEFORE reading bytes (FR-002). The returned
   ``ReaderCycleResult.change`` decides whether the cycle skips
   byte reads (TRUNCATED / RECREATED / MISSING / REAPPEARED) or
   proceeds normally (UNCHANGED).
2. Reads up to ``PER_CYCLE_BYTE_CAP_BYTES`` bytes from the
   persisted ``byte_offset`` (FR-019).
3. Splits on ``\\n`` (FR-005). Partial trailing bytes are NOT
   consumed; they're re-read on the next cycle.
4. For each complete record: redacts, classifies, runs through the
   ``DebounceManager``. Emit-ready events are persisted in an
   atomic SQLite commit per event (FR-006).
5. After the SQLite commit, appends one JSONL line per event via
   ``agenttower.events.writer.append_event``. On JSONL failure,
   leaves ``jsonl_appended_at`` NULL so the next cycle re-tries
   (FR-029 watermark).

The reader is the SOLE production-side caller of the
``log_offsets.advance_offset`` API (FR-004 / SC-008). The AST gate at
``tests/unit/test_logs_offset_advance_invariant.py`` enforces this
plus the prohibition on raw ``UPDATE log_offsets`` SQL inside
``src/agenttower/events/``.

This module is also the OWNER of the ``AGENTTOWER_TEST_READER_TICK``
test seam (Plan §R10) — set the env var to a Unix-domain-socket path
and the reader blocks on socket recv between cycles instead of
``time.sleep``. Tests write one byte to advance one cycle.
"""

from __future__ import annotations

import logging
import os
import socket
import sqlite3
import threading
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import (
    LONG_RUNNING_GRACE_SECONDS,
    PANE_EXITED_GRACE_SECONDS,
    PER_CYCLE_BYTE_CAP_BYTES,
    READER_CYCLE_WALLCLOCK_CAP_SECONDS,
    Clock,
    SystemClock,
    append_event,
)
from . import classifier_rules as classifier_rules_module
from .classifier import classify
from .dao import EventRow, insert_event, mark_jsonl_appended, select_pending_jsonl
from .debounce import DebounceManager, PendingEvent
from .session_registry import FollowSessionRegistry
from ..logs import host_fs as host_fs_mod
from ..logs import reader_recovery
from ..socket_api.lifecycle import LifecycleLogger
from ..state import log_attachments as la_state
from ..state import log_offsets as lo_state
from ..state import panes as panes_state


_LOG = logging.getLogger(__name__)


_READER_TICK_ENV_VAR = "AGENTTOWER_TEST_READER_TICK"


@dataclass(frozen=True)
class ReaderStatusSnapshot:
    """Serializable snapshot for ``agenttower status`` (data-model.md §7)."""

    last_cycle_started_at: Optional[str]
    last_cycle_duration_ms: Optional[int]
    active_attachments: int
    attachments_in_failure: list[dict[str, Any]]
    degraded_sqlite: Optional[dict[str, Any]] = None
    degraded_jsonl: Optional[dict[str, Any]] = None


@dataclass
class _AttachmentCycleResult:
    """Outcome of one per-attachment cycle. Internal only."""

    events_emitted: int = 0
    bytes_read: int = 0
    failed: bool = False
    failure_class: Optional[str] = None


class EventsReader:
    """Background reader thread + per-cycle entry point.

    Construct once at daemon boot. Call :meth:`start` to spawn the
    thread; :meth:`stop` to shut it down (the thread joins before
    returning). Tests can call :meth:`run_cycle_for_attachment`
    directly without the thread.
    """

    def __init__(
        self,
        *,
        state_db: Path,
        events_file: Path,
        lifecycle_logger: LifecycleLogger | None,
        follow_session_registry: FollowSessionRegistry | None = None,
        clock: Clock | None = None,
        cycle_cap_seconds: float = READER_CYCLE_WALLCLOCK_CAP_SECONDS,
        per_cycle_byte_cap_bytes: int = PER_CYCLE_BYTE_CAP_BYTES,
        debounce_manager: DebounceManager | None = None,
        pane_exited_grace_seconds: float = PANE_EXITED_GRACE_SECONDS,
        long_running_grace_seconds: float = LONG_RUNNING_GRACE_SECONDS,
    ) -> None:
        # T058 — FR-020 / FR-022 invariant: on cold start the reader
        # treats the persisted ``log_offsets`` rows as authoritative and
        # never carries any byte/line offset across a restart in
        # memory. The reader does NOT cache prior offsets in
        # ``__init__``; every cycle re-reads from SQLite. The FR-022
        # corollary — restart resume MUST NOT depend on JSONL state — is
        # satisfied by construction: this constructor takes only the
        # ``events_file`` Path (the JSONL append target), never reads
        # from it, and the FR-029 watermark column ``jsonl_appended_at``
        # in SQLite is the single source of truth for re-emission.
        self._state_db = state_db
        self._events_file = events_file
        self._lifecycle_logger = lifecycle_logger
        self._follow_session_registry = follow_session_registry
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._cycle_cap = float(cycle_cap_seconds)
        self._byte_cap = int(per_cycle_byte_cap_bytes)
        self._debounce = debounce_manager or DebounceManager()

        self._pane_exited_grace = float(pane_exited_grace_seconds)
        self._long_running_grace = float(long_running_grace_seconds)
        # Per-attachment "have we already emitted X for this lifecycle?"
        # tracking. FR-018 requires exactly one ``pane_exited`` per
        # attached pane lifecycle. FR-013 requires one ``long_running``
        # per running task; once an eligible event lands AFTER a
        # ``long_running`` emission, the marker resets so a later
        # quiet period can emit again.
        #
        # P10 (review MEDIUM defensive) — these sets are only mutated
        # from the reader thread today (single-writer), so no lock is
        # strictly required. They are read by other threads only via
        # ``status_snapshot`` which doesn't expose them. If a future
        # refactor introduces a second writer (e.g., per-attachment
        # workers), wrap these accesses with ``self._lock`` like the
        # other shared snapshot fields.
        self._pane_exited_emitted: set[str] = set()  # attachment_ids
        self._long_running_marked: set[str] = set()  # attachment_ids

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Status snapshot — written under self._lock.
        self._last_cycle_started_at: str | None = None
        self._last_cycle_duration_ms: int | None = None
        self._active_attachments: int = 0
        self._attachments_in_failure: list[dict[str, Any]] = []
        self._degraded_sqlite: Optional[dict[str, Any]] = None
        self._degraded_jsonl: Optional[dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop_target, name="agenttower-events-reader", daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Status snapshot for ``agenttower status``
    # ------------------------------------------------------------------

    def status_snapshot(self) -> ReaderStatusSnapshot:
        with self._lock:
            return ReaderStatusSnapshot(
                last_cycle_started_at=self._last_cycle_started_at,
                last_cycle_duration_ms=self._last_cycle_duration_ms,
                active_attachments=self._active_attachments,
                attachments_in_failure=list(self._attachments_in_failure),
                degraded_sqlite=(
                    dict(self._degraded_sqlite) if self._degraded_sqlite else None
                ),
                degraded_jsonl=(
                    dict(self._degraded_jsonl) if self._degraded_jsonl else None
                ),
            )

    # ------------------------------------------------------------------
    # Run loop (T030)
    # ------------------------------------------------------------------

    def _run_loop_target(self) -> None:
        """Thread main. Runs cycles until ``_stop_event`` is set."""
        try:
            self.run_loop()
        except Exception:  # pragma: no cover (defensive)
            _LOG.exception("events reader loop crashed")

    def run_loop(self) -> None:
        """Run cycles until shutdown.

        Each cycle:
        1. Open a fresh SQLite connection (isolation_level=None so we
           can drive ``BEGIN IMMEDIATE`` explicitly).
        2. Walk every active attachment; call
           ``run_cycle_for_attachment`` for each.
        3. Run the JSONL retry pass (FR-029 watermark).
        4. Wait for the next tick (clock cap or test-tick socket).
        """
        while not self._stop_event.is_set():
            cycle_started_monotonic = self._clock.monotonic()
            cycle_started_iso = self._clock.now_iso()

            try:
                self._run_one_cycle(now_iso=cycle_started_iso, now_monotonic=cycle_started_monotonic)
            except Exception:  # pragma: no cover (defensive)
                _LOG.exception("events reader cycle raised; will retry next cycle")

            # Update the status snapshot.
            cycle_duration = self._clock.monotonic() - cycle_started_monotonic
            with self._lock:
                self._last_cycle_started_at = cycle_started_iso
                self._last_cycle_duration_ms = int(cycle_duration * 1000)

            # Wait for next tick.
            remaining = max(0.0, self._cycle_cap - cycle_duration)
            self._wait_until_next_tick(remaining)

    def _wait_until_next_tick(self, remaining: float) -> None:
        """Honor the ``AGENTTOWER_TEST_READER_TICK`` seam if set."""
        tick_path = os.environ.get(_READER_TICK_ENV_VAR)
        if tick_path:
            # Test mode: block on the socket. One byte = one tick.
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                sock.settimeout(remaining if remaining > 0 else None)
                sock.bind(tick_path)
                try:
                    sock.recv(1)
                finally:
                    sock.close()
                    try:
                        os.unlink(tick_path)
                    except OSError:
                        pass
            except (socket.timeout, OSError):
                pass
            return
        # Production mode: respect stop_event.
        self._stop_event.wait(timeout=remaining)

    def _run_one_cycle(self, *, now_iso: str, now_monotonic: float) -> None:
        """Walk every active attachment and process its cycle."""
        # T051 — cycle-time janitor: evict expired follow sessions before
        # any cycle work so a SIGKILLed CLI's session is freed promptly.
        if self._follow_session_registry is not None:
            try:
                self._follow_session_registry.gc_expired(
                    now_monotonic=now_monotonic
                )
            except Exception:  # pragma: no cover — defensive
                _LOG.exception("follow-session janitor failed")

        conn = sqlite3.connect(self._state_db, isolation_level=None)
        # P5 (review MEDIUM) — defensive PRAGMA re-application. WAL mode
        # is file-level and persists across connections, but explicit
        # re-set on each new connection costs nothing and guards against
        # mode downgrades if the .db file is migrated.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            attachments = la_state.select_actives(conn) if hasattr(
                la_state, "select_actives"
            ) else _list_active_attachments(conn)
            with self._lock:
                self._active_attachments = len(attachments)

            failures: list[dict[str, Any]] = []
            for record in attachments:
                try:
                    self.run_cycle_for_attachment(
                        conn, attachment=record,
                        now_iso=now_iso, now_monotonic=now_monotonic,
                    )
                except Exception as exc:
                    _LOG.exception(
                        "reader cycle for attachment %s failed",
                        record.attachment_id,
                    )
                    failures.append(
                        {
                            "attachment_id": record.attachment_id,
                            "agent_id": record.agent_id,
                            "error_class": type(exc).__name__,
                            "since": now_iso,
                        }
                    )

            with self._lock:
                self._attachments_in_failure = failures

            # FR-029 — JSONL retry pass.
            self._retry_pending_jsonl_appends(conn, now_iso=now_iso)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Per-attachment cycle (T029)
    # ------------------------------------------------------------------

    def run_cycle_for_attachment(
        self,
        conn: sqlite3.Connection,
        *,
        attachment: la_state.LogAttachmentRecord,
        now_iso: str,
        now_monotonic: float,
    ) -> _AttachmentCycleResult:
        """Process one attachment's cycle.

        Order (Plan §R11 + FR-002 + FR-005 + FR-006):

        1. (Plan §R11) ``pane_exited`` synthesis — emit one synthetic
           ``pane_exited`` event (FR-016/017/018) when FEAT-004
           reports the bound pane inactive AND the
           ``pane_exited_grace`` window has elapsed since the last
           output. Exactly once per attachment lifecycle.
        2. (Plan §R11) ``long_running`` synthesis — emit one synthetic
           ``long_running`` event (FR-013) when ``now -
           last_output_at >= long_running_grace`` and the most-recent
           prior emitted event is in the eligible set
           (``activity``, ``error``, ``test_failed``,
           ``manual_review_needed``, ``swarm_member_reported``).
           Exactly once per running task; resets when a fresh
           eligible event lands.
        3. Call ``reader_cycle_offset_recovery`` exactly once (FR-002).
        4. If the recovery result is anything other than UNCHANGED,
           skip the byte-read step (FR-002 / FR-023). The recovery
           helper has already updated state.
        5. Read up to ``PER_CYCLE_BYTE_CAP_BYTES`` from the persisted
           ``byte_offset`` (FR-019).
        6. Split on ``\\n`` (FR-005); keep partial trailing bytes.
        7. For each complete record: redact → classify → debounce.
        8. For each emit-ready event: atomic SQLite commit
           (insert_event + advance_offset) inside one
           ``BEGIN IMMEDIATE`` transaction (FR-006).
        9. After commit, append to JSONL and update
           ``jsonl_appended_at`` (FR-025 / FR-029 watermark).
        """
        result = _AttachmentCycleResult()

        # T079/T089 / Plan §R11 — synthesized event types.
        # ``pane_exited`` and ``long_running`` are NOT regex matches
        # (FR-016 / FR-013); they are synthesized at cycle entry,
        # BEFORE the FEAT-007 recovery call so the synthesized rows
        # use the persisted ``byte_offset`` (no advance) for
        # ``byte_range_start = byte_range_end``.
        self._maybe_synthesize_pane_exited(
            conn, attachment=attachment,
            now_iso=now_iso, now_monotonic=now_monotonic,
        )
        self._maybe_synthesize_long_running(
            conn, attachment=attachment,
            now_iso=now_iso, now_monotonic=now_monotonic,
        )

        # T064 audit — FR-003 / FR-041 / FR-042 obligations:
        #   * the reader does NOT mutate ``log_attachments`` or
        #     ``log_offsets`` rows directly (FR-003) — only via the
        #     FEAT-007 helpers below and the ``lo_state.advance_offset``
        #     helper at commit time;
        #   * the reader does NOT call ``detect_file_change`` directly
        #     and does NOT inline its logic (FR-042) — the recovery
        #     helper is the SOLE entry to file-change classification;
        #   * the reader calls ``reader_cycle_offset_recovery`` exactly
        #     once per cycle BEFORE any byte read (FR-002 / FR-041).
        # The AST gate at ``tests/unit/test_logs_offset_advance_invariant.py``
        # enforces (a) no raw INSERT/UPDATE SQL against either table in
        # ``src/agenttower/events/`` and (b) no production import of
        # the test seam ``advance_offset_for_test``.

        # ----- Step 3: FR-002 recovery call (EXACTLY ONCE per cycle) -----
        recovery_result = reader_recovery.reader_cycle_offset_recovery(
            conn=conn,
            events_file=self._events_file,
            lifecycle_logger=self._lifecycle_logger,
            agent_id=attachment.agent_id,
            log_path=attachment.log_path,
            timestamp=now_iso,
        )

        # T065 — no-replay invariant (FR-043 / SC-004 / SC-005). When
        # the recovery helper signals a non-UNCHANGED change
        # (TRUNCATED, RECREATED, MISSING, or REAPPEARED), the reader
        # MUST skip ALL byte reads in this cycle. Combined with the
        # offset reset that ``reader_cycle_offset_recovery`` performs
        # for TRUNCATED/RECREATED, this guarantees no event is
        # emitted whose ``byte_range_start`` falls within the
        # pre-reset region — the durable contract that FEAT-007's
        # T175/T176/T177 integration tests assert end-to-end.
        if recovery_result.change is not lo_state.FileChangeKind.UNCHANGED:
            return result

        # Re-fetch the offset row; it may have been updated by the
        # recovery helper.
        offset_row = lo_state.select(
            conn, agent_id=attachment.agent_id, log_path=attachment.log_path
        )
        if offset_row is None:
            # FR-039 — missing offset row for an active attachment.
            # Surface the inconsistency; do not invent values.
            result.failed = True
            result.failure_class = "missing_offset_row"
            return result

        # T059 — FR-021 invariant: the byte-read step MUST start at the
        # persisted ``byte_offset``. A defensive assertion here makes
        # any future refactor that introduces an in-memory offset
        # cache visibly fail rather than silently emitting events for
        # already-classified bytes.
        persisted_byte_offset = offset_row.byte_offset
        assert persisted_byte_offset >= 0, (
            f"FR-021 violation: persisted byte_offset is "
            f"{persisted_byte_offset} for attachment "
            f"{attachment.attachment_id}; offsets must always be >= 0"
        )

        # ----- Step 5: read bytes -----
        try:
            new_bytes = self._read_bytes(
                Path(attachment.log_path), persisted_byte_offset, self._byte_cap
            )
        except OSError as exc:
            # FR-038 — unreadable log surface (EACCES etc.) — don't
            # crash; surface diagnostically. The cycle skips byte
            # reads but other attachments continue.
            result.failed = True
            result.failure_class = type(exc).__name__
            return result

        if not new_bytes:
            return result
        result.bytes_read = len(new_bytes)

        # ----- Step 6: split on \n, keep partial trailing -----
        complete_records, advance_bytes, advance_lines = _split_complete_records(
            new_bytes
        )
        if not complete_records:
            # T7 (review HIGH) — long-line memory bound: if the cycle
            # read PER_CYCLE_BYTE_CAP_BYTES worth of bytes and found
            # ZERO complete records, the on-disk file has a single
            # un-terminated line longer than the cycle byte cap. Without
            # an escape hatch, the reader would re-read the same N bytes
            # every cycle indefinitely, never advancing offsets and
            # never emitting an event for content beyond the cap.
            #
            # Force-emit a one-time synthetic ``activity`` event with the
            # excerpt-cap-truncated record-fragment, advance offsets past
            # the consumed bytes, and continue. This bounds memory pressure
            # at the per-cycle cap and prevents a runaway agent from
            # starving other attachments.
            if len(new_bytes) >= self._byte_cap:
                try:
                    record_text = new_bytes.decode("utf-8", errors="replace")
                except Exception:
                    record_text = ""
                outcome = classify(record_text)
                forced = self._debounce.submit(
                    attachment_id=attachment.attachment_id,
                    outcome=outcome,
                    observed_at=now_iso,
                    monotonic=now_monotonic,
                    byte_range_start=offset_row.byte_offset,
                    byte_range_end=offset_row.byte_offset + len(new_bytes),
                    line_offset_start=offset_row.line_offset,
                    line_offset_end=offset_row.line_offset,
                )
                if forced:
                    advance_bytes = len(new_bytes)
                    advance_lines = 0
                    complete_records = []  # no real records to commit
                    events_to_emit_forced = forced
                    # Fall through to the commit path with these synthetic
                    # events; mirror the normal flow.
                    return self._commit_forced_long_line(
                        conn, attachment=attachment,
                        offset_row=offset_row,
                        events_to_emit=events_to_emit_forced,
                        advance_bytes=advance_bytes,
                        now_iso=now_iso,
                        now_monotonic=now_monotonic,
                    )
            return result  # only partial-line bytes; re-read next cycle (FR-005)

        # ----- Steps 7-9: classify, debounce, atomic commit per event -----
        events_to_emit: list[PendingEvent] = []
        for i, record_bytes in enumerate(complete_records):
            try:
                record_text = record_bytes.decode("utf-8", errors="replace")
            except Exception:
                record_text = ""
            outcome = classify(record_text)
            byte_start = offset_row.byte_offset + (
                sum(len(r) + 1 for r in complete_records[:i])  # +1 for \n
            )
            byte_end = byte_start + len(record_bytes) + 1  # include \n
            line_start = offset_row.line_offset + i
            line_end = line_start + 1
            emitted = self._debounce.submit(
                attachment_id=attachment.attachment_id,
                outcome=outcome,
                observed_at=now_iso,
                monotonic=now_monotonic,
                byte_range_start=byte_start,
                byte_range_end=byte_end,
                line_offset_start=line_start,
                line_offset_end=line_end,
            )
            events_to_emit.extend(emitted)

        # Plus any windows that aged out this cycle.
        events_to_emit.extend(
            self._debounce.flush_expired(
                monotonic=now_monotonic, observed_at=now_iso
            )
        )

        # Atomic commit: each event row + the offset advance go
        # together (FR-006). We use a single transaction for all
        # events emitted this cycle — Plan §"Plan summary" allows
        # "single atomic commit per emitted event OR per cycle batch
        # within a single transaction".
        new_byte_offset = offset_row.byte_offset + advance_bytes
        new_line_offset = offset_row.line_offset + advance_lines
        new_last_event_offset = (
            events_to_emit[-1].byte_range_end
            if events_to_emit
            else offset_row.last_event_offset
        )

        committed_event_ids: list[tuple[int, EventRow]] = []
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for ev in events_to_emit:
                    row = EventRow(
                        event_id=0,  # ignored on insert
                        event_type=ev.event_type,
                        agent_id=attachment.agent_id,
                        attachment_id=attachment.attachment_id,
                        log_path=attachment.log_path,
                        byte_range_start=ev.byte_range_start,
                        byte_range_end=ev.byte_range_end,
                        line_offset_start=ev.line_offset_start,
                        line_offset_end=ev.line_offset_end,
                        observed_at=ev.observed_at,
                        record_at=None,  # always null in MVP (Clarifications Q3)
                        excerpt=ev.excerpt,
                        classifier_rule_id=ev.rule_id,
                        debounce_window_id=ev.debounce_window_id,
                        debounce_collapsed_count=ev.debounce_collapsed_count,
                        debounce_window_started_at=ev.debounce_window_started_at,
                        debounce_window_ended_at=ev.debounce_window_ended_at,
                        schema_version=1,
                        jsonl_appended_at=None,
                    )
                    new_event_id = insert_event(conn, row)
                    committed_event_ids.append((new_event_id, row))
                # Advance offsets in the same transaction (FR-006).
                lo_state.advance_offset(
                    conn,
                    agent_id=attachment.agent_id,
                    log_path=attachment.log_path,
                    byte_offset=new_byte_offset,
                    line_offset=new_line_offset,
                    last_event_offset=new_last_event_offset,
                    file_inode=offset_row.file_inode,
                    file_size_seen=offset_row.file_size_seen,
                    last_output_at=now_iso,
                    timestamp=now_iso,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.Error:
            # FR-040 — degraded SQLite. T077 (Phase 8) wires the
            # buffered-retry path; for now, surface the failure and
            # leave offsets unchanged.
            result.failed = True
            result.failure_class = "sqlite_commit"
            with self._lock:
                self._degraded_sqlite = {
                    "since": now_iso,
                    "buffered_attachments": [
                        {
                            "attachment_id": attachment.attachment_id,
                            "agent_id": attachment.agent_id,
                            "buffered_count": len(events_to_emit),
                            "last_error_class": "sqlite3.Error",
                        }
                    ],
                }
            return result

        # ----- Step 9: JSONL append AFTER SQLite commit (FR-025/29) -----
        # H2/H3 fix — wrap each row's JSONL append + watermark UPDATE
        # in an explicit BEGIN/COMMIT so the watermark is durably
        # persisted before we notify followers. Without the explicit
        # transaction, the UPDATE would sit in an implicit transaction
        # on the ``isolation_level=None`` connection and a process kill
        # between JSONL write and the implicit commit would leave the
        # watermark NULL → re-emit on restart. Notify is moved AFTER
        # the watermark is durable so followers cannot observe a row
        # whose ``jsonl_appended_at`` is still NULL.
        successfully_appended: list[tuple[int, EventRow]] = []
        for new_event_id, row in committed_event_ids:
            try:
                self._append_event_to_jsonl(row, event_id=new_event_id)
            except OSError:
                # FR-029 — leave jsonl_appended_at NULL; retry next cycle.
                with self._lock:
                    self._degraded_jsonl = {
                        "since": now_iso,
                        "pending_event_count": (
                            (self._degraded_jsonl or {}).get("pending_event_count", 0) + 1
                        ),
                        "last_error_class": "OSError",
                    }
                continue

            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    mark_jsonl_appended(conn, new_event_id, now_iso)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                successfully_appended.append((new_event_id, row))
            except sqlite3.Error:
                # JSONL succeeded but the watermark UPDATE failed; the
                # next cycle's retry pass will pick the row up via the
                # ``idx_events_jsonl_pending`` partial index. Surface
                # the SQLite-degraded condition rather than the JSONL
                # one (the source of truth is the SQLite write).
                with self._lock:
                    self._degraded_sqlite = {
                        "since": now_iso,
                        "buffered_attachments": [
                            {
                                "attachment_id": attachment.attachment_id,
                                "agent_id": attachment.agent_id,
                                "buffered_count": 0,
                                "last_error_class": "sqlite3.Error",
                            }
                        ],
                    }

        # Notify followers ONLY after the watermark is durable for that
        # row. A waking follower's DAO query will then never see a row
        # whose ``jsonl_appended_at`` is NULL.
        if self._follow_session_registry is not None:
            for _, row in successfully_appended:
                self._follow_session_registry.notify(
                    agent_id=row.agent_id, event_type=row.event_type
                )

        result.events_emitted = len(committed_event_ids)
        return result

    # ------------------------------------------------------------------
    # T7 (review HIGH) — long-line escape hatch
    # ------------------------------------------------------------------

    def _commit_forced_long_line(
        self,
        conn: sqlite3.Connection,
        *,
        attachment: la_state.LogAttachmentRecord,
        offset_row: lo_state.LogOffsetRecord,
        events_to_emit: list[PendingEvent],
        advance_bytes: int,
        now_iso: str,
        now_monotonic: float,  # noqa: ARG002
    ) -> _AttachmentCycleResult:
        """Commit one synthetic long-line event + advance offsets.

        Used only when a cycle read ``PER_CYCLE_BYTE_CAP_BYTES`` of
        bytes WITHOUT finding a complete record. Forces forward
        progress so a runaway no-newline agent does not starve other
        attachments.
        """
        result = _AttachmentCycleResult()
        new_byte_offset = offset_row.byte_offset + advance_bytes
        new_line_offset = offset_row.line_offset
        new_last_event_offset = (
            events_to_emit[-1].byte_range_end
            if events_to_emit
            else offset_row.last_event_offset
        )
        committed_event_ids: list[tuple[int, EventRow]] = []
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for ev in events_to_emit:
                    row = EventRow(
                        event_id=0,
                        event_type=ev.event_type,
                        agent_id=attachment.agent_id,
                        attachment_id=attachment.attachment_id,
                        log_path=attachment.log_path,
                        byte_range_start=ev.byte_range_start,
                        byte_range_end=ev.byte_range_end,
                        line_offset_start=ev.line_offset_start,
                        line_offset_end=ev.line_offset_end,
                        observed_at=ev.observed_at,
                        record_at=None,
                        excerpt=ev.excerpt,
                        classifier_rule_id=ev.rule_id,
                        debounce_window_id=ev.debounce_window_id,
                        debounce_collapsed_count=ev.debounce_collapsed_count,
                        debounce_window_started_at=ev.debounce_window_started_at,
                        debounce_window_ended_at=ev.debounce_window_ended_at,
                        schema_version=1,
                        jsonl_appended_at=None,
                    )
                    new_event_id = insert_event(conn, row)
                    committed_event_ids.append((new_event_id, row))
                lo_state.advance_offset(
                    conn,
                    agent_id=attachment.agent_id,
                    log_path=attachment.log_path,
                    byte_offset=new_byte_offset,
                    line_offset=new_line_offset,
                    last_event_offset=new_last_event_offset,
                    file_inode=offset_row.file_inode,
                    file_size_seen=offset_row.file_size_seen,
                    last_output_at=now_iso,
                    timestamp=now_iso,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.Error:
            result.failed = True
            result.failure_class = "sqlite_commit"
            return result
        result.events_emitted = len(committed_event_ids)
        result.bytes_read = advance_bytes
        return result

    # ------------------------------------------------------------------
    # JSONL retry watermark (FR-029)
    # ------------------------------------------------------------------

    def _retry_pending_jsonl_appends(
        self, conn: sqlite3.Connection, *, now_iso: str
    ) -> None:
        """Replay pending JSONL appends from the SQLite source of truth."""
        try:
            pending = select_pending_jsonl(conn, limit=50)
        except sqlite3.Error:
            return
        if not pending:
            with self._lock:
                self._degraded_jsonl = None
            return

        remaining_after_retry = 0
        for row in pending:
            try:
                self._append_event_to_jsonl(row, event_id=row.event_id)
                mark_jsonl_appended(conn, row.event_id, now_iso)
            except OSError:
                remaining_after_retry += 1
        with self._lock:
            if remaining_after_retry == 0:
                self._degraded_jsonl = None
            else:
                self._degraded_jsonl = {
                    "since": (self._degraded_jsonl or {}).get("since", now_iso),
                    "pending_event_count": remaining_after_retry,
                    "last_error_class": "OSError",
                }

    # ------------------------------------------------------------------
    # JSONL emission
    # ------------------------------------------------------------------

    def _append_event_to_jsonl(self, row: EventRow, *, event_id: int) -> None:
        """Render one event into the FR-027 JSONL stable schema and append."""
        payload = {
            "event_id": event_id,
            "event_type": row.event_type,
            "agent_id": row.agent_id,
            "attachment_id": row.attachment_id,
            "log_path": row.log_path,
            "byte_range_start": row.byte_range_start,
            "byte_range_end": row.byte_range_end,
            "line_offset_start": row.line_offset_start,
            "line_offset_end": row.line_offset_end,
            "observed_at": row.observed_at,
            "record_at": row.record_at,
            "excerpt": row.excerpt,
            "classifier_rule_id": row.classifier_rule_id,
            "debounce": {
                "window_id": row.debounce_window_id,
                "collapsed_count": row.debounce_collapsed_count,
                "window_started_at": row.debounce_window_started_at,
                "window_ended_at": row.debounce_window_ended_at,
            },
            "schema_version": row.schema_version,
        }
        append_event(self._events_file, payload)

    # ------------------------------------------------------------------
    # Byte read (single source of truth — go through host_fs.py)
    # ------------------------------------------------------------------

    def _read_bytes(
        self, log_path: Path, byte_offset: int, cap: int
    ) -> bytes:
        """Read up to ``cap`` bytes starting at ``byte_offset``.

        Routes through FEAT-007's ``host_fs`` adapter so the
        ``AGENTTOWER_TEST_LOG_FS_FAKE`` seam works for tests. If the
        adapter doesn't expose a tail-read API, we fall back to
        direct ``os.read``; the adapter's stat path still owns
        correctness.
        """
        # The FEAT-007 adapter has ``read_tail_lines`` but not a
        # byte-range read. Use direct os.open here (the AST gate
        # forbids only test seams + log_attachments/log_offsets SQL,
        # not file I/O).
        fd = os.open(str(log_path), os.O_RDONLY)
        try:
            os.lseek(fd, byte_offset, os.SEEK_SET)
            return os.read(fd, cap)
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Synthesized event types (Plan §R11 / FR-013 / FR-016..018)
    # ------------------------------------------------------------------

    # Eligibility table for ``long_running`` (FR-013 / contracts/
    # classifier-catalogue.md §"long_running eligibility"). Most-recent
    # prior emitted event types that make a fresh ``long_running``
    # eligible:
    _LONG_RUNNING_ELIGIBLE = frozenset(
        {
            "activity", "error", "test_failed",
            "manual_review_needed", "swarm_member_reported",
        }
    )

    def _last_event_for_attachment(
        self,
        conn: sqlite3.Connection,
        attachment_id: str,
    ) -> tuple[str, int] | None:
        """Return ``(event_type, event_id)`` for the most recent event
        on this attachment, or None if no events have been emitted yet.
        """
        row = conn.execute(
            "SELECT event_type, event_id FROM events "
            "WHERE attachment_id = ? "
            "ORDER BY event_id DESC LIMIT 1",
            (attachment_id,),
        ).fetchone()
        return (row[0], int(row[1])) if row else None

    def _persist_synthetic_event(
        self,
        conn: sqlite3.Connection,
        *,
        attachment: la_state.LogAttachmentRecord,
        event_type: str,
        rule_id: str,
        now_iso: str,
        offset_row: lo_state.LogOffsetRecord,
    ) -> int | None:
        """Insert one synthetic event row + advance the offsets row's
        timestamp (no byte/line offset change). Returns the new
        ``event_id``, or None on commit failure (which is surfaced as
        ``degraded_sqlite``)."""
        synth = EventRow(
            event_id=0,
            event_type=event_type,
            agent_id=attachment.agent_id,
            attachment_id=attachment.attachment_id,
            log_path=attachment.log_path,
            byte_range_start=offset_row.byte_offset,
            byte_range_end=offset_row.byte_offset,
            line_offset_start=offset_row.line_offset,
            line_offset_end=offset_row.line_offset,
            observed_at=now_iso,
            record_at=None,
            excerpt="",
            classifier_rule_id=rule_id,
            debounce_window_id=None,
            debounce_collapsed_count=1,
            debounce_window_started_at=None,
            debounce_window_ended_at=None,
            schema_version=1,
            jsonl_appended_at=None,
        )
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                event_id = insert_event(conn, synth)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.Error:
            with self._lock:
                self._degraded_sqlite = {
                    "since": now_iso,
                    "buffered_attachments": [
                        {
                            "attachment_id": attachment.attachment_id,
                            "agent_id": attachment.agent_id,
                            "buffered_count": 1,
                            "last_error_class": "sqlite3.Error",
                        }
                    ],
                }
            return None

        # JSONL append + watermark for the synthetic row, mirroring
        # the byte-driven path. Failures leave ``jsonl_appended_at``
        # NULL for the next-cycle retry pass.
        try:
            self._append_event_to_jsonl(synth, event_id=event_id)
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    mark_jsonl_appended(conn, event_id, now_iso)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            except sqlite3.Error:
                pass  # next cycle's retry pass will pick up the row
        except OSError:
            with self._lock:
                self._degraded_jsonl = {
                    "since": now_iso,
                    "pending_event_count": (
                        (self._degraded_jsonl or {}).get("pending_event_count", 0)
                        + 1
                    ),
                    "last_error_class": "OSError",
                }

        if self._follow_session_registry is not None:
            self._follow_session_registry.notify(
                agent_id=attachment.agent_id, event_type=event_type
            )
        return event_id

    def _maybe_synthesize_pane_exited(
        self,
        conn: sqlite3.Connection,
        *,
        attachment: la_state.LogAttachmentRecord,
        now_iso: str,
        now_monotonic: float,  # noqa: ARG002 (reserved for monotonic-driven future tweak)
    ) -> None:
        """Synthesize one ``pane_exited`` event (FR-016/017/018) iff:

        * FEAT-004's pane state for the attachment's bound pane is
          inactive (``panes.active = 0``);
        * ``now - last_output_at >= pane_exited_grace_seconds`` (FR-017);
        * we have not already emitted ``pane_exited`` for this
          attachment lifecycle (FR-018, in-memory tracker
          ``self._pane_exited_emitted``).
        """
        if attachment.attachment_id in self._pane_exited_emitted:
            return

        pane_row = conn.execute(
            "SELECT active FROM panes "
            "WHERE container_id = ? AND tmux_socket_path = ? "
            "  AND tmux_session_name = ? AND tmux_window_index = ? "
            "  AND tmux_pane_index = ? AND tmux_pane_id = ?",
            (
                attachment.container_id, attachment.tmux_socket_path,
                attachment.tmux_session_name, attachment.tmux_window_index,
                attachment.tmux_pane_index, attachment.tmux_pane_id,
            ),
        ).fetchone()
        if pane_row is None:
            return  # FEAT-004 hasn't observed this pane yet
        if int(pane_row[0]) != 0:
            return  # pane is still active

        offset_row = lo_state.select(
            conn, agent_id=attachment.agent_id, log_path=attachment.log_path
        )
        if offset_row is None:
            return
        # Use last_output_at as the "last byte seen" reference; if
        # NULL, fall back to the offset row's updated_at.
        last_output_at = offset_row.last_output_at or offset_row.updated_at
        if not last_output_at:
            return
        # ISO-8601 with offset → datetime; compare seconds elapsed.
        try:
            from datetime import datetime as _dt
            last_dt = _dt.fromisoformat(last_output_at.replace("Z", "+00:00"))
            now_dt = _dt.fromisoformat(now_iso.replace("Z", "+00:00"))
            elapsed = (now_dt - last_dt).total_seconds()
        except (ValueError, TypeError):
            return
        if elapsed < self._pane_exited_grace:
            return

        emitted_id = self._persist_synthetic_event(
            conn, attachment=attachment,
            event_type="pane_exited",
            rule_id=classifier_rules_module.PANE_EXITED_SYNTH_RULE_ID,
            now_iso=now_iso,
            offset_row=offset_row,
        )
        if emitted_id is not None:
            self._pane_exited_emitted.add(attachment.attachment_id)

    def _maybe_synthesize_long_running(
        self,
        conn: sqlite3.Connection,
        *,
        attachment: la_state.LogAttachmentRecord,
        now_iso: str,
        now_monotonic: float,  # noqa: ARG002
    ) -> None:
        """Synthesize one ``long_running`` event (FR-013) iff:

        * ``now - last_output_at >= long_running_grace_seconds``;
        * the most-recent prior emitted event for this attachment is
          in the FR-013 eligibility set;
        * we have not already emitted ``long_running`` since the last
          eligible event landed (in-memory tracker
          ``self._long_running_marked``).
        """
        last = self._last_event_for_attachment(
            conn, attachment.attachment_id
        )
        if last is None:
            return
        last_event_type, _ = last

        # Reset the marker when a fresh eligible event lands AFTER a
        # prior ``long_running`` emission.
        if (
            attachment.attachment_id in self._long_running_marked
            and last_event_type in self._LONG_RUNNING_ELIGIBLE
        ):
            self._long_running_marked.discard(attachment.attachment_id)

        if attachment.attachment_id in self._long_running_marked:
            return
        if last_event_type not in self._LONG_RUNNING_ELIGIBLE:
            return

        offset_row = lo_state.select(
            conn, agent_id=attachment.agent_id, log_path=attachment.log_path
        )
        if offset_row is None:
            return
        last_output_at = offset_row.last_output_at or offset_row.updated_at
        if not last_output_at:
            return
        try:
            from datetime import datetime as _dt
            last_dt = _dt.fromisoformat(last_output_at.replace("Z", "+00:00"))
            now_dt = _dt.fromisoformat(now_iso.replace("Z", "+00:00"))
            elapsed = (now_dt - last_dt).total_seconds()
        except (ValueError, TypeError):
            return
        if elapsed < self._long_running_grace:
            return

        emitted_id = self._persist_synthetic_event(
            conn, attachment=attachment,
            event_type="long_running",
            rule_id=classifier_rules_module.LONG_RUNNING_SYNTH_RULE_ID,
            now_iso=now_iso,
            offset_row=offset_row,
        )
        if emitted_id is not None:
            self._long_running_marked.add(attachment.attachment_id)


# --------------------------------------------------------------------------
# Helpers (module level — pure)
# --------------------------------------------------------------------------


def _split_complete_records(
    raw: bytes,
) -> tuple[list[bytes], int, int]:
    """Split *raw* on ``b'\\n'``; return ``(records, advance_bytes, advance_lines)``.

    Partial trailing bytes (no terminating newline) are NOT included
    in ``records`` and are NOT counted toward ``advance_bytes``;
    they remain on disk and are re-read on the next cycle (FR-005).

    T6 (review HIGH) — PTY streams emit ``\\r\\n`` line endings; the
    trailing ``\\r`` is stripped from each record so anchored rule
    patterns (e.g., ``waiting_for_input.v1`` ending on ``\\?\\s*$``)
    match cleanly. Byte offsets advance over the original ``\\r\\n``
    pair so persistence stays aligned with the on-disk file.
    """
    if not raw:
        return [], 0, 0
    parts = raw.split(b"\n")
    # parts[-1] is the trailing partial (or empty if raw ends in \n).
    complete_raw = parts[:-1]
    # Strip trailing \r from each record (T6); offsets are still
    # computed against the on-disk byte length, so we record advance
    # against the pre-strip lengths.
    complete = [r[:-1] if r.endswith(b"\r") else r for r in complete_raw]
    advance = sum(len(r) for r in complete_raw) + len(complete_raw)  # +1 per \n
    return complete, advance, len(complete)


def _list_active_attachments(
    conn: sqlite3.Connection,
) -> list[la_state.LogAttachmentRecord]:
    """Fall-back enumerator when ``la_state.select_actives`` is absent.

    FEAT-007 ships ``select_active_for_agent`` and similar but no
    ``select_actives`` (no agent filter). The reader needs to walk
    EVERY active attachment per cycle, so we provide this small
    helper. It uses the same column ordering and row-decode that
    ``la_state`` exposes.
    """
    cur = conn.execute(
        "SELECT attachment_id FROM log_attachments WHERE status = 'active'"
    )
    out: list[la_state.LogAttachmentRecord] = []
    for (attachment_id,) in cur.fetchall():
        # Reuse the existing select_active_for_agent function would
        # require the agent_id; the cleanest path is a direct
        # by-attachment-id lookup. Inline it here (read-only).
        row = conn.execute(
            "SELECT attachment_id FROM log_attachments WHERE attachment_id = ? AND status = 'active'",
            (attachment_id,),
        ).fetchone()
        if row is None:
            continue
        # Defer to the by-agent-and-path helper — we need the full
        # row, so re-issue an explicit SELECT through la_state's
        # private decoder. Use the public ``select_for_agent_path``
        # helper after deriving the agent_id.
        agent_row = conn.execute(
            "SELECT agent_id, log_path FROM log_attachments WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
        if agent_row is None:
            continue
        agent_id, log_path = agent_row
        full = la_state.select_for_agent_path(
            conn, agent_id=agent_id, log_path=log_path
        )
        if full is not None and full.status == "active":
            out.append(full)
    return out


__all__ = ["EventsReader", "ReaderStatusSnapshot"]
