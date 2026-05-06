"""T061 / spec edge case 13 / FR-029: two ``config doctor`` invocations
running concurrently must not serialize behind each other.

Scenario per spec edge case 13: two ``agenttower config doctor``
subprocesses run concurrently from inside the same simulated container.
Both must exit independently with the documented status. The doctor
performs only read-only socket calls (FEAT-002 ``status``, FEAT-003
``list_containers``, FEAT-004 ``list_panes``) so no daemon-side mutex
is acquired; the two invocations MUST NOT serialize behind each other.

The wall-clock for the two invocations together is bounded by
``2 × SC-003`` (1.0 s) against a healthy daemon — concurrent execution
does not double the SC-003 budget. The bound is conservative: when the
two run truly in parallel the wall-clock approaches the single-invocation
SC-003 budget rather than 2×.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    run_config_init,
    stop_daemon_if_alive,
)


_SC_003_BUDGET_SECONDS = 0.500
_TWO_INVOCATIONS_BUDGET = 2 * _SC_003_BUDGET_SECONDS  # 1.0 s


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _pin_container_context(env, tmp_path: Path) -> None:
    fake_root = tmp_path / "fake-container-proc"
    (fake_root / "proc" / "self").mkdir(parents=True)
    (fake_root / "etc").mkdir(parents=True)
    (fake_root / "proc" / "self" / "cgroup").write_text(
        "0::/docker/abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567\n"
    )
    (fake_root / ".dockerenv").write_text("")
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(fake_root)
    env.setdefault("AGENTTOWER_TEST_DOCKER_FAKE", "1")
    for var in ("TMUX", "TMUX_PANE"):
        env.pop(var, None)


def _spawn_doctor(env) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["agenttower", "config", "doctor", "--json"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


# ---------------------------------------------------------------------------
# Both invocations exit independently
# ---------------------------------------------------------------------------


class TestConcurrentInvocationsExitIndependently:
    def test_both_complete_and_emit_valid_json(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)

        p1 = _spawn_doctor(env)
        p2 = _spawn_doctor(env)
        out1, err1 = p1.communicate(timeout=5)
        out2, err2 = p2.communicate(timeout=5)

        # Both parse to valid JSON envelopes
        envelope1 = json.loads(out1)
        envelope2 = json.loads(out2)
        assert "summary" in envelope1
        assert "summary" in envelope2
        assert "checks" in envelope1
        assert "checks" in envelope2

        # Neither leaked to stderr (FR-014 + edge case 15)
        assert err1 == "", repr(err1)
        assert err2 == "", repr(err2)

    def test_both_exit_codes_match_summary_exit_code(self, env, tmp_path):
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)

        p1 = _spawn_doctor(env)
        p2 = _spawn_doctor(env)
        out1, _ = p1.communicate(timeout=5)
        out2, _ = p2.communicate(timeout=5)
        env1 = json.loads(out1)
        env2 = json.loads(out2)

        assert env1["summary"]["exit_code"] == p1.returncode
        assert env2["summary"]["exit_code"] == p2.returncode

    def test_both_emit_six_check_rows(self, env, tmp_path):
        """Every check appears in both invocations (FR-027)."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)

        p1 = _spawn_doctor(env)
        p2 = _spawn_doctor(env)
        out1, _ = p1.communicate(timeout=5)
        out2, _ = p2.communicate(timeout=5)
        env1 = json.loads(out1)
        env2 = json.loads(out2)

        expected_keys = {
            "socket_resolved",
            "socket_reachable",
            "daemon_status",
            "container_identity",
            "tmux_present",
            "tmux_pane_match",
        }
        assert set(env1["checks"].keys()) == expected_keys
        assert set(env2["checks"].keys()) == expected_keys


# ---------------------------------------------------------------------------
# Concurrent execution does not serialize — wall-clock bound
# ---------------------------------------------------------------------------


