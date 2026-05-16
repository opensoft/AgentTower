"""T023 — FEAT-009 envelope rendering and body validation tests.

Covers FR-001 (envelope header shape), FR-002 (blank-line separator +
body verbatim), FR-003 (body validation rejections), FR-004 (size cap on
serialized envelope, not raw body).
"""

from __future__ import annotations

import pytest

from agenttower.routing.envelope import (
    DEFAULT_ENVELOPE_BODY_MAX_BYTES,
    BodyValidationError,
    EnvelopeIdentity,
    render_envelope,
    serialize_and_check_size,
    validate_body,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


_QUEEN = EnvelopeIdentity(
    agent_id="agt_aaaaaa111111",
    label="queen",
    role="master",
    capability="plan",
)
_WORKER = EnvelopeIdentity(
    agent_id="agt_bbbbbb222222",
    label="worker-1",
    role="slave",
    capability="implement",
)
_MSG_ID = "12345678-1234-4234-8234-123456789012"


# ──────────────────────────────────────────────────────────────────────
# FR-001 / FR-002 — envelope shape
# ──────────────────────────────────────────────────────────────────────


def test_render_envelope_contains_all_six_headers_in_order() -> None:
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"do thing").decode("utf-8")
    lines = out.split("\n")
    assert lines[0] == f"Message-Id: {_MSG_ID}"
    assert lines[1].startswith("From: ")
    assert lines[2].startswith("To: ")
    assert lines[3] == "Type: prompt"
    assert lines[4] == "Priority: normal"
    assert lines[5] == "Requires-Reply: yes"


def test_render_envelope_includes_message_id() -> None:
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"x").decode("utf-8")
    assert f"Message-Id: {_MSG_ID}\n" in out


def test_render_envelope_from_includes_agent_id_label_role_capability() -> None:
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"x").decode("utf-8")
    assert 'From: agt_aaaaaa111111 "queen" master [capability=plan]' in out


def test_render_envelope_to_includes_agent_id_label_role_capability() -> None:
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"x").decode("utf-8")
    assert 'To: agt_bbbbbb222222 "worker-1" slave [capability=implement]' in out


def test_render_envelope_omits_capability_bracket_when_none() -> None:
    sender_no_cap = EnvelopeIdentity(
        agent_id=_QUEEN.agent_id, label=_QUEEN.label,
        role=_QUEEN.role, capability=None,
    )
    out = render_envelope(_MSG_ID, sender_no_cap, _WORKER, b"x").decode("utf-8")
    # No capability bracket on the From line, but To still has its bracket.
    assert 'From: agt_aaaaaa111111 "queen" master\n' in out
    assert "capability=" in out  # the To line still has it


def test_render_envelope_omits_capability_bracket_when_empty_string() -> None:
    """Capability = "" is treated identically to None — no bracket."""
    sender = EnvelopeIdentity(
        agent_id=_QUEEN.agent_id, label=_QUEEN.label,
        role=_QUEEN.role, capability="",
    )
    out = render_envelope(_MSG_ID, sender, _WORKER, b"x").decode("utf-8")
    assert 'From: agt_aaaaaa111111 "queen" master\n' in out


def test_render_envelope_blank_line_separator_is_exactly_one() -> None:
    """FR-002: a single blank line (``\\n\\n``) separates the headers
    from the body. The body is consumed verbatim to end-of-envelope."""
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"body")
    headers, _, rest = out.partition(b"\n\n")
    assert rest == b"body"
    # Ensure no second \n\n (i.e., body section is verbatim).
    assert b"\n\n" not in rest


def test_render_envelope_body_is_byte_exact() -> None:
    """The body bytes appear in the rendered envelope verbatim — no
    encoding, escaping, or whitespace normalization."""
    body = b"line1\nline2\t\xe2\x80\x94em-dash"
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, body)
    assert out.endswith(body)


def test_render_envelope_multi_line_body_preserved() -> None:
    body = b"line1\nline2\nline3"
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, body)
    # Body should appear AFTER the blank-line separator, verbatim.
    _, _, after_blank = out.partition(b"\n\n")
    assert after_blank == body


def test_render_envelope_with_empty_body_still_renders_headers() -> None:
    """`render_envelope` does NOT validate the body — caller controls.
    With an empty body, the rendered envelope still has the blank-line
    separator and ends there."""
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"")
    assert out.endswith(b"\n\n")


# ──────────────────────────────────────────────────────────────────────
# FR-003 — body validation
# ──────────────────────────────────────────────────────────────────────


def test_validate_body_accepts_simple_ascii() -> None:
    validate_body(b"do thing")  # no exception


def test_validate_body_accepts_newline_and_tab() -> None:
    validate_body(b"line1\nline2\tcol")


def test_validate_body_accepts_multibyte_utf8() -> None:
    validate_body("em — dash and 日本語".encode("utf-8"))


def test_validate_body_rejects_empty_with_body_empty() -> None:
    with pytest.raises(BodyValidationError) as info:
        validate_body(b"")
    assert info.value.code == "body_empty"


def test_validate_body_rejects_non_bytes_input() -> None:
    """Defensive: a caller passing a str (not bytes) is a programmer
    error, but we surface the closed-set code rather than TypeError."""
    with pytest.raises(BodyValidationError) as info:
        validate_body("do thing")  # type: ignore[arg-type]
    assert info.value.code == "body_invalid_encoding"


def test_validate_body_rejects_invalid_utf8_with_body_invalid_encoding() -> None:
    invalid = b"\xff\xfe\xfd"
    with pytest.raises(BodyValidationError) as info:
        validate_body(invalid)
    assert info.value.code == "body_invalid_encoding"


