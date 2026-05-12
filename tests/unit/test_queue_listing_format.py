"""T067 — `agenttower queue` listing format unit test.

Asserts the human-readable column shape, the ``label(<agent_id-prefix>)``
rendering rule, the empty-state line, and the empty ``[]`` JSON output
per ``contracts/cli-queue.md`` §"Stdout / stderr".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agenttower.cli import main


def _row(
    *,
    message_id: str,
    state: str,
    sender_label: str = "queen",
    target_label: str = "worker-1",
    sender_agent_id: str = "agt_aaaaaaaaaaaa",
    target_agent_id: str = "agt_bbbbbbbbbbbb",
    excerpt: str = "do thing",
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "state": state,
        "block_reason": None,
        "failure_reason": None,
        "sender": {
            "agent_id": sender_agent_id,
            "label": sender_label,
            "role": "master",
            "capability": "codex",
        },
        "target": {
            "agent_id": target_agent_id,
            "label": target_label,
            "role": "slave",
            "capability": "codex",
        },
        "envelope_size_bytes": 92,
        "envelope_body_sha256": "a" * 64,
        "enqueued_at": "2026-05-12T15:32:04.123Z",
        "delivery_attempt_started_at": None,
        "delivered_at": None,
        "failed_at": None,
        "canceled_at": None,
        "last_updated_at": "2026-05-12T15:32:05.012Z",
        "operator_action": None,
        "operator_action_at": None,
        "operator_action_by": None,
        "excerpt": excerpt,
    }


def _install_cli_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[dict[str, Any]],
    tmp_path: Path,
) -> list[tuple[str, dict[str, Any]]]:
    from agenttower import cli as cli_mod

    captured: list[tuple[str, dict[str, Any]]] = []

    def _fake_send_request(
        socket_path: Any, method: str, params: dict[str, Any] | None = None,
        *args: Any, **kwargs: Any,
    ) -> dict[str, Any]:
        captured.append((method, params or {}))
        if method == "queue.list":
            return {"rows": rows, "next_cursor": None}
        raise AssertionError(f"unexpected method: {method}")

    def _fake_resolve_socket(*_a: Any, **_kw: Any) -> tuple[Any, Any]:
        class _R:
            path = tmp_path / "sock"
        return None, _R()

    monkeypatch.setattr(cli_mod, "send_request", _fake_send_request)
    monkeypatch.setattr(cli_mod, "_resolve_socket_with_paths", _fake_resolve_socket)
    return captured


# ──────────────────────────────────────────────────────────────────────
# Human mode: column layout + label(prefix) rendering
# ──────────────────────────────────────────────────────────────────────


def test_human_listing_shows_header_row(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        rows=[_row(message_id="11111111-2222-4333-8444-555555555555", state="queued")],
        tmp_path=tmp_path,
    )
    rc = main(["queue"])
    assert rc == 0
    out = capsys.readouterr().out
    first_line = out.split("\n")[0]
    # Header columns appear in the documented order.
    for column in (
        "MESSAGE_ID", "STATE", "SENDER", "TARGET",
        "ENQUEUED", "LAST_UPDATED", "EXCERPT",
    ):
        assert column in first_line


def test_human_listing_renders_label_and_agent_id_prefix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        rows=[_row(
            message_id="11111111-2222-4333-8444-555555555555",
            state="queued",
            sender_label="queen",
            sender_agent_id="agt_aaaa1111bbbb",
            target_label="worker-1",
            target_agent_id="agt_bbbb2222cccc",
        )],
        tmp_path=tmp_path,
    )
    rc = main(["queue"])
    assert rc == 0
    out = capsys.readouterr().out
    # Sender/target should render as ``label(agt_<8 hex>)`` — 8 chars
    # including the ``agt_`` prefix (so 4 hex chars after the prefix).
    assert "queen(agt_aaaa)" in out
    assert "worker-1(agt_bbbb)" in out


def test_human_listing_falls_back_to_bare_agent_id_when_label_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        rows=[_row(
            message_id="11111111-2222-4333-8444-555555555555",
            state="queued",
            sender_label="",
            target_label="",
        )],
        tmp_path=tmp_path,
    )
    rc = main(["queue"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "agt_aaaaaaaaaaaa" in out
    assert "(" not in out.split("STATE")[1].split("\n")[1]  # no label-paren in the row


def test_human_listing_empty_state_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(monkeypatch, rows=[], tmp_path=tmp_path)
    rc = main(["queue"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == "(no rows match)"


# ──────────────────────────────────────────────────────────────────────
# --json mode: array shape + empty list
# ──────────────────────────────────────────────────────────────────────


def test_json_listing_emits_array_of_row_objects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rows = [
        _row(message_id="11111111-2222-4333-8444-555555555555", state="queued"),
        _row(message_id="22222222-3333-4444-8555-666666666666", state="delivered"),
    ]
    _install_cli_stubs(monkeypatch, rows=rows, tmp_path=tmp_path)
    rc = main(["queue", "--json"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["message_id"] == "11111111-2222-4333-8444-555555555555"
    assert parsed[1]["state"] == "delivered"


def test_json_listing_empty_array(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(monkeypatch, rows=[], tmp_path=tmp_path)
    rc = main(["queue", "--json"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == "[]"


# ──────────────────────────────────────────────────────────────────────
# Filters are forwarded to the daemon verbatim
# ──────────────────────────────────────────────────────────────────────


def test_filters_forwarded_to_daemon(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    captured = _install_cli_stubs(monkeypatch, rows=[], tmp_path=tmp_path)
    rc = main([
        "queue",
        "--state", "blocked",
        "--target", "worker-1",
        "--sender", "queen",
        "--since", "2026-05-12T00:00:00.000Z",
        "--limit", "50",
    ])
    assert rc == 0
    assert len(captured) == 1
    method, params = captured[0]
    assert method == "queue.list"
    assert params["state"] == "blocked"
    assert params["target"] == "worker-1"
    assert params["sender"] == "queen"
    assert params["since"] == "2026-05-12T00:00:00.000Z"
    assert params["limit"] == 50


def test_limit_out_of_range_rejected_locally(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(monkeypatch, rows=[], tmp_path=tmp_path)
    rc = main(["queue", "--limit", "9999"])
    assert rc == 64  # argparse-style bad_request
    err = capsys.readouterr().err
    assert "--limit" in err
