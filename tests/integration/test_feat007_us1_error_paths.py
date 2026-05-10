"""US1 error-path integration tests for FEAT-007 attach-log.

Consolidated under one filename for the FEAT-007 test convention (one file
per logical scenario cluster); the appendix in ``specs/007-log-attachment-offsets/
tasks.md`` maps each test back to the originally-named tasks.md task.

Coverage:
* T052 — US1 AS3 / FR-020 / SC-006: pane reactivation reuses the
  attachment, retains ``byte_offset`` byte-for-byte.
* T053 — US1 AS4 / FR-019: path change supersedes the prior active row
  (active → superseded) and creates a new active row at the new path.
* T054 — SC-005 / FR-007: explicit ``--log`` not under any container
  bind mount refused with ``log_path_not_host_visible``; zero side
  effects.
* T057 — edge case: ``agents.active=0`` rejected with ``agent_inactive``.
* T058 — FR-009: same path owned by a different ``agent_id`` rejected
  with ``log_path_in_use``; conflicting ``agent_id`` surfaces in the
  error message.
* T060 — FR-040: two concurrent ``attach-log`` calls for the same
  ``agent_id`` serialize via ``agent_locks``; both succeed and the
  second observes the first's row (idempotent path).
* T061 — FR-041: two concurrent ``attach-log`` calls from different
  agents with colliding ``--log`` paths; first wins, second hits
  ``log_path_in_use``.
* T063 — daemon down → CLI exits 2 with the FEAT-002 daemon-unavailable
  message; no row, no JSONL.
* T064 — FR-038: client supplies a ``schema_version`` lower than the
  daemon's current → ``schema_version_newer`` (no state mutation).
* T065 — FR-039: wire envelope unknown keys → ``bad_request`` listing
  the offending keys; including ``source`` rejection on the wire.

The happy path (T050) and idempotency (T051) are covered by
``test_feat007_attach_log_smoke.py``; pipe-pane race (T055/T055a) by
``test_feat007_pipe_pane_race.py``; adversarial inputs (T059) by
``test_adversarial_inputs.py``; offset persistence (T081) by
``test_feat007_offset_persistence.py``; stale cascade (T153) by
``test_feat007_stale_cascade.py``.
"""

from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from agenttower.socket_api.client import DaemonError, send_request
from agenttower.state import log_offsets

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


CONTAINER_ID = "c" * 64
AGENT_ID = "agt_abc123def456"
SECOND_AGENT_ID = "agt_def456abc789"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def primed(tmp_path: Path):
    """Daemon up, one container + one registered agent (canonical bind mount)."""
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


def _attach(env, *, agent_id: str = AGENT_ID, log: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["agenttower", "attach-log", "--target", agent_id, "--json"]
    if log is not None:
        cmd.extend(["--log", log])
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)


def _seed_second_agent(state_db: Path, *, second_agent_id: str) -> None:
    """Add a second registered agent in the same container/pane."""
    pane_socket = "/tmp/tmux-1000/default"
    pane_session = "second-pane-session"
    pane_window = 0
    pane_index = 1
    pane_id = "%18"
    now = "2026-05-08T14:00:00.000000+00:00"
    pane_key = (CONTAINER_ID, pane_socket, pane_session, pane_window, pane_index, pane_id)

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            pane_key + ("bench-acme", "brett", 12346, "/dev/pts/1",
                        "bash", "/home/brett", "second", 1, 1, now, now),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (second_agent_id,) + pane_key + (
                "slave", "codex", "codex-02", "", None, "{}", now, now, None, 1,
            ),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T052 — pane reactivation reuses attachment, retains offsets
# ---------------------------------------------------------------------------


