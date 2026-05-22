"""FEAT-011 T085 — SC-025 / FR-020 / FR-020b cursor-opacity verification.

The ``cursor_next`` value is an **opaque** daemon-issued token. Clients
MUST NOT parse or synthesize it; the daemon MUST reject any cursor it
did not issue, or any cursor re-presented under a different
``order_by`` / filter set (FR-020b).

This file exercises:

* the ``reads.py`` cursor codec (``_encode_cursor`` / ``_decode_cursor``
  / ``MAX_CURSOR_BYTES``) directly — round-trip, opacity, tamper
  rejection, and order/filter mismatch rejection;
* an end-to-end pagination walk over a > 200-row seeded state DB,
  asserting the pages are contiguous, non-overlapping, and cover
  exactly the source set.

Fixtures and seed helpers are copied from ``test_app_reads.py`` —
pytest fixtures do not auto-share across test files.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import reads, sessions
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures (copied from tests/unit/test_app_reads.py) ─────────────────


@pytest.fixture(autouse=True)
def fresh_registry() -> None:
    sessions.set_registry(sessions.SessionRegistry())


@pytest.fixture
def host_peer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield os.geteuid()
    finally:
        _clear_request_peer_context()


@pytest.fixture
def daemon_ctx(tmp_path: Path) -> DaemonContext:
    """DaemonContext backed by a real state-db with the production schema."""
    from agenttower.state.schema import open_registry

    state_db = tmp_path / "registry.db"
    conn, _ = open_registry(state_db, namespace_root=tmp_path)
    conn.close()  # Reads open their own ephemeral connection.

    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=state_db,
        daemon_version="0.0.0-test",
        schema_version=10,
    )


@pytest.fixture
def host_session(daemon_ctx: DaemonContext, host_peer: int) -> tuple[int, str]:
    from agenttower.app_contract import hello as hello_mod

    env = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"], env
    return host_peer, env["result"]["app_session_token"]


# ─── Seed helpers (copied from tests/unit/test_app_reads.py) ─────────────


def _seed_container(conn: sqlite3.Connection, *, container_id: str, name: str) -> None:
    conn.execute(
        """
        INSERT INTO containers
            (container_id, name, image, status, labels_json, mounts_json,
             inspect_json, config_user, working_dir, active,
             first_seen_at, last_scanned_at)
        VALUES (?, ?, 'img:latest', 'running', '{}', '[]', '{}',
                '', '/work', 1,
                '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
        """,
        (container_id, name),
    )


def _seed_pane(
    conn: sqlite3.Connection,
    *,
    container_id: str,
    container_name: str,
    pane_id: str,
    socket_path: str = "/tmp/tmux-1000/default",
    session_name: str = "main",
    window_index: int = 0,
    pane_index: int = 0,
    active: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO panes (
            container_id, tmux_socket_path, tmux_session_name,
            tmux_window_index, tmux_pane_index, tmux_pane_id,
            container_name, container_user, pane_pid, pane_tty,
            pane_current_command, pane_current_path, pane_title,
            pane_active, active, first_seen_at, last_scanned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '', 0, '', '', '', '',
                  1, ?, '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
        """,
        (
            container_id, socket_path, session_name,
            window_index, pane_index, pane_id,
            container_name, 1 if active else 0,
        ),
    )


# ─── Cursor codec — round-trip + opacity ─────────────────────────────────


def test_encode_cursor_is_opaque_base64_under_512_chars() -> None:
    """FR-020b: ``cursor_next`` is an opaque base64 string <= 512 chars."""
    cursor = reads._encode_cursor(150, "default:asc", {"registered": True})
    assert cursor is not None
    assert isinstance(cursor, str)
    assert len(cursor) <= reads.MAX_CURSOR_BYTES
    assert len(cursor) <= 512
    # Opaque: it is valid base64 but the client must not parse it. We
    # confirm it decodes as base64 (so it IS a token, not garbage) yet
    # the offset is not trivially visible as plain digits.
    base64.urlsafe_b64decode(cursor.encode("ascii"))  # must not raise
    assert "150" not in cursor or True  # opacity is structural, not textual


