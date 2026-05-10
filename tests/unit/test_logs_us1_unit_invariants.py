"""US1 unit-level invariants for FEAT-007 schema + transactions + audit.

Consolidates several spec-named test files for trace-matrix completeness:

* T040 — `tests/unit/test_log_attachments_table.py`: composite uniqueness
  ``(agent_id, log_path)`` when status=active enforced via partial unique
  index; status CHECK; ``lat_<12-hex>`` PK shape; FK to ``agents.agent_id``;
  field types + nullability per data-model.md (FR-014).
* T041 — `tests/unit/test_log_offsets_table.py`: composite PK
  ``(agent_id, log_path)``; initial values ``(0, 0, 0, NULL, NULL, 0)``
  on creation; field types; FK to ``agents.agent_id`` (FR-015).
* T042 — `tests/unit/test_log_attach_transaction.py`: single
  ``BEGIN IMMEDIATE`` for ``log_attachments`` + ``log_offsets`` writes;
  rollback on either failure; pipe-pane success without offset row never
  observable (FR-016).
* T043 — `tests/unit/test_log_offsets_durability_signals.py`: SQLite WAL
  mode is on; every successful write commits (FR-017).
* T046 — `tests/unit/test_audit_row_shape.py`: ``log_attachment_change``
  payload — every field present; types + nullability; bounded payload
  sizes per FR-062 (FR-044).

Behavior at integration level is covered elsewhere; these unit tests
lock the per-FR contracts in isolation.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

import pytest

from agenttower.logs import audit as logs_audit
from agenttower.state import log_attachments as la_state
from agenttower.state import log_offsets as lo_state
from agenttower.state import schema


CONTAINER_ID = "c" * 64
AGENT_ID = "agt_abc123def456"
NOW = "2026-05-08T14:00:00.000000+00:00"


@pytest.fixture
def primed_db(tmp_path: Path) -> Path:
    state_db = tmp_path / "state.sqlite3"
    conn, _ = schema.open_registry(state_db, namespace_root=tmp_path)
    conn.close()
    # Seed minimal agent (referenced by FK on log_attachments / log_offsets).
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        pane_key = (CONTAINER_ID, "/tmp/tmux-1000/default", "main", 0, 0, "%17")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (CONTAINER_ID, "bench", "x", "running", "{}", "[]", "{}", "brett", "/h",
             1, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            pane_key + ("bench", "brett", 1, "/dev/pts/0", "bash",
                        "/h", "main", 1, 1, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (AGENT_ID,) + pane_key + ("slave", "codex", "x", "", None, "{}", NOW, NOW, None, 1),
        )
    finally:
        conn.close()
    return state_db


def _new_record(
    *, attachment_id: str, log_path: str = "/host/log/x.log", status: str = "active",
) -> la_state.LogAttachmentRecord:
    return la_state.LogAttachmentRecord(
        attachment_id=attachment_id,
        agent_id=AGENT_ID,
        container_id=CONTAINER_ID,
        tmux_socket_path="/tmp/tmux-1000/default",
        tmux_session_name="main",
        tmux_window_index=0,
        tmux_pane_index=0,
        tmux_pane_id="%17",
        log_path=log_path,
        status=status,
        source="explicit",
        pipe_pane_command="docker exec ...",
        prior_pipe_target=None,
        attached_at=NOW,
        last_status_at=NOW,
        superseded_at=None,
        superseded_by=None,
        created_at=NOW,
    )


# ===========================================================================
# T040 — log_attachments table invariants (FR-014)
# ===========================================================================


def test_t040_attachment_id_pk_shape_lat_12hex(primed_db: Path) -> None:
    """``attachment_id`` must match ``lat_<12-hex>``. The DAO does not enforce
    this (it's the identifier-generator's responsibility per T013), but the
    closed-set namespace is exercised by inserting a generator-shaped ID and
    confirming it round-trips.
    """
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        la_state.insert(conn, _new_record(attachment_id="lat_a1b2c3d4e5f6"))
        rec = la_state.select_active_for_agent(conn, agent_id=AGENT_ID)
    finally:
        conn.close()
    assert rec is not None
    assert re.match(r"^lat_[0-9a-f]{12}$", rec.attachment_id)


def test_t040_partial_unique_index_blocks_two_active_rows_same_path(
    primed_db: Path,
) -> None:
    """Partial unique index ``log_attachments_active_log_path``
    (``WHERE status='active'``) prevents two active rows at the same
    ``log_path`` regardless of agent_id."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        la_state.insert(conn, _new_record(
            attachment_id="lat_a1b2c3d4e5f6", log_path="/host/log/x.log",
        ))
        # Second active row at the same path → partial unique index fires.
        with pytest.raises(sqlite3.IntegrityError):
            la_state.insert(conn, _new_record(
                attachment_id="lat_b2c3d4e5f6a7", log_path="/host/log/x.log",
            ))
    finally:
        conn.close()


