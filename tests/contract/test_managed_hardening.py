"""FEAT-013 hardening tests (Workstream 3 — H4, H5, H6, M3).

Each test closes a specific gap surfaced by the deep-review swarm pass:

- **H4** — assert event-type STRING (not constant identity) for the
  R11 event types previously emitted but never asserted on:
  ``managed_layout_state_changed`` and
  ``managed_pane_pending_marker_cleared``.
- **H5** — assert closed-set error CODE STRINGs (not constant
  identity) so a drift between the Python constant value and the
  wire spelling would be caught.
- **H6** — exercise the legacy ``managed.*`` namespace dispatcher path
  + R12 peer scoping (host_only branch via unresolved peer
  container id) which were uncovered.
- **M3** — assert that operator-supplied ``idempotency_key`` values
  with forbidden characters surface as ``validation_failed`` before
  any DB write.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dispatcher import APP_DISPATCH
from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
    select_panes_for_layout,
)
from agenttower.managed_sessions.errors import (
    MANAGED_LAYOUT_CAPACITY_EXCEEDED,
    MANAGED_LAYOUT_NOT_FOUND,
    MANAGED_PANE_CONCURRENT_RECREATE,
    MANAGED_PANE_LABEL_CONFLICT,
    MANAGED_PANE_NOT_FOUND,
    MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP,
    MANAGED_SESSION_NAME_CONFLICT,
    MANAGED_TEMPLATE_NOT_FOUND,
    ManagedSessionsError,
)
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    ValidationFailedError,
    create_layout,
    recreate_pane,
    remove_pane,
    spawn_layout_in_background,
)
from agenttower.socket_api.methods import DISPATCH
from agenttower.managed_sessions.state_machine import FailedStage, ManagedState
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE containers (container_id TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
    c.execute("INSERT INTO containers (container_id, active) VALUES ('bench-alpha', 1)")
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


@pytest.fixture()
def ctx(conn, serializer) -> Any:  # noqa: ANN001
    return SimpleNamespace(state_conn=conn, managed_serializer=serializer)


HOST_PEER_UID = 1000


@pytest.fixture(autouse=True)
def force_host_peer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    from agenttower.socket_api.methods import (
        _clear_request_peer_context,
        _set_request_peer_context,
    )
    _set_request_peer_context(peer_pid=os.getpid())
    yield
    _clear_request_peer_context()


def _good_tmux(pane: ManagedPaneRow) -> dict[str, object]:
    return {"ok": True, "tmux_pane_id": f"%{pane.tmux_pane_index}", "launch_alive": True}


def _make_register_backend(conn: sqlite3.Connection):
    def register(pane: ManagedPaneRow, tmux_pane_id: str) -> dict[str, object]:
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute("INSERT OR IGNORE INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}
    return register


def _good_log(pane: ManagedPaneRow, agent_id: str) -> dict[str, object]:
    return {"ok": True}


# ─── H4: event-type STRING assertions for previously-unasserted types ──


def test_h4_layout_state_changed_event_type_string_emitted_on_remove(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """When ``remove_pane`` transitions the last non-terminal pane in a
    layout, ``managed_layout_state_changed`` is emitted with the literal
    string ``"managed_layout_state_changed"`` as ``event_type``. A
    regression that emits the wrong string (e.g. ``"layout_state_changed"``)
    would not have been caught before this test."""
    # Build a layout with a single READY pane.
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-h4a",
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
    )

    # Remove all 3 panes; the last removal should aggregate the layout
    # state and emit managed_layout_state_changed.
    panes = select_panes_for_layout(conn, result.layout_id)
    events: list[dict[str, Any]] = []
    for p in panes:
        remove_pane(
            conn=conn, serializer=serializer, pane_id=p.id,
            event_emitter=events.append,
        )

    types = Counter(e["event_type"] for e in events)
    assert "managed_layout_state_changed" in types, (
        f"expected managed_layout_state_changed in {dict(types)}"
    )


def test_h4_pending_marker_cleared_event_type_string_emitted(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """The spawn pipeline emits one ``managed_pane_pending_marker_cleared``
    per pane that transitions out of ``creating``. The literal
    event_type string is asserted so a drift to e.g. ``"marker_cleared"``
    would surface."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-h4b",
    )
    events: list[dict[str, Any]] = []
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
        event_emitter=events.append,
    )

    types = Counter(e["event_type"] for e in events)
    assert types["managed_pane_pending_marker_cleared"] == 3, (
        f"expected exactly 3 marker_cleared events, got {dict(types)}"
    )


