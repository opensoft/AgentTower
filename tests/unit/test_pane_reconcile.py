"""Unit tests for FEAT-004 reconcile pure function (T018 / FR-007 / FR-008)."""

from __future__ import annotations

from agenttower.discovery.pane_reconcile import ContainerMeta, reconcile
from agenttower.state.panes import PriorPaneRow
from agenttower.tmux import FailedSocketScan, OkSocketScan, ParsedPane


def _pane(pane_id: str, *, active: bool = False) -> ParsedPane:
    return ParsedPane(
        tmux_session_name="work",
        tmux_window_index=0,
        tmux_pane_index=int(pane_id.lstrip("%")) if pane_id.lstrip("%").isdigit() else 0,
        tmux_pane_id=pane_id,
        pane_pid=1234,
        pane_tty="/dev/pts/0",
        pane_current_command="bash",
        pane_current_path="/workspace",
        pane_title="title",
        pane_active=active,
    )


def _meta() -> ContainerMeta:
    return ContainerMeta(container_name="bench", container_user="user")


_CONTAINER = "c1"
_SOCKET = "/tmp/tmux-1000/default"
_SOCKET_DEFAULT = "/tmp/tmux-1000/default"
_SOCKET_WORK = "/tmp/tmux-1000/work"
_NOW = "2026-05-06T10:00:00.000000+00:00"


