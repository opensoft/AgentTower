"""Unit tests for FEAT-004 combined scan exit-code precedence."""

from __future__ import annotations

import argparse
from pathlib import Path

from agenttower import cli


def _args(*, containers: bool, panes: bool, json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(containers=containers, panes=panes, json=json)


def test_combined_scan_short_circuits_on_daemon_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: object())
    monkeypatch.setattr(cli, "_run_container_scan", lambda paths, args, first_block: 2)
    called = {"panes": 0}

    def fail_if_called(paths, args, first_block):
        called["panes"] += 1
        return 0

    monkeypatch.setattr(cli, "_run_pane_scan", fail_if_called)
    assert cli._scan_command(_args(containers=True, panes=True)) == 2
    assert called["panes"] == 0


def test_combined_scan_daemon_error_overrides_prior_degraded(monkeypatch) -> None:
    monkeypatch.setattr(cli, "resolve_paths", lambda: object())
    monkeypatch.setattr(cli, "_run_container_scan", lambda paths, args, first_block: 5)
    monkeypatch.setattr(cli, "_run_pane_scan", lambda paths, args, first_block: 3)
    assert cli._scan_command(_args(containers=True, panes=True)) == 3


def test_combine_scan_exit_codes_keeps_degraded_when_any_step_degrades() -> None:
    assert cli._combine_scan_exit_codes(0, 5) == 5
    assert cli._combine_scan_exit_codes(5, 0) == 5
    assert cli._combine_scan_exit_codes(0, 0) == 0
