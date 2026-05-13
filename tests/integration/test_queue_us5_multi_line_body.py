"""T079 — US5 multi-line body acceptance scenarios.

**Test mode**: socket-level integration. The byte-exact tmux paste
(single paste + one Enter rather than per-line send-keys) is verified
at the unit level by the FakeTmuxAdapter call-recording tests
(``test_tmux_adapter_paste_buffer.py``, ``test_delivery_worker_*.py``)
and confirmed end-to-end by the fresh-container E2E.

What this integration test verifies:

1. A 3-line body with embedded tab + 2-byte UTF-8 (em-dash) reaches
   ``delivered`` (or ``queued`` if the worker hasn't caught up yet).
2. The body's SHA-256 stored in the queue row matches the raw body
   bytes — proves the body was NOT mutated through the envelope or
   the BLOB round-trip.
3. The envelope_size_bytes column reflects the SERIALIZED envelope
   (headers + body), not just the raw body length.

The unit-level ``test_envelope_body_invariants.py`` already locks the
FR-003 body validator behavior; this test is the live-pipeline
witness.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from agenttower.socket_api.client import send_request

from . import _daemon_helpers as helpers
from . import _feat009_helpers as f9


_MASTER_ID = "agt_aaaaaaaaaaaa"
_SLAVE_ID = "agt_bbbbbbbbbbbb"

# 3 lines, tab char, em-dash (2-byte UTF-8 0xE2 0x80 0x94).
_MULTI_LINE_BODY: bytes = (
    "line one\tcol2\n"
    "line two — em-dash\n"
    "line three: $VAR and \\backslash\n"
).encode("utf-8")


def _send(
    paths: dict[str, Path], *, body: bytes,
    wait: bool = False, wait_timeout_seconds: float = 5.0,
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
        connect_timeout=2.0, read_timeout=10.0,
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
        yield env, paths
    finally:
        helpers.stop_daemon_if_alive(env)


def test_multi_line_body_reaches_delivered(
    daemon_with_master_and_slave,
) -> None:
    env, paths = daemon_with_master_and_slave
    row = _send(paths, body=_MULTI_LINE_BODY, wait=True, wait_timeout_seconds=15.0)
    assert row["state"] == "delivered", row


def test_multi_line_body_sha256_round_trips_byte_for_byte(
    daemon_with_master_and_slave,
) -> None:
    """The SHA-256 of the raw bytes equals the value stored in
    message_queue.envelope_body_sha256 — proves the body was NOT
    re-encoded or normalized through the BLOB column."""
    env, paths = daemon_with_master_and_slave
    expected_sha = hashlib.sha256(_MULTI_LINE_BODY).hexdigest()
    row = _send(paths, body=_MULTI_LINE_BODY, wait=False)
    assert row["envelope_body_sha256"] == expected_sha


def test_multi_line_envelope_size_includes_headers(
    daemon_with_master_and_slave,
) -> None:
    """FR-004: the size cap and the persisted ``envelope_size_bytes``
    apply to the SERIALIZED envelope (headers + body + blank-line
    separator), not the raw body. Confirms by asserting the persisted
    size is strictly greater than the raw body length."""
    env, paths = daemon_with_master_and_slave
    row = _send(paths, body=_MULTI_LINE_BODY, wait=False)
    raw_len = len(_MULTI_LINE_BODY)
    assert row["envelope_size_bytes"] > raw_len, (
        f"envelope_size_bytes ({row['envelope_size_bytes']}) should be "
        f"strictly greater than raw body length ({raw_len}) once the "
        "FR-001 header set + blank-line separator are prepended"
    )


def test_em_dash_preserved_through_jsonl_audit(
    daemon_with_master_and_slave,
) -> None:
    """The audit row's excerpt is rendered via the FR-047b pipeline
    (decode → redact → whitespace collapse → truncate), so it WON'T be
    byte-identical to the body. But it MUST contain the visible
    em-dash glyph (proving the UTF-8 decode round-tripped). The full
    byte-exact body lives in SQLite (envelope_body BLOB) and is
    asserted by the sha256 test above."""
    import time
    env, paths = daemon_with_master_and_slave
    row = _send(paths, body=_MULTI_LINE_BODY, wait=True, wait_timeout_seconds=15.0)
    msg_id = row["message_id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        records = f9.read_audit_jsonl(paths["events_file"])
        msg_records = [r for r in records if r.get("message_id") == msg_id]
        if any(r["event_type"] == "queue_message_delivered" for r in msg_records):
            break
        time.sleep(0.05)
    records = f9.read_audit_jsonl(paths["events_file"])
    msg_records = [r for r in records if r.get("message_id") == msg_id]
    excerpts = [r.get("excerpt", "") for r in msg_records]
    # At least one audit row carries the em-dash (FR-047b decodes UTF-8
    # first, so 0xE2 0x80 0x94 → '—' before any whitespace collapse).
    assert any("—" in e for e in excerpts), (
        f"em-dash not preserved through audit pipeline: excerpts={excerpts}"
    )
