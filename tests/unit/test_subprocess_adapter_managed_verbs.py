"""Argv-shape tests for SubprocessTmuxAdapter's FEAT-013 managed verbs (T057).

Stubs ``_run`` so no real ``docker``/``tmux`` is invoked; asserts the
composed argv is argv-first (no shell), carries the ``-P -F '#{pane_id}'``
print format, places launch argv after ``--``, and that ``has_session``
maps exit codes correctly.
"""

from __future__ import annotations

import subprocess

import pytest

from agenttower.tmux.adapter import TmuxError
from agenttower.tmux.subprocess_adapter import SubprocessTmuxAdapter


def _adapter_with_run(returncode: int, stdout: str = "", stderr: str = ""):
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin", "USER": "x"})
    adapter._resolve_docker = lambda: "docker"  # type: ignore[assignment]
    calls: list[list[str]] = []

    def fake_run(argv, *, container_id, socket_path, failure_reason=None):  # noqa: ANN001
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    adapter._run = fake_run  # type: ignore[assignment]
    return adapter, calls


def test_new_session_argv_is_argv_first_with_print_format() -> None:
    adapter, calls = _adapter_with_run(0, stdout="%3\n")
    pane_id = adapter.new_session(
        container_id="c1", bench_user="u", socket_path="/tmp/tmux-1000/default",
        session_name="feat013", window_name="agenttower",
        launch_argv=("claude", "--flag"), working_dir="/workspace",
        env={"LOG_LEVEL": "debug"},
    )
    assert pane_id == "%3"
    argv = calls[0]
    # docker exec -u u c1 tmux -S <socket> new-session ...
    assert argv[0] == "docker" and "exec" in argv
    assert argv[-len(('claude', '--flag')):] == ["claude", "--flag"]
    assert "--" in argv and argv.index("--") < argv.index("claude")
    assert "-P" in argv and "#{pane_id}" in argv
    assert "-c" in argv and "/workspace" in argv
    assert "-e" in argv and "LOG_LEVEL=debug" in argv
    # window + session names present as separate argv tokens.
    assert "feat013" in argv and "agenttower" in argv


def test_new_session_empty_argv_omits_separator() -> None:
    adapter, calls = _adapter_with_run(0, stdout="%0")
    adapter.new_session(
        container_id="c1", bench_user="u", socket_path="/s",
        session_name="s", window_name="w", launch_argv=(),
    )
    assert "--" not in calls[0]


def test_new_session_nonzero_raises_tmux_error() -> None:
    adapter, _ = _adapter_with_run(1, stderr="no server running")
    with pytest.raises(TmuxError):
        adapter.new_session(
            container_id="c1", bench_user="u", socket_path="/s",
            session_name="s", window_name="w", launch_argv=(),
        )


def test_new_session_empty_stdout_is_output_malformed() -> None:
    adapter, _ = _adapter_with_run(0, stdout="   \n")
    with pytest.raises(TmuxError) as exc:
        adapter.new_session(
            container_id="c1", bench_user="u", socket_path="/s",
            session_name="s", window_name="w", launch_argv=(),
        )
    assert exc.value.code == "output_malformed"


def test_split_window_includes_direction_flag() -> None:
    adapter, calls = _adapter_with_run(0, stdout="%5")
    adapter.split_window(
        container_id="c1", bench_user="u", socket_path="/s",
        session_name="feat013", direction="h", launch_argv=(),
    )
    assert "split-window" in calls[0]
    assert "-h" in calls[0]
    assert "feat013" in calls[0]


def test_split_window_rejects_bad_direction() -> None:
    adapter, _ = _adapter_with_run(0, stdout="%5")
    with pytest.raises(TmuxError):
        adapter.split_window(
            container_id="c1", bench_user="u", socket_path="/s",
            session_name="s", direction="x", launch_argv=(),
        )


def test_has_session_true_on_zero_exit() -> None:
    adapter, _ = _adapter_with_run(0)
    assert adapter.has_session(
        container_id="c1", bench_user="u", socket_path="/s", session_name="s"
    ) is True


def test_has_session_false_on_absent_session() -> None:
    adapter, _ = _adapter_with_run(1, stderr="can't find session: s")
    assert adapter.has_session(
        container_id="c1", bench_user="u", socket_path="/s", session_name="s"
    ) is False


def test_has_session_raises_on_docker_exec_failure() -> None:
    adapter, _ = _adapter_with_run(1, stderr="Error response from daemon: no such container")
    with pytest.raises(TmuxError):
        adapter.has_session(
            container_id="c1", bench_user="u", socket_path="/s", session_name="s"
        )


def test_set_pane_title_and_kill_pane_target_pane_id() -> None:
    adapter, calls = _adapter_with_run(0)
    adapter.set_pane_title(
        container_id="c1", bench_user="u", socket_path="/s",
        pane_id="%9", title="@MANAGED:tok:m1",
    )
    assert "select-pane" in calls[0] and "%9" in calls[0] and "@MANAGED:tok:m1" in calls[0]

    adapter2, calls2 = _adapter_with_run(0)
    adapter2.kill_pane(
        container_id="c1", bench_user="u", socket_path="/s", pane_id="%9",
    )
    assert "kill-pane" in calls2[0] and "%9" in calls2[0]


def test_is_pane_dead_argv_queries_pane_dead_format() -> None:
    adapter, calls = _adapter_with_run(0, stdout="0\n")
    dead = adapter.is_pane_dead(
        container_id="c1", bench_user="u", socket_path="/s", pane_id="%4",
    )
    assert dead is False
    argv = calls[0]
    assert "display-message" in argv and "-p" in argv
    assert "%4" in argv and "#{pane_dead}" in argv


def test_is_pane_dead_true_when_format_reports_one() -> None:
    adapter, _ = _adapter_with_run(0, stdout="1\n")
    assert adapter.is_pane_dead(
        container_id="c1", bench_user="u", socket_path="/s", pane_id="%4",
    ) is True


def test_is_pane_dead_true_when_pane_vanished() -> None:
    adapter, _ = _adapter_with_run(1, stderr="can't find pane: %4")
    assert adapter.is_pane_dead(
        container_id="c1", bench_user="u", socket_path="/s", pane_id="%4",
    ) is True


def test_is_pane_dead_raises_on_docker_exec_failure() -> None:
    adapter, _ = _adapter_with_run(
        1, stderr="Error response from daemon: no such container"
    )
    with pytest.raises(TmuxError):
        adapter.is_pane_dead(
            container_id="c1", bench_user="u", socket_path="/s", pane_id="%4",
        )
