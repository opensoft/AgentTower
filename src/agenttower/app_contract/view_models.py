"""FEAT-011 view-model builders (data-model.md §View Models).

Two flavors per entity:

* ``<entity>_view`` — the **full** view model documented in
  data-model.md, used by ``app.<entity>.list`` / ``app.<entity>.detail``.
* ``compact_<entity>`` — the **dashboard recent** projection: just
  enough fields to render a "Recent activity" row, used by
  ``app.dashboard.recent.<entity>``.

All builders are **pure projection functions** — no SQLite I/O, no
audit emission, no side effects. Upstream services pass the DAO row
plus any pre-computed derivation context (e.g., the linked agent for a
pane, the most-recent scan for an agent). The handler is responsible
for fetching that context once and passing it to many rows — the view
builders don't fan out to the DB.

Robust attribute access via ``_get`` accommodates dataclasses, plain
objects, ``dict``, and ``sqlite3.Row``. Fields named in the data-model
spec but absent from a row default to ``None`` (or the documented
fallback for booleans / ints) rather than raising.
"""

from __future__ import annotations

from typing import Any

from .versioning import ROLE_PRIORITY, STATE_PRIORITY


# ─── Full view models (data-model.md §View Models) ───────────────────────


def container_view(
    row: Any,
    *,
    pane_count: int | None = None,
    registered_agent_count: int | None = None,
    derived_state: str | None = None,
) -> dict[str, Any]:
    """ContainerViewModel (data-model.md).

    ``pane_count`` / ``registered_agent_count`` are derived joins the
    caller pre-computes. ``derived_state`` overrides the row's ``state``
    field when the caller has already classified ``active /
    inactive / degraded_scan`` per FR-016a (e.g., by joining with
    last-scan health).
    """
    return {
        "container_id": _get(row, "container_id"),
        "name": _get(row, "name", default=""),
        "state": derived_state if derived_state is not None else _get(row, "state", default=""),
        "image": _get(row, "image", default=""),
        # Round-6: FEAT-003 containers row has first_seen_at /
        # last_scanned_at — not created_at / last_seen_at.
        "first_seen_at": _get(row, "first_seen_at"),
        "last_scanned_at": _get(row, "last_scanned_at"),
        "pane_count": _coerce_int(pane_count) if pane_count is not None else _get(row, "pane_count", default=0),
        "registered_agent_count": (
            _coerce_int(registered_agent_count)
            if registered_agent_count is not None
            else _get(row, "registered_agent_count", default=0)
        ),
    }


def pane_view(
    row: Any,
    *,
    linked_agent_id: str | None = None,
    container_name: str | None = None,
) -> dict[str, Any]:
    """PaneViewModel (data-model.md).

    ``linked_agent_id`` is the joined ``agents.agent_id`` if any
    non-deleted agent links this pane (FR-022). ``None`` → ``registered:
    false``, ``agent_id: null``. ``container_name`` is the joined
    container name; falls back to ``""`` if not provided.
    """
    return {
        "pane_id": _get(row, "pane_id"),
        "container_id": _get(row, "container_id"),
        "container_name": (
            container_name
            if container_name is not None
            else _get(row, "container_name", default="")
        ),
        "tmux_socket": _get(row, "tmux_socket", default=""),
        "session_name": _get(row, "session_name", default=""),
        "window_index": _get(row, "window_index", default=0),
        "pane_index": _get(row, "pane_index", default=0),
        "registered": linked_agent_id is not None,
        "agent_id": linked_agent_id,
        "discovered_at": _get(row, "discovered_at"),
        "last_seen_at": _get(row, "last_seen_at"),
    }


