"""Unit tests for socket_resolve.py — FR-001, FR-002, R-001, SC-002.

Covers the FR-002 validator gates with closed-set ``<reason>`` tokens, the
priority chain `env_override → mounted_default → host_default`, and (per
analyze finding A4) the chained-symlink rejection rule.
"""

from __future__ import annotations

import os
import socket as socket_mod
import time
from pathlib import Path

import pytest

from agenttower.config_doctor.runtime_detect import (
    ContainerContext,
    HostContext,
)
from agenttower.config_doctor.socket_resolve import (
    MOUNTED_DEFAULT_PATH,
    ResolvedSocket,
    SocketPathInvalid,
    resolve_socket_path,
)
from agenttower.paths import Paths


def _make_paths(host_socket: Path) -> Paths:
    """Build a minimal Paths fixture; only ``socket`` is consulted by the resolver."""
    base = host_socket.parent
    return Paths(
        config_file=base / "config.toml",
        state_db=base / "state.sqlite3",
        events_file=base / "events.jsonl",
        logs_dir=base / "logs",
        socket=host_socket,
        cache_dir=base / "cache",
    )


@pytest.fixture
def real_unix_socket(tmp_path: Path):
    """Materialize an actual AF_UNIX socket file under tmp_path."""

    socket_path = tmp_path / "real.sock"
    sock = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
    sock.bind(str(socket_path))
    yield socket_path
    sock.close()
    if socket_path.exists():
        socket_path.unlink()


# ---------------------------------------------------------------------------
# Closed-set <reason> tokens (FR-002, contracts/cli.md §AGENTTOWER_SOCKET)
# ---------------------------------------------------------------------------


class TestReasonTokenSet:
    def test_closed_reason_set_is_exactly_five(self):
        assert SocketPathInvalid.REASONS == (
            "value is empty",
            "value is not absolute",
            "value contains NUL byte",
            "value does not exist",
            "value is not a Unix socket",
        )

    def test_unknown_reason_raises_on_construction(self):
        with pytest.raises(ValueError):
            SocketPathInvalid("not a real reason")


# ---------------------------------------------------------------------------
# Priority chain (FR-001)
# ---------------------------------------------------------------------------


class TestPriorityChain:
    def test_env_override_wins_when_set_and_valid(self, tmp_path, real_unix_socket):
        paths = _make_paths(tmp_path / "host.sock")
        env = {"AGENTTOWER_SOCKET": str(real_unix_socket)}
        resolved = resolve_socket_path(env, paths, ContainerContext(("dockerenv",)))
        assert resolved == ResolvedSocket(real_unix_socket, "env_override")

    def test_host_default_when_no_signal_no_override(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        resolved = resolve_socket_path({}, paths, HostContext())
        assert resolved == ResolvedSocket(tmp_path / "host.sock", "host_default")

    def test_host_default_when_container_but_mounted_default_missing(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        # No AGENTTOWER_SOCKET, runtime is container, but the global
        # /run/agenttower/agenttowerd.sock will not exist on a normal test box.
        resolved = resolve_socket_path({}, paths, ContainerContext(("dockerenv",)))
        # The mounted-default path is /run/agenttower/agenttowerd.sock — almost
        # certainly absent on the test host. Resolver must fall through to host_default.
        if not MOUNTED_DEFAULT_PATH.exists():
            assert resolved.source == "host_default"
            assert resolved.path == tmp_path / "host.sock"


# ---------------------------------------------------------------------------
# FR-002 validator gates
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_empty_string_rejected(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path({"AGENTTOWER_SOCKET": ""}, paths, HostContext())
        assert excinfo.value.reason == "value is empty"

    def test_whitespace_only_rejected(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path({"AGENTTOWER_SOCKET": "   "}, paths, HostContext())
        assert excinfo.value.reason == "value is empty"


class TestRelativePath:
    def test_relative_path_rejected(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": "relative/path.sock"},
                paths,
                HostContext(),
            )
        assert excinfo.value.reason == "value is not absolute"

    def test_dot_relative_path_rejected(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": "./run/sock"}, paths, HostContext()
            )
        assert excinfo.value.reason == "value is not absolute"


class TestNULByte:
    def test_nul_byte_rejected(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": "/run/agent\x00tower.sock"},
                paths,
                HostContext(),
            )
        assert excinfo.value.reason == "value contains NUL byte"


class TestNonExistentPath:
    def test_path_does_not_exist_rejected(self, tmp_path):
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": str(tmp_path / "nonexistent.sock")},
                paths,
                HostContext(),
            )
        assert excinfo.value.reason == "value does not exist"

    def test_broken_symlink_rejected(self, tmp_path):
        target = tmp_path / "missing-target.sock"
        link = tmp_path / "broken.sock"
        os.symlink(target, link)
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": str(link)}, paths, HostContext()
            )
        assert excinfo.value.reason == "value does not exist"


class TestNotASocket:
    def test_regular_file_rejected(self, tmp_path):
        regular = tmp_path / "not-a-socket"
        regular.write_text("hello")
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": str(regular)}, paths, HostContext()
            )
        assert excinfo.value.reason == "value is not a Unix socket"

    def test_directory_rejected(self, tmp_path):
        directory = tmp_path / "dir-not-socket"
        directory.mkdir()
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": str(directory)}, paths, HostContext()
            )
        assert excinfo.value.reason == "value is not a Unix socket"


