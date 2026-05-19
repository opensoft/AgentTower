# Observability & Audit Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for app-mutation audit JSONL, origin attribution, side-effect freedom on read paths, and operator attribution.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are the JSONL audit fields for app-driven mutations enumerated (`origin`, `app_session_id`, plus the existing FEAT-006..010 audit fields)? [Completeness, Spec §FR-044]
- [ ] CHK002 Is the audit-event taxonomy defined for each mutation method (which method emits which audit event type)? [Gap, Spec §FR-044]
- [ ] CHK003 Is the audit-event schema versioned (does adding `origin == "app"` require a JSONL schema version bump)? [Gap, Edge Cases §Schema version vs contract version]
- [ ] CHK004 Is "side-effect-free" (FR-045) defined to explicitly include "MUST NOT emit audit rows" for `app.readiness` and `app.dashboard`? [Clarity, Spec §FR-045]
- [ ] CHK005 Are observability requirements defined for metrics/tracing beyond JSONL audit, or is JSONL the only observability surface in FEAT-011? [Coverage, Spec §FR-044]

## Requirement Clarity

- [ ] CHK006 Is `origin == "app"` defined as the only valid app-origin string, or are there future variants permitted (e.g., `origin == "app.flutter"`)? [Gap, Spec §FR-044]
- [ ] CHK007 Is the policy for the CLI's `origin` value defined (`origin == "cli"`, `"host"`, or unset) so app vs CLI attribution is unambiguous? [Gap, Spec §FR-044]
- [ ] CHK008 Is "audit attribution" defined for non-mutation methods (e.g., does `app.dashboard` contribute to a request log)? [Clarity, Spec §FR-045]
- [ ] CHK009 Is "JSONL audit entries for app-initiated mutations consistent with existing FEAT-006..FEAT-010 audit semantics" (FR-044) operationalized — does each FEAT have a canonical audit event list to inherit? [Clarity, Spec §FR-044]

## Requirement Consistency

- [ ] CHK010 Are FR-009 ("SHOULD record `app_session_id`") and FR-044 ("SHOULD emit JSONL audit entries with `app_session_id`") consistent in modality (both SHOULD, neither MUST)? [Consistency, Spec §FR-009, §FR-044]
- [ ] CHK011 Is FR-009's "MUST NOT include the opaque `app_session_token`" consistent with SC-008's "MUST NOT appear in any JSONL row" — same scope, same enforcement? [Consistency, Spec §FR-009, §SC-008]
- [ ] CHK012 Are app-originated audit row requirements consistent with the existing FEAT-008 event pipeline — do they ride the same channel and use the same JSONL file, or a separate one? [Consistency, Spec §FR-044]
- [ ] CHK013 Is the `origin` field's set of allowed values consistent across user-story acceptance scenarios and FR-044? [Consistency]

## Scenario Coverage

- [ ] CHK014 Are requirements defined for failed mutations — must they emit audit rows (with a `result: failure` marker), or only successful ones? [Gap, Spec §FR-044]
- [ ] CHK015 Are requirements defined for partial mutations (e.g., `app.agent.register_from_pane` validation passes but persistence fails mid-write)? [Gap]
- [ ] CHK016 Is the behavior defined when the JSONL is unwritable (full disk, permission revoked) — does the mutation roll back, or proceed without audit? [Gap]
- [ ] CHK017 Is the behavior defined for audit-row ordering vs. mutation-commit ordering (does the audit row precede or follow the SQLite commit)? [Gap]
- [ ] CHK018 Is the behavior defined when concurrent app sessions emit audit rows simultaneously (per-row append serialization)? [Gap]

## Measurability

- [ ] CHK019 Can SC-008's "at least one JSONL audit row with `origin == "app"`" be programmatically asserted for every mutation method in the contract test suite? [Measurability, Spec §SC-008]
- [ ] CHK020 Can the negative invariant ("token never in JSONL") be verified by a `grep` test across all audit files? [Measurability, Spec §SC-008]
- [ ] CHK021 Can FR-045's "MUST be cheap and side-effect-free" be verified by an "audit row count before and after" test for `app.readiness` and `app.dashboard`? [Measurability, Spec §FR-045]

## Ambiguities, Conflicts, Gaps

- [ ] CHK022 Is the rotation/retention policy for JSONL audit affected by adding `origin`/`app_session_id` (size impact, retention budget)? [Gap]
- [ ] CHK023 Is the ordering guarantee between mutation success and audit row visibility defined (sync flush before response, or eventually-consistent)? [Gap, Spec §FR-044]
- [ ] CHK024 Are observability requirements defined for the `app.preflight` and `app.hello` calls (does the daemon log session establishment events somewhere)? [Gap]
- [ ] CHK025 Is the rule defined for whether the `client_id` / `client_version` fields from `app.hello` are included in audit rows for attribution? [Gap, Spec §FR-010, §FR-044]
- [ ] CHK026 Is the audit row format spec defined as JSONL only, or can future minors switch transport (e.g., to a binary log)? [Gap, Spec §FR-035, §FR-044]
