"""Unit tests for the FEAT-013 production tmux spawn backend (T057).

Exercises ``make_tmux_spawn_backend`` + ``build_spawn_backends`` against
the :class:`FakeTmuxAdapter` so the composition logic (socket
resolution, conflict pre-check, new-session-vs-split-window selection,
launch-argv threading, marker stamping, error mapping) is verified
without a real bench container. The real docker-exec path is smoke-tested
separately against a live bench container.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.managed_sessions.dao import ManagedPaneRow
from agenttower.managed_sessions.errors import MANAGED_SESSION_NAME_CONFLICT
from agenttower.managed_sessions.spawn_backends import (
    build_spawn_backends,
    make_tmux_spawn_backend,
)
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.tmux import FakeTmuxAdapter
from agenttower.tmux.adapter import TmuxError


CONTAINER = "c-bench-1"
UID = "1000"
EXPECTED_SOCKET = f"/tmp/tmux-{UID}/default"
BENCH_USER = "tester"


def _adapter() -> FakeTmuxAdapter:
    return FakeTmuxAdapter(
        {"containers": {CONTAINER: {"uid": UID, "sockets": {}}}}
    )


def _pane(
    *,
    index: int,
    label: str,
    launch_ref: str | None = None,
    token: str = "tok-abc",
    session: str = "feat013",
) -> ManagedPaneRow:
    return ManagedPaneRow(
        id=f"pane-{index}",
        layout_id="layout-1",
        container_id=CONTAINER,
        role="master" if index == 0 else "slave",
        capability="orchestrator" if index == 0 else "worker",
        label=label,
        tmux_session_name=session,
        tmux_pane_index=index,
        state=ManagedState.CREATING,
        chain_depth=0,
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
        launch_command_ref=launch_ref,
        pending_marker_token=token,
    )


def _backend(adapter: FakeTmuxAdapter, **kw):
    return make_tmux_spawn_backend(
        adapter=adapter,
        bench_user_resolver=lambda _cid: BENCH_USER,
        **kw,
    )


def test_first_pane_creates_session_and_returns_pane_id() -> None:
    adapter = _adapter()
    spawn = _backend(adapter)

    result = spawn(_pane(index=0, label="m1"))

    assert result["ok"] is True
    assert result["tmux_pane_id"] == "%0"
    assert result["socket_path"] == EXPECTED_SOCKET
    assert result["launch_alive"] is True

    verbs = [name for name, _ in adapter.managed_calls]
    # Conflict pre-check happens BEFORE new-session.
    assert verbs == ["has_session", "new_session", "set_pane_title"]

    _, new_kwargs = adapter.managed_calls[1]
    assert new_kwargs["session_name"] == "feat013"
    assert new_kwargs["socket_path"] == EXPECTED_SOCKET
    assert new_kwargs["bench_user"] == BENCH_USER
    # No launch ref → default shell (empty argv).
    assert new_kwargs["launch_argv"] == ()

    _, title_kwargs = adapter.managed_calls[2]
    assert title_kwargs["pane_id"] == "%0"
    assert title_kwargs["title"] == "@MANAGED:tok-abc:m1"


def test_session_name_conflict_short_circuits_before_new_session() -> None:
    adapter = _adapter()
    adapter.existing_sessions.add("feat013")
    spawn = _backend(adapter)

    result = spawn(_pane(index=0, label="m1"))

    assert result["ok"] is False
    assert result["error"]["code"] == MANAGED_SESSION_NAME_CONFLICT
    verbs = [name for name, _ in adapter.managed_calls]
    assert verbs == ["has_session"]  # new_session never attempted


def test_later_pane_splits_window() -> None:
    adapter = _adapter()
    spawn = _backend(adapter, split_direction="v")

    result = spawn(_pane(index=2, label="s2"))

    assert result["ok"] is True
    assert result["tmux_pane_id"] == "%0"
    verbs = [name for name, _ in adapter.managed_calls]
    # No conflict pre-check for non-first panes; split, then title.
    assert verbs == ["split_window", "set_pane_title"]
    _, split_kwargs = adapter.managed_calls[0]
    assert split_kwargs["direction"] == "v"
    assert split_kwargs["session_name"] == "feat013"


def test_launch_profile_argv_env_and_workdir_threaded(tmp_path: Path) -> None:
    profile_dir = tmp_path / "launch_commands"
    profile_dir.mkdir()
    (profile_dir / "claude.yaml").write_text(
        "name: claude\n"
        "command: [claude, --dangerously-skip-permissions]\n"
        "env: {LOG_LEVEL: debug}\n"
        "working_dir: /workspace\n",
        encoding="utf-8",
    )
    adapter = _adapter()
    spawn = _backend(adapter, profile_override_dir=profile_dir)

    result = spawn(_pane(index=0, label="m1", launch_ref="claude"))

    assert result["ok"] is True
    _, new_kwargs = adapter.managed_calls[1]
    assert new_kwargs["launch_argv"] == ("claude", "--dangerously-skip-permissions")
    assert new_kwargs["env"] == {"LOG_LEVEL": "debug"}
    assert new_kwargs["working_dir"] == "/workspace"


def test_unknown_launch_profile_maps_to_error() -> None:
    adapter = _adapter()
    spawn = _backend(adapter)

    result = spawn(_pane(index=0, label="m1", launch_ref="does-not-exist"))

    assert result["ok"] is False
    assert result["error"]["code"] == "managed_launch_command_not_found"


def test_tmux_error_maps_to_ok_false() -> None:
    adapter = _adapter()
    adapter.new_session_failures.append(
        TmuxError(code="docker_exec_failed", message="boom", container_id=CONTAINER)
    )
    spawn = _backend(adapter)

    result = spawn(_pane(index=0, label="m1"))

    assert result["ok"] is False
    assert result["error"]["code"] == "docker_exec_failed"


def test_default_bench_user_resolver_uses_env_user() -> None:
    adapter = _adapter()
    spawn = make_tmux_spawn_backend(adapter=adapter, env={"USER": "alice"})

    spawn(_pane(index=0, label="m1"))

    _, new_kwargs = adapter.managed_calls[1]
    assert new_kwargs["bench_user"] == "alice"


def test_build_spawn_backends_returns_three_callable_keys() -> None:
    adapter = _adapter()

    class _StubAgentService:
        def register_agent(self, params, socket_peer_uid):  # noqa: ANN001
            return {"agent": {"agent_id": "agent-xyz"}}

    class _StubLogService:
        def attach_log(self, params, socket_peer_uid, source):  # noqa: ANN001
            return None

    backends = build_spawn_backends(
        adapter=adapter,
        agent_service=_StubAgentService(),
        log_service=_StubLogService(),
        bench_user_resolver=lambda _cid: BENCH_USER,
    )

    assert set(backends) == {"tmux_spawn", "register", "log_attach"}
    pane = _pane(index=0, label="m1")
    spawn_result = backends["tmux_spawn"](pane)
    assert spawn_result["ok"] is True

    # register backend resolves the SAME socket the spawn backend used.
    reg_result = backends["register"](pane, spawn_result["tmux_pane_id"])
    assert reg_result == {"ok": True, "agent_id": "agent-xyz"}
    assert backends["log_attach"](pane, "agent-xyz") == {"ok": True}


def test_register_backend_threads_resolved_socket() -> None:
    adapter = _adapter()
    captured: dict[str, object] = {}

    class _CapturingAgentService:
        def register_agent(self, params, socket_peer_uid):  # noqa: ANN001
            captured.update(params)
            return {"agent": {"agent_id": "agent-1"}}

    backends = build_spawn_backends(
        adapter=adapter,
        agent_service=_CapturingAgentService(),
        log_service=type("L", (), {"attach_log": lambda *a, **k: None})(),
        bench_user_resolver=lambda _cid: BENCH_USER,
    )
    backends["register"](_pane(index=0, label="m1"), "%7")

    key = captured["pane_composite_key"]
    assert key["tmux_socket_path"] == EXPECTED_SOCKET
    assert key["tmux_pane_id"] == "%7"
