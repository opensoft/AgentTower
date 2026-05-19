# Bootstrap Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for the `app.preflight` and `app.hello` handshake — completeness of returned fields, clarity of state semantics, drift detection.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are all `app.hello` return fields enumerated (token, id, daemon_version, schema_version, app_contract_version, supported_minor_range, host_user_id, capability_flags, state)? [Completeness, Spec §FR-010]
- [ ] CHK002 Is `app.preflight`'s full return envelope defined (socket_reachable, daemon_reachable, code, app_contract_version)? [Completeness, Spec §FR-011]
- [ ] CHK003 Is `host_user_id`'s format (numeric UID, username string, or both) specified? [Gap, Spec §FR-010]
- [ ] CHK004 Is `daemon_version`'s format (semver, build hash, opaque string) specified? [Gap, Spec §FR-010]
- [ ] CHK005 Is `schema_version`'s format specified and tied to the SQLite/JSONL migration version it represents? [Gap, Spec §FR-010, Edge Cases §Schema version vs contract version]
- [ ] CHK006 Is the rule defined for what optional fields `app.hello` MAY return in addition to the required set (e.g., feature flags, build channel)? [Gap, Spec §FR-010]

## Requirement Clarity

- [ ] CHK007 Is `state == "ok"` semantics on `app.hello` defined — what condition would make `app.hello` return `state != "ok"`, or does it only fail via the error envelope? [Clarity, Spec §FR-010]
- [ ] CHK008 Is `supported_minor_range` clearly typed as min/max strings versus integers? [Clarity, Spec §FR-010]
- [ ] CHK009 Is the difference between `app.preflight` and `app.hello` clearly bounded — can `app.preflight` be called multiple times without side effects? [Clarity, Spec §FR-011]
- [ ] CHK010 Is "before `app.hello`" precisely defined — can `app.preflight` be called *after* `app.hello` as an idempotent diagnostic? [Gap, Spec §FR-011]

## Requirement Consistency

- [ ] CHK011 Is `app.preflight`'s closed-set code `{ok, daemon_unavailable, socket_missing, socket_permission_denied}` (FR-011) a strict subset of the FR-034 global closed set? [Consistency, Spec §FR-011, §FR-034]
- [ ] CHK012 Do FR-010 and Clarifications §Bootstrap agree on the field set returned by `app.hello`? [Consistency]
- [ ] CHK013 Are the User Story 1 step 2 fields consistent with FR-010's required field list? [Consistency, Spec §US1]
- [ ] CHK014 Is "host UID" used consistently across FR-005, FR-010, FR-041 (peer-cred vs. self-reported `host_user_id`)? [Consistency]

## Scenario Coverage

- [ ] CHK015 Are requirements defined for the case where `app.preflight` succeeds but `app.hello` immediately fails (e.g., race during shutdown)? [Gap]
- [ ] CHK016 Are requirements defined for the case where the daemon binds a different socket path than the app expects (configuration drift)? [Gap]
- [ ] CHK017 Is the behavior defined when `app.hello` is called and the host UID does not match (peer UID check fails) — does it return `permission_denied` from `app.hello`, or from the connection layer? [Gap, Spec §FR-005, §FR-041]
- [ ] CHK018 Is the behavior defined when `app.preflight` is called with an unexpected request body (extra fields, malformed)? [Gap]

## Measurability

- [ ] CHK019 Can the "additive" rule on `app.hello` field set (FR-010 last sentence) be tested by a contract suite that detects a removed field across versions? [Measurability, Spec §FR-010]
- [ ] CHK020 Is "MUST be callable without `app_session_token`" (FR-011) testable by sending `app.preflight` with no session token and asserting success? [Measurability, Spec §FR-011]
- [ ] CHK021 Can `app.preflight`'s "safe before `app.hello`" property be verified via daemon state inspection (no session, no audit row created)? [Measurability]

## Ambiguities, Conflicts, Gaps

- [ ] CHK022 Is there a defined upper bound on the size of `capability_flags`? [Gap, Spec §FR-010, §FR-039]
- [ ] CHK023 Is the rule defined for whether `app.preflight` may return `socket_reachable: true, daemon_reachable: false, code: "daemon_unavailable"` (partial-state result), or whether the call would have failed at the OS level first? [Ambiguity, Spec §FR-011]
- [ ] CHK024 Is the response envelope shape for `app.preflight` (success vs failure) explicitly aligned with FR-033's envelope rule, given that some `app.preflight` outcomes carry diagnostic codes that look like errors but might be on the success path? [Clarity, Spec §FR-011, §FR-033]
