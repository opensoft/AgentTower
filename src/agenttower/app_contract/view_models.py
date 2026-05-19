"""FEAT-011 compact view-model builders for dashboard recents.

The full per-entity view models (PaneViewModel, AgentViewModel, etc.)
documented in ``data-model.md`` §View Models are needed by US2/US3
read surfaces; this MVP slice only ships the compact "recent row"
builders the US1 dashboard needs.

Each compact builder is a pure function from a DAO row → a small dict
suitable for "Recent activity" rendering. The full view models will
follow in the US2/US3 implementation.
"""

from __future__ import annotations

from typing import Any

from .versioning import STATE_PRIORITY


def compact_event(row: Any) -> dict[str, Any]:
    """Compact ``event`` row → dashboard recent payload.

    ``row`` is whatever ``events.dao.select_events`` returns (an
    ``EventRow`` dataclass-like object with ``event_id``,
    ``event_type``, ``origin``, ``created_at``, ``agent_id``,
    ``payload``, etc.). We keep the contract robust to schema drift
    by accessing fields via ``getattr`` with safe defaults.
    """
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


# ─── Helpers ──────────────────────────────────────────────────────────────


def _get(row: Any, name: str, *, default: Any = None) -> Any:
    """Robust attribute / mapping access. Works for dataclasses, plain
    objects, ``dict``, and ``sqlite3.Row``."""
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    try:
        value = getattr(row, name)
        return value if value is not None else default
    except (AttributeError, TypeError):
        pass
    try:
        return row[name]  # sqlite3.Row supports mapping access
    except (KeyError, TypeError, IndexError):
        return default


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
    "compact_event",
    "compact_queue",
    "compact_route",
]
