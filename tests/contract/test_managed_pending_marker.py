"""FEAT-013 pending-managed marker contract test (T019).

Covers FR-014 marker format + parsing (the FEAT-004 scan must be able
to detect ``@MANAGED:<token>:<label>`` titles and skip pending panes),
plus the FR-022 5-minute TTL constant + sweep cadence.

The actual SQLite sweep loop is wired by T050 (Phase 6); this contract
exercises only the format / parsing / constants — what the scan and the
service.py spawn path depend on.
"""

from __future__ import annotations

import pytest

from agenttower.managed_sessions.pending_marker import (
    MARKER_TITLE_PREFIX,
    MARKER_TTL_SECONDS,
    SWEEP_INTERVAL_SECONDS,
    format_title,
    is_marker_title,
    new_marker_token,
    parse_title,
)


# ─── Constants (FR-022 + research §R5) ────────────────────────────────────


def test_ttl_is_five_minutes() -> None:
    """FR-022 sweep TTL = 5 minutes = 300 seconds."""
    assert MARKER_TTL_SECONDS == 300


def test_sweep_interval_is_60_seconds() -> None:
    """Research §R5: sweep runs every 60s + at boot."""
    assert SWEEP_INTERVAL_SECONDS == 60


def test_marker_prefix_constant() -> None:
    assert MARKER_TITLE_PREFIX == "@MANAGED:"


# ─── Token generation ────────────────────────────────────────────────────


def test_new_marker_token_is_unique() -> None:
    tokens = {new_marker_token() for _ in range(100)}
    assert len(tokens) == 100  # 100 distinct uuid4 values


def test_new_marker_token_is_non_empty_string() -> None:
    tok = new_marker_token()
    assert isinstance(tok, str)
    assert tok


# ─── Title format + parse round-trip ─────────────────────────────────────


def test_format_title_with_uuid_token_and_label() -> None:
    title = format_title("abc-123", "m1")
    assert title == "@MANAGED:abc-123:m1"


def test_parse_round_trip() -> None:
    """parse_title(format_title(t, l)) == (t, l)."""
    title = format_title("tok-xyz", "s2")
    parsed = parse_title(title)
    assert parsed == ("tok-xyz", "s2")


def test_format_title_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        format_title("", "label")


def test_format_title_rejects_empty_label() -> None:
    with pytest.raises(ValueError):
        format_title("token", "")


def test_format_title_rejects_token_with_colon() -> None:
    """``:`` separates the token from the label; tokens with ``:`` would
    confuse the parser."""
    with pytest.raises(ValueError):
        format_title("bad:token", "label")


# ─── Parse rejects non-marker titles ─────────────────────────────────────


def test_parse_returns_none_on_non_marker_title() -> None:
    """FEAT-004 scan: non-marker titles return ``None`` so the scan
    proceeds with normal adoption."""
    assert parse_title("just-a-pane-title") is None
    assert parse_title("@MANAGE:tok:lbl") is None  # close but no cigar
    assert parse_title("") is None


def test_is_marker_title_helper() -> None:
    assert is_marker_title("@MANAGED:tok:lbl")
    assert not is_marker_title("regular-title")
    assert not is_marker_title("")


# ─── Labels with special characters round-trip ──────────────────────────


def test_label_with_hyphens_and_dots_round_trips() -> None:
    """Labels resolved from operator templates can contain ``[A-Za-z0-9_.-]``
    per FR-016 amendment; the marker format must round-trip them."""
    title = format_title("uuid-1234", "host.example.com-m1")
    assert parse_title(title) == ("uuid-1234", "host.example.com-m1")


def test_label_with_colon_round_trips_via_greedy_match() -> None:
    """If a label contains ``:`` (rare; allowed character set excludes ``:``
    but be defensive), the parser greedy-matches everything after the
    first ``:`` as the label."""
    # This case is theoretical — FR-016 amendment disallows ``:`` in
    # operator-supplied labels — but the parser shouldn't crash if a
    # legacy title slips through.
    title = "@MANAGED:tok:label:with:colons"
    parsed = parse_title(title)
    assert parsed == ("tok", "label:with:colons")