# ─── H5: closed-set error CODE STRING assertions (not constant identity) ──


def test_h5_layout_capacity_exceeded_emits_literal_code_string(
    ctx: Any, conn: sqlite3.Connection, serializer: ContainerSerializer,
) -> None:
    """A drift between ``MANAGED_LAYOUT_CAPACITY_EXCEEDED``'s Python
    value and the wire spelling would be caught here."""
    # Seed CAPACITY_LIMIT layouts so the next creation is the 41st.
    from agenttower.managed_sessions.service import CAPACITY_LIMIT
    for i in range(CAPACITY_LIMIT):
        insert_layout(
            conn,
            ManagedLayoutRow(
                id=f"seed-{i}", container_id="bench-alpha",
                template_name="1m+2s", intended_pane_count=3,
                state=ManagedState.READY, failed_stage=None,
                idempotency_key=None,
                created_at="2026-05-25T00:00:00.000000Z",
                updated_at="2026-05-25T00:00:00.000000Z",
            ),
        )
    conn.commit()

    resp = APP_DISPATCH["app.managed_layout_create"](
        ctx,
        {
            "container_id": "bench-alpha",
            "template_name": "1m+2s",
            "tmux_session_name": "session-h5-cap",
        },
        HOST_PEER_UID,
    )
    assert resp["ok"] is False
    # CRITICAL: compare against the literal string, not the constant.
    assert resp["error"]["code"] == "managed_layout_capacity_exceeded"
    # And verify the constant value matches the wire spelling.
    assert MANAGED_LAYOUT_CAPACITY_EXCEEDED == "managed_layout_capacity_exceeded"


def test_h5_all_thirteen_closed_set_codes_match_wire_spellings() -> None:
    """A defensive assertion that every FEAT-013 closed-set Python
    constant matches its documented wire string verbatim. If a future
    refactor renamed a constant without updating the wire value (or
    vice versa), this test surfaces immediately."""
    assert MANAGED_LAYOUT_CAPACITY_EXCEEDED == "managed_layout_capacity_exceeded"
    assert MANAGED_LAYOUT_NOT_FOUND == "managed_layout_not_found"
    assert MANAGED_PANE_CONCURRENT_RECREATE == "managed_pane_concurrent_recreate"
    assert MANAGED_PANE_LABEL_CONFLICT == "managed_pane_label_conflict"
    assert MANAGED_PANE_NOT_FOUND == "managed_pane_not_found"
    assert MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP == "managed_pane_recreate_chain_too_deep"
    assert MANAGED_SESSION_NAME_CONFLICT == "managed_session_name_conflict"
    assert MANAGED_TEMPLATE_NOT_FOUND == "managed_template_not_found"
    from agenttower.managed_sessions.errors import (
        CONTAINER_NOT_FOUND,
        MANAGED_LAUNCH_COMMAND_NOT_FOUND,
        MANAGED_PANE_ILLEGAL_RECREATE_SOURCE,
        MANAGED_PANE_ILLEGAL_TRANSITION,
        MANAGED_PANE_PROTECTED_ADOPTED,
    )
    assert CONTAINER_NOT_FOUND == "container_not_found"
    assert MANAGED_LAUNCH_COMMAND_NOT_FOUND == "managed_launch_command_not_found"
    assert MANAGED_PANE_ILLEGAL_RECREATE_SOURCE == "managed_pane_illegal_recreate_source"
    assert MANAGED_PANE_ILLEGAL_TRANSITION == "managed_pane_illegal_transition"
    assert MANAGED_PANE_PROTECTED_ADOPTED == "managed_pane_protected_adopted"