def test_t052_pane_reactivation_reuses_attachment_retains_offset(primed) -> None:
    """US1 AS3 / FR-020 / SC-006 — re-attach after offset advance keeps the
    same row and retains ``byte_offset`` byte-for-byte.

    Sequence: attach (offset starts at 0) → advance offset to (4096, 137)
    via the FR-060 test seam → re-attach → assert SAME attachment_id,
    SAME byte_offset, exactly one row in each table, exactly one audit row.
    The re-attach is idempotent (FR-018) so no second audit row is appended.
    """
    env, _, paths = primed

    proc = _attach(env)
    assert proc.returncode == 0, proc.stderr
    first = json.loads(proc.stdout)["result"]
    attachment_id = first["attachment_id"]

    # Advance offset via the production-only test seam.
    conn = sqlite3.connect(str(paths["state_db"]), isolation_level=None)
    try:
        log_offsets.advance_offset_for_test(
            conn,
            agent_id=AGENT_ID,
            log_path=first["log_path"],
            byte_offset=4096,
            line_offset=137,
            last_event_offset=3200,
            file_inode="234:1234567",
            file_size_seen=8192,
            last_output_at="2026-05-08T15:00:00.000000+00:00",
            timestamp="2026-05-08T15:00:00.000000+00:00",
        )
    finally:
        conn.close()

    # Re-attach — same agent, same canonical path (no --log supplied).
    proc = _attach(env)
    assert proc.returncode == 0, proc.stderr
    second = json.loads(proc.stdout)["result"]

    # Same attachment_id (no new row), same status, is_new=False.
    assert second["attachment_id"] == attachment_id
    assert second["status"] == "active"
    assert second["is_new"] is False

    # Verify durable state.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n_la = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id = ?", (AGENT_ID,)
        ).fetchone()[0]
        assert n_la == 1, "FR-018: idempotent re-attach must not duplicate row"
        offset_row = conn.execute(
            "SELECT byte_offset, line_offset, last_event_offset, file_inode, file_size_seen "
            "FROM log_offsets WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert offset_row == (4096, 137, 3200, "234:1234567", 8192), (
        f"FR-020 / SC-006: byte_offset must be retained byte-for-byte; got {offset_row}"
    )

    # Exactly one audit row (FR-018 + FR-045: idempotent re-attach is no audit).
    audit = [
        line for line in paths["events_file"].read_text().splitlines()
        if '"type": "log_attachment_change"' in line
        or '"type":"log_attachment_change"' in line
    ]
    assert len(audit) == 1, f"expected 1 audit row total, got {len(audit)}"


# ---------------------------------------------------------------------------
# T053 — supersede path change (active → superseded)
# ---------------------------------------------------------------------------


def test_t053_supersede_path_change_active_to_superseded(primed, tmp_path: Path) -> None:
    """US1 AS4 / FR-019 — explicit ``--log <new-path>`` supersedes the
    prior active row.

    Sequence: attach without --log (canonical path → row A) → attach with
    explicit --log under the canonical bind-mount (different path → row B).
    Row A transitions ``active → superseded``; ``superseded_at`` and
    ``superseded_by`` are populated; row B is a fresh active row at offset
    (0, 0). Two audit rows, both ``log_attachment_change``.
    """
    env, _, paths = primed

    # First attach: canonical path.
    proc = _attach(env)
    assert proc.returncode == 0, proc.stderr
    first = json.loads(proc.stdout)["result"]
    first_attachment_id = first["attachment_id"]
    canonical_path = first["log_path"]

    # Build a NEW path under the same canonical bind-mount root that is
    # also under the canonical-log-root for that container.
    host_log_root = paths["state_dir"] / "logs" / CONTAINER_ID
    host_log_root.mkdir(parents=True, exist_ok=True)
    new_path = host_log_root / "operator_supplied.log"

    proc = _attach(env, log=str(new_path))
    assert proc.returncode == 0, proc.stderr
    second = json.loads(proc.stdout)["result"]

    assert second["attachment_id"] != first_attachment_id, (
        "FR-019 supersede must create a NEW row at the new path"
    )
    assert second["status"] == "active"
    assert second["log_path"] == str(new_path)

    # Verify the prior row went to superseded with the right linkage.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        prior = conn.execute(
            "SELECT status, superseded_at, superseded_by FROM log_attachments "
            "WHERE attachment_id = ?",
            (first_attachment_id,),
        ).fetchone()
    finally:
        conn.close()
    assert prior[0] == "superseded"
    assert prior[1] is not None, "superseded_at must be populated"
    assert prior[2] == second["attachment_id"], (
        "superseded_by must point at the new attachment_id"
    )

    # Two log_attachment_change audit rows total.
    audit = [
        line for line in paths["events_file"].read_text().splitlines()
        if '"type": "log_attachment_change"' in line
        or '"type":"log_attachment_change"' in line
    ]
    assert len(audit) == 2, f"expected 2 audit rows after supersede, got {len(audit)}"