class TestConcurrentExecutionDoesNotSerialize:
    def test_combined_wall_clock_within_two_sc003_budget(self, env, tmp_path):
        """Two concurrent doctor invocations together complete within
        ``2 × SC-003`` (1.0 s) against a healthy daemon. If the daemon
        serialized them behind a mutex, the wall-clock would approach
        2 × SC-003 only when each invocation hits the budget; in
        practice we expect it to be well under."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)

        start = time.perf_counter()
        p1 = _spawn_doctor(env)
        p2 = _spawn_doctor(env)
        p1.communicate(timeout=5)
        p2.communicate(timeout=5)
        elapsed = time.perf_counter() - start

        assert elapsed < _TWO_INVOCATIONS_BUDGET, (
            f"two concurrent doctor invocations took {elapsed:.3f}s; "
            f"budget is {_TWO_INVOCATIONS_BUDGET:.3f}s ({_SC_003_BUDGET_SECONDS}s × 2). "
            f"Likely indicates the daemon serialized the two invocations."
        )

    def test_neither_invocation_exceeds_single_sc003_budget(
        self, env, tmp_path
    ):
        """If the daemon held a mutex, the second invocation's per-process
        wall-clock would spike. Each individual invocation should still
        complete within its single-invocation SC-003 budget when run
        concurrently with another."""
        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)

        starts: list[float] = []
        ends: list[float] = []

        starts.append(time.perf_counter())
        p1 = _spawn_doctor(env)
        starts.append(time.perf_counter())
        p2 = _spawn_doctor(env)
        p1.communicate(timeout=5)
        ends.append(time.perf_counter())
        p2.communicate(timeout=5)
        ends.append(time.perf_counter())

        for i, (s, e) in enumerate(zip(starts, ends)):
            elapsed = e - s
            # Allow some slack above SC-003 — concurrent OS scheduling
            # can stretch a single doctor's wall-clock slightly even
            # without daemon-side serialization. The 2× budget catches
            # mutex serialization; the 1.5× cap here catches gross
            # regressions.
            assert elapsed < 1.5 * _SC_003_BUDGET_SECONDS, (
                f"invocation {i} took {elapsed:.3f}s; "
                f"unexpected slow-down under concurrent load"
            )


# ---------------------------------------------------------------------------
# Doctor remains a pure read-only diagnostic under concurrency (FR-029)
# ---------------------------------------------------------------------------


class TestConcurrencyPreservesNoDiskWrite:
    def test_state_dir_unchanged_after_concurrent_doctor_runs(
        self, env, tmp_path
    ):
        import hashlib

        from ._daemon_helpers import resolved_paths

        run_config_init(env)
        ensure_daemon(env)
        _pin_container_context(env, tmp_path)

        state_dir = resolved_paths(tmp_path)["state_dir"]

        def _snapshot() -> dict[Path, tuple[int, str]]:
            snap: dict[Path, tuple[int, str]] = {}
            if not state_dir.exists():
                return snap
            for child in state_dir.rglob("*"):
                if child.is_file():
                    data = child.read_bytes()
                    snap[child] = (len(data), hashlib.sha256(data).hexdigest())
            return snap

        before = _snapshot()
        p1 = _spawn_doctor(env)
        p2 = _spawn_doctor(env)
        p1.communicate(timeout=5)
        p2.communicate(timeout=5)
        after = _snapshot()

        # Note: the daemon's lifecycle log MAY record the underlying
        # FEAT-002 status round-trips per FR-029. We tolerate log-file
        # appends but reject schema/state mutations and new files
        # outside the log.
        log_path = resolved_paths(tmp_path)["log_file"]
        before_keys = set(before.keys()) - {log_path}
        after_keys = set(after.keys()) - {log_path}
        assert before_keys == after_keys, (
            f"new non-log files: {after_keys - before_keys}; "
            f"removed: {before_keys - after_keys}"
        )
        for path in before_keys:
            assert before[path] == after[path], (
                f"{path} changed under concurrent doctor"
            )
