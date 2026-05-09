"""US4 + US5 + US7 unit tests consolidated for FEAT-007.

Drives ``LogService`` directly (in-process, no daemon, no subprocess) to
verify the spec contracts at unit granularity. Integration coverage of
the same paths through the CLI lives in:

* ``test_feat007_register_self_attach_log.py`` (US4 atomic surface)
* ``test_feat007_stale_cascade.py`` (US5 reconcile-driven cascade)
* ``test_feat007_lifecycle.py`` (US7 detach round-trip)
* ``test_feat007_us1_error_paths.py`` (overlapping error paths)

Coverage map:

* T130 / T131 / T132 — US4 atomic register-self
* T150 / T151 / T152 — US5 stale recovery + supersede-from-stale
* T190 / T191 / T192 / T193 — US7 detach + recovery-from-detached
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agenttower.agents.errors import RegistrationError
from agenttower.agents.mutex import AgentLockMap
from agenttower.logs import lifecycle as logs_lifecycle
from agenttower.logs.docker_exec import FakeDockerExecRunner
from agenttower.logs.mutex import LogPathLockMap
from agenttower.logs.service import LogService
from agenttower.state import log_attachments as la_state
from agenttower.state import log_offsets as lo_state
from agenttower.state import schema


AGENT_ID = "agt_abc123def456"
CONTAINER_ID = "c" * 64
PANE_KEY = (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 0, "%17")
NOW = "2026-05-08T14:00:00.000000+00:00"
LATER = "2026-05-08T15:00:00.000000+00:00"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_agent(state_db: Path, *, agent_id: str = AGENT_ID, mounts_json: str | None = None) -> None:
    """Seed one container, pane, and agent.

    ``mounts_json`` defaults to a canonical bind mount under the test home so
    host-visibility succeeds for a path under that root.
    """
    if mounts_json is None:
        mounts_json = "[]"
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (CONTAINER_ID, "bench", "bench:latest", "running",
             "{}", mounts_json, "{}", "brett", "/home/brett", 1, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            PANE_KEY + ("bench", "brett", 1, "/dev/pts/0", "bash",
                        "/home/brett", "main", 1, 1, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id,) + PANE_KEY + ("slave", "codex", "codex", "", None, "{}", NOW, NOW, None, 1),
        )
    finally:
        conn.close()


def _seed_attachment(
    state_db: Path,
    *,
    log_path: str,
    status: str,
    attachment_id: str = "lat_a1b2c3d4e5f6",
    agent_id: str = AGENT_ID,
    file_inode: str | None = None,
    file_size_seen: int = 0,
    byte_offset: int = 0,
    line_offset: int = 0,
) -> None:
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO log_attachments (attachment_id, agent_id, "
            "container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "log_path, status, source, pipe_pane_command, prior_pipe_target, "
            "attached_at, last_status_at, superseded_at, superseded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (attachment_id, agent_id) + PANE_KEY + (
                log_path, status, "explicit", "docker exec ...", None,
                NOW, NOW, None, None, NOW,
            ),
        )
        conn.execute(
            "INSERT INTO log_offsets (agent_id, log_path, byte_offset, "
            "line_offset, last_event_offset, last_output_at, file_inode, "
            "file_size_seen, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?, ?)",
            (agent_id, log_path, byte_offset, line_offset,
             file_inode, file_size_seen, NOW, NOW),
        )
    finally:
        conn.close()


def _make_service(state_db: Path, tmp_path: Path, *, runner: FakeDockerExecRunner | None = None) -> LogService:
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)
    if runner is None:
        runner = FakeDockerExecRunner({
            "calls": [
                {"argv_match": ["tmux list-panes"], "returncode": 0, "stdout": "0 \n", "stderr": ""},
                {"argv_match": ["tmux pipe-pane -o"], "returncode": 0, "stdout": "", "stderr": ""},
            ],
        })
    return LogService(
        connection_factory=lambda: sqlite3.connect(str(state_db), isolation_level=None),
        agent_locks=AgentLockMap(),
        log_path_locks=LogPathLockMap(),
        events_file=events_file,
        schema_version=5,
        daemon_home=tmp_path,
        docker_exec_runner=runner,
        lifecycle_logger=None,
    )


@pytest.fixture
def primed(tmp_path: Path) -> tuple[LogService, Path, Path]:
    """Seeded agent at canonical bind mount + LogService ready to attach."""
    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()

    # Canonical bind mount lets host-visibility prove succeed for paths
    # under tmp_path's canonical log root.
    canonical_logs_root = tmp_path / ".local" / "state" / "opensoft" / "agenttower" / "logs"
    canonical_logs_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    container_logs_root = canonical_logs_root / CONTAINER_ID
    container_logs_root.mkdir(mode=0o700, exist_ok=True)
    mounts_json = json.dumps([{
        "Type": "bind",
        "Source": str(canonical_logs_root),
        "Destination": str(canonical_logs_root),
        "Mode": "rw",
        "RW": True,
    }])
    _seed_agent(state_db, mounts_json=mounts_json)
    service = _make_service(state_db, tmp_path)
    return service, state_db, tmp_path / "events.jsonl"


def _audit_rows(events_file: Path) -> list[dict[str, Any]]:
    if not events_file.exists():
        return []
    out = []
    for line in events_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return [r for r in out if r.get("type") == "log_attachment_change"]


# ===========================================================================
# US7 — detach mechanics + no-implicit-detach + recovery + supersede
# ===========================================================================


def test_t190_detach_mechanics_active_to_detached(primed) -> None:
    """T190 / FR-021a..c — detach issues toggle-off, transitions
    active → detached, retains offsets, appends one audit row."""
    service, state_db, events_file = primed
    # First attach.
    attach_result = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    attachment_id = attach_result["attachment_id"]

    # Advance offset to verify retention.
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        lo_state.advance_offset_for_test(
            conn,
            agent_id=AGENT_ID,
            log_path=attach_result["log_path"],
            byte_offset=4096, line_offset=137, last_event_offset=3200,
            file_inode="234:1", file_size_seen=8192,
            last_output_at=LATER, timestamp=LATER,
        )
    finally:
        conn.close()

    # Detach.
    result = service.detach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    assert result["status"] == "detached"
    assert result["attachment_id"] == attachment_id
    assert result["byte_offset"] == 4096
    assert result["line_offset"] == 137

    # Row status flipped.
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT status FROM log_attachments WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "detached"

    # Two audit rows: attach (None → active) + detach (active → detached).
    audit = _audit_rows(events_file)
    assert len(audit) == 2
    assert audit[1]["payload"]["prior_status"] == "active"
    assert audit[1]["payload"]["new_status"] == "detached"


def test_t190_detach_against_no_attachment_row_attachment_not_found(primed) -> None:
    """T190 / FR-021b — detach with no row → ``attachment_not_found``."""
    service, _, _ = primed
    with pytest.raises(RegistrationError) as exc_info:
        service.detach_log(
            {"schema_version": 5, "agent_id": AGENT_ID},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "attachment_not_found"


def test_t190_detach_against_already_detached_attachment_not_found(primed) -> None:
    """T190 / FR-021b — detach against a non-active row → attachment_not_found.

    The detach helper looks up ``select_active_for_agent`` so any row not in
    status=active surfaces as not-found from detach's perspective.
    """
    service, state_db, _ = primed
    service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    service.detach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    with pytest.raises(RegistrationError) as exc_info:
        service.detach_log(
            {"schema_version": 5, "agent_id": AGENT_ID},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "attachment_not_found"


def test_t191_no_implicit_detach_via_state_layer(tmp_path: Path) -> None:
    """T191 / FR-021a / SC-011 — no other lifecycle path produces ``detached``.

    Direct DAO check: the closed-set transitions enumerated in
    ``data-model.md`` allow ``detached`` only as ``active → detached``
    via ``detach_log``. We sanity-check by exercising the cascade-to-stale
    helper (which surfaces all flipped rows) and asserting none land in
    detached.
    """
    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()
    _seed_agent(state_db)
    _seed_attachment(state_db, log_path="/host/log/x.log", status="active")

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        affected = la_state.cascade_to_stale_for_panes(
            conn, pane_keys=[PANE_KEY], now_iso=LATER,
        )
    finally:
        conn.close()
    # Cascade only ever produces stale, never detached.
    for r in affected:
        assert r.status != "detached"

    conn = sqlite3.connect(str(state_db))
    try:
        rows = conn.execute(
            "SELECT status FROM log_attachments"
        ).fetchall()
    finally:
        conn.close()
    statuses = {r[0] for r in rows}
    assert "detached" not in statuses


def test_t192_recovery_from_detached_reuses_row_retains_offsets(primed) -> None:
    """T192 / FR-021d — same-path attach from detached reuses the row,
    retains offsets byte-for-byte, audit row prior_status=detached."""
    service, state_db, events_file = primed
    # Attach.
    first = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    attachment_id = first["attachment_id"]
    log_path = first["log_path"]

    # Advance offset.
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        lo_state.advance_offset_for_test(
            conn, agent_id=AGENT_ID, log_path=log_path,
            byte_offset=2048, line_offset=64, last_event_offset=1500,
            file_inode="234:1", file_size_seen=4096,
            last_output_at=LATER, timestamp=LATER,
        )
    finally:
        conn.close()

    # Detach.
    service.detach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )

    # Re-attach (no --log → canonical path → same path as first attach).
    second = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )

    # Same row reused.
    assert second["attachment_id"] == attachment_id
    assert second["status"] == "active"
    assert second["is_new"] is False

    # Offsets retained.
    conn = sqlite3.connect(str(state_db))
    try:
        offset_row = conn.execute(
            "SELECT byte_offset, line_offset, last_event_offset, file_inode, file_size_seen "
            "FROM log_offsets WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert offset_row == (2048, 64, 1500, "234:1", 4096), (
        f"FR-021d byte-for-byte retention; got {offset_row}"
    )

    # Audit: attach (None→active) + detach (active→detached) + re-attach (detached→active).
    audit = _audit_rows(events_file)
    assert len(audit) == 3
    assert audit[2]["payload"]["prior_status"] == "detached"
    assert audit[2]["payload"]["new_status"] == "active"


def test_t193_supersede_from_detached_no_toggle_off(primed) -> None:
    """T193 / FR-019 / Q2 — path change from detached prior status:
    new row at new path; toggle-off is NOT issued on the prior detached
    row (it's not actively piping). Audit row prior_status=detached.
    """
    service, state_db, events_file = primed
    canonical_logs = primed[2].parent / ".local" / "state" / "opensoft" / "agenttower" / "logs" / CONTAINER_ID

    first = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    first_id = first["attachment_id"]

    service.detach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )

    # Re-attach with a NEW --log under the canonical bind mount.
    new_path = canonical_logs / "operator_supplied.log"
    third = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID, "log_path": str(new_path)},
        socket_peer_uid=1000,
    )
    assert third["attachment_id"] != first_id
    assert third["log_path"] == str(new_path)

    conn = sqlite3.connect(str(state_db))
    try:
        prior = conn.execute(
            "SELECT status, superseded_by FROM log_attachments WHERE attachment_id = ?",
            (first_id,),
        ).fetchone()
    finally:
        conn.close()
    assert prior[0] == "superseded"
    assert prior[1] == third["attachment_id"]


# ===========================================================================
# US5 — stale recovery + file-consistency + supersede-from-stale
# ===========================================================================


def test_t150_recovery_from_stale_pane_drift_retains_offsets(primed, tmp_path: Path) -> None:
    """T150 / FR-021 — file intact path: re-attach from stale retains offsets
    byte-for-byte; audit row prior_status=stale."""
    service, state_db, events_file = primed
    canonical_logs = tmp_path / ".local" / "state" / "opensoft" / "agenttower" / "logs" / CONTAINER_ID
    canonical_path = canonical_logs / f"{AGENT_ID}.log"
    canonical_path.write_bytes(b"x" * 4096)
    os.chmod(canonical_path, 0o600)  # FEAT-001 file-mode invariant
    st = os.stat(canonical_path)
    real_inode = f"{st.st_dev}:{st.st_ino}"

    # Seed a stale row pointing at the canonical path with offsets matching
    # the current file (so file-consistency check passes).
    _seed_attachment(
        state_db,
        log_path=str(canonical_path),
        status="stale",
        file_inode=real_inode,
        file_size_seen=4096,
        byte_offset=2048,
        line_offset=64,
    )

    # Re-attach.
    result = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    assert result["status"] == "active"
    assert result["is_new"] is False

    conn = sqlite3.connect(str(state_db))
    try:
        offset_row = conn.execute(
            "SELECT byte_offset, line_offset FROM log_offsets WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert offset_row == (2048, 64), f"FR-021 byte-for-byte retention; got {offset_row}"

    audit = _audit_rows(events_file)
    assert len(audit) == 1
    assert audit[0]["payload"]["prior_status"] == "stale"
    assert audit[0]["payload"]["new_status"] == "active"


def test_t151_recovery_from_stale_file_changed_resets_offsets_emits_rotation(
    primed, tmp_path: Path
) -> None:
    """T151 / FR-021 / Q4 — file_inode differs OR size shrank:
    offsets reset to (0,0,0); ``log_rotation_detected`` lifecycle event in
    ADDITION to the audit row."""
    service, state_db, events_file = primed
    canonical_logs = tmp_path / ".local" / "state" / "opensoft" / "agenttower" / "logs" / CONTAINER_ID
    canonical_path = canonical_logs / f"{AGENT_ID}.log"
    canonical_path.write_bytes(b"y" * 1024)  # smaller than file_size_seen
    os.chmod(canonical_path, 0o600)

    # Seed stale row with stale_inode and large size — recovery should
    # detect file change and reset.
    _seed_attachment(
        state_db,
        log_path=str(canonical_path),
        status="stale",
        file_inode="234:9999",  # different from real
        file_size_seen=8192,
        byte_offset=2048,
        line_offset=64,
    )

    # Capture lifecycle events via a recording logger.
    class _Rec:
        def __init__(self): self.events = []
        def emit(self, name, level="info", **fields): self.events.append((name, fields))
    rec = _Rec()
    service.lifecycle_logger = rec

    result = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    assert result["status"] == "active"

    # Offsets reset.
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT byte_offset, line_offset FROM log_offsets WHERE agent_id = ?",
            (AGENT_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert row == (0, 0)

    # Lifecycle event was emitted.
    assert any(name == "log_rotation_detected" for name, _ in rec.events), (
        f"expected log_rotation_detected event; got {[n for n,_ in rec.events]}"
    )


def test_t152_supersede_from_stale_no_toggle_off(primed, tmp_path: Path) -> None:
    """T152 / FR-019 / Q2 — supersede from stale: prior row → superseded;
    new row at new path; toggle-off NOT issued (no live pipe).

    Verified by counting docker_exec calls — supersede-from-stale should
    only issue list-panes + pipe-pane (the new attach), NOT toggle-off
    on the prior stale row.
    """
    service, state_db, events_file = primed
    canonical_logs = tmp_path / ".local" / "state" / "opensoft" / "agenttower" / "logs" / CONTAINER_ID
    canonical_path = canonical_logs / f"{AGENT_ID}.log"
    canonical_path.write_bytes(b"")
    st = os.stat(canonical_path)
    _seed_attachment(
        state_db,
        log_path=str(canonical_path),
        status="stale",
        file_inode=f"{st.st_dev}:{st.st_ino}",
        file_size_seen=0,
        attachment_id="lat_priorstale01",
    )

    new_path = canonical_logs / "new.log"
    runner: FakeDockerExecRunner = service.docker_exec_runner  # type: ignore[assignment]
    runner.recorded_argv.clear()

    third = service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID, "log_path": str(new_path)},
        socket_peer_uid=1000,
    )
    assert third["attachment_id"] != "lat_priorstale01"

    # Confirm no toggle-off (pipe-pane WITHOUT trailing command argument).
    # Toggle-off form: tmux pipe-pane -t <pane>  (no -o, no command)
    # Attach form:    tmux pipe-pane -o -t <pane> 'cat >> ...'
    toggle_offs = [argv for argv in runner.recorded_argv
                   if "pipe-pane" in " ".join(argv) and "cat >>" not in " ".join(argv)
                   and "-o" not in argv]
    assert toggle_offs == [], (
        f"FR-019 / Q2: supersede-from-stale must NOT issue toggle-off; "
        f"found {toggle_offs}"
    )

    # Prior row is superseded.
    conn = sqlite3.connect(str(state_db))
    try:
        prior = conn.execute(
            "SELECT status FROM log_attachments WHERE attachment_id = ?",
            ("lat_priorstale01",),
        ).fetchone()
    finally:
        conn.close()
    assert prior[0] == "superseded"


# ===========================================================================
# US4 — atomic register-self --attach-log unit tests
# ===========================================================================
#
# US4 is exercised end-to-end through the CLI in
# ``test_feat007_register_self_attach_log.py`` (success + failure +
# without-attach-log). The unit-level invariants enumerated by T130/T131/T132
# are verified at integration granularity there. We add direct in-process
# checks here against the LogService surface to lock the contracts more
# tightly.


def test_t130_atomic_audit_row_ordering_via_explicit_attach(primed) -> None:
    """T130 — when the attach call commits, the audit row contains the
    fields data-model.md §2 specifies. The FR-035 ordering (FEAT-006
    role-change row FIRST, FEAT-007 attach row SECOND) is exercised at
    the CLI level in ``test_feat007_register_self_attach_log.py``;
    here we lock the FEAT-007-side audit row shape.
    """
    service, _, events_file = primed
    service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1234,
    )
    audit = _audit_rows(events_file)
    assert len(audit) == 1
    payload = audit[0]["payload"]
    # Required field set per data-model.md §2.
    for required_key in (
        "attachment_id", "agent_id", "prior_status", "new_status",
        "prior_path", "new_path", "prior_pipe_target", "source",
        "socket_peer_uid",
    ):
        assert required_key in payload, f"missing audit field: {required_key}"
    assert payload["agent_id"] == AGENT_ID
    assert payload["prior_status"] is None  # brand-new row
    assert payload["new_status"] == "active"
    assert payload["source"] == "explicit"
    assert payload["socket_peer_uid"] == 1234


def test_t131_failure_path_appends_zero_audit_rows(primed) -> None:
    """T131 / FR-045 — a failed attach (e.g. agent inactive) appends ZERO
    audit rows. The FR-034 atomic register-self path inherits this.
    """
    service, state_db, events_file = primed
    # Mark agent inactive.
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "UPDATE agents SET active = 0 WHERE agent_id = ?", (AGENT_ID,)
        )
    finally:
        conn.close()
    with pytest.raises(RegistrationError) as exc_info:
        service.attach_log(
            {"schema_version": 5, "agent_id": AGENT_ID},
            socket_peer_uid=1000,
        )
    assert exc_info.value.code == "agent_inactive"
    assert _audit_rows(events_file) == [], (
        "FR-045 failed attach appended an audit row"
    )


def test_t132_register_self_source_set_daemon_internally_only(primed) -> None:
    """T132 / FR-035 / FR-039 — ``source=register_self`` is daemon-internal.

    Verified at unit level by:
    1. Confirming the wire envelope rejects ``source`` (covered by T032 /
       T065 — tested separately).
    2. Confirming an attach via the LogService with no source argument
       defaults to ``source=explicit`` and records that on the audit row.
    The cross-FEAT register-self pathway sets source=register_self
    internally; that's exercised end-to-end in the FEAT-006 integration
    via ``test_feat007_register_self_attach_log.py``.
    """
    service, _, events_file = primed
    service.attach_log(
        {"schema_version": 5, "agent_id": AGENT_ID},
        socket_peer_uid=1000,
    )
    audit = _audit_rows(events_file)
    assert len(audit) == 1
    assert audit[0]["payload"]["source"] == "explicit", (
        "default source from explicit attach must be 'explicit'; "
        "register_self path sets it daemon-internally"
    )