# ─── FR-014 + T034: FEAT-004 scan integration ────────────────────────────


def test_feat004_scan_filter_strips_pending_managed_panes() -> None:
    """T034: FEAT-004's ``_filter_pending_managed_panes`` helper drops any
    pane whose title starts with ``@MANAGED:``. Verifies the cross-FEAT
    contract — the FEAT-013 marker prefix MUST be filterable by the
    FEAT-004 scan with no SQLite cross-check (research §R1: the title
    is the scan-side mirror; SQLite is the authoritative source).
    """
    from agenttower.discovery.pane_service import _filter_pending_managed_panes
    from agenttower.tmux.parsers import ParsedPane

    def pp(title: str) -> ParsedPane:
        return ParsedPane(
            tmux_session_name="session-a",
            tmux_window_index=0,
            tmux_pane_index=0,
            tmux_pane_id="%1",
            pane_pid=1234,
            pane_tty="/dev/pts/0",
            pane_current_command="bash",
            pane_current_path="/workspace",
            pane_title=title,
            pane_active=False,
        )

    inputs = [
        pp("m1"),                        # bare label — kept
        pp("@MANAGED:abc-123:m2"),       # pending-managed — skipped
        pp("s1"),                        # bare label — kept
        pp("@MANAGED:xyz-456:s2"),       # pending-managed — skipped
        pp(""),                          # empty title (edge case) — kept
        pp("@MANAGED:no-label"),         # missing-label variant — skipped (prefix matches)
    ]
    kept, skipped = _filter_pending_managed_panes(inputs)
    assert skipped == 3
    assert [p.pane_title for p in kept] == ["m1", "s1", ""]


def test_feat004_filter_returns_immutable_tuple() -> None:
    """The filter helper returns a ``tuple`` (not a list) so callers can
    reuse it directly in ``OkSocketScan(panes=...)`` which expects a
    sequence shape consistent with the unfiltered output."""
    from agenttower.discovery.pane_service import _filter_pending_managed_panes

    kept, _skipped = _filter_pending_managed_panes([])
    assert isinstance(kept, tuple)
    assert kept == ()


# ─── FR-022 / T050 — sweep() ────────────────────────────────────────────


import datetime as _dt
import sqlite3
import uuid

from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
)
from agenttower.managed_sessions.pending_marker import SweepOutcome, sweep
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


def _ts(when: _dt.datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.UTC)
    return when.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _make_test_conn():  # type: ignore[no-untyped-def]
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    _apply_migration_v9(c)
    return c


def _seed_creating_pane(
    conn,  # type: ignore[no-untyped-def]
    *,
    container_id: str = "bench-alpha",
    created_at: _dt.datetime,
    agent_id: str | None = None,
) -> str:
    layout_id = str(uuid.uuid4())
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id,
            container_id=container_id,
            template_name="1m+2s",
            intended_pane_count=1,
            state=ManagedState.CREATING,
            failed_stage=None,
            idempotency_key=None,
            created_at=_ts(created_at),
            updated_at=_ts(created_at),
        ),
    )
    if agent_id is not None:
        conn.execute("INSERT INTO agents (agent_id) VALUES (?)", (agent_id,))
    pane_id = str(uuid.uuid4())
    insert_pane(
        conn,
        ManagedPaneRow(
            id=pane_id,
            layout_id=layout_id,
            container_id=container_id,
            agent_id=agent_id,
            role="master",
            capability="orchestrator",
            label="m1",
            launch_command_ref=None,
            tmux_session_name="sweep-test",
            tmux_pane_index=0,
            pending_marker_token=str(uuid.uuid4()),
            state=ManagedState.CREATING,
            failed_stage=None,
            predecessor_id=None,
            chain_depth=0,
            created_at=_ts(created_at),
            updated_at=_ts(created_at),
        ),
    )
    conn.commit()
    return pane_id


