"""FEAT-011 T082 — SC-010: app.* socket methods produce state byte-for-byte
identical to the equivalent legacy CLI path.

SC-010 invariant: the FEAT-011 ``app.*`` namespace is an alternate front
door onto the same FEAT-006/007/010 service layer the operator CLI uses.
A given operation, performed via the socket or via the CLI, must leave the
SQLite state in the same shape.

Achievable parity case without a bench container
------------------------------------------------
**Route creation** is fully driveable from both fronts with no live
container, tmux, or Docker:

* legacy CLI: ``agenttower route add ...`` → ``routes.add`` socket method
  → ``RoutesService.add_route``;
* FEAT-011:   ``app.route.add`` over the socket → ``RoutesService.add_route``.

Both converge on the same FEAT-010 service call. This test creates one
route via each front against the **same** daemon, then reads the two
``routes`` SQLite rows and asserts they are equal **modulo** the columns
that are intrinsically per-row or per-caller:

* ``route_id``            — fresh ULID/identifier per row;
* ``created_at`` / ``updated_at`` — wall-clock timestamps;
* ``created_by_agent_id`` — caller attribution differs by front (the CLI
  attributes to the ``host-operator`` sentinel; ``app.route.add`` attributes
  to ``None`` per ``mutations.app_route_add``).

Every other column — ``event_type``, ``source_scope_*``, ``target_*``,
``master_*``, ``template``, ``enabled``, ``last_consumed_event_id`` — must
match exactly.

Deferred parity (documented, not skipped silently)
--------------------------------------------------
The agent-dependent parity methods — ``app.agent.register_from_pane``,
``app.agent.update`` (set-role / set-label / set-capability), and
``app.log.attach`` — require a real pane inside a real bench container to
drive their CLI counterparts end-to-end. Those are **deferred** here:
they are covered structurally by the US2 / US3 unit suites
(``tests/unit/test_app_adopt.py``, ``test_app_us3_mutations.py``), which
exercise the very same FEAT-006/007 service layer the legacy CLI calls.
The route-creation case is the representative SC-010 parity proof that is
deterministic in CI.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
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


# ─── Wire helpers ───────────────────────────────────────────────────────


def _open_socket(socket_path: Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    saved_cwd = os.getcwd()
    try:
        os.chdir(socket_path.parent)
        sock.connect(socket_path.name)
    finally:
        os.chdir(saved_cwd)
    return sock


def _call(sock: socket.socket, method: str, params: dict | None = None) -> dict:
    request: dict = {"method": method}
    if params is not None:
        request["params"] = params
    sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.decode("utf-8"))


def _one_shot_call(socket_path: Path, method: str, params: dict | None = None) -> dict:
    sock = _open_socket(socket_path)
    try:
        return _call(sock, method, params)
    finally:
        sock.close()


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
    return {"env": env, "socket": paths["socket"], "paths": paths}


# ─── Constants ──────────────────────────────────────────────────────────

# Columns that are intrinsically per-row or per-caller and therefore
# excluded from the byte-for-byte parity comparison.
_PARITY_EXCLUDED_COLUMNS = frozenset(
    {"route_id", "created_at", "updated_at", "created_by_agent_id"}
)

# A route definition that is identical regardless of which front creates
# it. `source` target rule needs no --target value; `activity` is a
# closed-set event type; the template references only FR-008 whitelist
# fields.
_ROUTE_EVENT_TYPE = "activity"
_ROUTE_TEMPLATE = "parity probe for {source_role}/{source_capability}"


def _read_routes(state_db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(state_db))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn.execute(
            "SELECT * FROM routes ORDER BY created_at, route_id"
        ).fetchall()
    finally:
        conn.close()


def _comparable(row: sqlite3.Row) -> dict:
    """Project a routes row to its parity-comparable columns."""
    return {
        key: row[key]
        for key in row.keys()
        if key not in _PARITY_EXCLUDED_COLUMNS
    }


# ─── Tests ──────────────────────────────────────────────────────────────


def test_route_add_cli_vs_app_parity(daemon: dict) -> None:
    """SC-010: a route created via ``agenttower route add`` and a route
    created via ``app.route.add`` produce ``routes`` rows that are equal
    on every column except ``route_id``, ``created_at``, ``updated_at``,
    and ``created_by_agent_id``."""
    env: dict[str, str] = daemon["env"]
    socket_path: Path = daemon["socket"]
    state_db: Path = daemon["paths"]["state_db"]

    # ── 1. Create one route via the legacy CLI. ──
    cli_proc = subprocess.run(
        [
            "agenttower",
            "route",
            "add",
            "--event-type",
            _ROUTE_EVENT_TYPE,
            "--target-rule",
            "source",
            "--template",
            _ROUTE_TEMPLATE,
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert cli_proc.returncode == 0, (
        f"`agenttower route add` failed: rc={cli_proc.returncode} "
        f"stdout={cli_proc.stdout!r} stderr={cli_proc.stderr!r}"
    )
    cli_route = json.loads(cli_proc.stdout)
    cli_route_id = cli_route["route_id"]

    # ── 2. Create an identical route via app.route.add over the socket. ──
    hello = _one_shot_call(socket_path, "app.hello", {"client_id": "t082"})
    assert hello["ok"] is True, hello
    token = hello["result"]["app_session_token"]

    app_resp = _one_shot_call(
        socket_path,
        "app.route.add",
        {
            "app_session_token": token,
            "event_type": _ROUTE_EVENT_TYPE,
            "target": {"rule": "source"},
            "template": _ROUTE_TEMPLATE,
        },
    )
    assert app_resp["ok"] is True, app_resp
    app_route_id = app_resp["result"]["row"]["route_id"]

    assert cli_route_id != app_route_id, "expected two distinct route_ids"

    # ── 3. Read both rows back from SQLite and compare. ──
    rows = _read_routes(state_db)
    by_id = {r["route_id"]: r for r in rows}
    assert cli_route_id in by_id, f"CLI route {cli_route_id} not in {list(by_id)}"
    assert app_route_id in by_id, f"app route {app_route_id} not in {list(by_id)}"

    cli_row = by_id[cli_route_id]
    app_row = by_id[app_route_id]

    # Both rows expose the exact FEAT-010 routes column set.
    assert set(cli_row.keys()) == set(app_row.keys())

    cli_cmp = _comparable(cli_row)
    app_cmp = _comparable(app_row)
    assert cli_cmp == app_cmp, (
        "SC-010 parity violation: CLI-created and app.route.add-created "
        "routes differ on a non-excluded column.\n"
        f"  CLI : {cli_cmp!r}\n"
        f"  app : {app_cmp!r}"
    )

    # The route definition itself round-tripped intact.
    assert cli_cmp["event_type"] == _ROUTE_EVENT_TYPE
    assert cli_cmp["template"] == _ROUTE_TEMPLATE
    assert cli_cmp["target_rule"] == "source"
    assert cli_cmp["enabled"] == 1


def test_app_route_add_row_matches_feat010_schema(daemon: dict) -> None:
    """Fallback / structural backstop: even independent of the CLI, an
    ``app.route.add`` mutation produces a ``routes`` row whose column set
    is exactly the FEAT-010 schema. This guards the SC-010 contract from
    the FEAT-011 side regardless of CLI availability."""
    socket_path: Path = daemon["socket"]
    state_db: Path = daemon["paths"]["state_db"]

    hello = _one_shot_call(socket_path, "app.hello", {"client_id": "t082-schema"})
    assert hello["ok"] is True, hello
    token = hello["result"]["app_session_token"]

    app_resp = _one_shot_call(
        socket_path,
        "app.route.add",
        {
            "app_session_token": token,
            "event_type": _ROUTE_EVENT_TYPE,
            "target": {"rule": "source"},
            "template": _ROUTE_TEMPLATE,
        },
    )
    assert app_resp["ok"] is True, app_resp
    route_id = app_resp["result"]["row"]["route_id"]

    rows = _read_routes(state_db)
    created = [r for r in rows if r["route_id"] == route_id]
    assert len(created) == 1, rows
    row = created[0]

    # FEAT-010 ``routes`` table columns (state/schema.py migration v8).
    expected_columns = {
        "route_id",
        "event_type",
        "source_scope_kind",
        "source_scope_value",
        "target_rule",
        "target_value",
        "master_rule",
        "master_value",
        "template",
        "enabled",
        "last_consumed_event_id",
        "created_at",
        "updated_at",
        "created_by_agent_id",
    }
    assert set(row.keys()) == expected_columns, (
        f"app.route.add produced a routes row with unexpected columns: "
        f"{sorted(row.keys())}"
    )
    # Spot-check the persisted values match the request.
    assert row["event_type"] == _ROUTE_EVENT_TYPE
    assert row["template"] == _ROUTE_TEMPLATE
    assert row["target_rule"] == "source"
    assert row["source_scope_kind"] == "any"
    assert row["enabled"] == 1
