"""FR-009 inactive-container cascade for `agenttower scan --panes` (T036).

Scenario: a container that was active during a prior pane scan becomes
inactive (FEAT-003 reconciliation flips ``containers.active`` to 0) before
the next pane scan. The pane scan MUST:

* flip every prior active pane row for that container to ``active=0``
  with ``last_scanned_at`` advanced (data-model §4.1 transition (c));
* count the container in ``containers_skipped_inactive``;
* NOT issue a ``docker exec`` against the container — verified here by
  removing it from the FakeTmuxAdapter fixture, which raises
  ``DOCKER_EXEC_FAILED`` if accessed (R-012 / SC-009);
* return exit ``0`` with ``status == "ok"`` (the cascade itself is a
  healthy outcome — FR-009 / SC-003).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from ._daemon_helpers import ensure_daemon, resolved_paths


def _write_docker_fake(
    path: Path, *, containers: list[dict[str, str]]
) -> None:
    """Render the FakeDocker fixture with *containers* as the running set.

    An empty list represents the "all containers stopped" snapshot used to
    drive FEAT-003 reconciliation toward ``active=0``.
    """
    path.write_text(
        json.dumps(
            {
                "list_running": {"action": "ok", "containers": containers},
                "inspect": {
                    "action": "ok",
                    "results": [
                        {
                            "container_id": c["container_id"],
                            "name": c["name"],
                            "image": "img",
                            "status": "running",
                            "config_user": "user",
                            "working_dir": "/workspace",
                        }
                        for c in containers
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_tmux_fake(
    path: Path,
    *,
    containers: dict[str, dict[str, list[dict]]] | None = None,
    uid: str = "1000",
) -> None:
    """Render the FakeTmuxAdapter fixture.

    Each entry of *containers* maps ``container_id -> {socket_name: [panes]}``.
    Containers omitted here will raise ``DOCKER_EXEC_FAILED`` if any
    ``docker exec``-style call is issued against them by the discovery
    pipeline — exactly the assertion FR-009 needs.
    """
    payload_containers: dict[str, dict] = {}
    for container_id, sockets in (containers or {}).items():
        payload_containers[container_id] = {"uid": uid, "sockets": sockets}
    path.write_text(
        json.dumps({"containers": payload_containers}),
        encoding="utf-8",
    )


def _basic_pane(pane_id: str, *, pane_index: int, active: bool) -> dict:
    return {
        "session_name": "work",
        "window_index": 0,
        "pane_index": pane_index,
        "pane_id": pane_id,
        "pane_pid": 1000 + pane_index,
        "pane_tty": f"/dev/pts/{pane_index}",
        "pane_current_command": "bash",
        "pane_current_path": "/workspace",
        "pane_title": f"user@bench [{pane_index}]",
        "pane_active": active,
    }


def _scan_containers(env, *, timeout: float = 15.0):
    return subprocess.run(
        ["agenttower", "scan", "--containers"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _scan_panes(env, *, json_mode: bool = False, timeout: float = 30.0):
    cmd = ["agenttower", "scan", "--panes"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _set_tmux_fake(env, fake_path: Path) -> None:
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(fake_path)


def _read_panes_rows(home: Path) -> list[tuple]:
    conn = sqlite3.connect(str(resolved_paths(home)["state_db"]))
    try:
        return conn.execute(
            "SELECT container_id, tmux_pane_id, active, last_scanned_at "
            "FROM panes ORDER BY tmux_pane_id"
        ).fetchall()
    finally:
        conn.close()


def test_inactive_container_panes_cascade_inactive_without_docker_exec(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-009 / SC-003 — prior active panes flip to inactive without docker exec."""
    env, docker_fake, home = env_with_fake
    container_id = "a" * 64
    container_meta = {"container_id": container_id, "name": "py-bench"}

    # Step 1: container present in docker + tmux fixtures; pane is active.
    _write_docker_fake(docker_fake, containers=[container_meta])
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        containers={
            container_id: {"default": [_basic_pane("%0", pane_index=0, active=True)]}
        },
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    assert _scan_containers(env).returncode == 0
    first_pane = _scan_panes(env)
    assert first_pane.returncode == 0, first_pane.stderr
    initial_rows = _read_panes_rows(home)
    assert initial_rows == [(container_id, "%0", 1, initial_rows[0][3])]
    initial_last_scanned = initial_rows[0][3]
    assert initial_last_scanned

    # Step 2: drop the container from BOTH fakes.
    #
    # Removing it from the docker fake makes FEAT-003 reconciliation flip the
    # row to ``active=0``. Removing it from the tmux fake guarantees that any
    # accidental ``docker exec`` against the container raises the fake's
    # "fake fixture has no container" error (DOCKER_EXEC_FAILED). The pane
    # scan must therefore prove FR-009 by NOT touching the container at all.
    _write_docker_fake(docker_fake, containers=[])
    _write_tmux_fake(tmux_fake, containers={})

    cascade_containers = _scan_containers(env)
    assert cascade_containers.returncode == 0, cascade_containers.stderr

    cascade_panes = _scan_panes(env, json_mode=True)
    assert cascade_panes.returncode == 0, cascade_panes.stderr
    payload = json.loads(cascade_panes.stdout.strip())
    assert payload["ok"] is True
    result = payload["result"]
    # Cascade is a healthy outcome — status MUST stay "ok" (FR-009 / SC-003).
    assert result["status"] == "ok"
    assert result["error_details"] == []
    # The inactive container was NOT scanned (no docker exec issued).
    assert result["containers_scanned"] == 0
    assert result["sockets_scanned"] == 0
    assert result["containers_skipped_inactive"] == 1
    # The prior active pane was reconciled to inactive.
    assert result["panes_reconciled_to_inactive"] == 1

    # SQLite check: the prior pane row is now inactive AND its
    # ``last_scanned_at`` advanced strictly past the first scan's value.
    rows_after = _read_panes_rows(home)
    assert len(rows_after) == 1
    cid, pane_id, active, last_scanned = rows_after[0]
    assert cid == container_id
    assert pane_id == "%0"
    assert active == 0
    assert last_scanned > initial_last_scanned


