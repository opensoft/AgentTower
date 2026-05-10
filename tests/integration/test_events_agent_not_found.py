"""T046 — FR-035a: ``events --target <unknown>`` exits 4 with
``agent_not_found``.

Distinct from "registered agent with zero events" (which returns
success with an empty stream — covered in
``test_events_us1_inspect.test_us1_as4_no_attachment_returns_empty``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import _daemon_helpers as helpers


def _agenttower_events(
    env: dict[str, str], *args: str, timeout: float = 10.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agenttower", "events", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _output_carries_code(result: subprocess.CompletedProcess[str], code: str) -> bool:
    """The local-error helper writes to stdout in --json mode and stderr
    in human mode (FEAT-002 _emit_local_error contract). Check both."""
    return code in (result.stdout or "") or code in (result.stderr or "")


def test_unknown_target_exits_4(tmp_path: Path) -> None:
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        result = _agenttower_events(
            env, "--target", "agt_ffffffffffff", "--json"
        )
        assert result.returncode == 4, (
            f"expected exit 4 (agent_not_found); got {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        assert _output_carries_code(result, "agent_not_found")
    finally:
        helpers.stop_daemon_if_alive(env)


def test_unknown_target_human_mode_exits_4(tmp_path: Path) -> None:
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        result = _agenttower_events(env, "--target", "agt_ffffffffffff")
        assert result.returncode == 4
        assert _output_carries_code(result, "agent_not_found")
    finally:
        helpers.stop_daemon_if_alive(env)


def test_invalid_agent_id_shape_exits_2(tmp_path: Path) -> None:
    """Pre-flight argument validation: bad agent_id shape → exit 2,
    no daemon round-trip."""
    env = helpers.isolated_env(tmp_path)
    result = subprocess.run(
        ["agenttower", "events", "--target", "invalid-id", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert result.returncode == 2
    assert _output_carries_code(result, "value_out_of_set") or _output_carries_code(result, "agt_")


def test_unknown_event_type_exits_2(tmp_path: Path) -> None:
    """Bad ``--type`` value → client-side validation → exit 2."""
    env = helpers.isolated_env(tmp_path)
    result = subprocess.run(
        ["agenttower", "events", "--type", "nonsense"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert result.returncode == 2
    # In human mode (no --json), this should land on stderr.
    assert "nonsense" in result.stderr or "unknown event type" in result.stderr
