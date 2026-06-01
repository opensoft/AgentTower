"""Unit tests for the FEAT-013 production tmux spawn backend (T057).

Exercises ``make_tmux_spawn_backend`` + ``build_spawn_backends`` against
the :class:`FakeTmuxAdapter` so the composition logic (socket
resolution, conflict pre-check, new-session-vs-split-window selection,
launch-argv threading, marker stamping, error mapping) is verified
without a real bench container. The real docker-exec path is smoke-tested
separately against a live bench container.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

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
    # Default the §R8 launch-exit probe OFF so the spawn-composition
    # tests don't sleep and don't add an ``is_pane_dead`` verb to the
    # call log; the probe has its own dedicated tests below.
    kw.setdefault("launch_probe_delay_s", 0.0)
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
    spawn = make_tmux_spawn_backend(
        adapter=adapter, env={"USER": "alice"}, launch_probe_delay_s=0.0
    )

    spawn(_pane(index=0, label="m1"))

    _, new_kwargs = adapter.managed_calls[1]
    assert new_kwargs["bench_user"] == "alice"


def test_build_spawn_backends_returns_three_callable_keys() -> None:
    adapter = _adapter()

    class _StubAgentService:
        connection_factory = staticmethod(lambda: None)

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
        launch_probe_delay_s=0.0,
    )

    assert set(backends) == {
        "tmux_spawn", "register", "log_attach", "session_conflict",
        "tmux_kill", "route_cleanup", "log_detach",
    }
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


def test_register_backend_maps_socket_resolution_tmuxerror_to_ok_false() -> None:
    """A TmuxError from socket resolution (resolve_uid) must become a clean
    {ok: False} — TmuxError is a frozen dataclass and would raise
    FrozenInstanceError if it propagated through the spawn pipeline's
    tx_guard contextmanager."""
    from agenttower.managed_sessions.spawn_backends import make_register_backend

    adapter = FakeTmuxAdapter(
        {"containers": {CONTAINER: {"id_u_failure": "docker_exec_failed"}}}
    )

    class _NeverCalledAgentService:
        def register_agent(self, params, socket_peer_uid):  # noqa: ANN001
            raise AssertionError("register_agent should not be reached")

    register = make_register_backend(
        _NeverCalledAgentService(),
        adapter=adapter,
        bench_user_resolver=lambda _cid: BENCH_USER,
    )
    result = register(_pane(index=0, label="m1"), "%0")
    assert result == {
        "ok": False,
        "error": {"code": "docker_exec_failed", "message": "fake docker_exec_failed"},
    }


# ─── §R8 launch-exit probe (T057b) ──────────────────────────────────────


def test_launch_probe_disabled_skips_is_pane_dead_and_assumes_alive() -> None:
    adapter = _adapter()
    spawn = _backend(adapter, launch_probe_delay_s=0.0)

    result = spawn(_pane(index=0, label="m1"))

    assert result["launch_alive"] is True
    assert "is_pane_dead" not in [name for name, _ in adapter.managed_calls]


def test_launch_probe_reports_alive_when_pane_survives() -> None:
    adapter = _adapter()
    slept: list[float] = []
    spawn = _backend(
        adapter, launch_probe_delay_s=1.0, sleep_fn=slept.append
    )

    result = spawn(_pane(index=0, label="m1"))

    # Settled for the §R8 window, probed exactly once, pane alive.
    assert slept == [1.0]
    assert result["launch_alive"] is True
    probe_calls = [kw for name, kw in adapter.managed_calls if name == "is_pane_dead"]
    assert len(probe_calls) == 1
    assert probe_calls[0]["pane_id"] == "%0"
    assert probe_calls[0]["socket_path"] == EXPECTED_SOCKET


def test_launch_probe_reports_dead_drives_launch_alive_false() -> None:
    adapter = _adapter()
    # The spawned pane (%0) has already exited by probe time.
    adapter.dead_pane_ids.add("%0")
    spawn = _backend(adapter, launch_probe_delay_s=1.0, sleep_fn=lambda _s: None)

    result = spawn(_pane(index=0, label="m1", launch_ref=None))

    assert result["ok"] is True
    assert result["launch_alive"] is False


def test_launch_probe_tmuxerror_is_swallowed_as_alive() -> None:
    adapter = _adapter()
    adapter.is_pane_dead_failures.append(
        TmuxError(code="docker_exec_failed", message="probe boom", container_id=CONTAINER)
    )
    spawn = _backend(adapter, launch_probe_delay_s=1.0, sleep_fn=lambda _s: None)

    result = spawn(_pane(index=0, label="m1"))

    # Indeterminate probe must not downgrade a pane that genuinely spawned.
    assert result["ok"] is True
    assert result["launch_alive"] is True


# ─── Session-name conflict checker (T057b part 3) ───────────────────────


def test_session_conflict_checker_resolves_socket_and_delegates() -> None:
    from agenttower.managed_sessions.spawn_backends import (
        make_session_conflict_checker,
    )

    adapter = _adapter()
    adapter.existing_sessions.add("occupied")
    check = make_session_conflict_checker(
        adapter=adapter, bench_user_resolver=lambda _cid: BENCH_USER
    )

    assert check(CONTAINER, "occupied") is True
    assert check(CONTAINER, "free") is False

    # Delegated to has_session against the resolved bench socket.
    has_calls = [kw for name, kw in adapter.managed_calls if name == "has_session"]
    assert has_calls[0]["socket_path"] == EXPECTED_SOCKET
    assert has_calls[0]["bench_user"] == BENCH_USER


# ─── Recovery list-panes channel (T058) ─────────────────────────────────


def _recovery_channel(adapter: FakeTmuxAdapter):
    from agenttower.managed_sessions.spawn_backends import (
        make_recovery_list_panes_channel,
    )

    return make_recovery_list_panes_channel(
        adapter=adapter, bench_user_resolver=lambda _cid: BENCH_USER
    )


def _pane_fixture(session: str, index: int, *, title: str = "") -> dict:
    return {
        "session_name": session,
        "window_index": 0,
        "pane_index": index,
        "pane_id": f"%{index}",
        "pane_pid": 1000 + index,
        "pane_title": title,
    }


def test_recovery_channel_maps_panes_without_stripping_pending_managed() -> None:
    adapter = FakeTmuxAdapter(
        {
            "containers": {
                CONTAINER: {
                    "uid": UID,
                    "sockets": {
                        "default": [
                            # A still-pending managed pane (marker title set)
                            # MUST be reported live — reconcile needs to see it.
                            _pane_fixture("feat013", 0, title="@MANAGED:tok:m1"),
                            _pane_fixture("feat013", 1),
                        ],
                    },
                }
            }
        }
    )

    rows = _recovery_channel(adapter)(CONTAINER)

    assert rows == [
        {"tmux_session_name": "feat013", "tmux_pane_index": 0},
        {"tmux_session_name": "feat013", "tmux_pane_index": 1},
    ]


def test_recovery_channel_socket_dir_missing_returns_empty() -> None:
    adapter = FakeTmuxAdapter(
        {"containers": {CONTAINER: {"uid": UID, "socket_dir_missing": True}}}
    )
    assert _recovery_channel(adapter)(CONTAINER) == []


def test_recovery_channel_tmux_no_server_socket_contributes_nothing() -> None:
    adapter = FakeTmuxAdapter(
        {
            "containers": {
                CONTAINER: {
                    "uid": UID,
                    "sockets": {"default": {"failure": "tmux_no_server"}},
                }
            }
        }
    )
    assert _recovery_channel(adapter)(CONTAINER) == []


def test_recovery_channel_propagates_socket_dir_docker_failure() -> None:
    adapter = FakeTmuxAdapter(
        {
            "containers": {
                CONTAINER: {
                    "uid": UID,
                    "socket_listing_failure": "docker_exec_failed",
                }
            }
        }
    )
    # Uncertain liveness → propagate so the boot reconcile leaves rows alone.
    with pytest.raises(TmuxError):
        _recovery_channel(adapter)(CONTAINER)


def test_recovery_channel_propagates_non_recoverable_per_socket_error() -> None:
    adapter = FakeTmuxAdapter(
        {
            "containers": {
                CONTAINER: {
                    "uid": UID,
                    "sockets": {"default": {"failure": "docker_exec_timeout"}},
                }
            }
        }
    )
    with pytest.raises(TmuxError):
        _recovery_channel(adapter)(CONTAINER)


def test_recovery_channel_salvages_malformed_partial_panes() -> None:
    from agenttower.tmux.parsers import ParsedPane

    adapter = _adapter()
    partial = (
        ParsedPane(
            tmux_session_name="feat013",
            tmux_window_index=0,
            tmux_pane_index=2,
            tmux_pane_id="%2",
            pane_pid=42,
            pane_tty="",
            pane_current_command="",
            pane_current_path="",
            pane_title="",
            pane_active=True,
        ),
    )

    def _list_panes(*, container_id, bench_user, socket_path):  # noqa: ANN001
        raise TmuxError(
            code="output_malformed",
            message="one bad row",
            container_id=container_id,
            tmux_socket_path=socket_path,
            partial_panes=partial,
        )

    # One socket present so the loop runs; override list_panes to raise
    # OUTPUT_MALFORMED carrying a salvageable partial.
    adapter._script["containers"][CONTAINER]["sockets"] = {"default": []}
    adapter.list_panes = _list_panes  # type: ignore[assignment]

    rows = _recovery_channel(adapter)(CONTAINER)
    assert rows == [{"tmux_session_name": "feat013", "tmux_pane_index": 2}]


# ─── Remove-pane backends (T059) ────────────────────────────────────────


class _FakeAgentService:
    """Minimal AgentService stub exposing the ``connection_factory`` the
    kill backend uses to look up an agent's durable ``%N`` pane id."""

    def __init__(self) -> None:
        self.connection_factory = lambda: SimpleNamespace(close=lambda: None)


