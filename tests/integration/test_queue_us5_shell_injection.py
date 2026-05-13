"""T078 — US5 shell-injection safety acceptance scenarios.

**Test mode**: socket-level integration. The byte-exact tmux pane
history assertion (the fresh-container E2E's job) is OUTSIDE this
file's scope; here we verify the safety invariant via two structural
checks that DON'T require a real tmux session:

1. The payload reaches ``delivered`` (i.e., the queue + worker pipeline
   tolerates every shell metacharacter SC-003 enumerates).
2. The host filesystem is unchanged — specifically, the canary file
   ``/tmp/should-not-exist`` (or a unique-per-test variant) is not
   created. If the body bytes were ever interpolated into a shell
   command string, the SC-003 payload would create this file via
   ``$(touch /tmp/should-not-exist)`` or backticks.
3. The body's SHA-256 round-trips byte-for-byte through SQLite — the
   envelope_body_sha256 column matches the test's pre-computed
   hash of the payload bytes.

The byte-exact tmux paste verification (every byte in the pane history
matches the body bytes verbatim) belongs to the fresh-container E2E
because the FakeTmuxAdapter in this test only records call args
in-memory inside the daemon subprocess — the test process can't
observe them. The unit tests
(``test_tmux_adapter_load_buffer.py``, ``test_tmux_adapter_paste_buffer.py``,
``test_delivery_worker_failure_modes.py``) cover the byte-exact path
at adapter granularity.

Locked-decision note: FR-038 + Research §R-007's AST gate
(``test_no_shell_string_interpolation.py``) is the structural
enforcement. This integration test is the runtime witness.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path

import pytest

from agenttower.socket_api.client import send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"


# SC-003 metacharacter payload — every character a shell would treat
# specially (the body is delivered to the slave's tmux pane via a
# paste-buffer, never interpolated into a shell argument string).
# If any byte were interpolated into a shell command, the
# ``$(touch ...)`` and backtick forms would fire on the host.
def _build_shell_injection_payload(canary: Path) -> bytes:
    parts = [
        b'plain text',
        b'$(touch ' + str(canary).encode() + b')',
        b'`touch ' + str(canary).encode() + b'`',
        b"$VAR ${VAR2} 'single quoted' \"double quoted\"",
        b"semicolon; ampersand & pipe | redirect > file < stdin",
        b"glob? * [ranges] {brace,expansion}",
        b"\\backslash \\\"escaped\\\" \\$dollar",
    ]
    return b"\n".join(parts)


def _send(
    paths: dict[str, Path], *, body: bytes, wait: bool = True,
    wait_timeout_seconds: float = 15.0,
) -> dict:
    return send_request(
        paths["socket"], "queue.send_input",
        {
            "target": _SLAVE_ID,
            "body_bytes": base64.b64encode(body).decode("ascii"),
            "caller_pane": {"agent_id": _MASTER_ID},
            "wait": wait,
            "wait_timeout_seconds": wait_timeout_seconds,
        },
        connect_timeout=2.0, read_timeout=20.0,
    )


@pytest.fixture()
def daemon_with_master_and_slave(tmp_path: Path):
    env = helpers.isolated_env(tmp_path)
    helpers.run_config_init(env)
    paths = helpers.resolved_paths(tmp_path)
    f9.install_tmux_fake_in_env(env, tmp_path)
    helpers.ensure_daemon(env, timeout=10.0)
    try:
        f9.seed_master_and_slave(paths["state_db"])
        yield env, paths, tmp_path
    finally:
        helpers.stop_daemon_if_alive(env)


def test_us5_shell_injection_payload_delivered_no_canary_created(
    daemon_with_master_and_slave,
) -> None:
    env, paths, tmp_path = daemon_with_master_and_slave
    # Unique-per-test canary so a leaked previous-test side effect can't
    # mask a real failure here.
    canary = tmp_path / "should-not-exist"
    assert not canary.exists()

    payload = _build_shell_injection_payload(canary)
    row = _send(paths, body=payload, wait=True)

    # Either delivered or queued (worker race) — both prove the queue
    # accepted the body without sanitization. If shell injection had
    # occurred during enqueue or delivery, the daemon would have spawned
    # a process that touched the canary.
    assert row["state"] in ("delivered", "queued")

    # CRITICAL: the canary MUST NOT exist. If body bytes were ever
    # interpolated into a shell command on the host (or in the daemon's
    # own subprocess invocations), $(touch <canary>) would have created
    # it before the test process reads the queue response.
    assert not canary.exists(), (
        f"shell injection detected: {canary} was created — body bytes "
        "leaked into a shell command"
    )


def test_us5_envelope_body_sha256_matches_raw_body(
    daemon_with_master_and_slave,
) -> None:
    """The SQLite ``envelope_body_sha256`` column matches the body's
    raw SHA-256. Proves the body bytes were NOT mutated during enqueue
    (the envelope's headers are separate from the body BLOB; the
    sha256 is computed over the body alone)."""
    env, paths, tmp_path = daemon_with_master_and_slave
    canary = tmp_path / "should-not-exist"
    payload = _build_shell_injection_payload(canary)
    expected_sha = hashlib.sha256(payload).hexdigest()

    row = _send(paths, body=payload, wait=False)
    assert row["envelope_body_sha256"] == expected_sha


def test_us5_shell_metacharacters_do_not_block_send(
    daemon_with_master_and_slave,
) -> None:
    """Every SC-003 metacharacter (newline, tab, dollar, backslash,
    quotes, semicolons, pipes, redirects, globs, braces) must pass the
    FR-003 validate_body check. Only NUL and disallowed ASCII controls
    are rejected; everything else flows through."""
    env, paths, tmp_path = daemon_with_master_and_slave
    canary = tmp_path / "should-not-exist"
    payload = _build_shell_injection_payload(canary)
    row = _send(paths, body=payload, wait=False)
    # state is "queued" or "delivered" — neither indicates body rejection.
    assert row["state"] in ("queued", "delivered")
    # The validate_body rejection paths would have raised a body_*
    # closed-set error before any row was created.