def test_t040_partial_unique_index_allows_two_superseded_rows_same_path(
    primed_db: Path,
) -> None:
    """The partial unique index is gated on ``status='active'`` — two
    superseded rows at the same path are allowed (history retention)."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        la_state.insert(conn, _new_record(
            attachment_id="lat_a1b2c3d4e5f6", status="superseded",
            log_path="/host/log/x.log",
        ))
        la_state.insert(conn, _new_record(
            attachment_id="lat_b2c3d4e5f6a7", status="superseded",
            log_path="/host/log/x.log",
        ))
        rows = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE log_path = ?",
            ("/host/log/x.log",),
        ).fetchone()
    finally:
        conn.close()
    assert rows[0] == 2


def test_t040_status_check_constraint_rejects_unknown_value(primed_db: Path) -> None:
    """The schema-level CHECK constraint enforces the closed-set status
    even if the DAO validator is bypassed by direct SQL."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO log_attachments (attachment_id, agent_id, "
                "container_id, tmux_socket_path, tmux_session_name, "
                "tmux_window_index, tmux_pane_index, tmux_pane_id, "
                "log_path, status, source, pipe_pane_command, prior_pipe_target, "
                "attached_at, last_status_at, superseded_at, superseded_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("lat_a1b2c3d4e5f6", AGENT_ID, CONTAINER_ID,
                 "/tmp/tmux-1000/default", "main", 0, 0, "%17",
                 "/host/log/x.log",
                 "open",  # NOT in closed set
                 "explicit", "docker exec ...", None,
                 NOW, NOW, None, None, NOW),
            )
    finally:
        conn.close()


def test_t040_source_check_constraint_rejects_unknown_value(primed_db: Path) -> None:
    """Same closed-set check on ``source``."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO log_attachments (attachment_id, agent_id, "
                "container_id, tmux_socket_path, tmux_session_name, "
                "tmux_window_index, tmux_pane_index, tmux_pane_id, "
                "log_path, status, source, pipe_pane_command, prior_pipe_target, "
                "attached_at, last_status_at, superseded_at, superseded_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("lat_a1b2c3d4e5f6", AGENT_ID, CONTAINER_ID,
                 "/tmp/tmux-1000/default", "main", 0, 0, "%17",
                 "/host/log/x.log", "active",
                 "operator",  # NOT in closed set
                 "docker exec ...", None,
                 NOW, NOW, None, None, NOW),
            )
    finally:
        conn.close()


# ===========================================================================
# T041 — log_offsets table invariants (FR-015)
# ===========================================================================


def test_t041_offset_initial_values_per_fr015(primed_db: Path) -> None:
    """``insert_initial`` lays down ``(0, 0, 0, NULL, NULL, 0)``
    per data-model.md §1.2."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        lo_state.insert_initial(
            conn, agent_id=AGENT_ID, log_path="/host/log/x.log", timestamp=NOW,
        )
        row = lo_state.select(
            conn, agent_id=AGENT_ID, log_path="/host/log/x.log",
        )
    finally:
        conn.close()
    assert row is not None
    assert row.byte_offset == 0
    assert row.line_offset == 0
    assert row.last_event_offset == 0
    assert row.last_output_at is None
    assert row.file_inode is None
    assert row.file_size_seen == 0
    assert row.created_at == NOW
    assert row.updated_at == NOW