# ---------------------------------------------------------------------------
# T057 — inactive agent rejection
# ---------------------------------------------------------------------------


def test_t057_inactive_agent_rejected(primed) -> None:
    """Edge case — ``agents.active=0`` rejected with ``agent_inactive``.

    Mark the seeded agent inactive directly in the DB and assert attach-log
    refuses without state mutation, zero JSONL audit row, exit 3.
    """
    env, _, paths = primed

    # Mark the agent inactive.
    conn = sqlite3.connect(str(paths["state_db"]), isolation_level=None)
    try:
        conn.execute(
            "UPDATE agents SET active = 0 WHERE agent_id = ?", (AGENT_ID,)
        )
    finally:
        conn.close()

    proc = _attach(env)
    assert proc.returncode == 3, (
        f"agent_inactive should exit 3, got {proc.returncode}; stderr={proc.stderr!r}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope["error"]["code"] == "agent_inactive", (
        f"expected agent_inactive, got {envelope!r}"
    )

    # Zero rows, zero JSONL.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n_la = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id = ?", (AGENT_ID,)
        ).fetchone()[0]
        n_lo = conn.execute(
            "SELECT count(*) FROM log_offsets WHERE agent_id = ?", (AGENT_ID,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_la == 0
    assert n_lo == 0
    if paths["events_file"].exists():
        for line in paths["events_file"].read_text().splitlines():
            assert "log_attachment_change" not in line


# ---------------------------------------------------------------------------
# T058 — log_path_in_use across different agents
# ---------------------------------------------------------------------------


def test_t058_log_path_in_use_when_owned_by_other_agent(primed, tmp_path: Path) -> None:
    """FR-009 — different agent owns same path → ``log_path_in_use``.

    Sequence: agent A attaches with explicit --log P → agent B (different
    agent_id) tries to attach with the same --log P → exit 3
    ``log_path_in_use`` and the conflicting agent_id appears in the
    actionable message. Agent A's state is not mutated; agent B's
    attempt produces zero rows / zero JSONL.
    """
    env, _, paths = primed
    _seed_second_agent(paths["state_db"], second_agent_id=SECOND_AGENT_ID)

    # Both agents share the same canonical bind-mount root. The daemon
    # requires 0o700 on log dirs (FR-008/048/057); pre-create with that mode.
    host_log_root = paths["state_dir"] / "logs" / CONTAINER_ID
    host_log_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    import os as _os
    _os.chmod(host_log_root, 0o700)
    shared_path = str(host_log_root / "shared.log")

    # Agent A claims the path.
    proc = _attach(env, agent_id=AGENT_ID, log=shared_path)
    assert proc.returncode == 0, proc.stderr
    first = json.loads(proc.stdout)["result"]
    first_attachment_id = first["attachment_id"]

    # Agent B attempts the same path.
    proc = _attach(env, agent_id=SECOND_AGENT_ID, log=shared_path)
    assert proc.returncode == 3, (
        f"FR-009 should exit 3 for log_path_in_use, got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope["error"]["code"] == "log_path_in_use"
    assert AGENT_ID in envelope["error"]["message"], (
        f"FR-009: actionable message must surface conflicting agent_id; "
        f"got {envelope['error']['message']!r}"
    )

    # Agent A state intact.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n_a_la = conn.execute(
            "SELECT count(*) FROM log_attachments "
            "WHERE agent_id = ? AND status = 'active'",
            (AGENT_ID,),
        ).fetchone()[0]
        a_attachment = conn.execute(
            "SELECT attachment_id FROM log_attachments WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()
        # Agent B has no row.
        n_b_la = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id = ?",
            (SECOND_AGENT_ID,),
        ).fetchone()[0]
        n_b_lo = conn.execute(
            "SELECT count(*) FROM log_offsets WHERE agent_id = ?",
            (SECOND_AGENT_ID,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert n_a_la == 1
    assert a_attachment[0] == first_attachment_id, (
        "Agent A's attachment_id must be unchanged by Agent B's failed attempt"
    )
    assert n_b_la == 0
    assert n_b_lo == 0

    # Exactly one audit row total — Agent A's success only.
    audit = [
        line for line in paths["events_file"].read_text().splitlines()
        if '"type": "log_attachment_change"' in line
        or '"type":"log_attachment_change"' in line
    ]
    assert len(audit) == 1, (
        f"FR-045: failed attaches MUST NOT append audit; got {len(audit)} rows"
    )


# ---------------------------------------------------------------------------
# T060 — concurrent attach-log on same agent serializes via agent_locks
# ---------------------------------------------------------------------------


def test_t060_concurrent_attach_same_agent_serializes(primed) -> None:
    """FR-040 — two concurrent ``attach-log`` calls for the same agent_id
    serialize through ``agent_locks``; both succeed. The second observes
    the first's writes inside its ``BEGIN IMMEDIATE`` transaction (the
    FR-018 idempotent re-attach branch fires).

    Asserts: both exits 0, exactly one row in each table (no double-row),
    exactly one audit row (FR-018 idempotent path appends nothing).
    """
    env, _, paths = primed

    def _call() -> subprocess.CompletedProcess[str]:
        return _attach(env)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_call) for _ in range(2)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for proc in results:
        assert proc.returncode == 0, (
            f"FR-040: concurrent attach must serialize, not fail; "
            f"got returncode={proc.returncode}, stderr={proc.stderr!r}"
        )

    # Exactly one row in each table — the second call hit the FR-018
    # idempotent re-attach branch.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n_la = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()[0]
        n_lo = conn.execute(
            "SELECT count(*) FROM log_offsets WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_la == 1
    assert n_lo == 1

    # Exactly one audit row — first call commits one, the FR-018 idempotent
    # second call appends none (verified by the smoke test, re-asserted here
    # to lock the FR-040 invariant against future mutex regressions).
    audit = [
        line for line in paths["events_file"].read_text().splitlines()
        if '"type": "log_attachment_change"' in line
        or '"type":"log_attachment_change"' in line
    ]
    assert len(audit) == 1


# ---------------------------------------------------------------------------
# T061 — concurrent attach-log with colliding --log paths from different agents
# ---------------------------------------------------------------------------


def test_t061_concurrent_attach_colliding_paths_first_wins(primed, tmp_path: Path) -> None:
    """FR-041 — two agents, same explicit --log path, fired concurrently:
    first wins (active row); second hits ``log_path_in_use``. Serialization
    is via the per-log_path mutex registry (T027).
    """
    env, _, paths = primed
    _seed_second_agent(paths["state_db"], second_agent_id=SECOND_AGENT_ID)

    host_log_root = paths["state_dir"] / "logs" / CONTAINER_ID
    host_log_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    import os as _os
    _os.chmod(host_log_root, 0o700)
    shared_path = str(host_log_root / "raced.log")

    def _call(agent_id: str) -> subprocess.CompletedProcess[str]:
        return _attach(env, agent_id=agent_id, log=shared_path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_a = pool.submit(_call, AGENT_ID)
        f_b = pool.submit(_call, SECOND_AGENT_ID)
        results = {AGENT_ID: f_a.result(), SECOND_AGENT_ID: f_b.result()}

    success_count = sum(1 for r in results.values() if r.returncode == 0)
    failure_count = sum(1 for r in results.values() if r.returncode == 3)
    assert success_count == 1, (
        f"FR-041 expected exactly one success; got success={success_count}, "
        f"failure={failure_count}; results={[r.returncode for r in results.values()]}"
    )
    assert failure_count == 1

    # Identify which agent won and which lost.
    winner_id = next(aid for aid, r in results.items() if r.returncode == 0)
    loser_id = next(aid for aid, r in results.items() if r.returncode == 3)

    # Loser's response is log_path_in_use, naming the winner.
    loser_envelope = json.loads(results[loser_id].stdout)
    assert loser_envelope["error"]["code"] == "log_path_in_use"
    assert winner_id in loser_envelope["error"]["message"], (
        f"FR-041: actionable message must surface conflicting agent_id "
        f"({winner_id!r}); got {loser_envelope['error']['message']!r}"
    )

    # Exactly one row at the contested path.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        rows = conn.execute(
            "SELECT agent_id, status FROM log_attachments WHERE log_path = ?",
            (shared_path,),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(winner_id, "active")], (
        f"FR-041: exactly one row at the contested path; got {rows}"
    )


# ---------------------------------------------------------------------------
# T063 — daemon down → exit 2
# ---------------------------------------------------------------------------


def test_t063_attach_log_no_daemon_exits_2(tmp_path: Path) -> None:
    """SC parallel to FEAT-006 SC-009 — daemon down → exit 2 with the
    FEAT-002 daemon-unavailable message; no row, no JSONL.

    This test does NOT use the ``primed`` fixture because we need the
    daemon NOT to be running. config init is still required so that paths
    exist.
    """
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake_path = tmp_path / "pipe_pane_fake.json"
    _write_pipe_pane_fake(fake_path)
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake_path)
    run_config_init(env)
    paths = resolved_paths(home)

    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", AGENT_ID, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 2, (
        f"daemon-down should exit 2 (FEAT-002 contract); "
        f"got {proc.returncode}, stderr={proc.stderr!r}"
    )

    # No state files mutated.
    if paths["state_db"].exists():
        conn = sqlite3.connect(str(paths["state_db"]))
        try:
            # Tables may exist from config init's schema migration; just assert
            # no rows in our tables.
            la = conn.execute(
                "SELECT count(*) FROM log_attachments"
            ).fetchone()[0]
            lo = conn.execute(
                "SELECT count(*) FROM log_offsets"
            ).fetchone()[0]
            assert la == 0
            assert lo == 0
        finally:
            conn.close()
    if paths["events_file"].exists():
        for line in paths["events_file"].read_text().splitlines():
            assert "log_attachment_change" not in line


# ---------------------------------------------------------------------------
# T065 — wire envelope unknown keys → bad_request (incl. source rejection)
# ---------------------------------------------------------------------------


def test_t065_unknown_keys_rejected_bad_request(primed) -> None:
    """FR-039 — unknown keys on the wire envelope produce ``bad_request``,
    listing the offending keys; the daemon-internal ``source`` key is
    rejected when supplied by a client (FR-039 closed-set rule).

    Bypasses the CLI argparse layer via ``send_request`` so the daemon
    sees the raw wire envelope a hand-crafted client could send.
    """
    env, _, paths = primed

    # 1. Unknown key on attach_log.
    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"],
            "attach_log",
            {
                "schema_version": 5,
                "agent_id": AGENT_ID,
                "log_path": str(paths["state_dir"] / "logs" / CONTAINER_ID / "ok.log"),
                "wholly_unknown_extra_key": True,
            },
            connect_timeout=2.0,
            read_timeout=5.0,
        )
    assert exc_info.value.code == "bad_request", (
        f"FR-039 unknown key should produce bad_request; got code={exc_info.value.code}"
    )
    assert "wholly_unknown_extra_key" in exc_info.value.message, (
        f"FR-039 message should list offending key; got {exc_info.value.message!r}"
    )

    # 2. Daemon-internal `source` rejected when supplied at the wire.
    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"],
            "attach_log",
            {
                "schema_version": 5,
                "agent_id": AGENT_ID,
                "source": "explicit",  # daemon-internal — clients cannot supply
            },
            connect_timeout=2.0,
            read_timeout=5.0,
        )
    assert exc_info.value.code == "bad_request"
    assert "source" in exc_info.value.message

    # 3. Unknown key on detach_log.
    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"],
            "detach_log",
            {
                "schema_version": 5,
                "agent_id": AGENT_ID,
                "extra": "nope",
            },
            connect_timeout=2.0,
            read_timeout=5.0,
        )
    assert exc_info.value.code == "bad_request"
    assert "extra" in exc_info.value.message

    # No state mutated by any of the three rejected calls.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n_la = conn.execute(
            "SELECT count(*) FROM log_attachments"
        ).fetchone()[0]
        n_lo = conn.execute(
            "SELECT count(*) FROM log_offsets"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_la == 0
    assert n_lo == 0
    if paths["events_file"].exists():
        for line in paths["events_file"].read_text().splitlines():
            assert "log_attachment_change" not in line


# ---------------------------------------------------------------------------
# T054 — explicit --log outside every bind mount → log_path_not_host_visible
# ---------------------------------------------------------------------------


def test_t054_log_path_outside_bind_mounts_rejected(primed) -> None:
    """SC-005 / FR-007 — supplied ``--log`` outside every container bind
    mount → ``log_path_not_host_visible``; zero rows, zero JSONL.

    The seeded container has exactly one bind mount source: the canonical
    log root under ``state_dir/logs``. Supplying any path outside that
    mount source should refuse.
    """
    env, _, paths = primed

    # Path is absolute, valid (FR-006 / FR-051..053 all pass), but it
    # isn't under any container bind mount source.
    outside_path = "/tmp/nope/elsewhere.log"

    proc = _attach(env, log=outside_path)
    assert proc.returncode == 3, (
        f"FR-007 outside-mount path should exit 3; got {proc.returncode}, "
        f"stderr={proc.stderr!r}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope["error"]["code"] == "log_path_not_host_visible", (
        f"FR-007 expected log_path_not_host_visible, got {envelope!r}"
    )

    # Zero rows, zero JSONL.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n_la = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()[0]
        n_lo = conn.execute(
            "SELECT count(*) FROM log_offsets WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_la == 0
    assert n_lo == 0
    if paths["events_file"].exists():
        for line in paths["events_file"].read_text().splitlines():
            assert "log_attachment_change" not in line


# ---------------------------------------------------------------------------
# T064 — client schema_version < daemon → schema_version_newer
# ---------------------------------------------------------------------------


def test_t064_client_older_schema_version_rejected(primed) -> None:
    """FR-038 — daemon advertises ``CURRENT_SCHEMA_VERSION=5``; if the
    client supplies ``schema_version=4``, the daemon refuses with
    ``schema_version_newer`` and no state mutates.

    Bypasses the CLI argparse layer via ``send_request`` because the CLI
    always advertises ``MAX_SUPPORTED_SCHEMA_VERSION`` (which equals the
    daemon's current at build time); a hand-crafted older client would
    send a lower number.
    """
    env, _, paths = primed

    with pytest.raises(DaemonError) as exc_info:
        send_request(
            paths["socket"],
            "attach_log",
            {
                "schema_version": 4,  # older than daemon's current=5
                "agent_id": AGENT_ID,
            },
            connect_timeout=2.0,
            read_timeout=5.0,
        )
    assert exc_info.value.code == "schema_version_newer", (
        f"FR-038 expected schema_version_newer for client_schema=4 < daemon=5; "
        f"got code={exc_info.value.code!r}, message={exc_info.value.message!r}"
    )
    # Message lists daemon vs. client schema for actionability.
    # Daemon advertises CURRENT_SCHEMA_VERSION; FEAT-008 bumped it to 6.
    assert "schema_version=6" in exc_info.value.message
    assert "expected=4" in exc_info.value.message

    # Repeat the gate against detach_log + attach_log_status + attach_log_preview
    # to confirm every FEAT-007 method dispatches through the same gate.
    for method in ("detach_log", "attach_log_status"):
        with pytest.raises(DaemonError) as exc_info:
            send_request(
                paths["socket"],
                method,
                {"schema_version": 4, "agent_id": AGENT_ID},
                connect_timeout=2.0,
                read_timeout=5.0,
            )
        assert exc_info.value.code == "schema_version_newer", (
            f"FR-038 schema_version_newer must fire for method={method!r}; "
            f"got code={exc_info.value.code!r}"
        )

    # No state mutated.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n_la = conn.execute(
            "SELECT count(*) FROM log_attachments"
        ).fetchone()[0]
        n_lo = conn.execute(
            "SELECT count(*) FROM log_offsets"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_la == 0
    assert n_lo == 0


# ---------------------------------------------------------------------------
# T197 — no implicit detach through any non-operator lifecycle path
# ---------------------------------------------------------------------------


def test_t197_no_implicit_detach_through_any_lifecycle_path(primed) -> None:
    """SC-011 / FR-021a — exercise every non-operator lifecycle path that
    could touch an attachment row and assert ``detached`` is NEVER reached.

    The closed-set ``detached`` is reachable ONLY by explicit operator
    ``detach-log``. We exercise:

    1. Pane reconcile cascade (active → stale via FEAT-004 reconcile path).
    2. Reader cycle missing (active → stale via FR-026).
    3. Idempotent re-attach (active → active, no transition).
    4. Re-attach from stale (stale → active).

    After each, we assert no row is ever in status=detached.
    """
    env, _, paths = primed

    # First attach.
    proc = _attach(env)
    assert proc.returncode == 0, proc.stderr
    first = json.loads(proc.stdout)["result"]
    attachment_id = first["attachment_id"]

    # Path 1: directly cascade to stale via the state DAO.
    from agenttower.state import log_attachments as la_state
    conn = sqlite3.connect(str(paths["state_db"]), isolation_level=None)
    try:
        la_state.cascade_to_stale_for_panes(
            conn,
            pane_keys=[(
                "c" * 64, "/tmp/tmux-1000/default", "main", 0, 0, "%17",
            )],
            now_iso="2026-05-08T15:00:00.000000+00:00",
        )
    finally:
        conn.close()
    _assert_no_detached_row(paths)

    # Path 2: re-attach from stale → back to active.
    proc = _attach(env)
    assert proc.returncode == 0, proc.stderr
    _assert_no_detached_row(paths)

    # Path 3: idempotent re-attach (same path, status=active).
    proc = _attach(env)
    assert proc.returncode == 0, proc.stderr
    _assert_no_detached_row(paths)

    # Path 4: simulate reader-cycle missing-file flip via the reader_recovery
    # helper (in-process, parallels what FEAT-008 will do).
    from agenttower.logs.reader_recovery import reader_cycle_offset_recovery
    canonical_path = first["log_path"]
    # Delete the file under the daemon to simulate FR-026 missing condition.
    import os as _os
    if _os.path.exists(canonical_path):
        _os.unlink(canonical_path)
    conn = sqlite3.connect(str(paths["state_db"]), isolation_level=None)
    try:
        reader_cycle_offset_recovery(
            conn=conn, events_file=paths["events_file"],
            lifecycle_logger=None,
            agent_id=first["agent_id"], log_path=canonical_path,
            timestamp="2026-05-08T16:00:00.000000+00:00",
        )
    finally:
        conn.close()
    _assert_no_detached_row(paths)


def _assert_no_detached_row(paths: dict[str, Path]) -> None:
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        rows = conn.execute(
            "SELECT status FROM log_attachments"
        ).fetchall()
    finally:
        conn.close()
    statuses = {r[0] for r in rows}
    assert "detached" not in statuses, (
        f"FR-021a / SC-011: detached MUST be reachable only via operator "
        f"detach-log; saw statuses {statuses}"
    )
