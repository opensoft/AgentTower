"""Unit tests for `SubprocessTmuxAdapter` (FEAT-004 / US3 / T034).

These tests drive the production tmux adapter against a monkey-patched
``subprocess.run`` and ``shutil.which`` so we can exercise every closed-set
``TmuxError`` mapping branch without ever spawning a real ``docker`` binary.

Coverage references:
- FR-018 — 5-second timeout + kill/wait cleanup → ``docker_exec_timeout``.
- FR-019 — closed-set error codes (``docker_exec_failed``,
  ``socket_unreadable``, ``socket_dir_missing``, ``tmux_no_server``,
  ``tmux_unavailable``, ``docker_unavailable``).
- FR-020 — bench-user fallback chain
  (``config_user`` → ``$USER`` → ``getpwuid``) and ``:uid``-stripping rule.
- FR-021 — typed argv, ``shell=False``, no shell metacharacter interpolation.
- FR-033 — closed set of in-container subprocess invocations
  (``id -u`` / ``ls -1 -- /tmp/tmux-<uid>`` / ``tmux -S <socket> list-panes -a -F``).
- R-003 — kill-itself-fails escalation: see the explicit-skip note below.
- R-005 — error messages bounded; never raw stderr.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from agenttower.discovery.pane_service import _resolve_bench_user
from agenttower.socket_api import errors as _errors
from agenttower.tmux import subprocess_adapter as adapter_module
from agenttower.tmux.adapter import TmuxError


@dataclass
class _Completed:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


# A safe ``ls`` listing that yields zero socket names so the inner argv
# capture for tests targeting ``id -u`` does not fall through to a second
# subprocess call before the test inspects ``captured``.
_VALID_ID_U_STDOUT = "1000\n"


@pytest.fixture(autouse=True)
def _ungate_docker(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin ``shutil.which("docker")`` so ``_resolve_docker`` succeeds.

    The session-scoped guard in ``tests/conftest.py`` rewrites
    ``shutil.which`` to return ``None`` for ``docker``; we overwrite that
    with a per-test patch so the adapter can build its argv list.
    """
    monkeypatch.setattr(
        adapter_module.shutil, "which", lambda name, **kw: f"/usr/bin/{name}"
    )
    yield


# -- Argv shape (FR-021, FR-033) --------------------------------------------


def test_resolve_uid_argv_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        captured["argv"] = argv
        captured["kw"] = kw
        return _Completed(returncode=0, stdout=_VALID_ID_U_STDOUT)

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    uid = adapter.resolve_uid(container_id="abc", bench_user="user")

    assert uid == "1000"
    # ``docker exec`` is followed by FEAT-007 / Bug-2 locale-pinning ``-e``
    # flags then ``-u <user> <container_id>``.
    assert captured["argv"] == [
        "/usr/bin/docker",
        "exec",
        "-e",
        "LANG=C.UTF-8",
        "-e",
        "LC_ALL=C.UTF-8",
        "-u",
        "user",
        "abc",
        "id",
        "-u",
    ]
    # FR-021 — typed argv, never a shell string.
    assert captured["kw"]["shell"] is False
    assert captured["kw"]["timeout"] == pytest.approx(5.0)
    assert captured["kw"]["check"] is False
    # No shell metacharacters were interpolated into argv elements.
    for element in captured["argv"]:
        assert isinstance(element, str)
        for meta in ("$", "`", "&&", "||", ";", "|", ">", "<", "*", "?"):
            assert meta not in element, f"shell metachar {meta!r} in {element!r}"


def test_list_socket_dir_argv_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        captured["argv"] = argv
        captured["kw"] = kw
        return _Completed(returncode=0, stdout="")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    listing = adapter.list_socket_dir(container_id="abc", bench_user="user", uid="1000")

    assert listing.container_id == "abc"
    assert listing.uid == "1000"
    assert listing.sockets == ()
    assert captured["argv"] == [
        "/usr/bin/docker",
        "exec",
        "-e",
        "LANG=C.UTF-8",
        "-e",
        "LC_ALL=C.UTF-8",
        "-u",
        "user",
        "abc",
        "ls",
        "-1",
        "--",
        "/tmp/tmux-1000",
    ]
    assert captured["kw"]["shell"] is False
    assert captured["kw"]["timeout"] == pytest.approx(5.0)


