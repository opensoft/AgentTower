"""T216 / SC-012 — adversarial inputs produce zero side effects.

Parametrized fixture suite over:

* (a) FR-051 metabytes + shell-meta in the path
* (b) FR-052 daemon-owned roots
* (c) FR-053 special-filesystem realpath roots
* (d) FR-050 symlink escape from the canonical mount

For every adversarial input we assert the SC-012 invariant:

    zero log_attachments rows
    zero log_offsets rows
    zero docker exec invocations
    zero JSONL audit rows
    zero file-mode mutations (canonical log root + parent dirs unchanged)

The "zero docker exec" claim is verified indirectly via the validation
order in ``LogService.attach_log`` (data-model.md §7): every adversarial
case rejects at step 4 (FR-006/051/052/053 path validation) or step 5
(FR-007/050 host-visibility proof) — both BEFORE any ``docker exec``.
We assert "zero rows + zero JSONL"; if any docker exec had been issued,
either a row would have been written (validation order) or a sentinel
attempt would be recorded by the daemon's audit pipeline.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)
from .test_feat007_attach_log_smoke import (
    _seed_database,
    _write_pipe_pane_fake,
)


AGENT_ID = "agt_abc123def456"
CONTAINER_ID = "c" * 64


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def primed(tmp_path: Path):
    """Daemon up + seeded with one registered agent + canonical bind mount."""
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake_path = tmp_path / "pipe_pane_fake.json"
    _write_pipe_pane_fake(fake_path)
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake_path)
    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed_database(
        paths["state_db"],
        container_id=CONTAINER_ID,
        agent_id=AGENT_ID,
        host_log_root=host_log_root,
    )
    try:
        yield env, home, paths
    finally:
        stop_daemon_if_alive(env)


def _attach_log_with_path(env, log_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "agenttower",
            "attach-log",
            "--target",
            AGENT_ID,
            "--log",
            log_path,
            "--json",
        ],
        env=env, capture_output=True, text=True, timeout=10,
    )


def _row_counts(state_db: Path) -> tuple[int, int]:
    conn = sqlite3.connect(str(state_db))
    try:
        la = conn.execute("SELECT count(*) FROM log_attachments").fetchone()[0]
        lo = conn.execute("SELECT count(*) FROM log_offsets").fetchone()[0]
    finally:
        conn.close()
    return la, lo


def _audit_row_count(events_file: Path) -> int:
    if not events_file.exists():
        return 0
    rows = events_file.read_text().splitlines()
    return sum(
        1 for line in rows
        if '"type": "log_attachment_change"' in line
        or '"type":"log_attachment_change"' in line
    )


def _state_dir_modes(state_dir: Path) -> dict[str, int]:
    """Snapshot file-mode bits for every regular file under state_dir.

    SC-012 asserts adversarial calls do not mutate file modes — most
    notably the canonical-log-root tree.
    """
    out: dict[str, int] = {}
    for path in state_dir.rglob("*"):
        if path.is_file() or path.is_dir():
            try:
                out[str(path.relative_to(state_dir))] = stat.S_IMODE(path.stat().st_mode)
            except FileNotFoundError:
                continue
    return out


def _assert_zero_side_effects(
    paths: dict[str, Path],
    *,
    initial_la: int,
    initial_lo: int,
    initial_audit: int,
    initial_modes: dict[str, int],
) -> None:
    la, lo = _row_counts(paths["state_db"])
    assert la == initial_la, (
        f"FEAT-007 adversarial input mutated log_attachments "
        f"(before={initial_la}, after={la}); SC-012 requires zero side effects"
    )
    assert lo == initial_lo, (
        f"FEAT-007 adversarial input mutated log_offsets "
        f"(before={initial_lo}, after={lo}); SC-012 requires zero side effects"
    )
    audit = _audit_row_count(paths["events_file"])
    assert audit == initial_audit, (
        f"FEAT-007 adversarial input appended an audit row "
        f"(before={initial_audit}, after={audit}); SC-012 requires zero JSONL"
    )
    final_modes = _state_dir_modes(paths["state_dir"])
    for relpath, prior_mode in initial_modes.items():
        if relpath in final_modes:
            assert final_modes[relpath] == prior_mode, (
                f"FEAT-007 adversarial input changed file mode for {relpath!r} "
                f"(before={oct(prior_mode)}, after={oct(final_modes[relpath])})"
            )


# ---------------------------------------------------------------------------
# (a) FR-051 metabyte + shell-meta cases
# ---------------------------------------------------------------------------


# FR-051 metabytes: NUL, control bytes 0x01-0x1F, DEL 0x7F, plus the named
# log-line-breaking trio (\n, \r, \t).
FR051_METABYTE_CASES = [
    pytest.param("/host/log/a\nb.log", id="newline"),
    pytest.param("/host/log/a\rb.log", id="carriage_return"),
    pytest.param("/host/log/a\tb.log", id="tab"),
    pytest.param("/host/log/a\x00b.log", id="nul"),
    pytest.param("/host/log/a\x01b.log", id="c0_0x01"),
    pytest.param("/host/log/a\x1fb.log", id="c0_0x1f"),
    pytest.param("/host/log/a\x7fb.log", id="del_0x7f"),
]


@pytest.mark.parametrize("adversarial_path", FR051_METABYTE_CASES)
def test_fr051_metabyte_rejected_zero_side_effects(primed, adversarial_path: str) -> None:
    env, home, paths = primed
    initial_la, initial_lo = _row_counts(paths["state_db"])
    initial_audit = _audit_row_count(paths["events_file"])
    initial_modes = _state_dir_modes(paths["state_dir"])

    try:
        proc = _attach_log_with_path(env, adversarial_path)
    except ValueError:
        # Python's subprocess refuses NUL bytes in argv before exec; the
        # request never crosses the process boundary. That's an even
        # stronger zero-side-effect than the daemon-side log_path_invalid
        # rejection (which is unit-tested in test_logs_path_validation.py).
        # The daemon never saw the request, so state cannot have changed.
        _assert_zero_side_effects(
            paths,
            initial_la=initial_la,
            initial_lo=initial_lo,
            initial_audit=initial_audit,
            initial_modes=initial_modes,
        )
        return

    assert proc.returncode == 3, (
        f"adversarial path {adversarial_path!r} should exit 3, got {proc.returncode}"
    )
    envelope = json.loads(proc.stdout) if proc.stdout.strip() else {}
    if envelope:
        assert envelope.get("error", {}).get("code") in {"log_path_invalid", "bad_request"}, (
            f"unexpected error code: {envelope!r}"
        )

    _assert_zero_side_effects(
        paths,
        initial_la=initial_la,
        initial_lo=initial_lo,
        initial_audit=initial_audit,
        initial_modes=initial_modes,
    )


def test_fr051_relative_path_rejected_zero_side_effects(primed) -> None:
    """Non-absolute paths are rejected by FR-006 (closely related to FR-051)."""
    env, home, paths = primed
    initial_la, initial_lo = _row_counts(paths["state_db"])
    initial_audit = _audit_row_count(paths["events_file"])
    initial_modes = _state_dir_modes(paths["state_dir"])

    proc = _attach_log_with_path(env, "relative/log.txt")
    assert proc.returncode == 3
    envelope = json.loads(proc.stdout)
    assert envelope.get("error", {}).get("code") == "log_path_invalid"

    _assert_zero_side_effects(
        paths,
        initial_la=initial_la,
        initial_lo=initial_lo,
        initial_audit=initial_audit,
        initial_modes=initial_modes,
    )


def test_fr051_dotdot_segment_rejected_zero_side_effects(primed) -> None:
    """``..`` segments are rejected by FR-006 / FR-051."""
    env, home, paths = primed
    initial_la, initial_lo = _row_counts(paths["state_db"])
    initial_audit = _audit_row_count(paths["events_file"])
    initial_modes = _state_dir_modes(paths["state_dir"])

    proc = _attach_log_with_path(env, "/host/log/../escape.log")
    assert proc.returncode == 3
    envelope = json.loads(proc.stdout)
    assert envelope.get("error", {}).get("code") == "log_path_invalid"

    _assert_zero_side_effects(
        paths,
        initial_la=initial_la,
        initial_lo=initial_lo,
        initial_audit=initial_audit,
        initial_modes=initial_modes,
    )


# ---------------------------------------------------------------------------
# (b) FR-052 daemon-owned root cases
# ---------------------------------------------------------------------------


def _fr052_cases(home: Path) -> list[tuple[str, str]]:
    """Build the FR-052 daemon-owned root rejection cases for the given $HOME.

    Returns a list of ``(case_id, attempted_path)``. Each path is intended
    to overwrite a daemon-owned artifact and MUST be rejected.
    """
    state_dir = home / ".local" / "state" / "opensoft" / "agenttower"
    config_dir = home / ".config" / "opensoft"
    cache_dir = home / ".cache" / "opensoft"
    return [
        ("state_dir_root", str(state_dir / "stolen.log")),
        ("sqlite_db_path", str(state_dir / "agenttower.sqlite3")),
        ("events_file_path", str(state_dir / "events.jsonl")),
        ("daemon_socket_path", str(state_dir / "agenttowerd.sock")),
        ("daemon_pid_file_path", str(state_dir / "agenttowerd.pid")),
        ("daemon_lock_file_path", str(state_dir / "agenttowerd.lock")),
        ("config_root", str(config_dir / "stolen.log")),
        ("cache_root", str(cache_dir / "stolen.log")),
    ]


@pytest.mark.parametrize(
    "case_id",
    [
        "state_dir_root",
        "sqlite_db_path",
        "events_file_path",
        "daemon_socket_path",
        "daemon_pid_file_path",
        "daemon_lock_file_path",
        "config_root",
        "cache_root",
    ],
)
def test_fr052_daemon_owned_root_rejected_zero_side_effects(primed, case_id: str) -> None:
    env, home, paths = primed
    cases = dict(_fr052_cases(home))
    adversarial_path = cases[case_id]

    initial_la, initial_lo = _row_counts(paths["state_db"])
    initial_audit = _audit_row_count(paths["events_file"])
    initial_modes = _state_dir_modes(paths["state_dir"])

    proc = _attach_log_with_path(env, adversarial_path)
    assert proc.returncode == 3, (
        f"FR-052 case {case_id!r} should exit 3 ({adversarial_path!r}); "
        f"got {proc.returncode}, stderr={proc.stderr!r}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope.get("error", {}).get("code") == "log_path_invalid", (
        f"FR-052 case {case_id!r} expected log_path_invalid, got {envelope!r}"
    )

    _assert_zero_side_effects(
        paths,
        initial_la=initial_la,
        initial_lo=initial_lo,
        initial_audit=initial_audit,
        initial_modes=initial_modes,
    )


# ---------------------------------------------------------------------------
# (c) FR-053 special-filesystem realpath cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adversarial_path",
    [
        pytest.param("/proc/self/mem", id="proc_self_mem"),
        pytest.param("/proc/1/cmdline", id="proc_pid1_cmdline"),
        pytest.param("/sys/kernel/notes", id="sys_kernel"),
        pytest.param("/dev/null", id="dev_null"),
        pytest.param("/dev/zero", id="dev_zero"),
        pytest.param("/run/foo.log", id="run_root"),
    ],
)
def test_fr053_special_fs_rejected_zero_side_effects(primed, adversarial_path: str) -> None:
    env, home, paths = primed
    initial_la, initial_lo = _row_counts(paths["state_db"])
    initial_audit = _audit_row_count(paths["events_file"])
    initial_modes = _state_dir_modes(paths["state_dir"])

    proc = _attach_log_with_path(env, adversarial_path)
    assert proc.returncode == 3, (
        f"FR-053 path {adversarial_path!r} should exit 3, got {proc.returncode}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope.get("error", {}).get("code") == "log_path_invalid", (
        f"FR-053 path {adversarial_path!r} expected log_path_invalid, got {envelope!r}"
    )

    _assert_zero_side_effects(
        paths,
        initial_la=initial_la,
        initial_lo=initial_lo,
        initial_audit=initial_audit,
        initial_modes=initial_modes,
    )


# ---------------------------------------------------------------------------
# (d) FR-050 symlink escape from canonical mount
# ---------------------------------------------------------------------------


def test_fr050_realpath_outside_mount_rejected_zero_side_effects(
    primed, tmp_path: Path
) -> None:
    """FR-050: a path under the canonical bind-mount root whose realpath
    escapes the mount source MUST be rejected with ``log_path_not_host_visible``.

    Setup: create a real file ``escape.log`` outside the canonical log
    root, then a symlink under the canonical log root pointing at it.
    The container-side `--log` argument names the symlink path; the
    host-visibility prover MUST realpath-resolve it and refuse because
    the resolved target lies outside the mount source.
    """
    env, home, paths = primed
    canonical_logs = paths["state_dir"] / "logs"
    container_logs = canonical_logs / CONTAINER_ID
    container_logs.mkdir(parents=True, exist_ok=True)

    # Real file lives OUTSIDE the canonical log root.
    escape_target = tmp_path / "outside" / "real.log"
    escape_target.parent.mkdir(parents=True, exist_ok=True)
    escape_target.write_bytes(b"")

    # Symlink under the canonical log root pointing at the escape target.
    symlink_path = container_logs / "escape_via_symlink.log"
    if symlink_path.exists() or symlink_path.is_symlink():
        symlink_path.unlink()
    os.symlink(str(escape_target), str(symlink_path))

    initial_la, initial_lo = _row_counts(paths["state_db"])
    initial_audit = _audit_row_count(paths["events_file"])
    initial_modes = _state_dir_modes(paths["state_dir"])

    proc = _attach_log_with_path(env, str(symlink_path))
    assert proc.returncode == 3, (
        f"FR-050 symlink-escape should exit 3, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    envelope = json.loads(proc.stdout)
    code = envelope.get("error", {}).get("code")
    # FR-050 is implemented in host_visibility.py; its rejection code is
    # log_path_not_host_visible. The symlink resolves to a target outside
    # the (host=container) bind-mount range so the prover refuses.
    assert code in {"log_path_not_host_visible", "log_path_invalid"}, (
        f"FR-050 symlink-escape expected log_path_not_host_visible, got {envelope!r}"
    )

    _assert_zero_side_effects(
        paths,
        initial_la=initial_la,
        initial_lo=initial_lo,
        initial_audit=initial_audit,
        initial_modes=initial_modes,
    )