def test_transition_a_inactive_flip_when_pane_disappears() -> None:
    """Prior active pane absent from a successful socket scan → inactivate."""
    prior = {
        (_CONTAINER, _SOCKET, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        socket_results={(_CONTAINER, _SOCKET): OkSocketScan(panes=())},  # empty
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert write_set.upserts == []
    assert (_CONTAINER, _SOCKET, "work", 0, 0, "%0") in write_set.inactivate
    assert write_set.panes_reconciled_inactive == 1
    assert write_set.panes_seen == 0


def test_transition_b_refresh_when_pane_present() -> None:
    """Pane present in parsed set → upsert (full row refresh; active stays 1)."""
    prior = {
        (_CONTAINER, _SOCKET, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        socket_results={(_CONTAINER, _SOCKET): OkSocketScan(panes=(_pane("%0"),))},
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert len(write_set.upserts) == 1
    assert write_set.inactivate == []
    assert write_set.panes_seen == 1
    # Pre-existing active rows do not bump panes_newly_active counter.
    assert write_set.panes_newly_active == 0


def test_panes_newly_active_counts_first_time_panes() -> None:
    write_set = reconcile(
        prior_panes={},
        socket_results={
            (_CONTAINER, _SOCKET): OkSocketScan(
                panes=(_pane("%0"), _pane("%1"))
            )
        },
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert write_set.panes_seen == 2
    assert write_set.panes_newly_active == 2


def test_sanitize_and_truncate_records_pane_truncation_note() -> None:
    huge_title = "x" * 5000
    raw = ParsedPane(
        tmux_session_name="work",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id="%0",
        pane_pid=1,
        pane_tty="/dev/pts/0",
        pane_current_command="bash",
        pane_current_path="/workspace",
        pane_title=huge_title,
        pane_active=True,
    )
    write_set = reconcile(
        prior_panes={},
        socket_results={(_CONTAINER, _SOCKET): OkSocketScan(panes=(raw,))},
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert len(write_set.upserts) == 1
    assert len(write_set.pane_truncations) == 1
    note = write_set.pane_truncations[0]
    assert note.field == "pane_title"
    assert note.tmux_pane_id == "%0"
    assert note.original_len == 5000
    # Persisted title is bounded to MAX_TITLE.
    assert len(write_set.upserts[0].pane_title) <= 2048


def test_reconcile_does_not_delete_rows() -> None:
    """FR-008 — reconcile NEVER produces a delete write."""
    prior = {
        (_CONTAINER, _SOCKET, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        socket_results={(_CONTAINER, _SOCKET): OkSocketScan(panes=())},
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    # The only "removal" is an inactivate (active flag flip). No delete attribute.
    assert hasattr(write_set, "inactivate")
    assert not hasattr(write_set, "delete")


# ---------------------------------------------------------------------------
# US2 multi-socket reconciliation (T028).
# ---------------------------------------------------------------------------


def test_two_ok_socket_scans_on_same_container_union_upserts() -> None:
    """Two successful sockets on one container → upserts cover both, no inactivate."""
    write_set = reconcile(
        prior_panes={},
        socket_results={
            (_CONTAINER, _SOCKET_DEFAULT): OkSocketScan(
                panes=(_pane("%0"), _pane("%1"))
            ),
            (_CONTAINER, _SOCKET_WORK): OkSocketScan(
                panes=(_pane("%2"),)
            ),
        },
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    sockets_in_upserts = {u.tmux_socket_path for u in write_set.upserts}
    assert sockets_in_upserts == {_SOCKET_DEFAULT, _SOCKET_WORK}
    assert len(write_set.upserts) == 3
    assert write_set.inactivate == []
    assert write_set.panes_seen == 3
    assert write_set.panes_newly_active == 3


def test_ok_plus_failed_socket_preserves_failed_socket_prior_panes() -> None:
    """FR-011 — failed sibling socket → prior panes go to touch_only, untouched.

    The OkSocketScan socket's panes upsert (or inactivate if missing); the
    FailedSocketScan socket's prior rows must NOT be inactivated because the
    container itself is reachable (per data-model §4.1 transition (e)).
    """
    prior = {
        # OkSocketScan side: one prior pane that will be re-seen (refresh).
        (_CONTAINER, _SOCKET_DEFAULT, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
        # FailedSocketScan side: one active + one inactive prior pane that
        # must be preserved as-is (sibling-socket preservation).
        (_CONTAINER, _SOCKET_WORK, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
        (_CONTAINER, _SOCKET_WORK, "work", 0, 1, "%1"): PriorPaneRow(
            active=False, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        socket_results={
            (_CONTAINER, _SOCKET_DEFAULT): OkSocketScan(panes=(_pane("%0"),)),
            (_CONTAINER, _SOCKET_WORK): FailedSocketScan(
                error_code="tmux_socket_scan_failed",
                error_message="boom",
            ),
        },
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    upsert_keys = {u.composite_key for u in write_set.upserts}
    assert (_CONTAINER, _SOCKET_DEFAULT, "work", 0, 0, "%0") in upsert_keys
    # No prior pane on the failed socket may appear in inactivate.
    failed_socket_keys = {
        (_CONTAINER, _SOCKET_WORK, "work", 0, 0, "%0"),
        (_CONTAINER, _SOCKET_WORK, "work", 0, 1, "%1"),
    }
    assert failed_socket_keys.isdisjoint(set(write_set.inactivate))
    # Both prior rows on the failed socket land in touch_only (active flag
    # unchanged because touch_only never flips active).
    touch_set = set(write_set.touch_only)
    assert failed_socket_keys.issubset(touch_set)


def test_pane_id_reused_across_distinct_sockets_yields_distinct_composite_keys() -> None:
    """FR-007 — `%0` reused across two sockets → two separate upsert rows."""
    write_set = reconcile(
        prior_panes={},
        socket_results={
            (_CONTAINER, _SOCKET_DEFAULT): OkSocketScan(panes=(_pane("%0"),)),
            (_CONTAINER, _SOCKET_WORK): OkSocketScan(panes=(_pane("%0"),)),
        },
        tmux_unavailable_containers=set(),
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert len(write_set.upserts) == 2
    composite_keys = [u.composite_key for u in write_set.upserts]
    assert composite_keys[0] != composite_keys[1]
    sockets_in_keys = {key[1] for key in composite_keys}
    assert sockets_in_keys == {_SOCKET_DEFAULT, _SOCKET_WORK}
    # All other components of the composite key match — only socket differs.
    for i in (0, 2, 3, 4, 5):
        assert composite_keys[0][i] == composite_keys[1][i]


def test_tmux_unavailable_container_takes_precedence_over_sibling_preservation() -> None:
    """FR-010 path beats FR-011 path: every prior row → touch_only, none inactivate."""
    prior = {
        (_CONTAINER, _SOCKET_DEFAULT, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
        (_CONTAINER, _SOCKET_WORK, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
        (_CONTAINER, _SOCKET_WORK, "work", 0, 1, "%1"): PriorPaneRow(
            active=False, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        # Both sockets failed — but socket_results entries are not strictly
        # required to drive the FR-010 path; the container being in
        # tmux_unavailable_containers is what matters.
        socket_results={
            (_CONTAINER, _SOCKET_DEFAULT): FailedSocketScan(
                error_code="tmux_socket_scan_failed", error_message="x"
            ),
            (_CONTAINER, _SOCKET_WORK): FailedSocketScan(
                error_code="tmux_socket_scan_failed", error_message="y"
            ),
        },
        tmux_unavailable_containers={_CONTAINER},
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert write_set.upserts == []
    assert write_set.inactivate == []
    touch_set = set(write_set.touch_only)
    assert touch_set == set(prior.keys())


# ---------------------------------------------------------------------------
# US3 (T033) FR-009 / FR-010 / FR-011 cascade and preservation transitions.
# ---------------------------------------------------------------------------


def test_fr009_cascade_inactivates_active_panes_and_touches_inactive() -> None:
    """FR-009 transition (c) — inactive-container cascade flips active prior
    rows and touches inactive prior rows; no docker exec is invoked (no entry
    in socket_results), and counters reflect a single skipped container."""
    prior = {
        (_CONTAINER, _SOCKET, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
        (_CONTAINER, _SOCKET, "work", 0, 1, "%1"): PriorPaneRow(
            active=False, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        # Empty: no per-(container,socket) scan was issued for the cascade
        # container — i.e., no docker exec ran for c1.
        socket_results={},
        tmux_unavailable_containers=set(),
        inactive_cascade_containers={_CONTAINER},
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert write_set.upserts == []
    active_key = (_CONTAINER, _SOCKET, "work", 0, 0, "%0")
    inactive_key = (_CONTAINER, _SOCKET, "work", 0, 1, "%1")
    assert active_key in write_set.inactivate
    assert inactive_key not in write_set.inactivate
    assert inactive_key in write_set.touch_only
    assert write_set.containers_skipped_inactive == 1
    assert write_set.containers_tmux_unavailable == 0


def test_fr009_cascade_does_not_count_containers_without_prior_panes() -> None:
    """containers_skipped_inactive counts only cascade containers that
    actually had prior panes (data-model §3.5 / §5 intersection rule)."""
    prior = {
        (_CONTAINER, _SOCKET, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        socket_results={},
        tmux_unavailable_containers=set(),
        # c2 has no prior_panes rows so it should not be counted.
        inactive_cascade_containers={_CONTAINER, "c2"},
        container_metadata={_CONTAINER: _meta(), "c2": _meta()},
        now_iso=_NOW,
    )
    assert write_set.containers_skipped_inactive == 1
    assert write_set.containers_tmux_unavailable == 0
    # The single c1 active prior row still flips.
    assert (_CONTAINER, _SOCKET, "work", 0, 0, "%0") in write_set.inactivate
    assert write_set.upserts == []


def test_fr010_tmux_unavailable_does_not_invoke_inactivate() -> None:
    """FR-010 transition (d) — tmux-unavailable container preserves all prior
    rows: no inactivates, both prior rows go to touch_only, counter == 1."""
    prior = {
        (_CONTAINER, _SOCKET, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
        (_CONTAINER, _SOCKET, "work", 0, 1, "%1"): PriorPaneRow(
            active=False, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        # No per-socket scan attempted — container marked unavailable upstream.
        socket_results={},
        tmux_unavailable_containers={_CONTAINER},
        inactive_cascade_containers=set(),
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    assert write_set.upserts == []
    assert write_set.inactivate == []
    touch_set = set(write_set.touch_only)
    assert touch_set == set(prior.keys())
    assert write_set.containers_skipped_inactive == 0
    assert write_set.containers_tmux_unavailable == 1


def test_counters_disjoint_when_one_container_is_both_unavailable_and_cascade() -> None:
    """Cascade wins over tmux-unavailable when a container is in both sets
    (data-model §4.1 transition (c) precedence; §3.5 counter formula:
    `containers_tmux_unavailable = len(tmux_unavailable - inactive_cascade)`)."""
    prior = {
        (_CONTAINER, _SOCKET, "work", 0, 0, "%0"): PriorPaneRow(
            active=True, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
        (_CONTAINER, _SOCKET, "work", 0, 1, "%1"): PriorPaneRow(
            active=False, first_seen_at="2026-01-01T00:00:00+00:00"
        ),
    }
    write_set = reconcile(
        prior_panes=prior,
        socket_results={},
        tmux_unavailable_containers={_CONTAINER},
        inactive_cascade_containers={_CONTAINER},
        container_metadata={_CONTAINER: _meta()},
        now_iso=_NOW,
    )
    # Cascade path runs: active row flips, inactive row touches.
    active_key = (_CONTAINER, _SOCKET, "work", 0, 0, "%0")
    inactive_key = (_CONTAINER, _SOCKET, "work", 0, 1, "%1")
    assert active_key in write_set.inactivate
    assert inactive_key in write_set.touch_only
    assert write_set.upserts == []
    # Counter precedence: c1 counted under cascade, NOT under tmux-unavailable.
    assert write_set.containers_skipped_inactive == 1
    assert write_set.containers_tmux_unavailable == 0