def test_sweep_skips_fresh_markers():
    """A pane younger than 5 minutes is untouched by the sweep."""
    conn = _make_test_conn()
    now = _dt.datetime.now(_dt.UTC)
    _seed_creating_pane(conn, created_at=now - _dt.timedelta(seconds=30))

    out = sweep(conn)

    assert isinstance(out, SweepOutcome)
    assert out.panes_examined == 0
    assert out.panes_swept == 0
    row = conn.execute("SELECT state FROM managed_pane").fetchone()
    assert row[0] == "creating"


def test_sweep_transitions_stale_to_failed_with_pane_create_when_unregistered():
    """A stale pane with `agent_id IS NULL` (registration never happened)
    → failed_stage=pane_create."""
    conn = _make_test_conn()
    now = _dt.datetime.now(_dt.UTC)
    pane_id = _seed_creating_pane(
        conn,
        created_at=now - _dt.timedelta(minutes=10),
        agent_id=None,
    )

    out = sweep(conn)

    assert out.panes_swept == 1
    assert out.pane_create_failures == 1
    assert out.registration_failures == 0
    row = conn.execute(
        "SELECT state, failed_stage, pending_marker_token FROM managed_pane WHERE id = ?",
        (pane_id,),
    ).fetchone()
    assert row[0] == "failed"
    assert row[1] == "pane_create"
    assert row[2] is None  # marker cleared per CHECK invariant


def test_sweep_transitions_stale_to_failed_with_registration_when_registered():
    """A stale pane WITH `agent_id` set (registration ran; spawn task
    didn't finish) → failed_stage=registration."""
    conn = _make_test_conn()
    now = _dt.datetime.now(_dt.UTC)
    pane_id = _seed_creating_pane(
        conn,
        created_at=now - _dt.timedelta(minutes=10),
        agent_id="agent-stale-reg",
    )

    out = sweep(conn)

    assert out.panes_swept == 1
    assert out.pane_create_failures == 0
    assert out.registration_failures == 1
    row = conn.execute(
        "SELECT state, failed_stage FROM managed_pane WHERE id = ?",
        (pane_id,),
    ).fetchone()
    assert row[0] == "failed"
    assert row[1] == "registration"


def test_sweep_at_exactly_ttl_treats_as_stale():
    """Boundary: a pane EXACTLY at the TTL is swept (`created_at < cutoff`
    means anything not strictly newer; a pane at the cutoff is older or
    equal and thus stale)."""
    conn = _make_test_conn()
    now = _dt.datetime.now(_dt.UTC)
    _seed_creating_pane(
        conn,
        # Created 5min1sec ago — comfortably past the 5min TTL.
        created_at=now - _dt.timedelta(seconds=5 * 60 + 1),
    )

    out = sweep(conn)
    assert out.panes_swept == 1


def test_sweep_is_idempotent():
    """A second sweep on already-swept rows is a no-op (the WHERE clause
    filters to state='creating'; swept rows are now 'failed')."""
    conn = _make_test_conn()
    now = _dt.datetime.now(_dt.UTC)
    _seed_creating_pane(conn, created_at=now - _dt.timedelta(minutes=10))

    sweep(conn)
    second = sweep(conn)
    assert second.panes_examined == 0
    assert second.panes_swept == 0


def test_sweep_with_injectable_clock():
    """Clock injection lets tests advance time deterministically (used by
    the daemon-boot wiring path + perf-marker tasks)."""
    conn = _make_test_conn()
    # Seed a pane "now".
    real_now = _dt.datetime.now(_dt.UTC)
    _seed_creating_pane(conn, created_at=real_now)

    # First sweep with clock at real_now+30s → not stale.
    out_fresh = sweep(conn, clock=lambda: real_now + _dt.timedelta(seconds=30))
    assert out_fresh.panes_swept == 0

    # Second sweep with clock at real_now+10min → stale.
    out_stale = sweep(conn, clock=lambda: real_now + _dt.timedelta(minutes=10))
    assert out_stale.panes_swept == 1