def _registered_pane(agent_id: str | None) -> ManagedPaneRow:
    return dataclasses.replace(_pane(index=0, label="m1"), agent_id=agent_id)


def test_tmux_kill_backend_resolves_pane_id_via_agent_registry(monkeypatch) -> None:  # noqa: ANN001
    import agenttower.managed_sessions.spawn_backends as sbmod
    from agenttower.managed_sessions.spawn_backends import make_tmux_kill_backend

    monkeypatch.setattr(
        sbmod._state_agents, "select_agent_by_id",
        lambda conn, *, agent_id: SimpleNamespace(
            tmux_pane_id="%5", tmux_socket_path="/tmp/tmux-1000/default"
        ),
    )
    adapter = _adapter()
    kill = make_tmux_kill_backend(
        adapter=adapter, agent_service=_FakeAgentService(),
        bench_user_resolver=lambda _cid: BENCH_USER,
    )

    result = kill(_registered_pane("agt_aaaaaaaaaaaa"))

    assert result == {"ok": True}
    kill_calls = [kw for name, kw in adapter.managed_calls if name == "kill_pane"]
    assert len(kill_calls) == 1
    assert kill_calls[0]["pane_id"] == "%5"
    assert kill_calls[0]["socket_path"] == "/tmp/tmux-1000/default"
    assert kill_calls[0]["bench_user"] == BENCH_USER