def test_inactive_container_with_only_inactive_prior_panes_still_touches_them(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-009 + data-model §4.1 (c) — inactive prior rows still get last_scanned_at advanced.

    A container goes inactive AFTER all its prior pane rows are already
    ``active=0``. The cascade must NOT count them in
    ``panes_reconciled_to_inactive`` (they were already inactive) but MUST
    advance ``last_scanned_at`` to the cascade scan's ``started_at`` and
    still count the container in ``containers_skipped_inactive``.
    """
    env, docker_fake, home = env_with_fake
    container_id = "b" * 64
    container_meta = {"container_id": container_id, "name": "py-bench"}

    # Scan #1 — container present, pane %0 active.
    _write_docker_fake(docker_fake, containers=[container_meta])
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        containers={
            container_id: {"default": [_basic_pane("%0", pane_index=0, active=True)]}
        },
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    assert _scan_containers(env).returncode == 0
    assert _scan_panes(env).returncode == 0

    # Scan #2 — container still present but pane %0 disappeared. Per-socket
    # reconciliation flips the row to active=0 (sibling-socket inactivation
    # disabled because we have only one socket; this is the per-socket path).
    _write_tmux_fake(
        tmux_fake,
        containers={container_id: {"default": []}},
    )
    assert _scan_panes(env).returncode == 0
    rows_before_cascade = _read_panes_rows(home)
    assert rows_before_cascade == [
        (container_id, "%0", 0, rows_before_cascade[0][3])
    ]
    last_scanned_before = rows_before_cascade[0][3]

    # Scan #3 — drop the container from docker AND tmux fakes. The container
    # row flips to inactive on the FEAT-003 scan; the cascade pane scan must
    # touch the already-inactive pane row's last_scanned_at without invoking
    # docker exec.
    _write_docker_fake(docker_fake, containers=[])
    _write_tmux_fake(tmux_fake, containers={})
    assert _scan_containers(env).returncode == 0
    cascade = _scan_panes(env, json_mode=True)
    assert cascade.returncode == 0, cascade.stderr
    payload = json.loads(cascade.stdout.strip())
    result = payload["result"]
    assert result["status"] == "ok"
    assert result["containers_scanned"] == 0
    assert result["containers_skipped_inactive"] == 1
    # The pane was already inactive, so no NEW inactivation count.
    assert result["panes_reconciled_to_inactive"] == 0

    rows_after = _read_panes_rows(home)
    assert len(rows_after) == 1
    cid, pane_id, active, last_scanned = rows_after[0]
    assert cid == container_id
    assert pane_id == "%0"
    assert active == 0
    # last_scanned_at advanced even though no active->inactive transition.
    assert last_scanned > last_scanned_before
