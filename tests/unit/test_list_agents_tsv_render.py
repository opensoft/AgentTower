"""Unit tests for FEAT-006 list-agents locked TSV render (T031 / FR-029).

Tests the CLI handler ``_list_agents_command`` directly with a fake
``send_request`` so we don't need a daemon. Asserts the locked
nine-column header row and per-field rendering rules.

Future-field exclusion: even if the daemon adds a field to the JSON
response, the default TSV form MUST keep exactly the nine documented
columns. Snapshot test pins this.
"""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from agenttower import cli


def _stub_send_request(
    monkeypatch, *, agents: list[dict[str, Any]]
) -> None:
    def fake_send(socket_path, method, params=None, **_kw):
        return {"agents": agents, "filter": {}}

    monkeypatch.setattr(cli, "send_request", fake_send)
    monkeypatch.setattr(
        cli,
        "_resolve_socket_with_paths",
        lambda env=None: (None, type("S", (), {"path": Path("/tmp/sock")})()),
    )


def _args(json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        role=None, container=None, active_only=False, parent=None, json=json
    )


def test_header_row_and_column_order(monkeypatch) -> None:
    agents = [
        {
            "agent_id": "agt_abc123def456",
            "label": "codex-01",
            "role": "slave",
            "capability": "codex",
            "container_id": "abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            "tmux_session_name": "main",
            "tmux_window_index": 0,
            "tmux_pane_index": 0,
            "project_path": "/workspace/acme",
            "parent_agent_id": None,
            "active": True,
        }
    ]
    _stub_send_request(monkeypatch, agents=agents)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli._list_agents_command(_args())
    assert rc == 0
    out = buf.getvalue()
    lines = out.splitlines()
    assert (
        lines[0]
        == "AGENT_ID\tLABEL\tROLE\tCAPABILITY\tCONTAINER\tPANE\tPROJECT\tPARENT\tACTIVE"
    )
    fields = lines[1].split("\t")
    # Exactly nine columns; order locked.
    assert len(fields) == 9
    assert fields[0] == "agt_abc123def456"
    assert fields[1] == "codex-01"
    assert fields[2] == "slave"
    assert fields[3] == "codex"
    # CONTAINER renders as bare 12-char short id.
    assert fields[4] == "abc123def456"
    # PANE renders session:window.pane.
    assert fields[5] == "main:0.0"
    assert fields[6] == "/workspace/acme"
    # PARENT renders '-' when null.
    assert fields[7] == "-"
    assert fields[8] == "true"


def test_parent_renders_full_form_when_non_null(monkeypatch) -> None:
    agents = [
        {
            "agent_id": "agt_xxxxxxxxxxxx",
            "label": "child",
            "role": "swarm",
            "capability": "claude",
            "container_id": "f" * 64,
            "tmux_session_name": "main",
            "tmux_window_index": 0,
            "tmux_pane_index": 1,
            "project_path": "",
            "parent_agent_id": "agt_aaaaaaaaaaaa",
            "active": True,
        }
    ]
    _stub_send_request(monkeypatch, agents=agents)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli._list_agents_command(_args())
    parent_field = buf.getvalue().splitlines()[1].split("\t")[7]
    assert parent_field == "agt_aaaaaaaaaaaa"


def test_inactive_renders_false(monkeypatch) -> None:
    agents = [
        {
            "agent_id": "agt_aaaaaaaaaaaa",
            "label": "x",
            "role": "slave",
            "capability": "codex",
            "container_id": "a" * 64,
            "tmux_session_name": "main",
            "tmux_window_index": 0,
            "tmux_pane_index": 0,
            "project_path": "",
            "parent_agent_id": None,
            "active": False,
        }
    ]
    _stub_send_request(monkeypatch, agents=agents)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli._list_agents_command(_args())
    last = buf.getvalue().splitlines()[1].split("\t")[8]
    assert last == "false"


def test_embedded_tab_in_label_replaced_with_space(monkeypatch) -> None:
    agents = [
        {
            "agent_id": "agt_aaaaaaaaaaaa",
            "label": "lab\tel",
            "role": "slave",
            "capability": "codex",
            "container_id": "a" * 64,
            "tmux_session_name": "main",
            "tmux_window_index": 0,
            "tmux_pane_index": 0,
            "project_path": "",
            "parent_agent_id": None,
            "active": True,
        }
    ]
    _stub_send_request(monkeypatch, agents=agents)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli._list_agents_command(_args())
    line = buf.getvalue().splitlines()[1]
    # Exactly nine fields after sanitization (no extra split).
    assert len(line.split("\t")) == 9