def test_tmux_kill_backend_no_agent_id_is_noop_success() -> None:
    from agenttower.managed_sessions.spawn_backends import make_tmux_kill_backend

    adapter = _adapter()
    kill = make_tmux_kill_backend(
        adapter=adapter, agent_service=_FakeAgentService(),
        bench_user_resolver=lambda _cid: BENCH_USER,
    )

    # Never-registered pane → no durable %N target → idempotent success.
    assert kill(_registered_pane(None)) == {"ok": True}
    assert not [name for name, _ in adapter.managed_calls if name == "kill_pane"]


def test_tmux_kill_backend_unknown_agent_is_noop_success(monkeypatch) -> None:  # noqa: ANN001
    import agenttower.managed_sessions.spawn_backends as sbmod
    from agenttower.managed_sessions.spawn_backends import make_tmux_kill_backend

    monkeypatch.setattr(
        sbmod._state_agents, "select_agent_by_id",
        lambda conn, *, agent_id: None,
    )
    adapter = _adapter()
    kill = make_tmux_kill_backend(
        adapter=adapter, agent_service=_FakeAgentService(),
        bench_user_resolver=lambda _cid: BENCH_USER,
    )
    assert kill(_registered_pane("agt_gone0000000")) == {"ok": True}


def test_tmux_kill_backend_maps_tmux_error_to_ok_false(monkeypatch) -> None:  # noqa: ANN001
    import agenttower.managed_sessions.spawn_backends as sbmod
    from agenttower.managed_sessions.spawn_backends import make_tmux_kill_backend

    monkeypatch.setattr(
        sbmod._state_agents, "select_agent_by_id",
        lambda conn, *, agent_id: SimpleNamespace(
            tmux_pane_id="%5", tmux_socket_path="/s"
        ),
    )
    adapter = _adapter()
    adapter.kill_pane_failures.append(
        TmuxError(code="docker_exec_failed", message="boom", container_id=CONTAINER)
    )
    kill = make_tmux_kill_backend(
        adapter=adapter, agent_service=_FakeAgentService(),
        bench_user_resolver=lambda _cid: BENCH_USER,
    )

    result = kill(_registered_pane("agt_aaaaaaaaaaaa"))
    assert result["ok"] is False
    assert result["error"]["code"] == "docker_exec_failed"


