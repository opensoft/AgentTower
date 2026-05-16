"""T060 — `agenttower send-input` human-readable stdout / stderr shape.

Asserts the one-line confirmation rendering for each terminal outcome:
``delivered`` → stdout exit 0; ``blocked`` / ``failed`` / wait timeout →
stderr with the closed-set exit code (FR-009 / contracts/cli-send-input.md
"Stdout / stderr discipline").
"""

from __future__ import annotations

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
    target_label: str = "worker-1",
) -> dict[str, Any]:
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
            "label": target_label,
            "role": "slave",
            "capability": "codex",
        },
        "envelope_size_bytes": 92,
        "envelope_body_sha256": "a" * 64,
        "enqueued_at": "2026-05-12T15:32:04.123Z",
        "delivery_attempt_started_at": None,
        "delivered_at": "2026-05-12T15:32:05.012Z" if state == "delivered" else None,
        "failed_at": "2026-05-12T15:32:05.500Z" if state == "failed" else None,
        "canceled_at": None,
        "last_updated_at": "2026-05-12T15:32:05.012Z",
        "operator_action": None,
        "operator_action_at": None,
        "operator_action_by": None,
        "excerpt": "do thing",
        "waited_to_terminal": waited,
    }


class _FakeResolvedTarget:
    container_id = _TARGET_PANE_KEY[0]
    pane_key = _TARGET_PANE_KEY


def _install_cli_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    send_input_response: dict[str, Any],
    tmp_path: Path,
) -> None:
    from agenttower import cli as cli_mod

    def _fake_resolve(**_kw: Any) -> _FakeResolvedTarget:
        return _FakeResolvedTarget()

    def _fake_send_request(
        socket_path: Any, method: str, params: dict[str, Any] | None = None,
        *args: Any, **kwargs: Any,
    ) -> dict[str, Any]:
        if method == "list_agents":
            return {
                "filter": {},
                "agents": [
                    {
                        "agent_id": "agt_aaaaaaaaaaaa",
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

    def _fake_resolve_socket(*_a: Any, **_kw: Any) -> tuple[Any, Any]:
        class _R:
            path = tmp_path / "sock"
        return None, _R()

    monkeypatch.setattr(
        "agenttower.agents.client_resolve.resolve_pane_composite_key",
        _fake_resolve,
    )
    monkeypatch.setattr(cli_mod, "send_request", _fake_send_request)
    monkeypatch.setattr(cli_mod, "_resolve_socket_with_paths", _fake_resolve_socket)


# ──────────────────────────────────────────────────────────────────────
# delivered → stdout, exit 0
# ──────────────────────────────────────────────────────────────────────


def test_delivered_one_line_confirmation_on_stdout(
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
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    # Stdout: one line "delivered: msg=<id> target=worker-1(agt_bbbbbbbbbbbb)".
    assert captured.out.startswith("delivered: msg=")
    assert "target=worker-1(agt_bbbbbbbbbbbb)" in captured.out
    assert captured.err == ""


# ──────────────────────────────────────────────────────────────────────
# blocked → stderr, exit per block_reason
# ──────────────────────────────────────────────────────────────────────


def test_blocked_kill_switch_off_writes_to_stderr_with_routing_disabled_label(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(
            state="blocked", block_reason="kill_switch_off",
        ),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_CODE_MAP["routing_disabled"]
    assert captured.out == ""
    assert "send-input failed:" in captured.err
    assert "routing_disabled" in captured.err
    assert "kill_switch_off" in captured.err  # block_reason carries the raw token


def test_blocked_target_not_active_writes_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(
            state="blocked", block_reason="target_not_active",
        ),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_CODE_MAP["target_not_active"]
    assert captured.out == ""
    assert "target_not_active" in captured.err


# ──────────────────────────────────────────────────────────────────────
# failed → stderr, exit per failure_reason
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "failure_reason",
    [
        "tmux_paste_failed",
        "docker_exec_failed",
        "tmux_send_keys_failed",
        "pane_disappeared_mid_attempt",
        "sqlite_lock_conflict",
        "attempt_interrupted",
    ],
)
def test_failed_writes_to_stderr_with_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    failure_reason: str,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="failed", failure_reason=failure_reason),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_CODE_MAP[failure_reason]
    assert captured.out == ""
    assert failure_reason in captured.err
    assert "send-input failed:" in captured.err


# ──────────────────────────────────────────────────────────────────────
# delivery_wait_timeout → stderr, exit 1
# ──────────────────────────────────────────────────────────────────────


def test_delivery_wait_timeout_writes_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """When the wait budget elapses with the row still queued, the CLI
    surfaces ``delivery_wait_timeout`` (exit 1)."""
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
        ]
    )
    captured = capsys.readouterr()
    assert rc == CLI_EXIT_CODE_MAP["delivery_wait_timeout"]
    assert captured.out == ""
    assert "delivery_wait_timeout" in captured.err


# ──────────────────────────────────────────────────────────────────────
# target rendering when label is empty falls back to agent_id only
# ──────────────────────────────────────────────────────────────────────


def test_human_target_render_falls_back_to_agent_id_when_label_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install_cli_stubs(
        monkeypatch,
        send_input_response=_row(state="delivered", target_label=""),
        tmp_path=tmp_path,
    )
    rc = main(
        [
            "send-input",
            "--target", "worker-1",
            "--message", "do thing",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    # No "label(agent_id)" rendering — just the bare agent_id.
    assert "target=agt_bbbbbbbbbbbb" in captured.out
    assert "(" not in captured.out.split("target=")[1]