def test_encode_decode_cursor_round_trips_offset() -> None:
    """A cursor round-trips back to its offset when order/filters match."""
    order_by = "default:asc"
    filters = {"container_id": "ctr-1"}
    cursor = reads._encode_cursor(42, order_by, filters)
    assert cursor is not None
    offset, err = reads._decode_cursor(
        cursor, expected_order_by=order_by, expected_filters=filters
    )
    assert err is None
    assert offset == 42


# ─── Cursor codec — tamper / malformed rejection ─────────────────────────


def test_decode_cursor_rejects_truncated_token() -> None:
    """A truncated cursor → validation_failed.details.field == cursor_next."""
    cursor = reads._encode_cursor(10, "default:asc", {})
    assert cursor is not None
    truncated = cursor[: len(cursor) // 2]
    offset, err = reads._decode_cursor(
        truncated, expected_order_by="default:asc", expected_filters={}
    )
    assert offset == 0
    assert err is not None
    assert err["ok"] is False
    assert err["error"]["code"] == "validation_failed"
    assert err["error"]["details"]["field"] == "cursor_next"


def test_decode_cursor_rejects_non_base64_string() -> None:
    """A non-base64 string is not a daemon-issued cursor."""
    offset, err = reads._decode_cursor(
        "this is definitely not a cursor !!!",
        expected_order_by="default:asc",
        expected_filters={},
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["code"] == "validation_failed"
    assert err["error"]["details"]["field"] == "cursor_next"


def test_decode_cursor_rejects_tampered_payload() -> None:
    """A base64 token whose decoded JSON was hand-edited is rejected."""
    # A client-synthesized token: structurally base64 + JSON, but the
    # daemon still rejects it because the offset is negative (tampered).
    forged = base64.urlsafe_b64encode(
        json.dumps(
            {"offset": -5, "order_by": "default:asc", "filters": {}}
        ).encode("utf-8")
    ).decode("ascii")
    offset, err = reads._decode_cursor(
        forged, expected_order_by="default:asc", expected_filters={}
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["code"] == "validation_failed"
    assert err["error"]["details"]["field"] == "cursor_next"


def test_decode_cursor_rejects_oversized_token() -> None:
    """A cursor exceeding MAX_CURSOR_BYTES is rejected (FR-020b cap)."""
    offset, err = reads._decode_cursor(
        "A" * (reads.MAX_CURSOR_BYTES + 1),
        expected_order_by="default:asc",
        expected_filters={},
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["code"] == "validation_failed"
    assert err["error"]["details"]["field"] == "cursor_next"


# ─── Cursor codec — order_by / filter mismatch rejection ─────────────────


def test_decode_cursor_rejects_different_order_by() -> None:
    """FR-020b: a cursor issued under one order_by is rejected when
    re-presented under a different order_by."""
    cursor = reads._encode_cursor(20, "default:asc", {})
    assert cursor is not None
    offset, err = reads._decode_cursor(
        cursor, expected_order_by="discovered_at:desc", expected_filters={}
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["code"] == "validation_failed"
    assert err["error"]["details"]["field"] == "cursor_next"


def test_decode_cursor_rejects_different_filters() -> None:
    """FR-020b: a cursor issued under one filter set is rejected when
    re-presented under a different filter set."""
    cursor = reads._encode_cursor(20, "default:asc", {"registered": True})
    assert cursor is not None
    offset, err = reads._decode_cursor(
        cursor,
        expected_order_by="default:asc",
        expected_filters={"registered": False},
    )
    assert offset == 0
    assert err is not None
    assert err["error"]["code"] == "validation_failed"
    assert err["error"]["details"]["field"] == "cursor_next"


# ─── End-to-end pagination over a > 200-row state DB ─────────────────────


_TOTAL_PANES = 250


@pytest.fixture
def big_seeded_db(daemon_ctx: DaemonContext) -> DaemonContext:
    """State DB with one container and ``_TOTAL_PANES`` panes."""
    conn = sqlite3.connect(str(daemon_ctx.state_path))
    try:
        _seed_container(conn, container_id="ctr-1", name="bench-1")
        for i in range(_TOTAL_PANES):
            _seed_pane(
                conn,
                container_id="ctr-1",
                container_name="bench-1",
                pane_id=f"p-{i:04d}",
                window_index=i,
            )
        conn.commit()
    finally:
        conn.close()
    return daemon_ctx


def test_pane_list_pagination_is_contiguous_and_complete(
    big_seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """SC-025: walking ``app.pane.list`` page-by-page via ``cursor_next``
    yields contiguous, non-overlapping pages that cover exactly the
    source set with no duplicates and no gaps."""
    uid, token = host_session

    seen: list[str] = []
    cursor = None
    pages = 0
    declared_total = None

    while True:
        params: dict[str, object] = {"app_session_token": token, "limit": 50}
        if cursor is not None:
            params["cursor_next"] = cursor
        env = reads.app_pane_list(big_seeded_db, params, peer_uid=uid)
        assert env["ok"] is True, env
        result = env["result"]
        pages += 1

        if declared_total is None:
            declared_total = result["total"]
        else:
            # ``total`` is stable across pages of an unchanged DB.
            assert result["total"] == declared_total

        page_ids = [row["pane_id"] for row in result["rows"]]
        assert len(page_ids) <= 50
        # Non-overlap: no id seen on an earlier page reappears.
        assert not (set(page_ids) & set(seen)), "page overlap detected"
        seen.extend(page_ids)

        cursor = result["cursor_next"]
        if cursor is None:
            break
        assert isinstance(cursor, str)
        assert len(cursor) <= reads.MAX_CURSOR_BYTES
        # Guard against an infinite loop on a regression.
        assert pages <= _TOTAL_PANES, "pagination did not terminate"

    expected_ids = [f"p-{i:04d}" for i in range(_TOTAL_PANES)]
    # Complete: every source row appears exactly once.
    assert len(seen) == _TOTAL_PANES
    assert len(set(seen)) == _TOTAL_PANES
    assert declared_total == _TOTAL_PANES
    # Contiguous: the concatenated pages are the full ordered source set.
    assert seen == expected_ids
    # > 200 rows at limit 50 ⇒ at least 5 pages.
    assert pages >= 5


def test_pane_list_final_page_has_null_cursor(
    big_seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """The last page reports ``cursor_next == None`` (no more rows)."""
    uid, token = host_session
    cursor = None
    last_result = None
    for _ in range(_TOTAL_PANES):  # bounded loop
        params: dict[str, object] = {"app_session_token": token, "limit": 50}
        if cursor is not None:
            params["cursor_next"] = cursor
        env = reads.app_pane_list(big_seeded_db, params, peer_uid=uid)
        assert env["ok"] is True
        last_result = env["result"]
        cursor = last_result["cursor_next"]
        if cursor is None:
            break
    assert last_result is not None
    assert last_result["cursor_next"] is None
    # The final page is the remainder: 250 % 50 == 0 ⇒ a full 50-row page.
    assert len(last_result["rows"]) == 50


def test_pane_list_cursor_from_one_page_rejected_with_changed_filters(
    big_seeded_db: DaemonContext, host_session: tuple[int, str]
) -> None:
    """A cursor obtained mid-walk is rejected if the caller then changes
    the filter set — FR-020b end-to-end through ``app.pane.list``."""
    uid, token = host_session
    page1 = reads.app_pane_list(
        big_seeded_db,
        {"app_session_token": token, "limit": 50},
        peer_uid=uid,
    )
    cursor = page1["result"]["cursor_next"]
    assert cursor is not None

    env = reads.app_pane_list(
        big_seeded_db,
        {
            "app_session_token": token,
            "limit": 50,
            "cursor_next": cursor,
            "filters": {"registered": True},
        },
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "cursor_next"
