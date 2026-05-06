"""Pure reconciliation function for FEAT-004 pane scans (R-008).

Given the prior SQLite state and the per-(container, socket) scan
outcomes, compute the write set the SQLite layer must apply (in one
transaction). No SQL, no I/O. Sanitization + truncation runs here so the
service layer stays focused on transaction boundaries and audit emit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..state.panes import (
    PaneCompositeKey,
    PaneReconcileWriteSet,
    PaneTruncationNote,
    PaneUpsert,
    PriorPaneRow,
)
from ..tmux import (
    FailedSocketScan,
    MAX_COMMAND,
    MAX_DEFAULT,
    MAX_PATH,
    MAX_TITLE,
    OkSocketScan,
    ParsedPane,
    SocketScanOutcome,
    sanitize_text,
)


@dataclass(frozen=True)
class ContainerMeta:
    """Per-container convenience metadata refreshed on every successful upsert."""

    container_name: str
    container_user: str


_FIELD_LIMITS = {
    "tmux_session_name": MAX_DEFAULT,
    "tmux_pane_id": MAX_DEFAULT,
    "pane_tty": MAX_DEFAULT,
    "pane_current_command": MAX_COMMAND,
    "pane_current_path": MAX_PATH,
    "pane_title": MAX_TITLE,
    "container_name": MAX_DEFAULT,
    "container_user": MAX_DEFAULT,
}


def reconcile(
    *,
    prior_panes: Mapping[PaneCompositeKey, PriorPaneRow],
    socket_results: Mapping[tuple[str, str], SocketScanOutcome],
    tmux_unavailable_containers: set[str],
    inactive_cascade_containers: set[str],
    container_metadata: Mapping[str, ContainerMeta],
    now_iso: str,
) -> PaneReconcileWriteSet:
    """Compute the FEAT-004 write set per data-model §5."""
    upserts: list[PaneUpsert] = []
    touch_only: list[PaneCompositeKey] = []
    inactivate: list[PaneCompositeKey] = []
    truncations: list[PaneTruncationNote] = []
    panes_newly_active = 0

    # ------------------------------------------------------------------
    # 1. Successful per-(container, socket) scans → upserts + per-socket
    #    inactivate set for prior rows that disappeared from the parsed set.
    # ------------------------------------------------------------------
    for (container_id, socket_path), outcome in socket_results.items():
        if not isinstance(outcome, OkSocketScan):
            continue
        meta = container_metadata.get(
            container_id, ContainerMeta(container_name="", container_user="")
        )
        parsed_keys: set[PaneCompositeKey] = set()
        for parsed in outcome.panes:
            upsert, pane_truncations = _build_upsert(
                container_id=container_id,
                socket_path=socket_path,
                meta=meta,
                parsed=parsed,
                now_iso=now_iso,
            )
            upserts.append(upsert)
            truncations.extend(pane_truncations)
            parsed_keys.add(upsert.composite_key)
            prior_row = prior_panes.get(upsert.composite_key)
            if prior_row is None or not prior_row.active:
                panes_newly_active += 1

        # Per-socket inactivate: prior rows on this (container, socket)
        # that were active and are not in the parsed set.
        for key, prior_row in prior_panes.items():
            if key[0] != container_id or key[1] != socket_path:
                continue
            if not prior_row.active:
                continue
            if key in parsed_keys:
                continue
            inactivate.append(key)

    # ------------------------------------------------------------------
    # 2. Failed per-(container, socket) scans whose container is otherwise
    #    reachable → touch_only for sibling-socket preservation (FR-011).
    # ------------------------------------------------------------------
    for (container_id, socket_path), outcome in socket_results.items():
        if not isinstance(outcome, FailedSocketScan):
            continue
        if container_id in tmux_unavailable_containers:
            continue
        if container_id in inactive_cascade_containers:
            continue
        for key in prior_panes.keys():
            if key[0] != container_id or key[1] != socket_path:
                continue
            touch_only.append(key)

    # ------------------------------------------------------------------
    # 3. tmux_unavailable containers → preserve every prior row regardless
    #    of socket (FR-010).
    # ------------------------------------------------------------------
    for container_id in tmux_unavailable_containers:
        if container_id in inactive_cascade_containers:
            continue
        for key in prior_panes.keys():
            if key[0] != container_id:
                continue
            touch_only.append(key)

    # ------------------------------------------------------------------
    # 4. Inactive-container cascade → flip prior active rows; touch the rest.
    # ------------------------------------------------------------------
    for container_id in inactive_cascade_containers:
        for key, prior_row in prior_panes.items():
            if key[0] != container_id:
                continue
            if prior_row.active:
                inactivate.append(key)
            else:
                touch_only.append(key)

    # ------------------------------------------------------------------
    # 5. Disappeared-socket inactivation (data-model §5 step 5):
    #    a container that was scanned (has at least one socket_results
    #    entry) AND is otherwise reachable, but whose prior pane refers
    #    to a socket that is no longer enumerated, MUST flip its active
    #    rows to inactive (and touch its inactive rows). This is the
    #    `tmux -L work kill-server` case (quickstart §3).
    # ------------------------------------------------------------------
    scanned_containers: set[str] = {c for (c, _s) in socket_results.keys()}
    sockets_by_container: dict[str, set[str]] = {}
    for (c, s) in socket_results.keys():
        sockets_by_container.setdefault(c, set()).add(s)
    for container_id in scanned_containers:
        if container_id in tmux_unavailable_containers:
            continue
        if container_id in inactive_cascade_containers:
            continue
        observed = sockets_by_container.get(container_id, set())
        for key, prior_row in prior_panes.items():
            if key[0] != container_id:
                continue
            if key[1] in observed:
                continue
            if prior_row.active:
                inactivate.append(key)
            else:
                touch_only.append(key)

    # ------------------------------------------------------------------
    # 6. Counters.
    # ------------------------------------------------------------------
    panes_seen = len(upserts)
    panes_reconciled_inactive = len(inactivate)
    containers_skipped_inactive = len(
        {c for c in inactive_cascade_containers if any(k[0] == c for k in prior_panes)}
    )
    containers_tmux_unavailable = len(
        tmux_unavailable_containers - inactive_cascade_containers
    )

    return PaneReconcileWriteSet(
        upserts=upserts,
        touch_only=touch_only,
        inactivate=inactivate,
        pane_truncations=truncations,
        panes_seen=panes_seen,
        panes_newly_active=panes_newly_active,
        panes_reconciled_inactive=panes_reconciled_inactive,
        containers_skipped_inactive=containers_skipped_inactive,
        containers_tmux_unavailable=containers_tmux_unavailable,
    )


def _build_upsert(
    *,
    container_id: str,
    socket_path: str,
    meta: ContainerMeta,
    parsed: ParsedPane,
    now_iso: str,
) -> tuple[PaneUpsert, list[PaneTruncationNote]]:
    truncations: list[PaneTruncationNote] = []

    def _clean(field: str, value: str, max_length: int) -> str:
        cleaned, truncated = sanitize_text(value, max_length)
        if truncated:
            truncations.append(
                PaneTruncationNote(
                    tmux_pane_id=parsed.tmux_pane_id,
                    field=field,
                    original_len=len(_strip_only(value)),
                )
            )
        return cleaned

    upsert = PaneUpsert(
        container_id=container_id,
        tmux_socket_path=socket_path,
        tmux_session_name=_clean(
            "tmux_session_name", parsed.tmux_session_name, MAX_DEFAULT
        ),
        tmux_window_index=parsed.tmux_window_index,
        tmux_pane_index=parsed.tmux_pane_index,
        tmux_pane_id=_clean("tmux_pane_id", parsed.tmux_pane_id, MAX_DEFAULT),
        container_name=_clean("container_name", meta.container_name, MAX_DEFAULT),
        container_user=_clean("container_user", meta.container_user, MAX_DEFAULT),
        pane_pid=parsed.pane_pid,
        pane_tty=_clean("pane_tty", parsed.pane_tty, MAX_DEFAULT),
        pane_current_command=_clean(
            "pane_current_command", parsed.pane_current_command, MAX_COMMAND
        ),
        pane_current_path=_clean(
            "pane_current_path", parsed.pane_current_path, MAX_PATH
        ),
        pane_title=_clean("pane_title", parsed.pane_title, MAX_TITLE),
        pane_active=parsed.pane_active,
        last_scanned_at=now_iso,
    )
    return upsert, truncations


def _strip_only(value: str) -> str:
    """Helper for `original_len`: count characters that survive byte-stripping
    but pre-truncation (so `original_len` reflects the user-visible length
    that triggered truncation, not the raw byte count)."""
    if value is None:
        return ""
    out: list[str] = []
    for ch in value:
        ord_ch = ord(ch)
        if ord_ch == 0x00:
            continue
        if ch == "\t" or ch == "\n":
            out.append(" ")
            continue
        if ord_ch < 0x20 or ord_ch == 0x7F:
            continue
        out.append(ch)
    return "".join(out)
