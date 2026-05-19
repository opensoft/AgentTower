# Success Criteria Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate measurability and testability of SC-001..SC-010, and identify success-criteria gaps for FRs added during clarification (pagination, idempotency, scan timeout, capability flags).
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Are all 10 success criteria stated with measurable thresholds (count, time, percentage, structural assertion)? [Completeness, Spec §SC-001..§SC-010]
- [X] CHK002 Is the test fixture defined for every SC (what state must exist before the test runs — containers, agents, queue rows, routes)? [Gap]
- [X] CHK003 Is the test scope defined for every SC (which methods must be covered, which paths included)? [Gap]
- [X] CHK004 Is there a success criterion for `app.preflight` correctness (FR-011 closed-set codes), or is it implicitly covered by SC-007? [Coverage, Spec §FR-011, §SC-007]
- [X] CHK005 Is there a success criterion for pagination correctness (FR-020a — default 50, cap 200, `validation_failed` on overflow)? [Gap, Spec §FR-020a]
- [X] CHK006 Is there a success criterion for idempotency correctness (FR-031a — dedupe, `deduplicated: true`)? [Gap, Spec §FR-031a]
- [X] CHK007 Is there a success criterion for capability_flags evolution (FR-039 — empty at v1.0, additive in later minors)? [Gap, Spec §FR-039]
- [X] CHK008 Is there a success criterion for scan timeout behavior (FR-030b — 30s cap, `scan_timeout` with `scan_id`, no server-side cancel)? [Gap, Spec §FR-030b]
- [X] CHK009 Is there a success criterion for cursor-based pagination correctness (`cursor_next` stable across calls)? [Gap, Spec §FR-020]
- [X] CHK010 Is there a success criterion for `app.agent.update` last-write-wins (FR-030a)? [Gap, Spec §FR-030a]

## Requirement Clarity

- [X] CHK011 Is SC-001's "zero lines parsing human CLI text" defined operationally — what counts as "CLI text" (subprocess stdout, log files, syslog)? [Clarity, Spec §SC-001]
- [X] CHK012 Is SC-002's "first rendered dashboard payload" defined as "response received" or "JSON parsed" or "rendered to UI"? [Ambiguity, Spec §SC-002]
- [X] CHK013 Is SC-003's "free-form prose error in `error.code`" testable by a regex (e.g., `^[a-z0-9_]+$`)? [Measurability, Spec §SC-003]
- [X] CHK014 Is SC-007's "structured, app-renderable state" defined — what makes a response "renderable"? [Ambiguity, Spec §SC-007]
- [X] CHK015 Is SC-009's "completes the dashboard + adopt + queue + route flows" defined as a specific test plan with explicit method calls? [Clarity, Spec §SC-009]
- [X] CHK016 Is SC-010's "byte-for-byte identical (modulo `origin`/`app_session_id` metadata)" defined to include or exclude timestamps? [Clarity, Spec §SC-010]

## Requirement Consistency

- [X] CHK017 Are SC-002 (≤500ms dashboard) and SC-004 (≤2s adopt) latency targets consistent with the FR-018 (no global lock) performance assumption? [Consistency, Spec §FR-018, §SC-002, §SC-004]
- [X] CHK018 Is SC-008's "MUST NOT appear in any JSONL row" consistent with FR-009's "MUST NOT include the opaque `app_session_token`"? [Consistency, Spec §FR-009, §SC-008]
- [X] CHK019 Is SC-010's "byte-for-byte identical (modulo `origin`/`app_session_id` metadata)" consistent with FR-044's audit requirements (does `origin`/`app_session_id` show up in *every* JSONL row, or only audit rows)? [Consistency, Spec §FR-044, §SC-010]
- [X] CHK020 Is SC-001's "verified by an integration harness that asserts no `agenttower` subprocess output is consumed" consistent with FR-002's preservation of legacy CLI methods (the daemon still has them, but the app must not call them)? [Consistency, Spec §FR-002, §SC-001]

## Scenario Coverage

- [X] CHK021 Is SC-006's "MUST NOT bind any TCP or non-Unix-domain socket during the entire test run" covering both runtime and shutdown? [Coverage, Spec §SC-006]
- [X] CHK022 Is SC-007's degraded-state coverage list (daemon unavailable, socket missing, schema/version incompatible, Docker unavailable, no containers, no panes, no agents) exhaustive of all FR-014 + Edge Cases failure modes? [Coverage, Spec §SC-007, §FR-014, Edge Cases]
- [X] CHK023 Is SC-009's "synthetic minor-N client running against a minor-(N+1) daemon" implementable today without inventing speculative future methods (since v1.0 has no minors yet)? [Measurability, Spec §SC-009]

## Measurability

- [X] CHK024 Can every SC be implemented as a green/red contract test today, given the current spec? [Measurability]
- [X] CHK025 Is "zero stray fields" (SC-005) testable when the major mismatch path returns *no* response, vs. returns an envelope with limited fields? [Ambiguity, Spec §SC-005]
- [X] CHK026 Is "zero internal state mutation on the daemon side" (SC-005) testable from outside (no observable side effects)? [Measurability, Spec §SC-005]
- [X] CHK027 Can SC-010's "byte-for-byte identical SQLite/JSONL state" be verified across all 10 enumerated operator-parity methods? [Measurability, Spec §SC-010]

## Ambiguities, Conflicts, Gaps

- [X] CHK028 Is the rule defined for whether an SC test SHOULD or MUST be part of the FEAT-011 acceptance test suite (i.e., are all 10 SCs gating)? [Gap]
- [X] CHK029 Is "verified by a fixture-comparison test" (SC-010) defined to be deterministic across machine timezones and locale? [Gap]
- [X] CHK030 Is the rule defined for how SCs evolve in additive minors — does adding a new method require a matching new SC? [Gap, Spec §FR-035]
- [X] CHK031 Is "100% of FEAT-011 mutation methods return a structured success envelope or a closed-set error code" (SC-003) testable across all 13 mutation methods in FR-029? [Measurability, Spec §SC-003, §FR-029]
- [X] CHK032 Is the success criterion for the FR-031a `idempotency_key` behavior implicit in SC-010 (byte-for-byte parity) or does it need its own SC? [Coverage, Spec §FR-031a, §SC-010]
