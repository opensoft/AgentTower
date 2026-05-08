"""Unit tests for FEAT-006 client_resolve (review-pass-6 N9 + N10).

The ``client_resolve`` module owns five closed-set error codes —
``host_context_unsupported``, ``container_unresolved``, ``not_in_tmux``,
``tmux_pane_malformed``, ``pane_unknown_to_daemon`` — plus the FR-041
focused-rescan budget (exactly one ``scan_panes`` call scoped to the
resolved container, no cascade). Before this file the module had zero
direct unit coverage; only ``host_context_unsupported`` was exercised
e2e. These tests parameterize each branch with monkeypatched
``send_request`` / ``runtime_detect`` / ``cd_identity`` / ``tmux_identity``
so a real socket and daemon are not required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agenttower.agents import client_resolve
from agenttower.agents.errors import RegistrationError
from agenttower.config_doctor import identity as cd_identity
from agenttower.config_doctor import runtime_detect, tmux_identity


SOCKET_PATH = Path("/tmp/test-daemon.sock")  # NOSONAR — not opened in unit tests
CONTAINER_ID = "a" * 64
SHORT_ID = CONTAINER_ID[:12]


def _container_dict(container_id: str = CONTAINER_ID, name: str = "bench-x") -> dict:
    return {"id": container_id, "name": name}


def _pane_dict(
    *,
    pane_id: str = "%17",
    session: str = "main",
    window: int = 0,
    index: int = 0,
    socket: str = "/tmp/tmux-1000/default",
    active: bool = True,
) -> dict:
    return {
        "container_id": CONTAINER_ID,
        "tmux_socket_path": socket,
        "tmux_session_name": session,
        "tmux_window_index": window,
        "tmux_pane_index": index,
        "tmux_pane_id": pane_id,
        "active": active,
    }


def _patch_runtime_in_container(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_detect,
        "detect",
        lambda proc_root=None: runtime_detect.ContainerContext(detection_signals=("dockerenv",)),
    )


def _patch_runtime_host(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_detect, "detect", lambda proc_root=None: runtime_detect.HostContext()
    )


def _patch_identity(monkeypatch, candidate_value: str = CONTAINER_ID) -> None:
    monkeypatch.setattr(
        cd_identity,
        "detect_candidate",
        lambda env, proc_root=None: cd_identity.IdentityCandidate(
            candidate=candidate_value, signal="env"
        ),
    )


def _patch_tmux(
    monkeypatch,
    *,
    in_tmux: bool = True,
    socket_path: str | None = "/tmp/tmux-1000/default",
    pane_id: str | None = "%17",
    pane_id_valid: bool = True,
    malformed_reason: str | None = None,
) -> None:
    monkeypatch.setattr(
        tmux_identity,
        "parse_tmux_env",
        lambda env: tmux_identity.ParsedTmuxEnv(
            in_tmux=in_tmux,
            tmux_socket_path=socket_path,
            server_pid="12345" if in_tmux else None,
            session_id="$0" if in_tmux else None,
            tmux_pane_id=pane_id,
            pane_id_valid=pane_id_valid,
            malformed_reason=malformed_reason,
        ),
    )


def _patch_send_request(monkeypatch, responses: dict[str, Any]) -> list[dict]:
    """Wire ``send_request`` to a sequence of canned responses keyed by method.

    Returns the call-log list — tests can assert call ordering / count
    after the function returns.
    """
    calls: list[dict] = []

    def fake_send(socket_path, method, params, **kwargs):
        calls.append({"method": method, "params": dict(params)})
        if isinstance(responses.get(method), list):
            # Pop the next pre-staged response for this method.
            return responses[method].pop(0)
        return responses.get(method, {})

    monkeypatch.setattr(client_resolve, "send_request", fake_send)
    return calls


# ---------------------------------------------------------------------------
# host_context_unsupported (FEAT-005-style runtime detection)
# ---------------------------------------------------------------------------


def test_host_context_unsupported(monkeypatch) -> None:
    _patch_runtime_host(monkeypatch)
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "host_context_unsupported"


# ---------------------------------------------------------------------------
# container_unresolved — three sub-paths
# ---------------------------------------------------------------------------


def test_container_unresolved_no_candidate(monkeypatch) -> None:
    _patch_runtime_in_container(monkeypatch)
    monkeypatch.setattr(
        cd_identity, "detect_candidate", lambda env, proc_root=None: None
    )
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "container_unresolved"


def test_container_unresolved_multi_candidate(monkeypatch) -> None:
    _patch_runtime_in_container(monkeypatch)
    monkeypatch.setattr(
        cd_identity,
        "detect_candidate",
        lambda env, proc_root=None: cd_identity.CgroupMultiCandidate(
            candidates=("a" * 64, "b" * 64)
        ),
    )
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "container_unresolved"


def test_container_unresolved_no_match(monkeypatch) -> None:
    """Identity resolves but the candidate does not appear in list_containers."""
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch, candidate_value=CONTAINER_ID)
    _patch_send_request(monkeypatch, {"list_containers": {"containers": []}})
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "container_unresolved"


def test_container_unresolved_multi_match(monkeypatch) -> None:
    """Two distinct containers match the candidate name."""
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch, candidate_value="bench-x")
    _patch_send_request(
        monkeypatch,
        {
            "list_containers": {
                "containers": [
                    _container_dict("a" * 64, "bench-x"),
                    _container_dict("b" * 64, "bench-x"),
                ]
            }
        },
    )
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "container_unresolved"
    assert "matched 2" in info.value.message


# ---------------------------------------------------------------------------
# not_in_tmux / tmux_pane_malformed
# ---------------------------------------------------------------------------


def test_not_in_tmux(monkeypatch) -> None:
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch)
    _patch_send_request(
        monkeypatch, {"list_containers": {"containers": [_container_dict()]}}
    )
    _patch_tmux(monkeypatch, in_tmux=False)
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "not_in_tmux"


def test_tmux_pane_malformed(monkeypatch) -> None:
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch)
    _patch_send_request(
        monkeypatch, {"list_containers": {"containers": [_container_dict()]}}
    )
    _patch_tmux(
        monkeypatch,
        in_tmux=True,
        malformed_reason="$TMUX has only 2 segments",
    )
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "tmux_pane_malformed"


# ---------------------------------------------------------------------------
# pane_unknown_to_daemon — including the FR-041 focused-rescan budget
# ---------------------------------------------------------------------------


def test_pane_unknown_to_daemon_after_focused_rescan(monkeypatch) -> None:
    """FR-041 / SC-008 (review-pass-6 N9): exactly one focused rescan.

    The first list_panes returns no match. The resolver then issues
    EXACTLY ONE ``scan_panes`` request scoped to the resolved
    container. The second list_panes still returns no match → resolver
    refuses with ``pane_unknown_to_daemon``. A regression that cascaded
    the rescan to all containers, or skipped scoping, would be
    visible in the captured call log.
    """
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch)
    _patch_tmux(monkeypatch)
    calls = _patch_send_request(
        monkeypatch,
        {
            "list_containers": {"containers": [_container_dict()]},
            "list_panes": [{"panes": []}, {"panes": []}],  # both empty
            "scan_panes": {"status": "ok"},
        },
    )
    with pytest.raises(RegistrationError) as info:
        client_resolve.resolve_pane_composite_key(
            socket_path=SOCKET_PATH, env={}, proc_root=None
        )
    assert info.value.code == "pane_unknown_to_daemon"

    methods = [c["method"] for c in calls]
    assert methods.count("scan_panes") == 1, "exactly one focused rescan"
    scan_call = next(c for c in calls if c["method"] == "scan_panes")
    assert scan_call["params"] == {"container": CONTAINER_ID}, (
        "rescan must be scoped to the resolved container"
    )
    # And the resolver MUST issue list_panes twice (before + after rescan).
    assert methods.count("list_panes") == 2


def test_focused_rescan_recovers_pane_after_first_miss(monkeypatch) -> None:
    """If the rescan publishes the pane, the second list_panes finds it
    and the resolver returns the pane key successfully — exercising the
    happy-path side of the FR-041 budget."""
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch)
    _patch_tmux(monkeypatch)
    calls = _patch_send_request(
        monkeypatch,
        {
            "list_containers": {"containers": [_container_dict()]},
            "list_panes": [
                {"panes": []},  # first miss
                {"panes": [_pane_dict()]},  # second succeeds after rescan
            ],
            "scan_panes": {"status": "ok"},
        },
    )
    target = client_resolve.resolve_pane_composite_key(
        socket_path=SOCKET_PATH, env={}, proc_root=None
    )
    assert target.container_id == CONTAINER_ID
    assert target.pane_key == (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 0, "%17")
    assert [c["method"] for c in calls].count("scan_panes") == 1


def test_inactive_pane_triggers_focused_rescan(monkeypatch) -> None:
    """A pane row present but ``active=false`` is treated as a miss for
    FR-041 purposes — same focused rescan path."""
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch)
    _patch_tmux(monkeypatch)
    calls = _patch_send_request(
        monkeypatch,
        {
            "list_containers": {"containers": [_container_dict()]},
            "list_panes": [
                {"panes": [_pane_dict(active=False)]},  # inactive → treat as miss
                {"panes": [_pane_dict(active=True)]},
            ],
            "scan_panes": {"status": "ok"},
        },
    )
    target = client_resolve.resolve_pane_composite_key(
        socket_path=SOCKET_PATH, env={}, proc_root=None
    )
    assert target.pane_key[5] == "%17"
    assert [c["method"] for c in calls].count("scan_panes") == 1


def test_happy_path_no_rescan(monkeypatch) -> None:
    """When the pane is already in the FEAT-004 registry, no focused
    rescan fires — the FR-041 budget is preserved at zero, not one."""
    _patch_runtime_in_container(monkeypatch)
    _patch_identity(monkeypatch)
    _patch_tmux(monkeypatch)
    calls = _patch_send_request(
        monkeypatch,
        {
            "list_containers": {"containers": [_container_dict()]},
            "list_panes": {"panes": [_pane_dict()]},
            "scan_panes": {"status": "ok"},  # never reached
        },
    )
    target = client_resolve.resolve_pane_composite_key(
        socket_path=SOCKET_PATH, env={}, proc_root=None
    )
    assert target.container_id == CONTAINER_ID
    methods = [c["method"] for c in calls]
    assert "scan_panes" not in methods, "no rescan when pane is already known"
