# Error Envelopes & Codes Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for response envelope shapes (success/failure), the closed-set error code registry, and per-code `details` semantics.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Are both envelope shapes (success `{ok: true, app_contract_version, result}` and failure `{ok: false, app_contract_version, error: {code, message, details}}`) fully specified with required fields? [Completeness, Spec §FR-033]
- [X] CHK002 Is `error.details` structure specified — is it always an object, sometimes null, with optional fields per code? [Clarity, Spec §FR-033]
- [X] CHK003 Are the per-code `details` fields enumerated for each closed-set code (e.g., `validation_failed` → `details.field`; `pane_already_registered` → `details.agent_id`; `scan_timeout` → `details.scan_id`; `app_contract_major_unsupported` → both versions)? [Completeness, Spec §FR-034, §US2, §US4, §FR-030b]
- [X] CHK004 Is `error.message` required to be human-readable, machine-friendly, or both? [Clarity, Spec §FR-033]
- [X] CHK005 Is the `error.code` field's character set / format constrained (e.g., `^[a-z0-9_]+$`)? [Gap, Spec §FR-034]

## Requirement Clarity

- [X] CHK006 Is "Free-form prose belongs in `error.message` and `error.details`, never in `error.code`" (FR-034) testable — can a contract test assert `error.code` matches a regex? [Measurability, Spec §FR-034]
- [X] CHK007 Is "closed set" definition tied to a single source-of-truth list, or duplicated across the spec risking drift? [Consistency, Spec §FR-034]
- [X] CHK008 Is the rule for adding closed-set codes (additive minor only — FR-035) consistent with FR-034's "additive in future minors" parenthetical? [Consistency, Spec §FR-034, §FR-035]
- [X] CHK009 Is the difference between `app.preflight` returning a `code` field (FR-011) and an `app.*` method returning `error.code` (FR-034) clear — is `app.preflight` always a success envelope with a diagnostic code, or sometimes a failure envelope? [Ambiguity, Spec §FR-011, §FR-033]

## Requirement Consistency

- [X] CHK010 Are all error codes used in user-story acceptance scenarios present in FR-034's closed set (`scan_timeout`, `pane_already_registered`, `validation_failed`, `stale_object`, `app_contract_major_unsupported`, `app_session_required`, `unknown_method`, `container_inactive`, `log_attach_blocked`, `daemon_unavailable`, `socket_missing`)? [Consistency, Spec §FR-034]
- [X] CHK011 Are FR-011's preflight codes `{ok, daemon_unavailable, socket_missing, socket_permission_denied}` a strict subset of FR-034's closed set? [Consistency, Spec §FR-011, §FR-034]
- [X] CHK012 Are codes consistently spelled (e.g., `daemon_unavailable` not `daemon-unavailable` or `daemonUnavailable`) across all FRs, user stories, and Clarifications? [Consistency]
- [X] CHK013 Are `routing_disabled` (FR-034) and FEAT-009's existing global kill-switch error name consistent? [Consistency, Spec §FR-034, §FR-031]

## Scenario Coverage

- [X] CHK014 Are requirements defined for an internal server error path (`internal_error` shape, mandatory fields, redaction policy)? [Coverage, Spec §FR-034]
- [X] CHK015 Is there a code for malformed JSON request (parse error before dispatch)? [Gap, Spec §FR-034]
- [X] CHK016 Is there a code for "unknown app namespace method" distinct from "method on existing namespace but wrong"? [Gap, Spec §FR-034 `unknown_method`]
- [X] CHK017 Is there a code or behavior defined for "request too large" / "payload exceeds limit"? [Gap]
- [X] CHK018 Is there a code for "rate limited" reserved or explicitly excluded as out-of-scope for v1.0? [Gap]
- [X] CHK019 Is there a code for "daemon shutting down" distinct from `daemon_unavailable`? [Gap]
- [X] CHK020 Is there a code for "session token format invalid" distinct from `app_session_expired`? [Gap, Spec §FR-007, §FR-034]

## Measurability

- [X] CHK021 Can SC-003's "zero free-form prose in `error.code`" be tested across the entire mutation surface (every error path → assert code is in registry)? [Measurability, Spec §SC-003]
- [X] CHK022 Can FR-034's closed-set claim be enforced by a registry-driven contract test that fails when the daemon returns an unregistered code? [Measurability, Spec §FR-034]
- [X] CHK023 Can the per-code `details` schema be enforced by a registry of `code → required_detail_fields` validated in tests? [Measurability]

## Ambiguities, Conflicts, Gaps

- [X] CHK024 Is `state == "ok"` used in `app.hello` (FR-010) the same as the success envelope's `ok: true`? Are both checked, or is `state` redundant on `app.hello` success? [Ambiguity, Spec §FR-010, §FR-033]
- [X] CHK025 Is there a defined behavior for codes that originate in underlying systems (e.g., FEAT-009 raises its own error name) — does the `app.*` layer translate to the closed set, or pass through? [Gap]
- [X] CHK026 Is the `app_contract_version` field on a failure envelope (FR-033) defined to always match the daemon's actual version (even when the failure is `app_contract_major_unsupported`)? [Clarity, Spec §FR-033, §US5]
- [X] CHK027 Is the rule defined for error code stability — can a future minor change the `details` fields of an existing code, or only add new optional `details` fields? [Gap, Spec §FR-035]
