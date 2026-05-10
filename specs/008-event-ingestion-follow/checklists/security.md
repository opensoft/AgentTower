# Security Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that security, redaction, authentication, error-message-leakage, and DoS-resistance requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Are redaction obligations specified for every durable surface (SQLite excerpt, JSONL excerpt, CLI human output, CLI `--json` output, `agenttower status` degraded surface)? [Completeness, Spec §FR-012]
- [ ] CHK002 Are peer-uid authentication requirements specified for the four new socket methods (`events.list`, `events.follow_open`, `events.follow_next`, `events.follow_close`)? [Completeness, Gap]
- [ ] CHK003 Are file-mode requirements (0o600 / 0o700) re-stated as binding for FEAT-008 additions, or is inheritance from FEAT-001 documented as an explicit precondition? [Completeness, Gap]
- [ ] CHK004 Are requirements specified for the events SQLite table's access path being daemon-only (no direct file read by clients)? [Completeness, Gap]
- [ ] CHK005 Are requirements specified for redacting any log content that might appear in the `events_persistence.degraded_*` error fields surfaced by `agenttower status`? [Completeness, Gap]
- [ ] CHK006 Are session_id unguessability requirements specified (entropy source, length, no monotonic component)? [Completeness, Gap]
- [ ] CHK007 Are requirements specified for what the `agent_not_found` error message MAY include vs MUST NOT include (e.g., must NOT echo back unrelated agent ids; must NOT include log paths)? [Completeness, Gap]
- [ ] CHK008 Are requirements specified for path-traversal validation of stored `log_path` values, or is this delegated to FEAT-007 with an explicit reference? [Completeness, Gap]
- [ ] CHK009 Are CLI input-validation obligations (`agent_id` shape, `--type` enum, ISO-8601, `--limit` bounds) explicitly required as client-side enforcement before daemon dispatch? [Completeness, Spec §FR-035a]
- [ ] CHK010 Are requirements specified for the test-seam production guard so `AGENTTOWER_TEST_*_FAKE` cannot be honored by a production daemon? [Completeness, Gap]
- [ ] CHK011 Is there a requirement that the `excerpt` field cannot exceed `per_event_excerpt_cap_bytes` regardless of input size (DoS via long lines)? [Completeness, Spec §FR-019, Edge Cases]

## Requirement Clarity

- [ ] CHK012 Is "redacted excerpt" defined unambiguously at the spec level (which patterns; which utility version)? [Clarity, Spec §FR-012]
- [ ] CHK013 Is "redaction runs before truncation" precise enough to be testable for a secret pattern split exactly at the cap boundary? [Clarity, Spec §Edge Cases]
- [ ] CHK014 Is "opaque at the CLI boundary" defined operationally for cursors (e.g., cannot be hand-derived without a daemon round-trip)? [Clarity, Spec §FR-030, Clarifications]
- [ ] CHK015 Is "closed-set `agent_not_found` error" precisely defined as a stable string identifier with documented payload shape? [Clarity, Spec §FR-035a]
- [ ] CHK016 Is "in-memory buffer" in FR-040 explicit about the buffer NOT being written to disk and NOT spanning daemon restart? [Clarity, Spec §FR-040, Clarifications]
- [ ] CHK017 Is the `classifier_rule_id` pattern required to be ASCII-only and matchable to a closed registry (preventing rule-id injection from log content)? [Clarity, Gap]

## Requirement Consistency

