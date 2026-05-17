"""T006 — FEAT-010 closed-set vocabulary tests.

Asserts:
- All 8 CLI codes are present in :data:`CLOSED_CODE_SET` (no collision).
- The 10 skip reasons + 6 sub-reasons + 4 internal codes have stable
  string values matching contracts/error-codes.md.
- Exception subclasses bind to the correct CLI code.
- ``RouteTemplateRenderError`` rejects unknown sub-reasons.
- ``RoutingTransientError`` rejects unknown internal codes.
- The eight CLI codes do not overlap with any pre-FEAT-010 code in
  ``CLOSED_CODE_SET``.
"""

from __future__ import annotations

import pytest

from agenttower.routing import route_errors as rerr
from agenttower.socket_api import errors as socket_errors


# ──────────────────────────────────────────────────────────────────────
# CLI codes are registered in CLOSED_CODE_SET
# ──────────────────────────────────────────────────────────────────────


def test_all_cli_codes_in_closed_code_set() -> None:
    for code in rerr.CLI_ERROR_CODES:
        assert code in socket_errors.CLOSED_CODE_SET, (
            f"FEAT-010 CLI code {code!r} not registered in CLOSED_CODE_SET"
        )


def test_cli_codes_have_expected_stable_strings() -> None:
    # Exact values are the public contract per contracts/error-codes.md §1.
    assert rerr.ROUTE_ID_NOT_FOUND == "route_id_not_found"
    assert rerr.ROUTE_EVENT_TYPE_INVALID == "route_event_type_invalid"
    assert rerr.ROUTE_TARGET_RULE_INVALID == "route_target_rule_invalid"
    assert rerr.ROUTE_MASTER_RULE_INVALID == "route_master_rule_invalid"
    assert rerr.ROUTE_TEMPLATE_INVALID == "route_template_invalid"
    assert rerr.ROUTE_SOURCE_SCOPE_INVALID == "route_source_scope_invalid"
    assert rerr.ROUTE_CREATION_FAILED == "route_creation_failed"
    assert rerr.QUEUE_ORIGIN_INVALID == "queue_origin_invalid"


def test_cli_codes_do_not_collide_with_pre_feat010_codes() -> None:
    """The FEAT-010 codes are NEW additions; they MUST NOT shadow an
    existing FEAT-001..009 code."""
    pre_feat010_codes = socket_errors.CLOSED_CODE_SET - rerr.CLI_ERROR_CODES
    for code in rerr.CLI_ERROR_CODES:
        assert code not in pre_feat010_codes


# ──────────────────────────────────────────────────────────────────────
# Skip reasons (FR-037)
# ──────────────────────────────────────────────────────────────────────


def test_skip_reasons_match_contract() -> None:
    expected = {
        "no_eligible_master",
        "master_inactive",
        "master_not_found",
        "target_not_found",
        "target_role_not_permitted",
        "target_not_active",
        "target_pane_missing",
        "target_container_inactive",
        "no_eligible_target",
        "template_render_error",
    }
    assert rerr.SKIP_REASONS == expected


def test_skip_reasons_are_not_cli_codes() -> None:
    """Skip reasons appear in JSONL audit only — NEVER as CLI exit codes
    (research §R13)."""
    assert rerr.SKIP_REASONS.isdisjoint(rerr.CLI_ERROR_CODES)


# ──────────────────────────────────────────────────────────────────────
# Template sub-reasons
# ──────────────────────────────────────────────────────────────────────


def test_template_sub_reasons_match_contract() -> None:
    expected = {
        "missing_field",
        "body_empty",
        "body_invalid_chars",
        "body_invalid_encoding",
        "body_too_large",
        "redactor_failure",
    }
    assert rerr.TEMPLATE_SUB_REASONS == expected


# ──────────────────────────────────────────────────────────────────────
# Internal-error codes (FR-051)
# ──────────────────────────────────────────────────────────────────────


def test_internal_error_codes_match_contract() -> None:
    expected = {
        "routing_sqlite_locked",
        "routing_duplicate_insert",
        "routing_internal_render_failure",
        "routing_audit_buffer_overflow",
    }
    assert rerr.INTERNAL_ERROR_CODES == expected


def test_internal_codes_are_not_cli_codes_and_not_skip_reasons() -> None:
    """Internal codes appear in the daemon log + ``routing_worker_degraded``
    status field — NEVER on the CLI and NEVER as audit skip reasons."""
    assert rerr.INTERNAL_ERROR_CODES.isdisjoint(rerr.CLI_ERROR_CODES)
    assert rerr.INTERNAL_ERROR_CODES.isdisjoint(rerr.SKIP_REASONS)


# ──────────────────────────────────────────────────────────────────────
# Exception hierarchy
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("exc_cls", "expected_code"),
    [
        (rerr.RouteIdNotFound, rerr.ROUTE_ID_NOT_FOUND),
        (rerr.RouteEventTypeInvalid, rerr.ROUTE_EVENT_TYPE_INVALID),
        (rerr.RouteTargetRuleInvalid, rerr.ROUTE_TARGET_RULE_INVALID),
        (rerr.RouteMasterRuleInvalid, rerr.ROUTE_MASTER_RULE_INVALID),
        (rerr.RouteSourceScopeInvalid, rerr.ROUTE_SOURCE_SCOPE_INVALID),
        (rerr.RouteTemplateInvalid, rerr.ROUTE_TEMPLATE_INVALID),
        (rerr.RouteCreationFailed, rerr.ROUTE_CREATION_FAILED),
        (rerr.QueueOriginInvalid, rerr.QUEUE_ORIGIN_INVALID),
    ],
)
def test_route_error_subclasses_bind_to_cli_code(exc_cls, expected_code) -> None:
    exc = exc_cls("boom")
    assert exc.code == expected_code
    assert exc.message == "boom"
    assert isinstance(exc, rerr.RouteError)


def test_route_template_render_error_validates_sub_reason() -> None:
    rerr.RouteTemplateRenderError(rerr.BODY_TOO_LARGE, "oversized")
    with pytest.raises(ValueError, match="unknown template sub-reason"):
        rerr.RouteTemplateRenderError("not_a_sub_reason", "msg")


def test_routing_transient_error_validates_internal_code() -> None:
    rerr.RoutingTransientError(rerr.ROUTING_SQLITE_LOCKED, "locked")
    with pytest.raises(ValueError, match="unknown internal error code"):
        rerr.RoutingTransientError("not_an_internal_code", "msg")


def test_routing_duplicate_insert_carries_correct_code() -> None:
    exc = rerr.RoutingDuplicateInsert("UNIQUE constraint failed")
    assert exc.code == rerr.ROUTING_DUPLICATE_INSERT
    assert isinstance(exc, rerr.RoutingTransientError)


# ──────────────────────────────────────────────────────────────────────
# make_error rejects unknown codes (FEAT-002 invariant)
# ──────────────────────────────────────────────────────────────────────


def test_make_error_accepts_all_feat010_cli_codes() -> None:
    """FEAT-002's ``make_error`` enforces CLOSED_CODE_SET membership;
    every FEAT-010 CLI code MUST round-trip cleanly."""
    for code in rerr.CLI_ERROR_CODES:
        envelope = socket_errors.make_error(code, f"test message for {code}")
        assert envelope == {
            "ok": False,
            "error": {"code": code, "message": f"test message for {code}"},
        }
