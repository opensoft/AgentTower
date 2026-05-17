"""T014 — FEAT-010 template parsing + rendering tests.

Covers ``agenttower.routing.template``:

* :func:`validate_template_string` — accepts every whitelisted field,
  rejects unknown fields, honors ``{{`` / ``}}`` literal-brace escape.
* :func:`render_template` — substitutes every whitelisted field,
  routes ``{event_excerpt}`` through the FEAT-007 redactor (test
  seam confirms the raw excerpt never appears in the output), and
  maps FEAT-009 body-validation failures to the matching
  ``RouteTemplateRenderError`` sub-reason per contracts/error-codes.md §3.
"""

from __future__ import annotations

import pytest

from agenttower.routing import route_errors as rerr
from agenttower.routing import template as tpl


# ──────────────────────────────────────────────────────────────────────
# validate_template_string
# ──────────────────────────────────────────────────────────────────────


def test_validate_accepts_every_whitelisted_field() -> None:
    template = (
        "{event_id} {event_type} {source_agent_id} {source_label} "
        "{source_role} {source_capability} {event_excerpt} {observed_at}"
    )
    used = tpl.validate_template_string(template)
    assert set(used) == tpl.ALLOWED_TEMPLATE_FIELDS


def test_validate_accepts_no_placeholders() -> None:
    """A template with no placeholders is valid (operator may want a
    static prompt)."""
    used = tpl.validate_template_string("plain static prompt")
    assert used == []


def test_validate_rejects_unknown_field() -> None:
    with pytest.raises(rerr.RouteTemplateInvalid, match="unknown field"):
        tpl.validate_template_string("hello {not_a_real_field}")


def test_validate_rejects_empty_template() -> None:
    with pytest.raises(rerr.RouteTemplateInvalid, match="non-empty string"):
        tpl.validate_template_string("")


def test_validate_treats_double_braces_as_literal() -> None:
    """``{{`` / ``}}`` are str.format-style escapes for literal braces
    and MUST NOT be parsed as placeholders."""
    used = tpl.validate_template_string("literal {{not_a_field}} brace")
    assert used == []


def test_validate_mixed_literal_and_placeholder() -> None:
    used = tpl.validate_template_string(
        "literal {{x}} plus placeholder {event_id}"
    )
    assert used == ["event_id"]


# ──────────────────────────────────────────────────────────────────────
# extract_template_fields
# ──────────────────────────────────────────────────────────────────────


def test_extract_returns_unique_placeholders() -> None:
    fields = tpl.extract_template_fields(
        "{event_id} and again {event_id} and {event_type}"
    )
    assert fields == {"event_id", "event_type"}


# ──────────────────────────────────────────────────────────────────────
# render_template — happy path
# ──────────────────────────────────────────────────────────────────────


def _identity_redactor(line: str) -> str:
    """Test seam: no redaction applied."""
    return line


def _trapping_redactor(line: str) -> str:
    """Test seam: replace every char with X so we can prove the
    redactor was actually invoked on {event_excerpt}."""
    return "X" * len(line)


def test_render_substitutes_every_whitelisted_field() -> None:
    template = (
        "id={event_id} type={event_type} "
        "src_id={source_agent_id} src_label={source_label} "
        "src_role={source_role} src_cap={source_capability} "
        "obs={observed_at} body={event_excerpt}"
    )
    rendered = tpl.render_template(
        template,
        fields={
            "event_id": 42,
            "event_type": "waiting_for_input",
            "source_agent_id": "agt_a1b2c3d4e5f6",
            "source_label": "slave-1",
            "source_role": "slave",
            "source_capability": "codex",
            "observed_at": "2026-05-17T00:00:00.000Z",
        },
        raw_event_excerpt="please respond",
        redactor=_identity_redactor,
    )
    assert isinstance(rendered, bytes)
    text = rendered.decode("utf-8")
    assert "id=42" in text
    assert "type=waiting_for_input" in text
    assert "src_id=agt_a1b2c3d4e5f6" in text
    assert "src_label=slave-1" in text
    assert "src_role=slave" in text
    assert "src_cap=codex" in text
    assert "obs=2026-05-17T00:00:00.000Z" in text
    assert "body=please respond" in text