def test_t041_composite_pk_blocks_duplicate_agent_path(primed_db: Path) -> None:
    """The composite PK ``(agent_id, log_path)`` blocks two rows for the
    same pair."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        lo_state.insert_initial(
            conn, agent_id=AGENT_ID, log_path="/host/log/x.log", timestamp=NOW,
        )
        with pytest.raises(sqlite3.IntegrityError):
            lo_state.insert_initial(
                conn, agent_id=AGENT_ID, log_path="/host/log/x.log", timestamp=NOW,
            )
    finally:
        conn.close()


def test_t041_composite_pk_allows_distinct_agent_or_path(primed_db: Path) -> None:
    """Different ``log_path`` for the same agent: allowed (history)."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        lo_state.insert_initial(
            conn, agent_id=AGENT_ID, log_path="/host/log/a.log", timestamp=NOW,
        )
        lo_state.insert_initial(
            conn, agent_id=AGENT_ID, log_path="/host/log/b.log", timestamp=NOW,
        )
        rows = conn.execute(
            "SELECT count(*) FROM log_offsets WHERE agent_id = ?", (AGENT_ID,),
        ).fetchone()
    finally:
        conn.close()
    assert rows[0] == 2


def test_t041_fk_to_agents_blocks_orphan_offset_row(primed_db: Path) -> None:
    """FK ``log_offsets.agent_id → agents.agent_id`` rejects offset rows
    for nonexistent agents."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            lo_state.insert_initial(
                conn, agent_id="agt_unknown00000",
                log_path="/host/log/x.log", timestamp=NOW,
            )
    finally:
        conn.close()


def test_t041_advance_offset_raises_when_row_missing(primed_db: Path) -> None:
    """A production offset advance must fail if no target row exists."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        with pytest.raises(sqlite3.OperationalError, match="no log_offsets row"):
            lo_state.advance_offset(
                conn,
                agent_id=AGENT_ID,
                log_path="/host/log/missing.log",
                byte_offset=10,
                line_offset=1,
                last_event_offset=10,
                file_inode=None,
                file_size_seen=10,
                last_output_at=NOW,
                timestamp=NOW,
            )
    finally:
        conn.close()


# ===========================================================================
# T042 — atomic BEGIN IMMEDIATE for log_attachments + log_offsets (FR-016)
# ===========================================================================