def test_list_panes_argv_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        captured["argv"] = argv
        captured["kw"] = kw
        return _Completed(returncode=0, stdout="")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    adapter.list_panes(
        container_id="abc",
        bench_user="user",
        socket_path="/tmp/tmux-1000/work",
    )

    argv = captured["argv"]
    # FR-033 — exactly the documented invocation shape; FEAT-007 / Bug-2
    # adds ``-e LANG=C.UTF-8 -e LC_ALL=C.UTF-8`` between ``exec`` and ``-u``.
    assert argv[:2] == ["/usr/bin/docker", "exec"]
    assert "LANG=C.UTF-8" in argv
    assert "LC_ALL=C.UTF-8" in argv
    u_idx = argv.index("-u")
    assert argv[u_idx:u_idx + 3] == ["-u", "user", "abc"]
    assert "tmux" in argv
    tmux_idx = argv.index("tmux")
    assert argv[tmux_idx : tmux_idx + 6] == [
        "tmux",
        "-S",
        "/tmp/tmux-1000/work",
        "list-panes",
        "-a",
        "-F",
    ]
    fmt = argv[tmux_idx + 6]
    # The format string carries the documented tmux variables (R-002).
    for token in (
        "#{session_name}",
        "#{window_index}",
        "#{pane_index}",
        "#{pane_id}",
        "#{pane_pid}",
        "#{pane_tty}",
        "#{pane_current_command}",
        "#{pane_current_path}",
        "#{pane_title}",
        "#{pane_active}",
    ):
        assert token in fmt
    assert captured["kw"]["shell"] is False
    assert captured["kw"]["timeout"] == pytest.approx(5.0)


# -- Failure mode → closed-set code mapping ---------------------------------


def test_timeout_expired_normalizes_to_docker_exec_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-018 — ``subprocess.run`` performs kill+wait before raising.

    Reaching the ``except TimeoutExpired`` clause means stdlib's terminate-
    and-wait cleanup succeeded; we map it to ``docker_exec_timeout``.
    """

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 5.0))

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(TmuxError) as exc_info:
        adapter.resolve_uid(container_id="abc", bench_user="user")

    assert exc_info.value.code == _errors.DOCKER_EXEC_TIMEOUT
    assert exc_info.value.container_id == "abc"
    # R-005 — message bounded, mentions the budget, contains no raw stderr.
    assert "5.0s" in exc_info.value.message
    assert "Permission denied" not in exc_info.value.message
    assert "Traceback" not in exc_info.value.message


def test_id_u_non_zero_exit_yields_docker_exec_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _Completed(returncode=127, stderr="bash: id: not found")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(TmuxError) as exc_info:
        adapter.resolve_uid(container_id="abc", bench_user="user")

    assert exc_info.value.code == _errors.DOCKER_EXEC_FAILED
    assert exc_info.value.container_id == "abc"


def test_socket_listing_permission_denied_yields_socket_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-019 — ``socket_unreadable`` ONLY on the socket-listing call."""

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _Completed(
            returncode=1,
            stderr="ls: cannot open directory '/tmp/tmux-1000': Permission denied",
        )

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(TmuxError) as exc_info:
        adapter.list_socket_dir(container_id="abc", bench_user="user", uid="1000")

    assert exc_info.value.code == _errors.SOCKET_UNREADABLE
    assert exc_info.value.container_id == "abc"


def test_socket_listing_no_such_dir_yields_socket_dir_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _Completed(
            returncode=2,
            stderr="ls: cannot access '/tmp/tmux-1000': No such file or directory",
        )

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(TmuxError) as exc_info:
        adapter.list_socket_dir(container_id="abc", bench_user="user", uid="1000")

    assert exc_info.value.code == _errors.SOCKET_DIR_MISSING
    assert exc_info.value.container_id == "abc"


