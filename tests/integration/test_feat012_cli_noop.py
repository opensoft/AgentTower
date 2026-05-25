"""FEAT-012 T156 — CLI non-regression smoke.

Constitution principle IV ("Observable and Scriptable") says every feature
must remain usable from the CLI. FEAT-012 introduces a Dart/Flutter desktop
app under ``apps/control_panel/``. The constitution-level invariant is:

    Installing the desktop app MUST NOT modify the behavior of any FEAT-002
    through FEAT-010 CLI command, and MUST NOT cause any FEAT-002 through
    FEAT-010 CLI command to read from or write to the desktop app's
    per-OS-user data directory (``<app-data>/agenttower-control-panel/``
    per plan.md §Storage and FR-061a).

This test asserts both halves of that invariant on the daemon-CLI lane —
the same lane the analyze finding ``Const2`` was raised on.

The test deliberately does NOT exercise the desktop app itself. The
desktop app is a separate Dart Flutter process under ``apps/control_panel/``
and has its own ``flutter test`` lane. T156's job is the inverse: prove
that *the existence* of FEAT-012's desktop-app data files in the user's
home directory cannot affect the legacy CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
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


# ─── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


@pytest.fixture
def daemon(env: dict[str, str]) -> dict:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    paths = resolved_paths(Path(env["HOME"]))
    return {"env": env, "paths": paths}


# ─── Helpers ────────────────────────────────────────────────────────────


def _cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    """Run an ``agenttower`` CLI command against the isolated env."""
    return subprocess.run(
        ["agenttower", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ─── Constants ──────────────────────────────────────────────────────────

# Representative FEAT-002..010 CLI subcommands that:
#   * always succeed against a fresh daemon with no bench container,
#   * emit deterministic structured output (JSON), and
#   * exercise the FEAT-002/006/007/008/009/010 read paths.
#
# These are the surfaces a regression in FEAT-012 could plausibly perturb
# (they all eventually read the same SQLite store that the daemon owns).
# Each entry is (label, [argv...]) — the label is used in assertion
# messages so a failure points at the offending subcommand.
_REGRESSION_SURFACES: tuple[tuple[str, list[str]], ...] = (
    ("config-doctor",  ["config", "doctor", "--json"]),
    ("config-paths",   ["config", "paths", "--json"]),
    ("agent-list",     ["agent", "list", "--json"]),
    ("route-list",     ["route", "list", "--json"]),
    ("queue-list",     ["queue", "list", "--json"]),
    ("event-list",     ["event", "list", "--json"]),
)


# ─── Tests ──────────────────────────────────────────────────────────────


def test_cli_surfaces_remain_callable_post_feat012(daemon: dict) -> None:
    """Constitution IV / Const2 — every representative FEAT-002..010 CLI
    surface still returns exit 0 with parseable JSON after FEAT-012's
    desktop-app code has landed in the repository.

    A regression in this test means a FEAT-012 code change broke the CLI
    promise — the FEAT-012 desktop app must be purely additive."""
    env: dict[str, str] = daemon["env"]
    failures: list[str] = []
    for label, argv in _REGRESSION_SURFACES:
        proc = _cli(env, *argv)
        if proc.returncode != 0:
            failures.append(
                f"{label}: rc={proc.returncode}\n"
                f"  stdout={proc.stdout!r}\n  stderr={proc.stderr!r}"
            )
            continue
        # Each surface advertises --json so we expect parseable JSON.
        try:
            json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            failures.append(
                f"{label}: rc=0 but stdout is not JSON: {e}\n"
                f"  stdout={proc.stdout!r}"
            )
    assert not failures, (
        "FEAT-012 regression: one or more FEAT-002..010 CLI surfaces "
        "broke or returned malformed output:\n\n" + "\n\n".join(failures)
    )


def test_desktop_app_data_dir_does_not_leak_into_cli(daemon: dict) -> None:
    """Const2 namespace-isolation invariant — populating the FEAT-012
    desktop app's data directory MUST NOT change the byte-output of any
    FEAT-002..010 CLI command.

    Per plan.md §Storage and FR-061a, the desktop app persists state at
    ``<app-data>/agenttower-control-panel/`` (a sibling-of-not-inside-of
    the daemon's namespace). This test simulates "the desktop app has
    been installed and has written state" by populating that directory,
    then asserts every regression surface produces byte-identical output
    before and after."""
    env: dict[str, str] = daemon["env"]
    home = Path(env["HOME"])

    # ── 1. Snapshot CLI outputs in a clean state. ──
    pre: dict[str, str] = {}
    for label, argv in _REGRESSION_SURFACES:
        proc = _cli(env, *argv)
        assert proc.returncode == 0, (
            f"baseline {label} failed: rc={proc.returncode} "
            f"stderr={proc.stderr!r}"
        )
        pre[label] = proc.stdout

    # ── 2. Materialize a plausible desktop-app data tree. ──
    # The exact paths mirror plan.md §Storage: ux-state.json under the
    # XDG-equivalent app-data root, plus a rotating-log directory.
    #
    # We populate both XDG-style ($XDG_CONFIG_HOME) and dot-fallback paths
    # so the test catches a leak regardless of which path resolution the
    # CLI happens to use on the current OS.
    candidate_roots = [
        home / ".config" / "agenttower-control-panel",
        home / ".local" / "share" / "agenttower-control-panel",
        home / "Library" / "Application Support" / "agenttower-control-panel",
    ]
    for root in candidate_roots:
        root.mkdir(parents=True, exist_ok=True)
        (root / "ux-state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "app_major": 0,
                    "app_contract_major": 1,
                    "last_workspace": "agent_ops",
                    "theme": "dark",
                    "density": "compact",
                }
            )
        )
        logs = root / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "app.log").write_text(
            '{"ts":"2026-05-25T04:00:00Z","level":"info",'
            '"event":"desktop_app_started"}\n'
        )

    # ── 3. Re-run each surface and assert byte-identical output. ──
    leaks: list[str] = []
    for label, argv in _REGRESSION_SURFACES:
        proc = _cli(env, *argv)
        if proc.returncode != 0:
            leaks.append(
                f"{label}: rc became {proc.returncode} after desktop-app "
                f"data dir was populated. stderr={proc.stderr!r}"
            )
            continue
        if proc.stdout != pre[label]:
            leaks.append(
                f"{label}: stdout changed.\n"
                f"  pre  sha256={_hash(pre[label])}\n"
                f"  post sha256={_hash(proc.stdout)}\n"
                f"  pre  = {pre[label]!r}\n"
                f"  post = {proc.stdout!r}"
            )
    assert not leaks, (
        "FEAT-012 Const2 namespace-isolation violation — the desktop "
        "app's data directory leaked into a daemon-CLI command:\n\n"
        + "\n\n".join(leaks)
    )