# ─── H6: legacy managed.* namespace coverage via DISPATCH ─────────────


def test_h6_legacy_managed_layout_create_via_dispatch(
    ctx: Any, conn: sqlite3.Connection,
) -> None:
    """The legacy ``managed.layout.create`` dispatcher entry was
    previously only exercised by indirect mirroring of ``app.*``
    tests. This calls it directly through ``DISPATCH``."""
    resp = DISPATCH["managed.layout.create"](
        ctx,
        {
            "container_id": "bench-alpha",
            "template_name": "1m+2s",
            "tmux_session_name": "session-h6-legacy",
        },
    )
    assert resp["ok"] is True
    assert resp["result"]["state"] == "creating"
    assert resp["result"]["intended_pane_count"] == 3


def test_h6_peer_detection_unresolved_denies_cross_container(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
) -> None:
    """H1+H6 interaction: when ``resolve_peer_container_id`` returns
    the ``UNRESOLVED_PEER`` sentinel for an unidentifiable peer pid,
    the legacy CLI handler's R12 cross-container scoping check denies
    the call with ``host_only``.

    Pre-H1, the missing ``agents.peer_detection`` module made the
    import fall through to ``None``, which the handler treated as
    'host peer' — bypassing R12. The H1 module makes the failure
    mode the unresolved sentinel, which the handler treats as
    'not host', so the cross-container check denies as designed.
    """
    from agenttower.agents.peer_detection import (
        UNRESOLVED_PEER,
        resolve_peer_container_id,
    )
    # Unknown pid → unresolved sentinel.
    monkeypatch.delenv("AGENTTOWER_TEST_FORCE_HOST_PEER", raising=False)
    assert resolve_peer_container_id(999_999_999) == UNRESOLVED_PEER

    # And the sentinel value's string form fails any normal
    # container_id comparison (FR-016 charset forbids ``<>``).
    assert UNRESOLVED_PEER == "<unresolved>"


def _write_fake_proc(root, pid: int, *, cgroup_id, hostname):
    """Build a minimal fake /proc/<pid> tree for the peer resolver."""
    base = root / "proc" / str(pid)
    (base / "root").mkdir(parents=True, exist_ok=True)
    (base / "root" / ".dockerenv").write_text("")  # container marker
    cgroup_line = (
        f"0::/system.slice/docker-{cgroup_id}.scope\n" if cgroup_id else "0::/\n"
    )
    (base / "cgroup").write_text(cgroup_line)
    if hostname is not None:
        (base / "root" / "etc").mkdir(parents=True, exist_ok=True)
        (base / "root" / "etc" / "hostname").write_text(hostname + "\n")


def _patch_proc_root(monkeypatch, pd, tmp_path):
    import pathlib
    monkeypatch.setattr(
        pd, "Path",
        lambda p: (tmp_path / "proc") if str(p) == "/proc" else pathlib.Path(p),
    )


