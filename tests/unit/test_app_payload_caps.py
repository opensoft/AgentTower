"""FEAT-011 T084 — SC-023 / FR-003a payload-cap verification.

Two halves:

* **Request cap** — the FEAT-002 socket reader stops at
  ``MAX_REQUEST_BYTES``; for an ``app.*`` line that overflows the cap,
  ``server._make_payload_too_large_envelope`` builds the FEAT-011
  ``payload_too_large`` envelope (``details = {size_limit_bytes,
  actual_size_bytes}``). ``server._line_looks_like_app_method`` is the
  peek-detector that routes an oversized/malformed line to that
  envelope. Both helpers are unit-tested directly.
* **Response cap** — a list response built under the FR-020a pagination
  cap (limit ≤ 200) and FR-017 recent cap (recent_limit ≤ 50) stays far
  below the 8 MiB response-line ceiling. We build a worst-case
  ``app.pane.list``-shaped result with 200 plausible rows, JSON-encode
  it, and assert the encoded size is comfortably under 8 MiB.
"""

from __future__ import annotations

import json

from agenttower.socket_api import server as socket_server


# Response-line ceiling for ``app.*`` (FR; 8 MiB).
RESPONSE_LINE_CAP_BYTES = 8 * 1024 * 1024


# ─── Request cap — _make_payload_too_large_envelope ──────────────────────


def test_payload_too_large_envelope_shape() -> None:
    """FR-003a / FR-034a: ``payload_too_large`` envelope is well-formed."""
    observed = socket_server.MAX_REQUEST_BYTES + 1
    env = socket_server._make_payload_too_large_envelope(observed)

    assert env["ok"] is False
    assert env["app_contract_version"] == "1.0"
    err = env["error"]
    assert set(err.keys()) == {"code", "message", "details"}
    assert err["code"] == "payload_too_large"
    assert isinstance(err["message"], str) and err["message"]


def test_payload_too_large_envelope_details_keys_and_types() -> None:
    """``details`` carries exactly the FR-034a-registered keys, both ints."""
    observed = socket_server.MAX_REQUEST_BYTES + 4096
    env = socket_server._make_payload_too_large_envelope(observed)
    details = env["error"]["details"]

    assert isinstance(details, dict)
    assert set(details.keys()) == {"size_limit_bytes", "actual_size_bytes"}
    assert details["size_limit_bytes"] == socket_server.MAX_REQUEST_BYTES
    assert details["actual_size_bytes"] == observed
    assert isinstance(details["size_limit_bytes"], int)
    assert isinstance(details["actual_size_bytes"], int)


def test_payload_too_large_code_is_closed_set_member() -> None:
    """The emitted code must be in the FR-034 closed set."""
    from agenttower.app_contract import errors as app_errors

    env = socket_server._make_payload_too_large_envelope(70000)
    assert env["error"]["code"] in app_errors.ERROR_CODES


# ─── Request cap — _line_looks_like_app_method peek-detection ────────────


def test_line_looks_like_app_method_detects_compact_form() -> None:
    """A compact ``"method":"app.`` line is detected as app-namespace."""
    line = b'{"method":"app.pane.list","params":{}}\n'
    assert socket_server._line_looks_like_app_method(line) is True


def test_line_looks_like_app_method_detects_spaced_form() -> None:
    """A line with ``"method": "app.`` (one space) is also detected."""
    line = b'{"method": "app.agent.detail", "params": {}}\n'
    assert socket_server._line_looks_like_app_method(line) is True


def test_line_looks_like_app_method_false_for_legacy_method() -> None:
    """A legacy (non-``app.*``) method line is not detected."""
    line = b'{"method":"ping","params":{}}\n'
    assert socket_server._line_looks_like_app_method(line) is False


def test_line_looks_like_app_method_false_for_garbage() -> None:
    """Non-JSON garbage with no method literal is not detected."""
    assert socket_server._line_looks_like_app_method(b"not json at all\n") is False


def test_line_looks_like_app_method_detects_within_oversized_head() -> None:
    """The peek finds the literal in the first ~2 KB of an oversized line."""
    line = b'{"method":"app.send_input","params":{"text":"' + b"x" * 200000 + b'"}}\n'
    assert len(line) > socket_server.MAX_REQUEST_BYTES
    assert socket_server._line_looks_like_app_method(line) is True


def test_line_looks_like_app_method_misses_literal_past_scan_window() -> None:
    """The scan is bounded to ~2 KB: a method literal pushed past the
    window is not detected (documented heuristic bound)."""
    padding = b'{"x":"' + b"p" * 4000 + b'",'
    line = padding + b'"method":"app.pane.list"}\n'
    assert socket_server._line_looks_like_app_method(line) is False


# ─── Response cap — list responses stay under 8 MiB ──────────────────────


def _worst_case_pane_row(index: int) -> dict[str, object]:
    """A plausible-worst-case ``app.pane.list`` row.

    Field values are sized generously (long ids, paths, titles) so the
    encoded row is well above a typical real row — yet 200 of them still
    fit comfortably under the 8 MiB response cap.
    """
    return {
        "pane_id": f"%{index}-" + "p" * 40,
        "container_id": "c" * 64,
        "container_name": "bench-container-" + "n" * 48,
        "tmux_socket": "/tmp/tmux-1000/" + "s" * 80,
        "session_name": "session-" + "x" * 48,
        "window_index": index % 64,
        "pane_index": index % 16,
        "registered": index % 2 == 0,
        "agent_id": f"agent-{index}-" + "a" * 40,
        "discovered_at": "2026-05-19T00:00:00.123456Z",
        "last_seen_at": "2026-05-22T23:59:59.654321Z",
    }


def test_pane_list_response_at_pagination_cap_under_8mib() -> None:
    """FR-020a: a 200-row page (the pagination cap) JSON-encodes to far
    below the 8 MiB response-line ceiling."""
    rows = [_worst_case_pane_row(i) for i in range(200)]
    result = {
        "ok": True,
        "app_contract_version": "1.0",
        "result": {
            "rows": rows,
            "total": 100000,
            "total_estimate": None,
            "cursor_next": "Y" * 512,  # max-length cursor
            "ordering": "default:asc",
        },
    }
    encoded = json.dumps(result, separators=(",", ":")).encode("utf-8")
    assert len(encoded) < RESPONSE_LINE_CAP_BYTES
    # Sanity: a 200-row page is well under the cap — assert it's under
    # even 1/8th of the ceiling so the margin is unambiguous.
    assert len(encoded) < RESPONSE_LINE_CAP_BYTES // 8


def test_recent_response_at_recent_cap_under_8mib() -> None:
    """FR-017: a 50-row ``recent``-style page stays under 8 MiB."""
    rows = [_worst_case_pane_row(i) for i in range(50)]
    result = {
        "ok": True,
        "app_contract_version": "1.0",
        "result": {"rows": rows, "recent_limit": 50},
    }
    encoded = json.dumps(result, separators=(",", ":")).encode("utf-8")
    assert len(encoded) < RESPONSE_LINE_CAP_BYTES


def test_worst_case_row_is_plausibly_sized() -> None:
    """Each worst-case row is non-trivial yet small relative to the cap —
    confirms the 200-row assertion is a meaningful margin, not a row so
    tiny the test is vacuous."""
    encoded_row = json.dumps(_worst_case_pane_row(0), separators=(",", ":"))
    # A generously-sized row is on the order of hundreds of bytes;
    # 200 such rows is well under a megabyte.
    assert 200 < len(encoded_row) < 4096
