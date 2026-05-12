"""T081 — Envelope body invariants (FR-003 / FR-004 / SC-009).

Asserts that :func:`routing.envelope.validate_body` and
:func:`routing.envelope.serialize_and_check_size` reject the four
body-invalid forms cheaply (no I/O, well under 100 ms each) and that
the size cap is applied to the SERIALIZED envelope rather than the raw
body bytes.
"""

from __future__ import annotations

import time

import pytest

from agenttower.routing.envelope import (
    BodyValidationError,
    EnvelopeIdentity,
    render_envelope,
    serialize_and_check_size,
    validate_body,
)


_SENDER = EnvelopeIdentity(
    agent_id="agt_aaaaaaaaaaaa",
    label="queen",
    role="master",
    capability="codex",
)
_TARGET = EnvelopeIdentity(
    agent_id="agt_bbbbbbbbbbbb",
    label="worker-1",
    role="slave",
    capability="codex",
)
_MSG_ID = "11111111-2222-4333-8444-555555555555"


# ──────────────────────────────────────────────────────────────────────
# 1. validate_body rejects the four body-invalid forms (FR-003)
# ──────────────────────────────────────────────────────────────────────


def test_validate_body_rejects_empty_with_body_empty() -> None:
    with pytest.raises(BodyValidationError) as exc:
        validate_body(b"")
    assert exc.value.code == "body_empty"


def test_validate_body_rejects_invalid_utf8_with_body_invalid_encoding() -> None:
    # Lone continuation byte: 0x80 is not a valid start-of-sequence.
    with pytest.raises(BodyValidationError) as exc:
        validate_body(b"hello \x80 world")
    assert exc.value.code == "body_invalid_encoding"


def test_validate_body_rejects_nul_byte_with_body_invalid_chars() -> None:
    with pytest.raises(BodyValidationError) as exc:
        validate_body(b"hello\x00world")
    assert exc.value.code == "body_invalid_chars"


def test_validate_body_rejects_other_disallowed_controls_with_body_invalid_chars() -> None:
    # 0x07 is BEL; FR-003 only allows \n (0x0a) and \t (0x09) among
    # ASCII controls.
    with pytest.raises(BodyValidationError) as exc:
        validate_body(b"hello\x07world")
    assert exc.value.code == "body_invalid_chars"


def test_validate_body_accepts_newline_and_tab() -> None:
    # No exception expected.
    validate_body(b"line1\nline2\tcol2\n")
    validate_body("héllo — em-dash".encode("utf-8"))


def test_validate_body_rejects_non_bytes_type_with_body_invalid_encoding() -> None:
    # Defense in depth: a non-bytes input (e.g., str) is rejected as
    # body_invalid_encoding rather than crashing inside the validator.
    with pytest.raises(BodyValidationError) as exc:
        validate_body("hello")  # type: ignore[arg-type]
    assert exc.value.code == "body_invalid_encoding"


# ──────────────────────────────────────────────────────────────────────
# 2. serialize_and_check_size applies the cap to the SERIALIZED envelope
# ──────────────────────────────────────────────────────────────────────


def test_size_cap_applies_to_serialized_envelope_not_raw_body() -> None:
    """FR-004: the cap is on the SERIALIZED envelope (headers + body),
    not the raw body. With a tight cap, a body that JUST fits raw
    still exceeds when the headers are prepended."""
    # Render once to measure the header overhead.
    rendered_empty = render_envelope(_MSG_ID, _SENDER, _TARGET, b"x")
    header_overhead = len(rendered_empty) - 1  # subtract the 'x'

    # Build a body that, raw, would fit a 100-byte cap but serialized
    # would exceed it (the headers alone are well over 100 bytes).
    body = b"a" * 90
    assert len(body) < 100
    assert header_overhead + len(body) > 100

    with pytest.raises(BodyValidationError) as exc:
        serialize_and_check_size(
            _MSG_ID, _SENDER, _TARGET, body, max_bytes=100,
        )
    assert exc.value.code == "body_too_large"