def agent_view(
    row: Any,
    *,
    log_attached: bool | None = None,
    pane_active: bool | None = None,
) -> dict[str, Any]:
    """AgentViewModel (data-model.md).

    ``log_attached`` is True iff a FEAT-007 ``log_attachments`` row
    exists for this agent (FR-023). ``pane_active`` is True iff the
    linked pane was seen on the most recent scan (FR-023). Both are
    derived joins the caller pre-computes.
    """
    role = _get(row, "role", default="unknown")
    return {
        "agent_id": _get(row, "agent_id"),
        "role": role,
        "role_priority": ROLE_PRIORITY.get(role, 99),
        "capability": _get(row, "capability", default=""),
        "label": _get(row, "label", default=""),
        "project_path": _get(row, "project_path"),
        "parent_agent_id": _get(row, "parent_agent_id"),
        "container_id": _get(row, "container_id"),
        "pane_id": _get(row, "pane_id"),
        "registered_at": _get(row, "registered_at"),
        "log_attached": (
            bool(log_attached)
            if log_attached is not None
            else bool(_get(row, "log_attached", default=False))
        ),
        "pane_active": (
            bool(pane_active)
            if pane_active is not None
            else bool(_get(row, "pane_active", default=False))
        ),
    }


def log_attachment_view(row: Any) -> dict[str, Any]:
    """LogAttachmentViewModel (data-model.md — Round-6 corrected).

    Projects the shipped FEAT-007 ``log_attachments`` columns. The row
    has no ``last_output_at`` or ``bytes_written`` (byte offsets live
    in the separate ``log_offsets`` table); its status set is
    ``{active, superseded, stale, detached}``.
    """
    return {
        "attachment_id": _get(row, "attachment_id"),
        "agent_id": _get(row, "agent_id"),
        "container_id": _get(row, "container_id"),
        "log_path": _get(row, "log_path", default=""),
        "status": _get(row, "status", default=""),
        "source": _get(row, "source", default=""),
        "attached_at": _get(row, "attached_at"),
        "last_status_at": _get(row, "last_status_at"),
    }


def event_view(row: Any) -> dict[str, Any]:
    """EventViewModel (data-model.md — Round-6 corrected).

    Projects the shipped FEAT-008 ``events`` columns. The row has no
    ``origin`` column and no structured ``payload``; the human-readable
    content is ``excerpt`` (already redacted by FEAT-008) and the
    timestamp is ``observed_at``.
    """
    return {
        "event_id": _get(row, "event_id"),
        "event_type": _get(row, "event_type", default=""),
        "agent_id": _get(row, "agent_id"),
        "observed_at": _get(row, "observed_at"),
        "excerpt": _get(row, "excerpt", default=""),
        "classifier_rule_id": _get(row, "classifier_rule_id", default=""),
        "summary": _summarize_event(row),
    }


def queue_view(row: Any) -> dict[str, Any]:
    """QueueViewModel (data-model.md — Round-5 corrected).

    Full queue-row projection over the shipped FEAT-009
    ``message_queue`` columns. ``state_priority`` is the FR-021a
    normative mapping, used by ``app.queue.list`` default ordering.

    The FEAT-009 row has no ``origin`` / ``route_id`` / ``event_id``
    columns; the parties are ``sender_agent_id`` / ``target_agent_id``;
    the enqueue timestamp is ``enqueued_at``; the payload is raw
    ``envelope_body`` bytes surfaced as a redacted ``payload_preview``.
    """
    state = _get(row, "state", default="")
    return {
        "message_id": _get(row, "message_id"),
        "state": state,
        "state_priority": STATE_PRIORITY.get(state, 99),
        "block_reason": _get(row, "block_reason"),
        "failure_reason": _get(row, "failure_reason"),
        "sender_agent_id": _get(row, "sender_agent_id"),
        "target_agent_id": _get(row, "target_agent_id"),
        "payload_preview": _get(row, "payload_preview", default=""),
        "enqueued_at": _get(row, "enqueued_at"),
        "last_updated_at": _get(row, "last_updated_at"),
    }


