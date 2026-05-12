"""T021 — FEAT-009 excerpt pipeline tests.

FR-047b + Clarifications Q3 of 2026-05-11 + Group-A walk Q3 of 2026-05-12.

Pipeline (under test):

1. UTF-8 decode body bytes.
2. Apply FEAT-007 redactor.
3. Collapse ``\\s+`` to a single space.
4. Truncate at cap (default 240).
5. Append ``…`` only if step (4) discarded characters.

Failure path (Group-A walk Q3): on any redactor exception, return the
fixed placeholder ``[excerpt unavailable: redactor failed]``. The raw
body MUST NEVER appear as a fallback.
"""

from __future__ import annotations

import pytest

from agenttower.routing.excerpt import (
    DEFAULT_EXCERPT_CAP,
    ELLIPSIS,
    REDACTOR_FAILED_PLACEHOLDER,
    render_excerpt,
)


# Identity redactor: returns its input verbatim. Useful for isolating
# the whitespace-collapse + truncation steps from FEAT-007's behaviour.
def _identity(line: str) -> str:
    return line


# ──────────────────────────────────────────────────────────────────────
# Happy-path: ordering, whitespace, truncation
# ──────────────────────────────────────────────────────────────────────


def test_render_excerpt_identity_redactor_returns_body() -> None:
    assert render_excerpt(b"do thing", _identity) == "do thing"


def test_render_excerpt_decodes_utf8() -> None:
    """Multi-byte UTF-8 (e.g. em-dash, U+2014) round-trips."""
    assert render_excerpt("hello — world".encode("utf-8"), _identity) == "hello — world"


def test_render_excerpt_collapses_newlines_to_single_space() -> None:
    body = b"line one\nline two\nline three"
    assert render_excerpt(body, _identity) == "line one line two line three"


def test_render_excerpt_collapses_tabs_to_single_space() -> None:
    body = b"col1\tcol2\tcol3"
    assert render_excerpt(body, _identity) == "col1 col2 col3"


def test_render_excerpt_collapses_mixed_whitespace_runs() -> None:
    """Multiple whitespace chars in a row → single ASCII space."""
    body = b"a  \t\n   b\r\n\tc"
    assert render_excerpt(body, _identity) == "a b c"


def test_render_excerpt_preserves_internal_punctuation_and_unicode() -> None:
    body = b"prompt: 'do thing' & wait $X; em\xe2\x80\x94dash"
    out = render_excerpt(body, _identity)
    # Identity redactor passes the bytes through; only whitespace
    # normalization runs.
    assert out == "prompt: 'do thing' & wait $X; em—dash"


# ──────────────────────────────────────────────────────────────────────
# Step 4 + 5: truncation behaviour
# ──────────────────────────────────────────────────────────────────────


def test_render_excerpt_no_truncation_when_at_or_below_cap() -> None:
    body = ("x" * DEFAULT_EXCERPT_CAP).encode("utf-8")
    out = render_excerpt(body, _identity)
    assert out == "x" * DEFAULT_EXCERPT_CAP
    assert not out.endswith(ELLIPSIS)


def test_render_excerpt_truncates_when_above_cap_and_appends_ellipsis() -> None:
    body = ("x" * (DEFAULT_EXCERPT_CAP + 1)).encode("utf-8")
    out = render_excerpt(body, _identity)
    assert out == "x" * DEFAULT_EXCERPT_CAP + ELLIPSIS
    assert len(out) == DEFAULT_EXCERPT_CAP + 1


def test_render_excerpt_truncation_marker_only_when_truncation_occurred() -> None:
    # Exactly at cap → no ellipsis.
    body_eq = ("a" * DEFAULT_EXCERPT_CAP).encode("utf-8")
    assert not render_excerpt(body_eq, _identity).endswith(ELLIPSIS)
    # One over cap → ellipsis.
    body_over = ("a" * (DEFAULT_EXCERPT_CAP + 1)).encode("utf-8")
    assert render_excerpt(body_over, _identity).endswith(ELLIPSIS)


def test_render_excerpt_custom_cap_is_respected() -> None:
    body = b"hello world this is a long body"
    out = render_excerpt(body, _identity, cap=11)
    assert out == "hello world" + ELLIPSIS


def test_render_excerpt_cap_applies_after_whitespace_collapse_not_before() -> None:
    """Truncation counts characters in the collapsed form, not the raw body."""
    # The raw body is 30 chars but collapses to 6 chars ("a b c d").
    body = b"a    \n\t   b    \n   c\n\nd"
    out = render_excerpt(body, _identity, cap=100)
    assert out == "a b c d"  # Well under the cap; no ellipsis.


