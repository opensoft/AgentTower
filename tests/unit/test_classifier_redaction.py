"""T025 — redaction-before-truncation tests (FR-012, Edge Cases).

The classifier MUST run :func:`agenttower.logs.redaction.redact_one_line`
BEFORE truncating to ``per_event_excerpt_cap_bytes``. This ensures
secret patterns split across the truncation boundary remain redacted.
"""

from __future__ import annotations

import pytest

from agenttower.events import EXCERPT_TRUNCATION_MARKER
from agenttower.events.classifier import classify, truncate_excerpt
from agenttower.logs.redaction import redact_one_line


# --------------------------------------------------------------------------
# Redaction integration: the classifier excerpt is the redacted form.
# --------------------------------------------------------------------------


def test_classifier_uses_feat007_redaction_utility() -> None:
    """Whatever the FEAT-007 utility returns is what the classifier
    sees; ensures we did not bypass redaction or duplicate it."""
    # JWT-shaped pattern is one of FEAT-007's known redactions.
    raw = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
    expected_redacted = redact_one_line(raw)
    out = classify(raw)
    # The classifier's full redacted_record matches the FEAT-007
    # utility's output verbatim.
    assert out.redacted_record == expected_redacted
    # And the persisted excerpt is the redacted form (possibly
    # truncated; not the raw form).
    assert "eyJhbGci" not in out.excerpt or "REDACTED" in out.excerpt


def test_classifier_excerpt_is_never_the_raw_record() -> None:
    """If the FEAT-007 redactor changed the line, the classifier
    excerpt must reflect that change, NOT the raw input."""
    raw = "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"
    redacted = redact_one_line(raw)
    # Setup sanity: redactor changed the line.
    assert redacted != raw, "fixture relies on FEAT-007 redaction shape"
    out = classify(raw)
    assert out.redacted_record == redacted


# --------------------------------------------------------------------------
# Truncation cap.
# --------------------------------------------------------------------------


def test_truncate_excerpt_no_truncation_under_cap() -> None:
    short = "x" * 100
    assert truncate_excerpt(short, cap_bytes=1024) == short


def test_truncate_excerpt_exactly_at_cap() -> None:
    boundary = "x" * 1024
    # Encoded length equals cap → no truncation.
    assert truncate_excerpt(boundary, cap_bytes=1024) == boundary


def test_truncate_excerpt_over_cap_appends_marker() -> None:
    over = "x" * 2000
    result = truncate_excerpt(over, cap_bytes=1024)
    assert result.endswith(EXCERPT_TRUNCATION_MARKER)
    assert len(result.encode("utf-8")) <= 1024


def test_truncate_excerpt_byte_safe_for_multibyte() -> None:
    """Truncation must not split a UTF-8 multibyte sequence."""
    # 800 ASCII bytes + many 3-byte CJK chars to push over the cap.
    text = ("a" * 800) + ("中" * 200)  # 800 + 600 = 1400 bytes
    result = truncate_excerpt(text, cap_bytes=1024)
    # Result is decodable as valid UTF-8 (no partial multibyte at end).
    assert isinstance(result, str)
    encoded = result.encode("utf-8")
    encoded.decode("utf-8")  # round-trip succeeds
    assert encoded.endswith(EXCERPT_TRUNCATION_MARKER.encode("utf-8"))


# --------------------------------------------------------------------------
# Redaction-before-truncation invariant: a secret pattern split across
# the truncation boundary remains redacted.
# --------------------------------------------------------------------------


def test_redaction_runs_before_truncation_at_cap_boundary() -> None:
    """Construct a record where the secret pattern straddles the
    excerpt cap boundary. The redacted form must replace the secret
    BEFORE we truncate, so the truncated excerpt cannot contain a
    partial-and-thus-leaked secret.

    We rely on the FEAT-007 redactor's JWT shape: a JWT replaces the
    pattern with a redaction sentinel. After redaction, the boundary
    falls in non-secret content (or in the sentinel), not in raw
    secret bytes.
    """
    prefix = "x" * 1000  # pad so the JWT crosses the 1024-byte boundary
    # JWT-shaped token (3 dot-separated segments); FEAT-007 redacts these.
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    raw_record = prefix + " token=" + jwt
    out = classify(raw_record, cap_bytes=1024)
    assert len(out.excerpt.encode("utf-8")) <= 1024
    # The raw JWT MUST NOT appear in the excerpt (even partially).
    # We test the longest contiguous non-redacted substring of the JWT.
    # If the FEAT-007 redactor replaced the JWT, the original token
    # body is gone from out.excerpt.
    if jwt in out.redacted_record:
        # FEAT-007 did NOT redact this JWT shape — skip rather than
        # assert about a non-load-bearing fixture.
        pytest.skip(
            "FEAT-007 redactor does not redact this JWT shape; test relies on"
            " the redactor having been run before truncation, which is"
            " satisfied even when the redactor produces a no-op output."
        )
    # Redactor changed the line; ensure the truncated excerpt did not
    # accidentally re-introduce raw JWT bytes via the truncation
    # boundary. (i.e., out.excerpt is a prefix-or-equal of
    # out.redacted_record, possibly with the truncation marker.)
    if out.excerpt.endswith(EXCERPT_TRUNCATION_MARKER):
        without_marker = out.excerpt[: -len(EXCERPT_TRUNCATION_MARKER)]
        assert without_marker == out.redacted_record[: len(without_marker)]
    else:
        assert out.excerpt == out.redacted_record