def route_view(row: Any) -> dict[str, Any]:
    """RouteViewModel (data-model.md — Round-6 corrected).

    Projects the shipped FEAT-010 ``routes`` columns. Source-scope,
    target, and master are stored as **paired** ``*_kind``/``*_rule`` +
    ``*_value`` columns and are composed here into nested objects. The
    route's last-change timestamp is ``updated_at`` (there is no
    ``last_used_at`` column).
    """
    return {
        "route_id": _get(row, "route_id"),
        "enabled": bool(_get(row, "enabled", default=False)),
        "event_type": _get(row, "event_type", default=""),
        "source_scope": {
            "kind": _get(row, "source_scope_kind", default=""),
            "value": _get(row, "source_scope_value"),
        },
        "target": {
            "rule": _get(row, "target_rule", default=""),
            "value": _get(row, "target_value"),
        },
        "master": {
            "rule": _get(row, "master_rule", default=""),
            "value": _get(row, "master_value"),
        },
        "template": _get(row, "template", default=""),
        "last_consumed_event_id": _coerce_int(
            _get(row, "last_consumed_event_id", default=0)
        ),
        "created_at": _get(row, "created_at"),
        "updated_at": _get(row, "updated_at"),
    }


# ─── Compact builders (dashboard recents) ────────────────────────────────


def compact_event(row: Any) -> dict[str, Any]:
    """Compact ``event`` row → dashboard recent payload (FR-017)."""
    return {
        "id": _get(row, "event_id"),
        "timestamp": _get(row, "created_at"),
        "type": _get(row, "event_type", default=""),
        "origin": _get(row, "origin", default=""),
        "agent_id": _get(row, "agent_id"),
        "summary": _summarize_event(row),
    }


def compact_queue(row: Any) -> dict[str, Any]:
    """Compact ``message_queue`` row → dashboard recent payload."""
    state = _get(row, "state", default="")
    return {
        "id": _get(row, "message_id"),
        "timestamp": _get(row, "created_at"),
        "type": _get(row, "origin", default="direct"),
        "state": state,
        "state_priority": STATE_PRIORITY.get(state, 99),
        "target_agent_id": _get(row, "target_agent_id"),
        "summary": _summarize_queue(row),
    }


def compact_route(row: Any) -> dict[str, Any]:
    """Compact ``routes`` row → dashboard recent payload."""
    return {
        "id": _get(row, "route_id"),
        "timestamp": _get(row, "created_at"),
        "type": "route",
        "enabled": bool(_get(row, "enabled", default=False)),
        "summary": _summarize_route(row),
    }


# ─── Helpers ─────────────────────────────────────────────────────────────


def _get(row: Any, name: str, *, default: Any = None) -> Any:
    """Robust attribute / mapping access. Works for dataclasses, plain
    objects, ``dict``, and ``sqlite3.Row``.

    A stored ``None`` is treated as "no value" and the ``default`` is
    returned in its place, consistent across the dict path
    (``row.get(name, default)`` only fires on missing keys, so we
    additionally normalize ``None`` → ``default`` here) and the
    getattr path.
    """
    if row is None:
        return default
    if isinstance(row, dict):
        value = row.get(name, default)
        return value if value is not None else default
    try:
        value = getattr(row, name)
        return value if value is not None else default
    except (AttributeError, TypeError):
        pass
    try:
        value = row[name]
    except (KeyError, TypeError, IndexError):
        return default
    return value if value is not None else default


def _coerce_int(value: Any) -> int:
    """Best-effort int coercion for derived count fields."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _summarize_event(row: Any) -> str:
    """Short prose for a "Recent events" row. ≤ 256 chars."""
    event_type = _get(row, "event_type", default="")
    agent_id = _get(row, "agent_id")
    if agent_id:
        return f"{event_type} from {agent_id}"[:256]
    return event_type[:256] if event_type else "(event)"


def _summarize_queue(row: Any) -> str:
    """Short prose for a "Recent queue activity" row. ≤ 256 chars."""
    state = _get(row, "state", default="")
    target = _get(row, "target_agent_id", default="")
    return f"{state} → {target}"[:256]


def _summarize_route(row: Any) -> str:
    """Short prose for a "Recent routes" row. ≤ 256 chars."""
    route_id = _get(row, "route_id", default="")
    enabled = bool(_get(row, "enabled", default=False))
    flag = "enabled" if enabled else "disabled"
    return f"route {route_id} ({flag})"[:256]


__all__ = [
    # Full view models
    "container_view",
    "pane_view",
    "agent_view",
    "log_attachment_view",
    "event_view",
    "queue_view",
    "route_view",
    # Compact builders
    "compact_event",
    "compact_queue",
    "compact_route",
]