class _FakeRoutesService:
    def __init__(self, routes) -> None:  # noqa: ANN001
        self._routes = routes
        self.removed: list[str] = []

    def list_routes(self):  # noqa: ANN201
        return list(self._routes)

    def remove_route(self, route_id, *, deleted_by_agent_id):  # noqa: ANN001
        self.removed.append(route_id)


def _route(route_id: str, *, source=None, target=None, master=None):  # noqa: ANN001
    return SimpleNamespace(
        route_id=route_id,
        source_scope_value=source,
        target_value=target,
        master_value=master,
    )


def test_route_cleanup_removes_only_routes_referencing_agent() -> None:
    from agenttower.managed_sessions.spawn_backends import make_route_cleanup_backend

    agent = "agt_aaaaaaaaaaaa"
    routes = [
        _route("r-src", source=agent),
        _route("r-tgt", target=agent),
        _route("r-mst", master=agent),
        _route("r-other", source="agt_bbbbbbbbbbbb"),
    ]
    svc = _FakeRoutesService(routes)
    make_route_cleanup_backend(svc)(_registered_pane(agent))

    assert svc.removed == ["r-src", "r-tgt", "r-mst"]


def test_route_cleanup_noop_without_agent_or_service() -> None:
    from agenttower.managed_sessions.spawn_backends import make_route_cleanup_backend

    svc = _FakeRoutesService([_route("r", source="agt_aaaaaaaaaaaa")])
    # No agent_id → no cleanup.
    make_route_cleanup_backend(svc)(_registered_pane(None))
    assert svc.removed == []
    # No routes_service → no-op (doesn't raise).
    make_route_cleanup_backend(None)(_registered_pane("agt_aaaaaaaaaaaa"))


def test_route_cleanup_tolerates_per_route_remove_error() -> None:
    from agenttower.managed_sessions.spawn_backends import make_route_cleanup_backend

    agent = "agt_aaaaaaaaaaaa"

    class _AngryRoutes(_FakeRoutesService):
        def remove_route(self, route_id, *, deleted_by_agent_id):  # noqa: ANN001
            if route_id == "r1":
                raise RuntimeError("RouteIdNotFound race")
            self.removed.append(route_id)

    svc = _AngryRoutes([_route("r1", source=agent), _route("r2", target=agent)])
    make_route_cleanup_backend(svc)(_registered_pane(agent))
    # r1 raised but the loop continued and removed r2.
    assert svc.removed == ["r2"]


class _FakeLogService:
    def __init__(self) -> None:
        self.detached: list[dict] = []

    def detach_log(self, params, *, socket_peer_uid):  # noqa: ANN001
        self.detached.append(params)
        return {"status": "detached"}


def test_log_detach_backend_detaches_by_agent_id() -> None:
    from agenttower.managed_sessions.spawn_backends import make_log_detach_backend

    svc = _FakeLogService()
    make_log_detach_backend(svc)(_registered_pane("agt_aaaaaaaaaaaa"))
    assert svc.detached == [{"agent_id": "agt_aaaaaaaaaaaa"}]


def test_log_detach_backend_noop_without_agent_id() -> None:
    from agenttower.managed_sessions.spawn_backends import make_log_detach_backend

    svc = _FakeLogService()
    make_log_detach_backend(svc)(_registered_pane(None))
    assert svc.detached == []