def test_size_cap_passes_when_serialized_envelope_under_cap() -> None:
    """Sanity: a small body comfortably under the cap returns the
    rendered envelope bytes."""
    body = b"hi"
    rendered = serialize_and_check_size(
        _MSG_ID, _SENDER, _TARGET, body, max_bytes=65_536,
    )
    assert isinstance(rendered, bytes)
    assert rendered.endswith(body)


def test_size_cap_uses_default_when_not_supplied() -> None:
    """The default cap (65 536 bytes) is broad enough for typical
    prompts — a 1 KiB body succeeds."""
    body = b"x" * 1024
    rendered = serialize_and_check_size(_MSG_ID, _SENDER, _TARGET, body)
    assert isinstance(rendered, bytes)
    assert len(rendered) < 65_536


# ──────────────────────────────────────────────────────────────────────
# 3. Cheap-and-deterministic: every rejection completes well under 100 ms
# ──────────────────────────────────────────────────────────────────────


def test_validate_body_rejection_under_100ms() -> None:
    """SC-009: validation rejects bad bodies in well under 100 ms.
    Tightens the budget to 10 ms — validate_body is pure CPU and
    should complete in microseconds. We use 10 ms here as a generous
    upper bound that still catches accidental I/O regressions."""
    samples = [
        b"",
        b"\x80",
        b"hello\x00world",
        b"hello\x07world",
    ]
    deadline_seconds = 0.010
    for sample in samples:
        start = time.perf_counter()
        try:
            validate_body(sample)
        except BodyValidationError:
            pass
        elapsed = time.perf_counter() - start
        assert elapsed < deadline_seconds, (
            f"validate_body({sample!r}) took {elapsed*1000:.2f} ms "
            f"(budget: {deadline_seconds*1000:.0f} ms)"
        )


def test_size_cap_rejection_under_100ms() -> None:
    """SC-009: body_too_large rejection is also cheap.
    A 1 MiB body exceeds the default cap and should be rejected in
    well under 100 ms — the size check is a single length comparison
    after rendering, so the rejection time is dominated by the
    rendering itself, which is still cheap."""
    body = b"x" * (1024 * 1024)  # 1 MiB
    start = time.perf_counter()
    try:
        serialize_and_check_size(_MSG_ID, _SENDER, _TARGET, body)
    except BodyValidationError as exc:
        assert exc.code == "body_too_large"
    elapsed = time.perf_counter() - start
    assert elapsed < 0.100, (
        f"body_too_large rejection took {elapsed*1000:.2f} ms (budget: 100 ms)"
    )


# ──────────────────────────────────────────────────────────────────────
# 4. Rejection path emits NO SQLite state — caller-side guarantee
# ──────────────────────────────────────────────────────────────────────


def test_validate_body_is_pure_function_no_side_effects() -> None:
    """validate_body is a pure function — it takes bytes and returns
    None or raises. Verifies that the validator has no global state
    (no module-level counters, caches, etc.). Calling it twice with
    the same input yields the same outcome."""
    body = b"hello\x00world"
    with pytest.raises(BodyValidationError) as exc1:
        validate_body(body)
    with pytest.raises(BodyValidationError) as exc2:
        validate_body(body)
    assert exc1.value.code == exc2.value.code == "body_invalid_chars"


def test_size_cap_invokes_validate_body_first() -> None:
    """Empty body is rejected with body_empty (NOT body_too_large)
    even if max_bytes is small — proves serialize_and_check_size runs
    validate_body BEFORE the size check (so a malformed body fails
    fast without rendering)."""
    with pytest.raises(BodyValidationError) as exc:
        serialize_and_check_size(_MSG_ID, _SENDER, _TARGET, b"", max_bytes=10)
    assert exc.value.code == "body_empty"