def test_validate_body_rejects_nul_byte_with_body_invalid_chars() -> None:
    with pytest.raises(BodyValidationError) as info:
        validate_body(b"valid prefix\x00with nul")
    assert info.value.code == "body_invalid_chars"


@pytest.mark.parametrize(
    "control_byte",
    [0x01, 0x02, 0x07, 0x08, 0x0B, 0x0C, 0x0D, 0x1B, 0x1F, 0x7F],
)
def test_validate_body_rejects_other_ascii_controls(control_byte: int) -> None:
    """Every ASCII control byte 0x00-0x1F (except \\t=0x09, \\n=0x0a) plus
    0x7F (DEL) is rejected per FR-003."""
    body = b"prefix" + bytes([control_byte]) + b"suffix"
    with pytest.raises(BodyValidationError) as info:
        validate_body(body)
    assert info.value.code == "body_invalid_chars"


def test_validate_body_accepts_lone_tab() -> None:
    validate_body(b"\t")  # \t alone is allowed


def test_validate_body_accepts_lone_newline() -> None:
    validate_body(b"\n")  # \n alone is allowed


def test_validate_body_rejects_high_unicode_with_nul_within_multibyte_sequence() -> None:
    """A valid-UTF-8 body with embedded NUL must still be rejected.
    NUL is valid UTF-8 but FR-003 forbids it explicitly."""
    body = "before\x00after".encode("utf-8")
    with pytest.raises(BodyValidationError) as info:
        validate_body(body)
    assert info.value.code == "body_invalid_chars"


# ──────────────────────────────────────────────────────────────────────
# FR-004 — size cap on serialized envelope
# ──────────────────────────────────────────────────────────────────────


def test_serialize_and_check_size_returns_rendered_bytes_on_success() -> None:
    out = serialize_and_check_size(_MSG_ID, _QUEEN, _WORKER, b"do thing")
    # Smoke: looks like an envelope.
    assert b"Message-Id:" in out
    assert out.endswith(b"do thing")


def test_serialize_and_check_size_runs_validate_body_first() -> None:
    """An invalid body raises BEFORE size is checked."""
    with pytest.raises(BodyValidationError) as info:
        serialize_and_check_size(_MSG_ID, _QUEEN, _WORKER, b"")
    assert info.value.code == "body_empty"


def test_serialize_and_check_size_enforces_cap_on_serialized_envelope() -> None:
    """Per FR-004: the cap is on headers + body, not raw body alone.
    Therefore a body slightly under the cap can still overflow once
    headers are added."""
    # Build a body whose RAW size is well under the cap but whose
    # SERIALIZED envelope exceeds it.
    cap = 1024
    # Calculate header length for these specific identities.
    sample = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"")
    header_len = len(sample)
    # Body just barely too big when headers are added.
    body = b"x" * (cap - header_len + 1)
    with pytest.raises(BodyValidationError) as info:
        serialize_and_check_size(_MSG_ID, _QUEEN, _WORKER, body, max_bytes=cap)
    assert info.value.code == "body_too_large"


def test_serialize_and_check_size_accepts_at_cap() -> None:
    """A body that produces an envelope EXACTLY at the cap is accepted
    (off-by-one: cap is inclusive)."""
    cap = 1024
    sample = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"")
    header_len = len(sample)
    body = b"x" * (cap - header_len)
    out = serialize_and_check_size(_MSG_ID, _QUEEN, _WORKER, body, max_bytes=cap)
    assert len(out) == cap


def test_serialize_and_check_size_default_cap_is_64_kib() -> None:
    """Default ``DEFAULT_ENVELOPE_BODY_MAX_BYTES`` is 64 KiB per
    Assumptions "Body size cap"."""
    assert DEFAULT_ENVELOPE_BODY_MAX_BYTES == 65_536
    # A 65 KiB body comfortably fits.
    body = b"x" * 65_000
    out = serialize_and_check_size(_MSG_ID, _QUEEN, _WORKER, body)
    assert len(out) > 65_000  # rendered envelope is body + headers


def test_serialize_and_check_size_rejects_header_stuffing_attack() -> None:
    """Defense: an attacker who somehow inflated header text (impossible
    here because we control header rendering) can't bypass the cap
    because the cap is on the SERIALIZED envelope, not the raw body."""
    # The actual attack vector for "header stuffing" doesn't exist
    # because the caller controls neither the headers nor the
    # rendering; this test is a smoke for the invariant.
    cap = 200  # tiny cap
    body = b"x" * 50  # raw body well under cap
    # The serialized envelope is body + ~150 bytes of headers; with a
    # 200-byte cap, this could go either way depending on the identity
    # length. Pick an identity with a long label/capability to push
    # over.
    long_id = EnvelopeIdentity(
        agent_id="agt_cccccc333333",
        label="a-long-label-pushes-envelope-size",
        role="slave",
        capability="a-long-capability-string",
    )
    with pytest.raises(BodyValidationError) as info:
        serialize_and_check_size(_MSG_ID, _QUEEN, long_id, body, max_bytes=cap)
    assert info.value.code == "body_too_large"


# ──────────────────────────────────────────────────────────────────────
# Integration: render + validate ordering invariant
# ──────────────────────────────────────────────────────────────────────


def test_render_envelope_does_not_validate_body() -> None:
    """`render_envelope` is pure — passing it an invalid body returns
    a malformed but rendered envelope. Body validation MUST be called
    separately (or via `serialize_and_check_size`)."""
    # An empty body + render → still produces a valid-looking envelope
    # ending in the blank-line separator.
    out = render_envelope(_MSG_ID, _QUEEN, _WORKER, b"")
    assert out.endswith(b"\n\n")
    # No exception was raised.
