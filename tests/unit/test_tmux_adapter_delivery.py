"""T039 + T040 — FEAT-009 tmux adapter delivery-method tests.

Covers the four new methods on :class:`agenttower.tmux.adapter.TmuxAdapter`:

* ``load_buffer`` — body piped via stdin; argv-only; failure_reason
  mapping (tmux_paste_failed / docker_exec_failed /
  pane_disappeared_mid_attempt).
* ``paste_buffer`` — non-zero return → tmux_paste_failed (or
  pane_disappeared_mid_attempt on pane-gone stderr).
* ``send_keys`` — non-zero return → tmux_send_keys_failed (or
  pane_disappeared_mid_attempt); closed-set ``key`` argument.
* ``delete_buffer`` — non-zero return → tmux_paste_failed (caller
  decides to suppress per Group-A walk Q1/Q2).

Plus end-to-end behaviour on :class:`FakeTmuxAdapter` (call recording
+ programmable failures + buffer accounting).

Subprocess-level tests use ``unittest.mock.patch`` on
``subprocess.run`` to verify argv discipline (NO shell=True, NO body
in argv, body always via ``input=``).
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from agenttower.tmux.adapter import TmuxError
from agenttower.tmux.fakes import FakeTmuxAdapter
from agenttower.tmux.subprocess_adapter import SubprocessTmuxAdapter


# ──────────────────────────────────────────────────────────────────────
# SubprocessTmuxAdapter — argv discipline + happy path + failure mapping
# ──────────────────────────────────────────────────────────────────────


def _ok_completed(*, returncode: int = 0, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=b"", stderr=stderr)


def _ok_completed_text(*, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


# ─── load_buffer ──────────────────────────────────────────────────────


def test_load_buffer_argv_is_argv_only_no_shell() -> None:
    """The argv MUST be a list passed with ``shell=False``; the body
    MUST appear only as ``input=`` (NEVER in argv)."""
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    body = b"sensitive prompt token"
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed()
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            adapter.load_buffer(
                container_id="c0", bench_user="u",
                socket_path="/tmp/tmux-1000/default",
                buffer_name="agenttower-abc", body=body,
            )
    assert mock_run.call_count == 1
    kwargs = mock_run.call_args.kwargs
    assert kwargs["shell"] is False
    assert kwargs["text"] is False
    assert kwargs["check"] is False
    # The body is passed via stdin, NOT through argv.
    assert kwargs["input"] == body
    argv = mock_run.call_args.args[0]
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)
    # The body's distinctive bytes do not appear ANYWHERE in argv.
    body_str = body.decode()
    for arg in argv:
        assert body_str not in arg, f"body leaked into argv element {arg!r}"


def test_load_buffer_argv_contains_expected_docker_exec_tmux_chain() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed()
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            adapter.load_buffer(
                container_id="container-A", bench_user="user-B",
                socket_path="/tmp/tmux-1000/default",
                buffer_name="agenttower-xyz", body=b"x",
            )
    argv = mock_run.call_args.args[0]
    # Spot-check expected tokens; precise positions don't matter.
    assert argv[0] == "/usr/bin/docker"
    assert "exec" in argv
    assert "container-A" in argv
    assert "user-B" in argv
    assert "tmux" in argv
    assert "/tmp/tmux-1000/default" in argv
    assert "load-buffer" in argv
    assert "agenttower-xyz" in argv
    assert "-" in argv  # stdin dash


def test_load_buffer_non_zero_return_raises_tmux_paste_failed() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed(returncode=1, stderr=b"some error")
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.load_buffer(
                    container_id="c", bench_user="u",
                    socket_path="/s", buffer_name="b", body=b"x",
                )
    assert info.value.failure_reason == "tmux_paste_failed"


def test_load_buffer_pane_disappeared_stderr_maps_to_pane_disappeared() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed(
            returncode=1, stderr=b"can't find pane: %0"
        )
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.load_buffer(
                    container_id="c", bench_user="u",
                    socket_path="/s", buffer_name="b", body=b"x",
                )
    assert info.value.failure_reason == "pane_disappeared_mid_attempt"


def test_load_buffer_timeout_maps_to_tmux_paste_failed() -> None:
    """A hung ``docker exec tmux load-buffer`` is classified as a
    tmux-step failure (``tmux_paste_failed``), not a generic docker
    exec failure — the FEAT-009 caller-specified ``failure_reason``
    override on ``_run_bytes`` propagates through."""
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5.0)
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.load_buffer(
                    container_id="c", bench_user="u",
                    socket_path="/s", buffer_name="b", body=b"x",
                )
    assert info.value.failure_reason == "tmux_paste_failed"


def test_load_buffer_file_not_found_maps_to_tmux_paste_failed() -> None:
    """FileNotFoundError on ``load_buffer`` → ``tmux_paste_failed``
    (the FR-018 reason chosen by the caller, threaded through
    ``_run_bytes``)."""
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("docker not found")
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.load_buffer(
                    container_id="c", bench_user="u",
                    socket_path="/s", buffer_name="b", body=b"x",
                )
    assert info.value.failure_reason == "tmux_paste_failed"


def test_load_buffer_rejects_non_bytes_body() -> None:
    """Defensive: body MUST be bytes (FR-038, research §R-007). A str
    or memoryview slip-up raises with failure_reason=tmux_paste_failed."""
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with pytest.raises(TmuxError) as info:
        adapter.load_buffer(
            container_id="c", bench_user="u",
            socket_path="/s", buffer_name="b",
            body="not bytes",  # type: ignore[arg-type]
        )
    assert info.value.failure_reason == "tmux_paste_failed"


# ─── paste_buffer ─────────────────────────────────────────────────────


def test_paste_buffer_argv_only_no_shell() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text()
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            adapter.paste_buffer(
                container_id="c", bench_user="u",
                socket_path="/s", pane_id="%0", buffer_name="agenttower-xyz",
            )
    kwargs = mock_run.call_args.kwargs
    assert kwargs["shell"] is False
    argv = mock_run.call_args.args[0]
    assert "paste-buffer" in argv
    assert "%0" in argv
    assert "agenttower-xyz" in argv


def test_paste_buffer_non_zero_return_maps_to_tmux_paste_failed() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text(returncode=1, stderr="generic tmux error")
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.paste_buffer(
                    container_id="c", bench_user="u",
                    socket_path="/s", pane_id="%0", buffer_name="b",
                )
    assert info.value.failure_reason == "tmux_paste_failed"


def test_paste_buffer_pane_gone_maps_to_pane_disappeared_mid_attempt() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text(returncode=1, stderr="no such pane: %1")
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.paste_buffer(
                    container_id="c", bench_user="u",
                    socket_path="/s", pane_id="%1", buffer_name="b",
                )
    assert info.value.failure_reason == "pane_disappeared_mid_attempt"


# ─── send_keys ────────────────────────────────────────────────────────


def test_send_keys_argv_only_with_enter_key() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text()
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            adapter.send_keys(
                container_id="c", bench_user="u",
                socket_path="/s", pane_id="%0", key="Enter",
            )
    argv = mock_run.call_args.args[0]
    assert "send-keys" in argv
    assert "%0" in argv
    assert "Enter" in argv
    kwargs = mock_run.call_args.kwargs
    assert kwargs["shell"] is False


def test_send_keys_rejects_keys_outside_mvp_closed_set() -> None:
    """Closed-set check (Assumptions §"Submit keystroke" + plan §"Defaults
    locked"). MVP only allows ``Enter`` — a future config-file override
    that opened the set MUST NOT allow arbitrary keystroke injection."""
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        with pytest.raises(TmuxError) as info:
            adapter.send_keys(
                container_id="c", bench_user="u",
                socket_path="/s", pane_id="%0", key="C-c",
            )
        # Did NOT call subprocess.run — closed-set check ran first.
        mock_run.assert_not_called()
    assert info.value.failure_reason == "tmux_send_keys_failed"


def test_send_keys_non_zero_maps_to_tmux_send_keys_failed() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text(returncode=1, stderr="generic")
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.send_keys(
                    container_id="c", bench_user="u",
                    socket_path="/s", pane_id="%0", key="Enter",
                )
    assert info.value.failure_reason == "tmux_send_keys_failed"


def test_send_keys_pane_gone_maps_to_pane_disappeared() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text(returncode=1, stderr="can't find pane: %0")
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.send_keys(
                    container_id="c", bench_user="u",
                    socket_path="/s", pane_id="%0", key="Enter",
                )
    assert info.value.failure_reason == "pane_disappeared_mid_attempt"


# ─── delete_buffer ────────────────────────────────────────────────────


def test_delete_buffer_argv_only() -> None:
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text()
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            adapter.delete_buffer(
                container_id="c", bench_user="u",
                socket_path="/s", buffer_name="agenttower-xyz",
            )
    argv = mock_run.call_args.args[0]
    assert "delete-buffer" in argv
    assert "agenttower-xyz" in argv


def test_delete_buffer_non_zero_raises_tmux_paste_failed() -> None:
    """delete_buffer failure carries failure_reason='tmux_paste_failed';
    the worker decides whether to surface it (Group-A Q1/Q2)."""
    adapter = SubprocessTmuxAdapter(env={"PATH": "/usr/bin:/bin"})
    with patch("agenttower.tmux.subprocess_adapter.subprocess.run") as mock_run:
        mock_run.return_value = _ok_completed_text(returncode=1, stderr="generic")
        with patch("agenttower.tmux.subprocess_adapter.shutil.which", return_value="/usr/bin/docker"):
            with pytest.raises(TmuxError) as info:
                adapter.delete_buffer(
                    container_id="c", bench_user="u",
                    socket_path="/s", buffer_name="b",
                )
    assert info.value.failure_reason == "tmux_paste_failed"


# ──────────────────────────────────────────────────────────────────────
# FakeTmuxAdapter call recording + buffer accounting
# ──────────────────────────────────────────────────────────────────────


def test_fake_records_full_4_method_delivery_sequence() -> None:
    f = FakeTmuxAdapter()
    f.load_buffer(
        container_id="c0", bench_user="u",
        socket_path="/tmp/tmux-1000/default",
        buffer_name="agenttower-abc", body=b"hello world",
    )
    f.paste_buffer(
        container_id="c0", bench_user="u",
        socket_path="/tmp/tmux-1000/default",
        pane_id="%0", buffer_name="agenttower-abc",
    )
    f.send_keys(
        container_id="c0", bench_user="u",
        socket_path="/tmp/tmux-1000/default",
        pane_id="%0", key="Enter",
    )
    f.delete_buffer(
        container_id="c0", bench_user="u",
        socket_path="/tmp/tmux-1000/default",
        buffer_name="agenttower-abc",
    )
    assert [c[0] for c in f.delivery_calls] == [
        "load_buffer", "paste_buffer", "send_keys", "delete_buffer",
    ]
    # Body byte-exact in the recorded call.
    assert f.delivery_calls[0][1]["body"] == b"hello world"
    # Buffer was cleaned up by delete_buffer.
    assert f.buffers == {}


def test_fake_load_buffer_failure_can_be_programmed() -> None:
    f = FakeTmuxAdapter()
    f.load_buffer_failures.append(
        TmuxError(
            code="docker_exec_failed", message="simulated",
            failure_reason="tmux_paste_failed",
        )
    )
    with pytest.raises(TmuxError) as info:
        f.load_buffer(
            container_id="c", bench_user="u", socket_path="/s",
            buffer_name="b", body=b"x",
        )
    assert info.value.failure_reason == "tmux_paste_failed"
    # The call is STILL recorded (failure happens after recording so
    # tests can assert what was attempted).
    assert len(f.delivery_calls) == 1


def test_fake_paste_buffer_failure_drains_failure_queue_fifo() -> None:
    """Programmed failures pop FIFO — first failure consumed on first
    call, next call would succeed."""
    f = FakeTmuxAdapter()
    f.paste_buffer_failures.append(
        TmuxError(
            code="docker_exec_failed", message="first",
            failure_reason="tmux_paste_failed",
        )
    )
    with pytest.raises(TmuxError):
        f.paste_buffer(
            container_id="c", bench_user="u", socket_path="/s",
            pane_id="%0", buffer_name="b",
        )
    # Failure queue is now empty; next call succeeds.
    f.paste_buffer(
        container_id="c", bench_user="u", socket_path="/s",
        pane_id="%0", buffer_name="b",
    )
    assert len(f.delivery_calls) == 2


def test_fake_send_keys_closed_set_rejection_matches_production() -> None:
    f = FakeTmuxAdapter()
    with pytest.raises(TmuxError) as info:
        f.send_keys(
            container_id="c", bench_user="u", socket_path="/s",
            pane_id="%0", key="C-c",
        )
    assert info.value.failure_reason == "tmux_send_keys_failed"


def test_fake_buffer_map_tracks_load_and_delete() -> None:
    f = FakeTmuxAdapter()
    f.load_buffer(
        container_id="c", bench_user="u", socket_path="/s",
        buffer_name="b1", body=b"first",
    )
    f.load_buffer(
        container_id="c", bench_user="u", socket_path="/s",
        buffer_name="b2", body=b"second",
    )
    assert f.buffers == {"b1": b"first", "b2": b"second"}
    f.delete_buffer(
        container_id="c", bench_user="u", socket_path="/s", buffer_name="b1",
    )
    assert f.buffers == {"b2": b"second"}


def test_fake_rejects_non_bytes_body() -> None:
    """Fake mirrors production behaviour: non-bytes body raises."""
    f = FakeTmuxAdapter()
    with pytest.raises(TmuxError) as info:
        f.load_buffer(
            container_id="c", bench_user="u", socket_path="/s",
            buffer_name="b", body="not bytes",  # type: ignore[arg-type]
        )
    assert info.value.failure_reason == "tmux_paste_failed"