def test_list_panes_no_server_running_yields_tmux_no_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _Completed(
            returncode=1,
            stderr="no server running on /tmp/tmux-1000/work",
        )

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(TmuxError) as exc_info:
        adapter.list_panes(
            container_id="abc",
            bench_user="user",
            socket_path="/tmp/tmux-1000/work",
        )

    assert exc_info.value.code == _errors.TMUX_NO_SERVER
    assert exc_info.value.container_id == "abc"
    assert exc_info.value.tmux_socket_path == "/tmp/tmux-1000/work"


def test_list_panes_tmux_not_found_yields_tmux_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _Completed(returncode=127, stderr="tmux: command not found")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(TmuxError) as exc_info:
        adapter.list_panes(
            container_id="abc",
            bench_user="user",
            socket_path="/tmp/tmux-1000/work",
        )

    assert exc_info.value.code == _errors.TMUX_UNAVAILABLE


def test_docker_unavailable_when_shutil_which_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-019 — ``docker_unavailable`` when the binary cannot be located."""
    monkeypatch.setattr(adapter_module.shutil, "which", lambda name, **kw: None)
    adapter = adapter_module.SubprocessTmuxAdapter(env={"PATH": "/empty"})

    with pytest.raises(TmuxError) as exc_info:
        adapter.resolve_uid(container_id="abc", bench_user="user")
    assert exc_info.value.code == _errors.DOCKER_UNAVAILABLE

    with pytest.raises(TmuxError) as exc_info:
        adapter.list_socket_dir(container_id="abc", bench_user="user", uid="1000")
    assert exc_info.value.code == _errors.DOCKER_UNAVAILABLE

    with pytest.raises(TmuxError) as exc_info:
        adapter.list_panes(
            container_id="abc",
            bench_user="user",
            socket_path="/tmp/tmux-1000/work",
        )
    assert exc_info.value.code == _errors.DOCKER_UNAVAILABLE


# -- Kill-escalation skip (R-003) -------------------------------------------
#
# Skipped: R-003 escalation needs Popen-level rewrite. ``subprocess.run``
# performs ``proc.kill(); proc.communicate()`` internally and swallows any
# secondary failure; reaching the ``except TimeoutExpired`` clause already
# implies that cleanup succeeded. Exercising the
# kill-itself-fails / 1 s grace-period escalation → ``internal_error``
# branch demanded by T034 would require rewriting the adapter on top of
# ``subprocess.Popen`` (so the test could inject a kill-failure) which is
# explicitly out of scope for this task. Recorded here as a deliberate gap
# so reviewers see the omission.


# -- _resolve_bench_user (FR-020) -------------------------------------------


def test_resolve_bench_user_config_user_takes_precedence() -> None:
    assert _resolve_bench_user("user", {"USER": "host"}) == "user"


def test_resolve_bench_user_falls_back_to_USER() -> None:
    assert _resolve_bench_user(None, {"USER": "host"}) == "host"


def test_resolve_bench_user_falls_back_to_getpwuid_when_USER_empty() -> None:
    pwd = pytest.importorskip("pwd")
    expected = pwd.getpwuid(os.getuid()).pw_name
    if not expected:  # pragma: no cover — CI shells always populate this
        pytest.skip("pwd.getpwuid returned no pw_name on this host")
    assert _resolve_bench_user(None, {}) == expected


def test_resolve_bench_user_returns_none_when_all_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pwd = pytest.importorskip("pwd")

    def _raise(_uid):  # noqa: ANN001, ANN202
        raise KeyError("no such uid")

    # Patch the module-level ``_pwd`` reference used inside _resolve_bench_user.
    from agenttower.discovery import pane_service as pane_service_module

    monkeypatch.setattr(pane_service_module._pwd, "getpwuid", _raise)
    # Also defeat the precedence rules: empty config_user, empty $USER.
    assert _resolve_bench_user(None, {}) is None
    # Sanity: pwd is the same module patched above.
    assert pwd is pane_service_module._pwd


def test_resolve_bench_user_strips_uid_form() -> None:
    """FR-020 — ``app:1001`` splits on the first ``:`` and yields ``app``."""
    assert _resolve_bench_user("app:1001", {}) == "app"
    # Nested colons still split on the FIRST one.
    assert _resolve_bench_user("app:1001:extra", {}) == "app"
    # An empty left-hand side falls through to the next fallback.
    assert _resolve_bench_user(":1001", {"USER": "host"}) == "host"