- [ ] CHK018 Are redaction requirements consistent between FR-012 (classifier emits redacted excerpt) and FR-027 (JSONL stable schema's excerpt field) — i.e., the same redaction utility runs at the same point? [Consistency, Spec §FR-012, FR-027]
- [ ] CHK019 Do the FEAT-001 file-mode contracts (0o600 / 0o700) apply transitively to FEAT-008 additions without explicit re-statement, or is FEAT-008's reuse of the path explicit enough? [Consistency, Gap]
- [ ] CHK020 Is peer-uid mismatch handling consistent between the new `events.*` methods and the existing FEAT-002 socket methods (same `socket_peer_uid_mismatch` lifecycle event)? [Consistency, Gap]
- [ ] CHK021 Is the closed-set error code naming consistent with FEAT-002 conventions (snake_case, no leading underscore, lowercase only)? [Consistency, Spec §FR-035a]
- [ ] CHK022 Are redaction-before-truncation guarantees consistent between the byte-cap split case (Edge Cases) and the excerpt-cap truncation case (Edge Cases)? [Consistency, Spec §Edge Cases]

## Acceptance Criteria Quality

- [ ] CHK023 Are SC items measurable for redaction guarantees (e.g., "100% of secret patterns in fixture set produce a redacted excerpt")? [Measurability, Gap]
- [ ] CHK024 Is SC-009 (FEAT-007 lifecycle classes do not appear in FEAT-008 events stream) strong enough to prevent log_path leakage via lifecycle event excerpts, or is a stronger requirement needed? [Acceptance Criteria, Spec §SC-009]
- [ ] CHK025 Are acceptance criteria specified for the maximum size of an error message body (DoS via crafted error text)? [Measurability, Gap]
- [ ] CHK026 Are acceptance criteria specified for the redaction fixture set's coverage (which categories of secret are tested: JWT, env-var-style, API key, password, generic high-entropy)? [Measurability, Gap]

## Scenario Coverage

- [ ] CHK027 Are requirements defined for secret patterns SPLIT across the per-cycle byte cap (first half on cycle N, second half on cycle N+1)? [Coverage, Gap]
- [ ] CHK028 Are requirements defined for secret patterns SPLIT across the per-event excerpt cap (redaction runs before truncation, but is the post-truncate marker boundary itself secret-safe)? [Coverage, Spec §Edge Cases]
- [ ] CHK029 Are requirements defined for the case where a redacted secret appears in an `activity` debounce window's collapsed `latest_excerpt`? [Coverage, Gap]
- [ ] CHK030 Are requirements specified for follow-session isolation between concurrent operators (one operator's `session_id` cannot subscribe to another operator's filter without re-auth)? [Coverage, Gap]
- [ ] CHK031 Are requirements specified for the case where the daemon emits an `agent_not_found` error for an `agent_id` shape-validated client-side (no echo of attacker-controlled value beyond bounded length)? [Coverage, Gap]

## Edge Case Coverage

- [ ] CHK032 Is the case "ANSI escape sequences in excerpts that could affect human-output rendering or be interpreted by downstream terminals" addressed (e.g., must be stripped or escaped in human output)? [Edge Case, Gap]
- [ ] CHK033 Is the case "log_path contains characters that need quoting for log aggregators / shell evaluation" addressed at the JSONL/CLI output boundary? [Edge Case, Gap]
- [ ] CHK034 Is `session_id` collision avoidance defined under the birthday-paradox bound for the configured 12-hex shape (≈ 4.7B combinations; collision probability at 50 sessions is ≈ negligible — but is this called out)? [Edge Case, Gap]
- [ ] CHK035 Are requirements specified for the boundary case where the FEAT-007 redaction utility is updated to redact a NEW pattern AFTER FEAT-008 events have already persisted that pattern unredacted (no retroactive redaction in MVP)? [Edge Case, Gap]
- [ ] CHK036 Is the case "operator pipes `events --json` into a downstream JSON parser and an excerpt contains crafted JSON-injection characters" addressed (the JSON encoder handles it — is this written as a requirement)? [Edge Case, Gap]

## Non-Functional Requirements

- [ ] CHK037 Are ReDoS-protection requirements specified for the classifier regex catalogue (e.g., no nested-quantifier patterns; pinned at the contract level)? [NFR, Spec §FR-007]
- [ ] CHK038 Are memory-exhaustion bounds specified for the per-cycle buffer AND the FR-040 in-memory degraded buffer (both bounded by `per_cycle_byte_cap_bytes`)? [NFR, Spec §FR-019, FR-040]
- [ ] CHK039 Are requirements specified for the maximum number of concurrent follow sessions (DoS via session-creation flood)? [NFR, Gap]

## Dependencies & Assumptions

- [ ] CHK040 Is the dependency on FEAT-007's `redact_one_line` version-pinned for stable security guarantees, AND is the assumption that local Unix socket peer-uid is sufficient authentication explicitly documented (not just implied by FEAT-002 inheritance)? [Dependency / Assumption, Spec §FR-012, Gap]
