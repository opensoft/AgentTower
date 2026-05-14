"""T059 — `agenttower send-input --json` stdout shape.

Asserts that ``--json`` mode emits exactly one JSON line on stdout
matching the ``contracts/queue-row-schema.md`` shape (FR-011), and that
the integer exit code is derived from the row's terminal state via
``routing.errors.CLI_EXIT_CODE_MAP``.

These tests stub the daemon socket (no real I/O); the CLI handler runs
to completion against an in-process fake ``send_request`` so the test
covers the full render path including the exit-code mapping.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agenttower.cli import main
from agenttower.routing.errors import CLI_EXIT_CODE_MAP


_TARGET_PANE_KEY = (
    "cont_xyz", "/tmp/tmux-1000/default", "swarm", 0, 0, "%1",
)


def _row(
    *,
    state: str,
    message_id: str = "11111111-2222-4333-8444-555555555555",
    block_reason: str | None = None,
    failure_reason: str | None = None,
    waited: bool = True,
) -> dict[str, Any]:
    """Build a fake queue-row payload matching the dispatcher's shape."""
    return {
        "message_id": message_id,
        "state": state,
        "block_reason": block_reason,
        "failure_reason": failure_reason,
        "sender": {
            "agent_id": "agt_aaaaaaaaaaaa",
            "label": "queen",
            "role": "master",
            "capability": "codex",
        },
        "target": {
            "agent_id": "agt_bbbbbbbbbbbb",
            "label": "worker-1",
            "role": "slave",
            "capability": "codex",
        },
        "envelope_size_bytes": 92,
        "envelope_body_sha256": "a" * 64,
        "enqueued_at": "2026-05-12T15:32:04.123Z",
        "delivery_attempt_started_at": (
            "2026-05-12T15:32:04.500Z" if state in ("delivered", "failed") else None
        ),
        "delivered_at": "2026-05-12T15:32:05.012Z" if state == "delivered" else None,
        "failed_at": "2026-05-12T15:32:05.500Z" if state == "failed" else None,
        "canceled_at": "2026-05-12T15:32:05.500Z" if state == "canceled" else None,
        "last_updated_at": "2026-05-12T15:32:05.012Z",
        "operator_action": None,
        "operator_action_at": None,
        "operator_action_by": None,
        "excerpt": "do thing",
        "waited_to_terminal": waited,
    }


class _FakeResolvedTarget:
    """Stub for :class:`ResolvedAgentTarget` returned by
    ``resolve_pane_composite_key``."""

    container_id = _TARGET_PANE_KEY[0]
    pane_key = _TARGET_PANE_KEY


def _install_cli_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    send_input_response: dict[str, Any],
    self_agent_id: str = "agt_aaaaaaaaaaaa",
    tmp_path: Path,
) -> list[tuple[str, dict[str, Any]]]:
    """Stub the FEAT-006 / FEAT-009 client-side helpers.

    Returns the captured ``(method, params)`` list of socket calls.
    """
    from agenttower import cli as cli_mod

    captured: list[tuple[str, dict[str, Any]]] = []

    def _fake_resolve(**kwargs: Any) -> _FakeResolvedTarget:
        return _FakeResolvedTarget()

    def _fake_send_request(
        socket_path: Any, method: str, params: dict[str, Any] | None = None,
        *args: Any, **kwargs: Any,
    ) -> dict[str, Any]:
        captured.append((method, params or {}))
        if method == "list_agents":
            return {
                "filter": {},
                "agents": [
                    {
                        "agent_id": self_agent_id,
                        "container_id": _TARGET_PANE_KEY[0],
                        "tmux_socket_path": _TARGET_PANE_KEY[1],
                        "tmux_session_name": _TARGET_PANE_KEY[2],
                        "tmux_window_index": _TARGET_PANE_KEY[3],
                        "tmux_pane_index": _TARGET_PANE_KEY[4],
                        "tmux_pane_id": _TARGET_PANE_KEY[5],
                        "role": "master",
                        "label": "queen",
                        "active": True,
                    }
                ],
            }
        if method == "queue.send_input":
            return send_input_response
        raise AssertionError(f"unexpected method: {method}")

    def _fake_resolve_socket(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
        class _R:
            path = tmp_path / "sock"
        return None, _R()

    # Patch the symbols where the CLI uses them.
    monkeypatch.setattr(
        "agenttower.agents.client_resolve.resolve_pane_composite_key",
        _fake_resolve,
    )
    monkeypatch.setattr(cli_mod, "send_request", _fake_send_request)
    monkeypatch.setattr(cli_mod, "_resolve_socket_with_paths", _fake_resolve_socket)
    return captured


def test_json_mode_emits_exactly_one_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="delivered"),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    lines = out.rstrip("\n").split("\n")
    assert len(lines) == 1, f"expected exactly one JSON line, got {len(lines)}"
    payload = json.loads(lines[0])
    assert payload["state"] == "delivered"
    assert payload["message_id"] == "11111111-2222-4333-8444-555555555555"
    # waited_to_terminal is a dispatcher-only field; the CLI strips it
    # from the wire shape so the contract surface is the row schema only.
    assert "waited_to_terminal" not in payload