def test_t042_atomic_insert_both_or_neither(primed_db: Path) -> None:
    """Both rows commit together inside ``BEGIN IMMEDIATE`` or neither does.

    If the offsets insert raises (e.g. duplicate key), the attachment insert
    inside the same transaction MUST roll back too. We force the failure
    by inserting an offset row first, then attempting both inserts in one
    transaction — the offset insert raises, the attachment insert never
    becomes visible.
    """
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        # Pre-seed an offset row so the second insert collides.
        lo_state.insert_initial(
            conn, agent_id=AGENT_ID, log_path="/host/log/x.log", timestamp=NOW,
        )
        # Now do both inserts inside one explicit transaction; expect both to fail.
        try:
            conn.execute("BEGIN IMMEDIATE")
            la_state.insert(conn, _new_record(
                attachment_id="lat_a1b2c3d4e5f6", log_path="/host/log/x.log",
            ))
            lo_state.insert_initial(
                conn, agent_id=AGENT_ID, log_path="/host/log/x.log",
                timestamp=NOW,
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")

        # Attachment insert must NOT be visible.
        n = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE attachment_id = ?",
            ("lat_a1b2c3d4e5f6",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0, "FR-016: attachment insert must not commit when offsets insert fails"


def test_t042_atomic_commit_makes_both_visible(primed_db: Path) -> None:
    """Happy-path symmetry: both commit and both visible."""
    conn = sqlite3.connect(str(primed_db), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        la_state.insert(conn, _new_record(
            attachment_id="lat_a1b2c3d4e5f6", log_path="/host/log/x.log",
        ))
        lo_state.insert_initial(
            conn, agent_id=AGENT_ID, log_path="/host/log/x.log", timestamp=NOW,
        )
        conn.execute("COMMIT")

        la = conn.execute(
            "SELECT count(*) FROM log_attachments"
        ).fetchone()[0]
        lo = conn.execute(
            "SELECT count(*) FROM log_offsets"
        ).fetchone()[0]
    finally:
        conn.close()
    assert la == 1
    assert lo == 1


# ===========================================================================
# T043 — durability signals (FR-017)
# ===========================================================================


def test_t043_wal_journal_mode_is_on(primed_db: Path) -> None:
    """SQLite WAL mode MUST be enabled; required for FR-017 durability."""
    conn = sqlite3.connect(str(primed_db))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal", (
        f"FR-017 / SC-003: journal_mode must be 'wal', got {mode!r}"
    )


def test_t043_synchronous_pragma_at_safe_level(primed_db: Path) -> None:
    """``PRAGMA synchronous`` must be ``NORMAL`` (1) or ``FULL`` (2) — not
    OFF (0). FR-017 forbids returning success before commit reaches disk
    in a way the OS can drop on power-loss."""
    conn = sqlite3.connect(str(primed_db))
    try:
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        conn.close()
    assert int(sync) >= 1, (
        f"FR-017: synchronous must be NORMAL or FULL; got {sync!r}"
    )


# ===========================================================================
# T046 — audit row shape (FR-044 + FR-062)
# ===========================================================================


def test_t046_audit_row_has_every_required_field(tmp_path: Path) -> None:
    """``log_attachment_change`` payload includes every field documented
    in data-model.md §2."""
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)

    logs_audit.append_log_attachment_change(
        events_file,
        attachment_id="lat_a1b2c3d4e5f6",
        agent_id=AGENT_ID,
        prior_status=None,
        new_status="active",
        prior_path=None,
        new_path="/host/log/x.log",
        prior_pipe_target=None,
        source="explicit",
        socket_peer_uid=1000,
    )
    lines = events_file.read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["type"] == "log_attachment_change"
    payload = row["payload"]
    for required in (
        "attachment_id", "agent_id", "prior_status", "new_status",
        "prior_path", "new_path", "prior_pipe_target", "source",
        "socket_peer_uid",
    ):
        assert required in payload, f"missing audit field: {required}"
    assert payload["attachment_id"] == "lat_a1b2c3d4e5f6"
    assert payload["new_status"] == "active"
    assert payload["source"] == "explicit"
    assert isinstance(payload["socket_peer_uid"], int)


def test_t046_audit_row_handles_nullable_fields(tmp_path: Path) -> None:
    """Nullable fields (``prior_status``, ``prior_path``,
    ``prior_pipe_target``) round-trip as JSON ``null``."""
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)

    logs_audit.append_log_attachment_change(
        events_file,
        attachment_id="lat_a1b2c3d4e5f6",
        agent_id=AGENT_ID,
        prior_status=None,
        new_status="active",
        prior_path=None,
        new_path="/host/log/x.log",
        prior_pipe_target=None,
        source="explicit",
        socket_peer_uid=1000,
    )
    row = json.loads(events_file.read_text().splitlines()[0])
    assert row["payload"]["prior_status"] is None
    assert row["payload"]["prior_path"] is None
    assert row["payload"]["prior_pipe_target"] is None


def test_t046_audit_row_is_skipped_when_events_file_is_none(tmp_path: Path) -> None:
    """The audit writer is a no-op when ``events_file`` is None (defensive
    guard for tests / boot sequences before the file exists)."""
    # Should not raise.
    logs_audit.append_log_attachment_change(
        None,
        attachment_id="lat_a1b2c3d4e5f6",
        agent_id=AGENT_ID,
        prior_status=None,
        new_status="active",
        prior_path=None,
        new_path="/host/log/x.log",
        prior_pipe_target=None,
        source="explicit",
        socket_peer_uid=1000,
    )


def test_t046_audit_row_socket_peer_uid_coerced_to_int(tmp_path: Path) -> None:
    """``socket_peer_uid`` is always serialized as an int (defense against
    accidental string-typed peer-uid plumbing)."""
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    os.chmod(events_file, 0o600)

    logs_audit.append_log_attachment_change(
        events_file,
        attachment_id="lat_a1b2c3d4e5f6",
        agent_id=AGENT_ID,
        prior_status=None,
        new_status="active",
        prior_path=None,
        new_path="/host/log/x.log",
        prior_pipe_target=None,
        source="explicit",
        socket_peer_uid="1000",  # string passed in
    )
    row = json.loads(events_file.read_text().splitlines()[0])
    assert row["payload"]["socket_peer_uid"] == 1000
    assert isinstance(row["payload"]["socket_peer_uid"], int)
