# Classifier Rule Catalogue Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that classifier rule, redaction, and debounce requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Are all 10 event types in the FR-008 catalogue required to have at least one matching rule documented in the rule catalogue? [Completeness, Spec §FR-008]
- [ ] CHK002 Is the rule-priority order required to be expressed in a deterministic, testable form (priority table or ordered list, not prose)? [Completeness, Spec §FR-008, Spec §Edge Cases]
- [ ] CHK003 Is `long_running` eligibility required to be defined as a complete state-transition table (which prior `event_type` values qualify, which do not)? [Completeness, Spec §FR-013]
- [ ] CHK004 Are explicit rules required for what triggers `completed`? [Gap, Spec §FR-008]
- [ ] CHK005 Are explicit rules required for what triggers `waiting_for_input`? [Gap, Spec §FR-008]
- [ ] CHK006 Are explicit rules required for what triggers `manual_review_needed`? [Gap, Spec §FR-008]
- [ ] CHK007 Are explicit rules required for distinguishing `error` from `test_failed` (separate matchers, no overlap by construction)? [Completeness, Spec §FR-008]
- [ ] CHK008 Are explicit rules required for what triggers `test_passed`? [Gap, Spec §FR-008]
- [ ] CHK009 Is the integration with the FEAT-007 redaction utility required at the rule level (every rule emits a redacted excerpt, never the raw bytes)? [Completeness, Spec §FR-012]
- [ ] CHK010 Are the per-attachment "last output at" data lifecycle requirements (initialization, update, reset on restart) specified? [Completeness, Spec §FR-013, FR-015]

## Requirement Clarity

- [ ] CHK011 Is "rule-based only" measurable in code (e.g., a regex/matcher list with no learned components, no network calls)? [Clarity, Spec §FR-007]
- [ ] CHK012 Is "conservative" defined operationally beyond "default to activity" (e.g., a precise decision rule for ambiguity)? [Clarity, Spec §FR-011]
- [ ] CHK013 Is "ongoing work following waiting_for_input is ineligible for long_running" precisely defined for the eligibility table? [Clarity, Spec §FR-013]
- [ ] CHK014 Is the `swarm_member_reported` regex shape exhaustive on whitespace, key ordering, escaping, and quoting? [Clarity, Spec §FR-009]
- [ ] CHK015 Is "redaction runs before truncation" clear about which redactor and which truncation marker apply? [Clarity, Spec §Edge Cases]
- [ ] CHK016 Is "exactly one event per debounce window" unambiguous about which record's excerpt is preserved (latest? first? configurable?)? [Clarity, Spec §FR-014]

## Requirement Consistency

- [ ] CHK017 Are the 10 event types in FR-008 the same set referenced by FR-014's collapse-eligible / one-to-one classification? [Consistency, Spec §FR-008, FR-014]
- [ ] CHK018 Does FR-009's strict-parse rule (malformed → `activity`) align with FR-011's conservative-default rule (ambiguous → `activity`) without rule overlap? [Consistency, Spec §FR-009, FR-011]
- [ ] CHK019 Are `classifier_rule_id` values required to be stable across the catalogue and consistent between SQLite and JSONL output? [Consistency, Spec §FR-027]
- [ ] CHK020 Are `pane_exited` requirements consistent between FR-016 (must be inferred from FEAT-004 state + grace), FR-017 (grace window), and FR-018 (one per lifecycle)? [Consistency, Spec §FR-016, FR-017, FR-018]

## Acceptance Criteria Quality

- [ ] CHK021 Is SC-007's "100% accuracy on every fixture line" measurable against a documented, version-pinned fixture set? [Measurability, Spec §SC-007]
- [ ] CHK022 Are negative test fixtures required (lines that MUST NOT classify as a domain-specific type)? [Acceptance Criteria, Gap]
- [ ] CHK023 Is "documented ambiguous line" defined with explicit fixture entries rather than leaving "ambiguous" up to test author judgment? [Measurability, Spec §SC-007]
- [ ] CHK024 Are acceptance criteria defined for the `debounce` object's `window_id`, `collapsed_count`, `window_started_at`, `window_ended_at` fields' shape and population rules? [Acceptance Criteria, Spec §FR-027]

## Scenario Coverage

- [ ] CHK025 Are requirements defined for multi-line records (continuation lines, line continuations from shells)? [Coverage, Gap]
- [ ] CHK026 Are requirements defined for ANSI escape sequences in lines (color codes, cursor motion, OSC sequences)? [Coverage, Gap]
- [ ] CHK027 Are requirements defined for rule matching across the per-cycle byte-cap (FR-019) truncation boundary? [Coverage, Spec §FR-019, Edge Cases]
- [ ] CHK028 Are requirements specified for protecting against catastrophic regex backtracking (ReDoS)? [Coverage, Gap, NFR]
- [ ] CHK029 Are requirements specified for the case where a classifier rule depends on prior reader-state (e.g., `long_running`) and that state is unavailable on first cycle? [Coverage, Spec §FR-013, FR-015]

## Edge Case Coverage

- [ ] CHK030 Is overlap between `error` and `test_failed` resolved by a documented priority order in the spec, not just the catalogue? [Edge Case, Spec §FR-008, Edge Cases]
- [ ] CHK031 Is the malformed-`AGENTTOWER_SWARM_MEMBER` case explicitly required to fall through to `activity`, not silently dropped? [Edge Case, Spec §FR-009]
- [ ] CHK032 Is `pane_exited` required to NOT be emitted when the log text mentions "exited" or similar (FR-016: "MUST NOT be inferred from log text alone")? [Edge Case, Spec §FR-016]
- [ ] CHK033 Is the case "rule matches partial trailing bytes" excluded by FR-005's complete-record rule? [Edge Case, Spec §FR-005]
- [ ] CHK034 Are debounce-collapse semantics defined when the latest record's excerpt is empty or whitespace-only? [Edge Case, Spec §FR-014]
- [ ] CHK035 Is the "secret pattern split across the truncation boundary" redaction guarantee documented as a hard requirement, not best-effort? [Edge Case, Spec §Edge Cases]

## Non-Functional Requirements

- [ ] CHK036 Are classifier latency requirements quantified per record (e.g., a per-record budget that fits within the cycle wall-clock cap at upper-bound throughput)? [NFR, Gap]
- [ ] CHK037 Are FR-010's pure-function purity requirements verifiable by static analysis or property test (no I/O, no clock reads inside the rule fn)? [NFR, Spec §FR-010]
- [ ] CHK038 Are memory bounds defined for per-attachment classifier state (last-output-at, debounce window) across the upper-bound 50-agent scale? [NFR, Gap]

## Dependencies & Assumptions

- [ ] CHK039 Is the dependency on FEAT-004 pane discovery for `pane_exited` documented and version-pinned? [Dependency, Spec §FR-016]
- [ ] CHK040 Is the assumption that `\n` is the record boundary documented (FR-005, Assumptions) AND the classifier explicitly required to break on it? [Assumption, Spec §FR-005, Assumptions]