def test_json_payload_carries_required_row_schema_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="delivered"),
        tmp_path=tmp_path,
    )
    main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out.strip())
    # Required keys per contracts/queue-row-schema.md.
    required = {
        "message_id", "state", "block_reason", "failure_reason",
        "sender", "target", "envelope_size_bytes", "envelope_body_sha256",
        "enqueued_at", "delivery_attempt_started_at", "delivered_at",
        "failed_at", "canceled_at", "last_updated_at",
        "operator_action", "operator_action_at", "operator_action_by",
        "excerpt",
    }
    assert required <= set(payload.keys()), (
        f"payload missing required keys: {required - set(payload.keys())}"
    )


@pytest.mark.parametrize(
    "state, block_reason, failure_reason, expected_code",
    [
        ("delivered", None, None, 0),
        ("blocked", "kill_switch_off", None, CLI_EXIT_CODE_MAP["routing_disabled"]),
        ("blocked", "target_role_not_permitted", None,
         CLI_EXIT_CODE_MAP["target_role_not_permitted"]),
        ("blocked", "target_not_active", None,
         CLI_EXIT_CODE_MAP["target_not_active"]),
        ("failed", None, "tmux_paste_failed",
         CLI_EXIT_CODE_MAP["tmux_paste_failed"]),
        ("failed", None, "sqlite_lock_conflict",
         CLI_EXIT_CODE_MAP["sqlite_lock_conflict"]),
        ("failed", None, "attempt_interrupted",
         CLI_EXIT_CODE_MAP["attempt_interrupted"]),
    ],
)
def test_exit_code_mapped_from_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    state: str,
    block_reason: str | None,
    failure_reason: str | None,
    expected_code: int,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(
            state=state, block_reason=block_reason, failure_reason=failure_reason,
        ),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
            "--json",
        ]
    )
    assert rc == expected_code


def test_delivery_wait_timeout_maps_to_exit_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """When the wait budget elapses with the row still non-terminal,
    the dispatcher returns ok with waited_to_terminal=false and the CLI
    surfaces ``delivery_wait_timeout`` (exit 1 per FR-009)."""
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="queued", waited=False),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
            "--json",
        ]
    )
    assert rc == CLI_EXIT_CODE_MAP["delivery_wait_timeout"]


def test_no_wait_with_non_terminal_state_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--no-wait`` returns success immediately after enqueue even when
    the row is still ``queued``. Different from the wait-timeout case
    because the caller didn't ask to wait."""
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="queued", waited=False),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
            "--no-wait",
            "--json",
        ]
    )
    assert rc == 0


def test_body_base64_encoded_on_wire(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The CLI base64-encodes the body before submitting it
    (contracts/socket-queue.md ``body_bytes``)."""
    import base64

    captured = _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="delivered"),
        tmp_path=tmp_path,
    )
    main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
            "--json",
        ]
    )
    submit_calls = [c for c in captured if c[0] == "queue.send_input"]
    assert len(submit_calls) == 1
    submitted_body = submit_calls[0][1]["body_bytes"]
    # Round-trip: the daemon would base64-decode and get the raw bytes.
    assert base64.b64decode(submitted_body) == b"do thing"


def test_body_from_message_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--message-file`` reads raw bytes from disk (including newlines /
    special bytes that would be unsafe in ``--message``)."""
    import base64

    body_path = tmp_path / "prompt.txt"
    body_bytes = b"line1\nline2\tcol2\n"
    body_path.write_bytes(body_bytes)
    captured = _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="delivered"),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message-file", str(body_path),
            "--json",
        ]
    )
    assert rc == 0
    submit = next(c for c in captured if c[0] == "queue.send_input")
    assert base64.b64decode(submit[1]["body_bytes"]) == body_bytes


def test_message_file_not_found_emits_bad_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--message-file`` I/O failures surface as ``bad_request``
    (FEAT-002 argparse-style exit 64), NOT ``body_invalid_chars``
    (which is reserved for FR-003 byte-level body validation)."""
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="delivered"),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message-file", str(tmp_path / "missing.txt"),
            "--json",
        ]
    )
    assert rc == 64
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_request"
