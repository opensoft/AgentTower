"""T091 — FR-026 / FR-044 / SC-009: lifecycle event separation.

The same ``events.jsonl`` file carries:
- FEAT-008 durable events (10 closed-set ``event_type`` values);
- FEAT-007 lifecycle events (``log_rotation_detected``,
  ``log_file_missing``, ``log_file_returned``,
  ``log_attachment_orphan_detected``, ``mounts_json_oversized``,
  ``socket_peer_uid_mismatch``);
- FEAT-007 audit rows (``log_attachment_change``).

The two sets are distinguishable by ``event_type`` and MUST NOT
overlap (FR-026). This test seeds events of both kinds and asserts
the partition is clean.

Note: This is a "consolidated lifecycle-surface assertion"
(spec §FR-044 / Plan §"Plan summary") — the dedicated per-class
FEAT-007 tests remain authoritative for individual class behavior.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from . import _daemon_helpers as helpers


# Closed sets per FR-026 / data-model.md §3.1.
FEAT008_EVENT_TYPES = frozenset(
    {
        "activity", "waiting_for_input", "completed", "error",
        "test_failed", "test_passed", "manual_review_needed",
        "long_running", "pane_exited", "swarm_member_reported",
    }
)
FEAT007_LIFECYCLE_TYPES = frozenset(
    {
        "log_rotation_detected", "log_file_missing", "log_file_returned",
        "log_attachment_orphan_detected", "mounts_json_oversized",
        "socket_peer_uid_mismatch",
    }
)
FEAT007_AUDIT_TYPES = frozenset({"log_attachment_change"})


def test_feat008_and_feat007_event_types_are_disjoint() -> None:
    """The closed sets do not overlap by spec construction."""
    assert FEAT008_EVENT_TYPES.isdisjoint(FEAT007_LIFECYCLE_TYPES)
    assert FEAT008_EVENT_TYPES.isdisjoint(FEAT007_AUDIT_TYPES)
    assert FEAT007_LIFECYCLE_TYPES.isdisjoint(FEAT007_AUDIT_TYPES)


def _seed_agent(db_path: Path, agent_id: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO agents (agent_id, container_id, "
            "tmux_socket_path, tmux_session_name, tmux_window_index, "
            "tmux_pane_index, tmux_pane_id, role, capability, label, "
            "project_path, parent_agent_id, effective_permissions, "
            "created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                agent_id, "c"*64, "/tmp/sock", "s", 0, 0, "%1",
                "slave", "shell", "demo", "", None, "{}",
                "2026-05-10T00:00:00.000000+00:00",
                "2026-05-10T00:00:00.000000+00:00",
                None, 1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_event_jsonl(events_file: Path, event_type: str, **fields) -> None:
    """Append a synthetic event to events.jsonl."""
    import os
    payload = {
        "ts": "2026-05-10T12:00:00.000000+00:00",
        "event_type": event_type,
        **fields,
    }
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    if not events_file.exists():
        events_file.touch()
        os.chmod(events_file, 0o600)
    with events_file.open("a", encoding="utf-8") as fh:
        fh.write(line)


def test_jsonl_partitions_cleanly_by_event_type(tmp_path: Path) -> None:
    """Seed both kinds of events into a fresh events.jsonl; partition
    by event_type and assert no overlap."""
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    paths = helpers.resolved_paths(tmp_path)
    try:
        _seed_agent(paths["state_db"], "agt_a1b2c3d4e5f6")

        # Seed via direct JSONL append (the same file the FEAT-008
        # reader and FEAT-007 lifecycle logger both write to).
        events_file = paths["events_file"]
        _seed_event_jsonl(events_file, "error", excerpt="boom")
        _seed_event_jsonl(events_file, "activity", excerpt="x")
        _seed_event_jsonl(
            events_file, "log_rotation_detected", agent_id="agt_a"
        )
        _seed_event_jsonl(
            events_file, "log_file_missing", agent_id="agt_a"
        )
        _seed_event_jsonl(
            events_file, "log_attachment_change", agent_id="agt_a"
        )

        # Partition by event_type.
        feat008: set[str] = set()
        feat007_lifecycle: set[str] = set()
        feat007_audit: set[str] = set()
        unknown: set[str] = set()
        with events_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                et = obj.get("event_type")
                if et in FEAT008_EVENT_TYPES:
                    feat008.add(et)
                elif et in FEAT007_LIFECYCLE_TYPES:
                    feat007_lifecycle.add(et)
                elif et in FEAT007_AUDIT_TYPES:
                    feat007_audit.add(et)
                elif et is not None:
                    unknown.add(et)

        # Both classes are present.
        assert feat008, "no FEAT-008 events found in JSONL"
        assert feat007_lifecycle, "no FEAT-007 lifecycle events in JSONL"
        # No cross-class overlap (closed-set construction).
        assert feat008.isdisjoint(feat007_lifecycle)
        assert feat008.isdisjoint(feat007_audit)
        # No surprise event types.
        assert not unknown, f"unknown event types in JSONL: {unknown}"
    finally:
        helpers.stop_daemon_if_alive(env)
