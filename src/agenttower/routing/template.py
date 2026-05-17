"""FEAT-010 template parsing and rendering (spec §FR-008 / §FR-025..028).

Two public entry points:

* :func:`validate_template_string` — parse-time check that every
  ``{<field>}`` placeholder names a field from the FR-008 closed
  whitelist. Called by ``routes_service.add_route`` BEFORE the row
  is INSERTed, so an unknown-field template fails at route-add time
  (Story 6 #2), not at fire time.

* :func:`render_template` — render-time substitution. The seven
  raw-pass fields are substituted as-is from the supplied mapping;
  ``{event_excerpt}`` is routed through the FEAT-007 redactor (via
  :func:`agenttower.routing.excerpt.render_excerpt`) BEFORE
  substitution per FR-026. The result is UTF-8-encoded and run
  through FEAT-009's :func:`agenttower.routing.envelope.validate_body`
  so any body that escapes the envelope-validation contract
  (FR-003 / FR-004 of FEAT-009) becomes a closed-set
  ``RouteTemplateRenderError(sub_reason=...)`` instead of a
  silent partial render.

The template grammar is the closed whitelist of single-pass
``{field}`` substitutions per research §R9. Specifically:

* No nested interpolation (a substituted value containing ``{field}``
  is NOT re-substituted).
* No expressions, function calls, format-spec syntax.
* Literal braces are written as ``{{`` and ``}}`` per Python's
  ``str.format_map`` convention (single-pass, predictable).

All functions are pure: no SQLite, no I/O.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Final, Mapping

from agenttower.routing.envelope import BodyValidationError, validate_body
from agenttower.routing.excerpt import render_excerpt
from agenttower.routing.route_errors import (
    BODY_EMPTY,
    BODY_INVALID_CHARS,
    BODY_INVALID_ENCODING,
    BODY_TOO_LARGE,
    MISSING_FIELD,
    RouteTemplateInvalid,
    RouteTemplateRenderError,
)

_log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# FR-008 whitelist
# ──────────────────────────────────────────────────────────────────────


_EVENT_EXCERPT_FIELD: Final[str] = "event_excerpt"

ALLOWED_TEMPLATE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "event_id",
        "event_type",
        "source_agent_id",
        "source_label",
        "source_role",
        "source_capability",
        _EVENT_EXCERPT_FIELD,
        "observed_at",
    }
)
"""The eight closed-set template fields from FR-008."""

# Match ``{<field>}`` — but NOT ``{{`` (literal-brace escape per
# str.format_map). The lookahead/behind keeps doubled braces out.
# The captured group is the field name; whitespace is NOT permitted.
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})"
)


# ──────────────────────────────────────────────────────────────────────
# Parse-time validation
# ──────────────────────────────────────────────────────────────────────


def extract_template_fields(template: str) -> set[str]:
    """Return the set of ``{<field>}`` placeholder names found in
    ``template`` (without the surrounding braces). Literal ``{{`` /
    ``}}`` pairs are NOT placeholders and are excluded.

    Pure helper used by :func:`validate_template_string`; also useful
    for diagnostics.
    """
    return set(_PLACEHOLDER_RE.findall(template))


def validate_template_string(template: str) -> list[str]:
    """Verify ``template`` references only fields in :data:`ALLOWED_TEMPLATE_FIELDS`.

    Args:
        template: The candidate template string (operator-supplied via
            ``agenttower route add --template``).

    Returns:
        The sorted list of placeholder field names actually used (for
        diagnostics / runtime field-prep optimization).

    Raises:
        RouteTemplateInvalid: When any placeholder references a field
            outside the whitelist, OR when ``template`` is empty.
    """
    if not isinstance(template, str) or not template:
        raise RouteTemplateInvalid("template must be a non-empty string")

    used = extract_template_fields(template)
    unknown = used - ALLOWED_TEMPLATE_FIELDS
    if unknown:
        raise RouteTemplateInvalid(
            f"template references unknown field(s) {sorted(unknown)!r}; "
            f"allowed fields are {sorted(ALLOWED_TEMPLATE_FIELDS)!r}"
        )
    return sorted(used)


# ──────────────────────────────────────────────────────────────────────
# Render
# ──────────────────────────────────────────────────────────────────────


_BODY_VALIDATION_CODE_TO_SUB_REASON: Final[dict[str, str]] = {
    BODY_EMPTY: BODY_EMPTY,
    BODY_INVALID_CHARS: BODY_INVALID_CHARS,
    BODY_INVALID_ENCODING: BODY_INVALID_ENCODING,
    BODY_TOO_LARGE: BODY_TOO_LARGE,
}


def render_template(
    template: str,
    *,
    fields: Mapping[str, Any],
    raw_event_excerpt: str,
    redactor: Callable[[str], str] | None = None,
) -> bytes:
    """Substitute every whitelisted ``{<field>}`` placeholder and
    return the validated UTF-8 body bytes.

    Substitution order is single-pass left-to-right per research §R9
    (no recursive substitution; literal ``{{`` / ``}}`` are passed
    through as-is). ``{event_excerpt}`` is routed through
    :func:`agenttower.routing.excerpt.render_excerpt` BEFORE
    substitution per FR-026 — the raw excerpt MUST NEVER appear in
    the rendered body.

    The rendered body is then run through FEAT-009's
    :func:`agenttower.routing.envelope.validate_body`; any failure
    surfaces as :class:`RouteTemplateRenderError` with a sub-reason
    matching the FEAT-009 closed-set body-validation code (per
    contracts/error-codes.md §3).

    Args:
        template: Operator-supplied template string. MUST have passed
            :func:`validate_template_string` at route-add time.
        fields: Mapping of every whitelisted field EXCEPT
            ``event_excerpt`` to its stringifiable value. Caller is
            responsible for populating ``source_label`` / ``source_role``
            / ``source_capability`` from the agent registry at
            evaluation time.
        raw_event_excerpt: The unredacted event excerpt (as stored
            on the FEAT-008 ``events.excerpt`` column). Routed through
            the redactor IFF the template uses ``{event_excerpt}``;
            otherwise ignored (still required as a parameter for API
            uniformity).
        redactor: Override the FEAT-007 redactor (test seam). Defaults
            to the FEAT-007 production redactor used by
            :mod:`agenttower.routing.excerpt`.

    Returns:
        The validated body bytes ready for
        :meth:`agenttower.routing.dao.MessageQueueDao.insert_queued`.

    Raises:
        RouteTemplateRenderError: With one of the sub-reasons from
            :data:`agenttower.routing.route_errors.TEMPLATE_SUB_REASONS`.
            Caller (the routing worker) maps to
            ``route_skipped(reason='template_render_error',
            sub_reason=<this>)``.
    """
    # Step 1: build the substitution map. For {event_excerpt}, apply
    # FEAT-007 redaction via render_excerpt (which also collapses
    # whitespace + truncates to the 240-char cap). For every other
    # field, the value passes through raw — those fields are
    # operator-controlled or daemon-generated per spec Assumptions.
    sub_map: dict[str, str] = {k: str(v) for k, v in fields.items()}

    if _EVENT_EXCERPT_FIELD in extract_template_fields(template):
        try:
            redacted = render_excerpt(
                raw_event_excerpt.encode("utf-8"), redactor=redactor
            )
        except Exception as exc:
            # The redactor raised — surface as a closed-set sub-reason
            # rather than substituting raw text (spec Assumptions:
            # "Redactor failure surfaces as a skip reason").
            from agenttower.routing.route_errors import REDACTOR_FAILURE
            raise RouteTemplateRenderError(
                REDACTOR_FAILURE,
                f"FEAT-007 redactor raised {type(exc).__name__}: {exc}",
            ) from exc
        sub_map[_EVENT_EXCERPT_FIELD] = redacted

    # Step 2: single-pass left-to-right substitution. Uses
    # str.format_map which handles {{ / }} literal escapes correctly
    # and raises KeyError on a placeholder we didn't populate.
    try:
        rendered = template.format_map(sub_map)
    except KeyError as exc:
        # Defended; should be unreachable if validate_template_string
        # passed at route-add time AND the caller populated `fields`
        # with all non-excerpt whitelisted fields. Belt-and-suspenders
        # path that maps to the documented sub-reason.
        missing_field = exc.args[0] if exc.args else "unknown"
        raise RouteTemplateRenderError(
            MISSING_FIELD,
            f"template references field {{{missing_field}}} but no value "
            f"was supplied at render time",
        ) from None

    # Step 3: UTF-8 encode, then run through FEAT-009 body validation.
    body_bytes = rendered.encode("utf-8")

    try:
        validate_body(body_bytes)
    except BodyValidationError as exc:
        sub_reason = _BODY_VALIDATION_CODE_TO_SUB_REASON.get(
            exc.code, BODY_INVALID_CHARS
        )
        raise RouteTemplateRenderError(
            sub_reason,
            f"rendered body failed FEAT-009 validation: {exc}",
        ) from exc

    return body_bytes