def test_render_excerpt_empty_body_returns_empty_string() -> None:
    assert render_excerpt(b"", _identity) == ""


def test_render_excerpt_whitespace_only_body_collapses_to_single_space() -> None:
    """``\\s+`` matches the entire body → one ASCII space."""
    body = b"\n\n\t   \r\n "
    assert render_excerpt(body, _identity) == " "


# ──────────────────────────────────────────────────────────────────────
# Step 1+2: redactor ordering + idempotence
# ──────────────────────────────────────────────────────────────────────


def test_render_excerpt_redactor_runs_before_whitespace_collapse() -> None:
    """If the redactor would emit whitespace, the collapse step still
    collapses that whitespace — so redaction MUST run first."""

    def insert_spaces(line: str) -> str:
        # Redactor that intentionally introduces a multi-space run; the
        # pipeline should collapse it.
        return line.replace("X", "  Y  ")

    body = b"prefix X suffix"
    out = render_excerpt(body, insert_spaces)
    assert out == "prefix Y suffix"


def test_render_excerpt_is_deterministic_idempotent() -> None:
    """Same input → same output, always."""
    body = b"do thing\n   with spaces"
    out_a = render_excerpt(body, _identity)
    out_b = render_excerpt(body, _identity)
    out_c = render_excerpt(body, _identity)
    assert out_a == out_b == out_c


def test_render_excerpt_default_redactor_is_feat007_redact_one_line() -> None:
    """Without an explicit redactor, the default is
    :func:`agenttower.logs.redaction.redact_one_line`. Smoke-test that
    a value the redactor knows how to redact (a bearer-token-like
    pattern) is redacted in the excerpt."""
    # FEAT-007 redacts strings looking like a sk-... bearer token.
    body = b"please use sk-abcdefghijklmnopqrstuvwxyz1234"
    out = render_excerpt(body)  # no redactor → uses FEAT-007
    # We don't assert the exact redacted form (that's FEAT-007's contract);
    # we assert the sensitive substring is NOT present.
    assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in out


# ──────────────────────────────────────────────────────────────────────
# Group-A walk Q3: redactor-failure fallback
# ──────────────────────────────────────────────────────────────────────


def test_render_excerpt_redactor_failure_returns_fixed_placeholder() -> None:
    """If the redactor raises, the pipeline substitutes the fixed
    placeholder. The raw body MUST NEVER leak."""

    def boom(line: str) -> str:
        raise ValueError("simulated redactor failure")

    body = b"sensitive token sk-secret"
    out = render_excerpt(body, boom)
    assert out == REDACTOR_FAILED_PLACEHOLDER
    # Critical safety property: the raw body's distinctive substring
    # MUST NOT appear in the fallback.
    assert "sensitive" not in out
    assert "sk-secret" not in out


def test_render_excerpt_redactor_failure_placeholder_fits_in_cap() -> None:
    """The placeholder is shorter than the default cap so it's never
    truncated."""
    assert len(REDACTOR_FAILED_PLACEHOLDER) < DEFAULT_EXCERPT_CAP


def test_render_excerpt_redactor_failure_does_not_apply_whitespace_collapse() -> None:
    """The placeholder is returned verbatim — steps 3–5 are skipped on
    the failure path."""

    def boom(line: str) -> str:
        raise RuntimeError("oops")

    out = render_excerpt(b"x", boom)
    assert out == REDACTOR_FAILED_PLACEHOLDER  # exactly, no trimming


@pytest.mark.parametrize(
    "exc_class",
    [ValueError, RuntimeError, RecursionError, MemoryError, OSError],
)
def test_render_excerpt_catches_broad_exception_classes(exc_class: type) -> None:
    """Any Exception subclass must be caught — not just regex errors."""

    def boom(line: str) -> str:
        raise exc_class("boom")

    assert render_excerpt(b"x", boom) == REDACTOR_FAILED_PLACEHOLDER


# ──────────────────────────────────────────────────────────────────────
# Edge: UTF-8 decode failure should also use the safe fallback
# ──────────────────────────────────────────────────────────────────────


def test_render_excerpt_invalid_utf8_falls_back_to_placeholder() -> None:
    """FR-003 should reject invalid UTF-8 at submit time so this code
    path is defensive — but if a malformed body somehow reaches
    render_excerpt, the safe-by-default fallback must trigger (not
    crash the worker)."""
    invalid_utf8 = b"\xff\xfe\xfd"  # Not valid UTF-8
    out = render_excerpt(invalid_utf8, _identity)
    assert out == REDACTOR_FAILED_PLACEHOLDER
