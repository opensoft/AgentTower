"""US1 AS2 / US1 AS4 / US3 integration coverage (T021, T022, T023, T034, T047, T018).

Bundles several short integration scenarios that share the same fixture
pattern: the daemon spawns under an isolated ``$HOME`` with optional
``AGENTTOWER_TEST_PROC_ROOT`` and ``AGENTTOWER_SOCKET`` overrides.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    run_config_init,
    status,
    stop_daemon_if_alive,
)
from ._proc_fixtures import fake_proc_root  # noqa: F401  (registers fixture)


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _run(env, *args):
    return subprocess.run(
        ["agenttower", *args], env=env, capture_output=True, text=True, timeout=10
    )


# ---------------------------------------------------------------------------
# US1 AS2 / T022 — AGENTTOWER_SOCKET override wins
# ---------------------------------------------------------------------------


class TestAgenttowerSocketOverride:
    def test_override_wins_over_host_default(self, tmp_path):
        """AGENTTOWER_SOCKET=<temp socket> overrides host default.

        We spawn the daemon under one $HOME, then point AGENTTOWER_SOCKET at
        its socket and verify status connects via the override path."""
        env = isolated_env(tmp_path)
        try:
            run_config_init(env)
            ensure_daemon(env)
            from ._daemon_helpers import resolved_paths

            socket_path = resolved_paths(tmp_path)["socket"]

            override_env = isolated_env(tmp_path)
            override_env["AGENTTOWER_SOCKET"] = str(socket_path)
            proc = _run(override_env, "config", "paths")
            assert proc.returncode == 0
            assert "SOCKET_SOURCE=env_override" in proc.stdout
        finally:
            stop_daemon_if_alive(env)

    def test_invalid_override_exits_1_with_fr002_message(self, tmp_path):
        env = isolated_env(tmp_path)
        env["AGENTTOWER_SOCKET"] = "relative/path.sock"
        proc = _run(env, "status")
        assert proc.returncode == 1
        assert "AGENTTOWER_SOCKET must be an absolute path to a Unix socket" in proc.stderr
        assert "value is not absolute" in proc.stderr


# ---------------------------------------------------------------------------
# US1 AS4 / T023 — no socket mount → exit 2 with FEAT-002 message
# ---------------------------------------------------------------------------


class TestNoSocketMount:
    def test_status_exits_2_when_no_daemon(self, tmp_path):
        env = isolated_env(tmp_path)
        run_config_init(env)
        # Do NOT ensure-daemon — socket file does not exist
        proc = status(env)
        assert proc.returncode == 2
        # FEAT-002 byte-stable error message
        assert "daemon is not running or socket is unreachable" in proc.stderr


# ---------------------------------------------------------------------------
# T018 — SOCKET_SOURCE integration: covers all three resolution branches
# ---------------------------------------------------------------------------


class TestSocketSourceLine:
    def test_host_context_yields_host_default(self, env):
        proc = _run(env, "config", "paths")
        assert proc.returncode == 0
        lines = proc.stdout.rstrip("\n").splitlines()
        # FEAT-008 appends EVENTS_* lines after SOCKET_SOURCE; the
        # SOCKET_SOURCE token now lives on line 7 of the FEAT-001..005
        # block.
        assert lines[6] == "SOCKET_SOURCE=host_default"

    def test_env_override_yields_env_override(self, env, tmp_path):
        # Materialize a real Unix socket so the validator passes
        import socket as _sm

        sock_path = tmp_path / "x.sock"
        s = _sm.socket(_sm.AF_UNIX, _sm.SOCK_STREAM)
        s.bind(str(sock_path))
        try:
            env["AGENTTOWER_SOCKET"] = str(sock_path)
            proc = _run(env, "config", "paths")
            assert proc.returncode == 0
            lines = proc.stdout.rstrip("\n").splitlines()
            assert lines[6] == "SOCKET_SOURCE=env_override"
            # And SOCKET= line reflects the override
            socket_line = next(line for line in lines if line.startswith("SOCKET="))
            assert socket_line == f"SOCKET={sock_path}"
        finally:
            s.close()
            if sock_path.exists():
                sock_path.unlink()


# ---------------------------------------------------------------------------
# T034 — host_context: doctor on host shell shows host_context (not fail)
# ---------------------------------------------------------------------------


class TestDoctorHostContext:
    def test_container_identity_is_host_context(self, env, tmp_path):
        """US2 AS3 — host context yields container_identity = info/host_context.

        We pin the runtime context to host by pointing
        ``AGENTTOWER_TEST_PROC_ROOT`` at an empty fake `/proc` (no
        ``/.dockerenv``, no cgroup match) — the dev box itself runs inside
        a container, so without this seam the test would observe
        ``ContainerContext`` and a hostname-driven candidate."""
        run_config_init(env)
        ensure_daemon(env)
        # Build an empty fake-/proc tree: no /.dockerenv, no cgroup match.
        fake_root = tmp_path / "fake-host-proc"
        (fake_root / "proc" / "self").mkdir(parents=True)
        (fake_root / "etc").mkdir(parents=True)
        (fake_root / "proc" / "self" / "cgroup").write_text("0::/\n")
        env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
        # Companion AGENTTOWER_TEST_* var so the FR-025 / A2 production
        # guard recognizes this as a test invocation, not a leaked
        # environment. AGENTTOWER_TEST_DOCKER_FAKE is the FEAT-003 test seam
        # already honored by the daemon.
        env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
        proc = _run(env, "config", "doctor", "--json")
        envelope = json.loads(proc.stdout)
        ci = envelope["checks"]["container_identity"]
        assert ci["status"] == "info"
        assert ci["sub_code"] == "host_context"


# ---------------------------------------------------------------------------
# T047 — tmux unset → not_in_tmux (info, never fail)
# ---------------------------------------------------------------------------


class TestTmuxUnset:
    def test_tmux_unset_yields_not_in_tmux(self, env):
        run_config_init(env)
        ensure_daemon(env)
        # Strip TMUX vars so we land in not_in_tmux territory regardless of
        # the host shell's state
        env = {k: v for k, v in env.items() if k not in ("TMUX", "TMUX_PANE")}
        proc = _run(env, "config", "doctor", "--json")
        envelope = json.loads(proc.stdout)
        tp = envelope["checks"]["tmux_present"]
        assert tp["status"] == "info"
        assert tp["sub_code"] == "not_in_tmux"
        # And tmux_pane_match propagates not_in_tmux (NOT a fail)
        tpm = envelope["checks"]["tmux_pane_match"]
        assert tpm["status"] == "info"
        assert tpm["sub_code"] == "not_in_tmux"
