"""FEAT-007 lifecycle event helpers (FR-046 / FR-061).

Wraps the daemon's :class:`agenttower.socket_api.lifecycle.LifecycleLogger`
with FEAT-007-specific suppression rules per FR-061:

* ``log_file_missing``: at most one per ``(agent_id, log_path)`` per
  stale-state entry; the next emission requires the row to first
  transition out of ``stale``.
* ``log_file_returned``: at most one per
  ``(agent_id, log_path, file_inode)`` triple.
* ``log_rotation_detected``: at most one per actual rotation (changed
  inode or size shrink relative to last seen).
* ``log_attachment_orphan_detected``: at most one per
  ``(container_id, pane_composite_key, observed_pipe_target)`` triple
  per daemon lifetime.

The suppression registry is in-memory only (data-model.md §3.6) and
resets on daemon restart. A previously-suppressed event MAY re-fire
once per triple post-restart; this is acceptable because lifecycle
events are observability signals, not audit rows.
"""

from __future__ import annotations

import threading
import json
from typing import Any, Optional

from ..socket_api.lifecycle import (
    EVENT_LOG_ATTACHMENT_ORPHAN_DETECTED,
    EVENT_LOG_FILE_MISSING,
    EVENT_LOG_FILE_RETURNED,
    EVENT_LOG_ROTATION_DETECTED,
    EVENT_MOUNTS_JSON_OVERSIZED,
    EVENT_SOCKET_PEER_UID_MISMATCH,
    LifecycleLogger,
)

# ---------------------------------------------------------------------------
# In-memory suppression registry.
# ---------------------------------------------------------------------------


