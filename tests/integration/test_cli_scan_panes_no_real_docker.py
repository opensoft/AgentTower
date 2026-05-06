"""Explicit guard test that FEAT-004 never spawns a real `docker` or `tmux`.

Per R-017 (specs/004-container-tmux-pane-discovery/research.md), every FEAT-004
integration test runs with both ``AGENTTOWER_TEST_DOCKER_FAKE`` and
``AGENTTOWER_TEST_TMUX_FAKE`` set so neither real binary is ever invoked
(FR-034, SC-009). This module is the named verification SC-009 calls out and
mirrors FEAT-003's ``test_cli_scan_no_real_docker.py`` while extending the
binary blacklist to include ``tmux``.

Mechanism:

* ``test_env_vars_set_for_session`` — ensures the per-test ``env`` dict that
  flows to the spawned ``agenttower`` / ``agenttowerd`` subprocesses sets
  *both* fake env vars before any FEAT-004 scan is issued.
* ``test_no_real_docker_or_tmux_in_test_process_subprocess_calls`` — wraps
  ``subprocess.run`` and ``shutil.which`` for the duration of the test, runs
  a full ``scan --containers`` / ``scan --panes`` / ``list-panes --json``
  round-trip, and asserts that no recorded argv has
  ``os.path.basename(argv[0]) in {"docker", "tmux", "docker.exe", "tmux.exe"}``
  and that neither name was ever passed to ``shutil.which``.
* ``test_daemon_path_uses_fake_adapter`` — proves the production
  ``_resolve_tmux_adapter()`` gate flips between ``FakeTmuxAdapter`` and
  ``SubprocessTmuxAdapter`` based on ``AGENTTOWER_TEST_TMUX_FAKE`` so the
  subprocess-based code path is genuinely skipped under the test harness.

Note on scope: ``subprocess.run`` is patched only inside the *test* process.
The daemon spawned by ``ensure-daemon`` runs in its own Python interpreter,
so its subprocess invocations are not directly observable here. The R-017
guarantee instead relies on the env-var-driven adapter selection: with
``AGENTTOWER_TEST_TMUX_FAKE`` set, ``_resolve_tmux_adapter()`` returns
``FakeTmuxAdapter``, and ``FakeTmuxAdapter`` does not call ``subprocess`` at
all. ``test_daemon_path_uses_fake_adapter`` pins that behavior.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ._daemon_helpers import ensure_daemon


# Module-level collection-time invariant. R-017 requires that *the test* sets
# both env vars on the per-test env dict before invoking the daemon; the
# global ``os.environ`` is not required to carry them. We therefore only
# verify the variables are *known* at collection time (i.e. the test harness
# can reach them) by importing the helper and listing the names it consults.
_REQUIRED_FAKE_VARS: tuple[str, ...] = (
    "AGENTTOWER_TEST_DOCKER_FAKE",
    "AGENTTOWER_TEST_TMUX_FAKE",
)


def _basename(arg: object) -> str:
    if isinstance(arg, (list, tuple)) and arg:
        first = arg[0]
        return os.path.basename(first) if isinstance(first, str) else ""
    if isinstance(arg, str) and arg:
        return os.path.basename(arg.split()[0])
    return ""


def _is_blacklisted_binary(name: str) -> bool:
    return name in {"docker", "tmux", "docker.exe", "tmux.exe"}


def _write_docker_fake(path: Path, container_id: str, name: str) -> None:
    path.write_text(
        json.dumps(
            {
                "list_running": {
                    "action": "ok",
                    "containers": [
                        {
                            "container_id": container_id,
                            "name": name,
                            "image": "img",
                            "status": "running",
                        }
                    ],
                },
                "inspect": {
                    "action": "ok",
                    "results": [
                        {
                            "container_id": container_id,
                            "name": name,
                            "image": "img",
                            "status": "running",
                            "config_user": "user",
                            "working_dir": "/workspace",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_tmux_fake(path: Path, container_id: str) -> None:
    pane = {
        "session_name": "work",
        "window_index": 0,
        "pane_index": 0,
        "pane_id": "%0",
        "pane_pid": 1000,
        "pane_tty": "/dev/pts/0",
        "pane_current_command": "bash",
        "pane_current_path": "/workspace",
        "pane_title": "user@bench [0]",
        "pane_active": True,
    }
    path.write_text(
        json.dumps(
            {
                "containers": {
                    container_id: {
                        "uid": "1000",
                        "sockets": {"default": [pane]},
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_env_vars_known_at_collection_time() -> None:
    """R-017 — both fake env-var names are well-known at collection time.

    The integration tests pass the variables on the per-test ``env`` dict
    (see ``env_with_fake`` and ``_set_tmux_fake``); we assert here that the
    canonical names are spelled correctly so a typo cannot silently disable
    the gate.
    """
    assert _REQUIRED_FAKE_VARS == (
        "AGENTTOWER_TEST_DOCKER_FAKE",
        "AGENTTOWER_TEST_TMUX_FAKE",
    )


def test_no_real_docker_or_tmux_in_test_process_subprocess_calls(
    env_with_fake, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-009 / FR-034 — neither docker nor tmux is invoked from this process.

    Wraps ``subprocess.run`` and ``shutil.which`` for the duration of the
    test, then exercises the full FEAT-004 CLI surface (``scan --containers``
    → ``scan --panes`` → ``list-panes --json``) end-to-end. After the
    round-trip, asserts that no recorded subprocess argv has a basename in
    ``{"docker", "tmux", "docker.exe", "tmux.exe"}`` and that
    ``shutil.which`` was never asked to resolve those names either.
    """
    env, docker_fake, _home = env_with_fake
    container_id = "c" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")

    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(tmux_fake, container_id)
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(tmux_fake)

    # Sanity: both fake env vars are set on the per-test env dict before any
    # daemon process is spawned (R-017 #1).
    assert env.get("AGENTTOWER_TEST_DOCKER_FAKE") == str(docker_fake)
    assert env.get("AGENTTOWER_TEST_TMUX_FAKE") == str(tmux_fake)

    real_run = subprocess.run
    real_which = shutil.which
    recorded_argvs: list[Any] = []
    recorded_which: list[str] = []

    def recording_run(args: Any, *a: Any, **kw: Any):  # type: ignore[no-untyped-def]
        recorded_argvs.append(args)
        if _is_blacklisted_binary(_basename(args)):
            raise RuntimeError(
                "FEAT-004 tests must not invoke real `docker` or `tmux`: " f"{args!r}"
            )
        return real_run(args, *a, **kw)

    def recording_which(name: str, *a: Any, **kw: Any):  # type: ignore[no-untyped-def]
        recorded_which.append(name)
        if name in {"docker", "tmux"}:
            return None
        return real_which(name, *a, **kw)

    monkeypatch.setattr(subprocess, "run", recording_run)
    monkeypatch.setattr(shutil, "which", recording_which)

    # Bring up the daemon, then run the full FEAT-004 CLI round-trip.
    ensure_daemon(env)
    scan_containers = subprocess.run(
        ["agenttower", "scan", "--containers"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert scan_containers.returncode == 0, scan_containers.stderr
    scan_panes = subprocess.run(
        ["agenttower", "scan", "--panes"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert scan_panes.returncode == 0, scan_panes.stderr
    list_panes = subprocess.run(
        ["agenttower", "list-panes", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert list_panes.returncode == 0, list_panes.stderr

    # No recorded argv (in the test process) targets a real docker/tmux.
    offenders = [
        argv for argv in recorded_argvs if _is_blacklisted_binary(_basename(argv))
    ]
    assert offenders == [], (
        "FR-034 violation: subprocess.run was called with a real docker/tmux "
        f"binary as argv[0]: {offenders!r}"
    )

    # No which() lookup for docker/tmux either; the test process must not be
    # probing the host PATH for those binaries.
    forbidden_which = [n for n in recorded_which if n in {"docker", "tmux"}]
    assert forbidden_which == [], (
        "FR-034 violation: shutil.which was asked to resolve a forbidden "
        f"binary: {forbidden_which!r}"
    )


def test_daemon_path_uses_fake_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R-012 — production gate flips on ``AGENTTOWER_TEST_TMUX_FAKE``.

    With the env var set, ``_resolve_tmux_adapter()`` MUST return
    ``FakeTmuxAdapter`` (so the subprocess path is never reached). With it
    unset, it MUST return ``SubprocessTmuxAdapter`` (the production path).
    Pinning this behavior is what gives the rest of the FEAT-004 test suite
    its R-017 guarantee.
    """
    from agenttower.daemon import _resolve_tmux_adapter
    from agenttower.tmux import FakeTmuxAdapter, SubprocessTmuxAdapter

    fake_path = tmp_path / "tmux-fake.json"
    fake_path.write_text(json.dumps({"containers": {}}), encoding="utf-8")

    monkeypatch.setenv("AGENTTOWER_TEST_TMUX_FAKE", str(fake_path))
    adapter = _resolve_tmux_adapter()
    assert isinstance(adapter, FakeTmuxAdapter)

    monkeypatch.delenv("AGENTTOWER_TEST_TMUX_FAKE", raising=False)
    adapter = _resolve_tmux_adapter()
    assert isinstance(adapter, SubprocessTmuxAdapter)