def test_render_with_no_placeholders_returns_template_bytes() -> None:
    rendered = tpl.render_template(
        "plain static prompt",
        fields={},
        raw_event_excerpt="ignored",
    )
    assert rendered == b"plain static prompt"


def test_render_honors_double_brace_literal_escape() -> None:
    rendered = tpl.render_template(
        "literal {{event_id}} not substituted; placeholder {event_id} is",
        fields={"event_id": 7},
        raw_event_excerpt="ignored",
    )
    assert (
        rendered.decode("utf-8")
        == "literal {event_id} not substituted; placeholder 7 is"
    )


# ──────────────────────────────────────────────────────────────────────
# render_template — FR-026 redaction enforcement
# ──────────────────────────────────────────────────────────────────────


def test_render_routes_event_excerpt_through_redactor() -> None:
    """FR-026: the raw excerpt MUST NEVER appear in the rendered body
    when ``{event_excerpt}`` is referenced. The test redactor replaces
    every char with X — if it weren't applied, "secret" would survive
    in the output."""
    rendered = tpl.render_template(
        "leaked? {event_excerpt}",
        fields={},
        raw_event_excerpt="secret-token-abc",
        redactor=_trapping_redactor,
    )
    text = rendered.decode("utf-8")
    assert "secret" not in text
    assert "X" in text


def test_render_skips_redactor_when_excerpt_not_referenced() -> None:
    """If the template doesn't use ``{event_excerpt}``, the redactor
    is not invoked — even a misbehaving redactor doesn't block
    rendering."""
    def _exploding_redactor(line: str) -> str:
        raise RuntimeError("redactor should NOT have been called")

    rendered = tpl.render_template(
        "no excerpt: {event_id}",
        fields={"event_id": 1},
        raw_event_excerpt="ignored",
        redactor=_exploding_redactor,
    )
    assert rendered == b"no excerpt: 1"


def test_render_handles_redactor_failure_placeholder_in_body() -> None:
    """When the redactor fails, render_excerpt returns a fixed
    placeholder string. That placeholder substitutes cleanly into the
    body — no exception, no raw-text leak."""
    def _exploding_redactor(line: str) -> str:
        raise RuntimeError("simulated redactor failure")

    rendered = tpl.render_template(
        "result: {event_excerpt}",
        fields={},
        raw_event_excerpt="secret-token",
        redactor=_exploding_redactor,
    )
    text = rendered.decode("utf-8")
    # Raw secret MUST NEVER survive even when the redactor fails.
    assert "secret" not in text
    # The placeholder appears verbatim (consumers see the failure
    # signal in the body itself).
    assert "[excerpt unavailable: redactor failed]" in text


# ──────────────────────────────────────────────────────────────────────
# render_template — body-validation mapping (FEAT-009 → sub_reasons)
# ──────────────────────────────────────────────────────────────────────


def test_render_maps_body_empty_to_sub_reason() -> None:
    with pytest.raises(rerr.RouteTemplateRenderError) as info:
        tpl.render_template(
            "",  # empty template — won't pass validate_template_string,
                 # but render is sometimes called without prior validate
                 # (defense in depth).
            fields={},
            raw_event_excerpt="",
        )
    assert info.value.sub_reason == rerr.BODY_EMPTY


def test_render_maps_invalid_chars_to_sub_reason() -> None:
    """A rendered body containing a NUL byte MUST fail with
    sub_reason=body_invalid_chars (FR-027 + FEAT-009 inheritance)."""
    with pytest.raises(rerr.RouteTemplateRenderError) as info:
        tpl.render_template(
            "before\x00after",
            fields={},
            raw_event_excerpt="ignored",
        )
    assert info.value.sub_reason == rerr.BODY_INVALID_CHARS


def test_render_uses_fields_value_str_repr_for_non_string_types() -> None:
    """``fields`` may contain int / bool / etc. — render stringifies via
    ``str()``. This makes ``{event_id}`` (an int on EventRow) work
    without callers having to pre-convert."""
    rendered = tpl.render_template(
        "{event_id}",
        fields={"event_id": 12345},
        raw_event_excerpt="",
    )
    assert rendered == b"12345"
