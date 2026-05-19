"""FEAT-011 JSONL audit emission for app-driven mutations (FR-044, FR-044a, FR-044b, FR-044c).

Wraps the existing FEAT-008 events writer (``events.writer.append_event``)
which already holds a process-wide ``threading.Lock`` around the
``O_APPEND`` write — that's the FR-044a mutex.

Contract responsibilities (FEAT-011-specific):

* **FR-044** — every app-driven mutation MUST emit an audit row whose
  ``origin`` field is set to ``"app"`` and whose ``app_session_id``
  carries the issuing session. The opaque ``app_session_token`` MUST
  NEVER appear in any audit row (SC-008).
* **FR-044a** — concurrent app sessions emitting audit rows MUST
  serialize through a process-wide mutex. Reusing the existing
  ``events.writer`` ``_lock`` satisfies this.
* **FR-044b** — **best-effort** semantics: if the JSONL writer raises
  (disk full, permission lost, fs error), the mutation MUST still
  succeed (SQLite already committed at the caller). The audit row is
  dropped, a single stderr warning is emitted per outage window, and
  the readiness ``jsonl`` subsystem flips to ``degraded`` / ``unavailable``
  so operators detect the dropped rows.
* **FR-044c** — caller orders: SQLite commit → ``emit_app_mutation()``
  → response envelope sent. The handler must not call this before
  committing the underlying state, or a stale-failure replay could
  produce an audit row without a matching SQLite row.

* **FR-044 reused upstream names** — Round-4 Block G Q44 fixed the
  audit event-type vocabulary as the upstream FEAT names (``queue_approved``,
  ``route_created``, ``agent_registered``, etc.); FEAT-011 does NOT
  introduce ``app.*``-namespaced event names. The ``origin="app"`` +
  ``app_session_id`` fields are the only FEAT-011 markers.
* **FR-044 — failure rows** — only **successful** commits emit audit
  rows; failed mutations live in daemon stderr/logs only.
* **FR-044 — preflight/hello** — ``app.preflight`` and ``app.hello``
  are NOT audited (Round-4 Block G Q49). ``client_id`` and
  ``client_version`` are NOT included (Round-4 Block G Q50).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from ..events import writer as _events_writer

if TYPE_CHECKING:
    from .sessions import AppSession


# Module-level state for the FR-044b "one stderr warning per outage
# window" rule. The "window" is bounded by ``_OUTAGE_WARN_INTERVAL_MS``
# — we throttle repeated warnings to prevent stderr spam during a
# sustained JSONL outage.
_OUTAGE_WARN_INTERVAL_MS: Final[int] = 60_000  # one warning per minute
_warn_lock = threading.Lock()
_last_outage_warn_ms: float = 0.0


def _maybe_warn_outage(reason: str) -> None:
    """Emit one stderr warning per outage window (FR-044b)."""
    global _last_outage_warn_ms
    now_ms = time.monotonic() * 1000.0
    with _warn_lock:
        if now_ms - _last_outage_warn_ms < _OUTAGE_WARN_INTERVAL_MS:
            return
        _last_outage_warn_ms = now_ms
    # Outside the lock — print is cheap but we don't want to serialize
    # all callers on it.
    print(
        f"FEAT-011: JSONL audit write failed ({reason}); "
        "mutation committed but audit row was dropped. "
        "Check the `jsonl` readiness subsystem.",
        file=sys.stderr,
        flush=True,
    )


def emit_app_mutation(
    events_file: Path | None,
    *,
    event_type: str,
    payload: dict[str, Any],
    session: "AppSession",
) -> bool:
    """Append one app-origin audit row to events.jsonl.

    Args:
        events_file: Path to the JSONL audit file (from
            ``DaemonContext.events_file``). May be ``None`` when running
            in a synthetic test harness without an audit file — in that
            case the call is a no-op that returns ``False``.
        event_type: The upstream FEAT audit event name byte-for-byte
            (``queue_approved``, ``route_created``,
            ``agent_registered``, etc. — Round-4 Block G Q44).
        payload: Event-specific fields. ``origin`` and ``app_session_id``
            are merged in by this function; do NOT pass them in
            ``payload``.
        session: The issuing ``AppSession`` (provides ``app_session_id``
            for audit attribution). The opaque ``app_session_token``
            is NEVER written.

    Returns:
        ``True`` if the row was durably written, ``False`` if the write
        was a no-op (``events_file is None``) or if the writer raised
        (FR-044b best-effort path: caller's mutation is unaffected).

    Never raises. FR-044b mandates that an audit-write failure MUST
    NOT propagate to the caller — the mutation already committed.
    """
    if events_file is None:
        # No audit file configured — synthetic test or pre-FEAT-008
        # daemon. Return False so the caller's contract test can detect
        # missing audit, but don't error.
        return False

    record: dict[str, Any] = {
        "event_type": event_type,
        "origin": "app",
        "app_session_id": session.app_session_id,
    }
    # ``payload`` overlays last so handlers can supply event-specific
    # fields freely — but they must NOT include ``origin`` /
    # ``app_session_id`` keys (those are owned by this helper).
    for protected in ("origin", "app_session_id", "app_session_token"):
        if protected in payload:
            raise ValueError(
                f"audit payload must not include {protected!r}; "
                "emit_app_mutation() owns that field"
            )
    record.update(payload)

    try:
        _events_writer.append_event(events_file, record)
    except OSError as exc:
        # FR-044b: JSONL outage — drop row, warn (rate-limited), and
        # signal to caller that audit was skipped. Caller's mutation
        # stays committed.
        _maybe_warn_outage(
            f"{type(exc).__name__}: {exc.strerror or exc}"
        )
        return False
    except Exception as exc:  # noqa: BLE001 — never propagate to caller
        # Defensive: any non-OSError exception is still treated as a
        # best-effort failure. We log + drop rather than re-raise.
        _maybe_warn_outage(f"{type(exc).__name__}: {exc}")
        return False
    return True


# Test seam: reset the outage-warning throttle so unit tests don't
# silently miss expected warnings.
def _reset_outage_warn_state() -> None:
    """Test seam — reset module-level outage-warn throttle."""
    global _last_outage_warn_ms
    with _warn_lock:
        _last_outage_warn_ms = 0.0


__all__ = [
    "emit_app_mutation",
]