class _SuppressionState:
    """In-memory FR-061 suppression maps; resets on daemon restart (§3.6)."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        # (agent_id, log_path) → True iff a log_file_missing was emitted for
        # the current stale entry. Cleared when the row leaves stale.
        self._missing: dict[tuple[str, str], bool] = {}
        # (agent_id, log_path, file_inode) → True iff a log_file_returned was
        # emitted for this triple.
        self._returned: set[tuple[str, str, str]] = set()
        # (agent_id, log_path, prior_inode_or_None, new_inode) → True iff a
        # rotation event was emitted for this rotation.
        self._rotated: set[tuple[str, str, Optional[str], Optional[str]]] = set()
        # (container_id, pane_composite_key_json, observed_pipe_target) → True iff
        # an orphan event was emitted in this daemon lifetime.
        self._orphans: set[tuple[str, str, str]] = set()

    def should_emit_missing(self, agent_id: str, log_path: str) -> bool:
        with self._guard:
            key = (agent_id, log_path)
            if self._missing.get(key, False):
                return False
            self._missing[key] = True
            return True

    def reset_missing(self, agent_id: str, log_path: str) -> None:
        """Called when the row leaves stale (re-attach, supersede, detach)."""
        with self._guard:
            self._missing.pop((agent_id, log_path), None)

    def should_emit_returned(
        self, agent_id: str, log_path: str, file_inode: Optional[str]
    ) -> bool:
        with self._guard:
            inode = file_inode if file_inode is not None else ""
            key = (agent_id, log_path, inode)
            if key in self._returned:
                return False
            self._returned.add(key)
            return True

    def should_emit_rotation(
        self,
        agent_id: str,
        log_path: str,
        prior_inode: Optional[str],
        new_inode: Optional[str],
    ) -> bool:
        with self._guard:
            key = (agent_id, log_path, prior_inode, new_inode)
            if key in self._rotated:
                return False
            self._rotated.add(key)
            return True

    def should_emit_orphan(
        self,
        container_id: str,
        pane_composite_key: dict[str, object],
        observed_pipe_target: str,
    ) -> bool:
        with self._guard:
            key = (
                container_id,
                json.dumps(pane_composite_key, sort_keys=True, separators=(",", ":")),
                observed_pipe_target,
            )
            if key in self._orphans:
                return False
            self._orphans.add(key)
            return True

    def reset_for_test(self) -> None:
        with self._guard:
            self._missing.clear()
            self._returned.clear()
            self._rotated.clear()
            self._orphans.clear()


_state = _SuppressionState()


def reset_suppression_for_path(agent_id: str, log_path: str) -> None:
    """Clear FR-061 ``log_file_missing`` suppression for ``(agent_id, log_path)``.

    Called by the production attach pipeline when a row leaves ``stale``
    (re-attach, supersede, detach) so a future stale entry can fire one
    fresh ``log_file_missing`` event.
    """
    _state.reset_missing(agent_id, log_path)


def _state_for_test() -> _SuppressionState:
    """Test-only accessor for the suppression state."""
    return _state


# ---------------------------------------------------------------------------
# Emission helpers (FR-046 / FR-061).
# ---------------------------------------------------------------------------


def emit_log_rotation_detected(
    logger: LifecycleLogger | None,
    *,
    agent_id: str,
    log_path: str,
    prior_inode: Optional[str],
    new_inode: Optional[str],
    prior_size: int,
    new_size: int,
) -> bool:
    """Emit ``log_rotation_detected`` (FR-024 / FR-025) with FR-061 suppression.

    Returns True if the event was actually emitted, False if dropped (logger
    absent OR FR-061 suppression). Callers that need to surface emit/suppress
    in their own result types use this signal.
    """
    if logger is None:
        return False
    if not _state.should_emit_rotation(agent_id, log_path, prior_inode, new_inode):
        return False
    logger.emit(
        EVENT_LOG_ROTATION_DETECTED,
        level="info",
        agent_id=agent_id,
        log_path=log_path,
        prior_inode=prior_inode if prior_inode is not None else "null",
        new_inode=new_inode if new_inode is not None else "null",
        prior_size=prior_size,
        new_size=new_size,
    )
    return True


def emit_log_file_missing(
    logger: LifecycleLogger | None,
    *,
    agent_id: str,
    log_path: str,
    last_known_inode: Optional[str],
    last_known_size: int,
) -> bool:
    """Emit ``log_file_missing`` (FR-026) with FR-061 per-stale-entry suppression."""
    if logger is None:
        return False
    if not _state.should_emit_missing(agent_id, log_path):
        return False
    logger.emit(
        EVENT_LOG_FILE_MISSING,
        level="warn",
        agent_id=agent_id,
        log_path=log_path,
        last_known_inode=last_known_inode if last_known_inode is not None else "null",
        last_known_size=last_known_size,
    )
    return True


def emit_log_file_returned(
    logger: LifecycleLogger | None,
    *,
    agent_id: str,
    log_path: str,
    prior_inode: Optional[str],
    new_inode: str,
    new_size: int,
) -> bool:
    """Emit ``log_file_returned`` (FR-026) with FR-046 triple suppression."""
    if logger is None:
        return False
    if not _state.should_emit_returned(agent_id, log_path, new_inode):
        return False
    logger.emit(
        EVENT_LOG_FILE_RETURNED,
        level="info",
        agent_id=agent_id,
        log_path=log_path,
        prior_inode=prior_inode if prior_inode is not None else "null",
        new_inode=new_inode,
        new_size=new_size,
    )
    return True


def emit_log_attachment_orphan_detected(
    logger: LifecycleLogger | None,
    *,
    container_id: str,
    pane_composite_key: dict[str, object],
    observed_pipe_target: str,
    pane_short_form: str,
) -> None:
    """Emit ``log_attachment_orphan_detected`` (FR-043) with per-lifetime suppression."""
    if logger is None:
        return
    if not _state.should_emit_orphan(container_id, pane_composite_key, observed_pipe_target):
        return
    logger.emit(
        EVENT_LOG_ATTACHMENT_ORPHAN_DETECTED,
        level="warn",
        container_id=container_id,
        pane_composite_key=pane_composite_key,
        pane_short_form=pane_short_form,
        observed_pipe_target=observed_pipe_target,
    )


def emit_mounts_json_oversized(
    logger: LifecycleLogger | None,
    *,
    container_id: str,
    observed_count: int,
    max_count: int,
) -> None:
    """Emit ``mounts_json_oversized`` (FR-063)."""
    if logger is None:
        return
    logger.emit(
        EVENT_MOUNTS_JSON_OVERSIZED,
        level="warn",
        container_id=container_id,
        observed_count=observed_count,
        max_count=max_count,
    )


def emit_socket_peer_uid_mismatch(
    logger: LifecycleLogger | None,
    *,
    observed_uid: int,
    expected_uid: int,
) -> None:
    """Emit ``socket_peer_uid_mismatch`` (FR-058)."""
    if logger is None:
        return
    logger.emit(
        EVENT_SOCKET_PEER_UID_MISMATCH,
        level="error",
        observed_uid=observed_uid,
        expected_uid=expected_uid,
    )


def reset_for_test() -> None:
    """Drop all FR-061 suppression state. Tests call between scenarios."""
    _state.reset_for_test()