# ---------------------------------------------------------------------------
# Symlinks (R-001 single-follow + analyze finding A4 chained-symlink rejection)
# ---------------------------------------------------------------------------


class TestSymlinkPolicy:
    def test_single_symlink_to_socket_accepted(self, tmp_path, real_unix_socket):
        link = tmp_path / "first-link.sock"
        os.symlink(real_unix_socket, link)
        paths = _make_paths(tmp_path / "host.sock")
        resolved = resolve_socket_path(
            {"AGENTTOWER_SOCKET": str(link)}, paths, HostContext()
        )
        assert resolved.source == "env_override"
        assert resolved.path == link

    def test_single_symlink_to_regular_file_rejected(self, tmp_path):
        regular = tmp_path / "regular"
        regular.write_text("not a socket")
        link = tmp_path / "link"
        os.symlink(regular, link)
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": str(link)}, paths, HostContext()
            )
        assert excinfo.value.reason == "value is not a Unix socket"

    def test_chained_symlink_rejected_a4(self, tmp_path, real_unix_socket):
        """A4: even if symlink → symlink → socket, the second-level link is NOT
        followed; the path fails with `value is not a Unix socket`."""
        first = tmp_path / "first.sock"
        second = tmp_path / "second.sock"
        os.symlink(real_unix_socket, second)  # second → real socket
        os.symlink(second, first)  # first → second (chain)
        paths = _make_paths(tmp_path / "host.sock")
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": str(first)}, paths, HostContext()
            )
        assert excinfo.value.reason == "value is not a Unix socket"


# ---------------------------------------------------------------------------
# SC-002 wall-clock budget (50 ms)
# ---------------------------------------------------------------------------


class TestPreFlightSpeed:
    @pytest.mark.parametrize(
        "value, expected_reason",
        [
            ("", "value is empty"),
            ("relative/path", "value is not absolute"),
            ("/path/with/\x00null", "value contains NUL byte"),
            ("/this/path/does/not/exist", "value does not exist"),
        ],
    )
    def test_invalid_input_rejected_under_50ms(self, tmp_path, value, expected_reason):
        paths = _make_paths(tmp_path / "host.sock")
        start = time.perf_counter()
        with pytest.raises(SocketPathInvalid) as excinfo:
            resolve_socket_path(
                {"AGENTTOWER_SOCKET": value}, paths, HostContext()
            )
        elapsed = time.perf_counter() - start
        assert elapsed < 0.050, f"validator took {elapsed*1000:.1f} ms"
        assert excinfo.value.reason == expected_reason


# ---------------------------------------------------------------------------
# T027 — _connect_via_chdir preservation: deep-cwd paths pass through untouched
# ---------------------------------------------------------------------------


class TestDeepCwdPassthrough:
    """T027 / edge case 12: the FEAT-002 sun_path 108-byte workaround lives in
    socket_api/client.py. The resolver must NOT alter or shorten a long
    socket-path; the chdir workaround is applied later."""

    def test_long_path_returned_untouched(self, tmp_path, real_unix_socket):
        # Construct a path longer than 108 bytes — even though the socket itself
        # lives at a short path, we test that the resolver path passes through
        # whatever the env says, byte-for-byte.
        long_dir = tmp_path / ("x" * 80)
        long_dir.mkdir()
        link_in_long = long_dir / "linked.sock"
        os.symlink(real_unix_socket, link_in_long)
        paths = _make_paths(tmp_path / "host.sock")
        resolved = resolve_socket_path(
            {"AGENTTOWER_SOCKET": str(link_in_long)}, paths, HostContext()
        )
        assert resolved.path == link_in_long
        assert resolved.source == "env_override"
        assert len(str(resolved.path)) > 80