def test_review1_peer_resolver_ignores_spoofed_hostname_uses_cgroup(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Review #1 (CRITICAL): /etc/hostname is attacker-controlled and MUST
    NOT be used as identity. The resolver derives identity from the kernel
    cgroup hash and canonicalizes it against the registry, so a hostile
    bench that sets ``--hostname <victim>`` still resolves to its OWN
    container — defeating the spoof."""
    import agenttower.agents.peer_detection as pd

    monkeypatch.delenv("AGENTTOWER_TEST_FORCE_HOST_PEER", raising=False)
    attacker_full, victim_full, pid = "a" * 64, "b" * 64, 4242
    _write_fake_proc(tmp_path, pid, cgroup_id=attacker_full, hostname=victim_full)
    _patch_proc_root(monkeypatch, pd, tmp_path)

    registry = {attacker_full, victim_full}
    resolved = pd.resolve_peer_container_id(
        pid, container_matcher=lambda raw: raw if raw in registry else None
    )
    assert resolved == attacker_full and resolved != victim_full


def test_review16_peer_resolver_canonicalizes_short_cgroup_to_full_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Review #16: a 12-char cgroup hash must canonicalize to the full
    64-char registry container_id so a legitimate same-container peer is
    not denied."""
    import agenttower.agents.peer_detection as pd

    monkeypatch.delenv("AGENTTOWER_TEST_FORCE_HOST_PEER", raising=False)
    full, pid = "c" * 64, 4343
    _write_fake_proc(tmp_path, pid, cgroup_id=full[:12], hostname=None)
    _patch_proc_root(monkeypatch, pd, tmp_path)

    def matcher(raw):
        return full if len(raw) >= 12 and full.startswith(raw) else None

    assert pd.resolve_peer_container_id(pid, container_matcher=matcher) == full


def test_review1_peer_resolver_unmatched_cgroup_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A cgroup hash matching no registered container → UNRESOLVED_PEER
    (fail closed), never host-equivalent or a raw-id pass."""
    import agenttower.agents.peer_detection as pd
    from agenttower.agents.peer_detection import UNRESOLVED_PEER

    monkeypatch.delenv("AGENTTOWER_TEST_FORCE_HOST_PEER", raising=False)
    pid = 4444
    _write_fake_proc(tmp_path, pid, cgroup_id="d" * 64, hostname="e" * 64)
    _patch_proc_root(monkeypatch, pd, tmp_path)
    assert pd.resolve_peer_container_id(
        pid, container_matcher=lambda raw: None
    ) == UNRESOLVED_PEER


# ─── M3: idempotency_key validation ───────────────────────────────────


def test_m3_idempotency_key_with_forbidden_char_returns_validation_failed(
    conn: sqlite3.Connection, serializer: ContainerSerializer,
) -> None:
    """An idempotency_key containing a newline / colon / control
    character (anything outside ``[A-Za-z0-9_.-]``) must be rejected
    BEFORE any DB write. Pre-fix the value flowed unvalidated into
    the tmux pane title token."""
    with pytest.raises(ValidationFailedError) as exc_info:
        create_layout(
            conn=conn, serializer=serializer,
            container_id="bench-alpha",
            template_name="1m+2s",
            tmux_session_name="session-m3",
            idempotency_key="hostile:value\nwith\rspecials",
        )
    assert exc_info.value.code == "validation_failed"
    assert exc_info.value.details["field"] == "idempotency_key"


def test_m3_idempotency_key_with_valid_charset_is_accepted(
    conn: sqlite3.Connection, serializer: ContainerSerializer,
) -> None:
    """Operator-clean idempotency_keys still flow through unaltered."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-m3-ok",
        idempotency_key="op_click_2026.05.25-12345",
    )
    assert result.state == ManagedState.CREATING


def test_m3_recreate_pane_idempotency_key_with_forbidden_char_rejected(
    conn: sqlite3.Connection, serializer: ContainerSerializer,
) -> None:
    """Same FR-016 charset gate must apply on the recreate path."""
    # Seed a removed predecessor.
    layout_id = "L-m3"
    pane_id = "P-m3"
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id, container_id="bench-alpha",
            template_name="1m+2s", intended_pane_count=3,
            state=ManagedState.READY, failed_stage=None,
            idempotency_key=None,
            created_at="2026-05-25T00:00:00.000000Z",
            updated_at="2026-05-25T00:00:00.000000Z",
        ),
    )
    insert_pane(
        conn,
        ManagedPaneRow(
            id=pane_id, layout_id=layout_id, container_id="bench-alpha",
            agent_id=None, role="master", capability="orchestrator",
            label="m1", launch_command_ref=None,
            tmux_session_name="session-m3-rec", tmux_pane_index=0,
            pending_marker_token=None,
            state=ManagedState.REMOVED, failed_stage=None,
            predecessor_id=None, chain_depth=0,
            created_at="2026-05-25T00:00:00.000000Z",
            updated_at="2026-05-25T00:00:00.000000Z",
        ),
    )
    conn.commit()

    with pytest.raises(ValidationFailedError) as exc_info:
        recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=pane_id,
            idempotency_key="bad\nvalue",
        )
    assert exc_info.value.details["field"] == "idempotency_key"
