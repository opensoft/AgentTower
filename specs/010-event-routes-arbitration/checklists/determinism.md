# Determinism Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for FEAT-010's determinism contract — replay reproducibility, arbitration ties, processing order, and explicit boundaries of the "byte-for-byte identical" guarantee.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## Replay Contract Scope

- [X] CHK001 Is the determinism guarantee scope explicitly bounded to FEAT-010-relevant entries (not all daemon output)? [Clarity, Spec §SC-010]
- [X] CHK002 Is "byte-for-byte identical" qualified with the exact set of excluded fields (wall-clock timestamps)? [Spec §SC-010]
- [X] CHK003 Are the inputs to the replay contract enumerated (initial DB snapshot + same event sequence)? [Completeness, Spec §SC-010]
- [X] CHK004 Is heartbeat emission explicitly outside the determinism contract (cadence is wall-clock-driven)? [Spec §FR-039a, Gap]
- [X] CHK005 Is the determinism boundary with FEAT-008 event ingestion (event_id assignment, source_role normalization) documented? [Gap]

## Master Arbitration Determinism

- [X] CHK006 Is the auto-arbitration winner rule (lexically-lowest active master `agent_id`) unambiguous and testable? [Clarity, Spec §FR-017, Story 3 #1]
- [X] CHK007 Are the active-master-set inputs to arbitration specified precisely (role=master AND active=true, no extra criteria)? [Spec §Assumptions, FR-017]
- [X] CHK008 Is the timing of the active-master snapshot specified (per-event evaluation vs per-cycle)? [Clarity, Spec §FR-020, Edge Cases]
- [X] CHK009 Are the closed-set skip reasons for arbitration failure (`no_eligible_master`, `master_inactive`, `master_not_found`) deterministically mapped to input conditions? [Spec §FR-016..018, FR-037]
- [X] CHK010 Is the captured `winner_master_agent_id` lifecycle (immutable from arbitration through queue insert) specified? [Spec §FR-020, Edge Cases]

## Target Selection Determinism

- [X] CHK011 Is the `target_rule=role` tie-break (lexically-lowest active matching agent) unambiguous across capability filters? [Clarity, Spec §FR-023]
- [X] CHK012 Is the `target_rule=explicit` resolution order (agent_id, then label, then tag) documented with the no-tags MVP caveat? [Spec §FR-021]
- [X] CHK013 Is the `target_rule=source` resolution behavior on deregistered-source race specified? [Spec §FR-022, Edge Cases]
- [X] CHK014 Are zero-match outcomes mapped to the closed-set `no_eligible_target` consistently across all rules? [Spec §FR-023, Story 1 #5]

## Cycle & Route Processing Order

- [X] CHK015 Is the per-cycle route ordering (created_at ASC, route_id lex tiebreak per FR-042) sufficient to ensure cross-route determinism? [Spec §FR-042]
- [X] CHK016 Is per-route event ordering (event_id ASC per FR-011) enforced inside the batch boundary? [Spec §FR-011, FR-041]
- [X] CHK017 Is the single-threaded sequential worker model (FR-014 + Clarifications) sufficient to eliminate intra-cycle race nondeterminism? [Spec §FR-014, Clarifications]
- [X] CHK018 Are batch boundaries (cycle N processes events `[cursor+1, cursor+batch_size]`) deterministic across restarts at the same cursor state? [Spec §FR-041, Gap]
- [X] CHK019 Is the routing-cycle execution order across cycles (FIFO interval-driven) specified to avoid scheduler-dependent reordering? [Spec §FR-040, Gap]

## Template Rendering Determinism

- [X] CHK020 Is the template substitution algorithm specified as a pure function of (template, event-fields-after-redaction)? [Clarity, Spec §FR-025]
- [X] CHK021 Is FEAT-007 redaction documented as a deterministic function (no random/time-based redaction)? [Spec §FR-026, Gap]
- [X] CHK022 Are missing-field render errors mapped to the same skip reason regardless of which field is missing? [Spec §FR-028]
- [X] CHK023 Is the substitution order (left-to-right? all-at-once?) specified to handle escaping consistently? [Gap]

## Read Consistency

- [X] CHK024 Are SQLite read-isolation requirements specified to ensure arbitration sees a consistent agent snapshot? [Gap, Spec §FR-020]
- [X] CHK025 Is the in-cycle consistency between "active master read" and "queue insert" specified (snapshot-based)? [Gap]
- [X] CHK026 Is the relationship between event-ingest-commit and route-cycle-read specified (do events committed during a cycle get picked up that cycle?)? [Gap]

## Determinism-Testability

- [X] CHK027 Are the Story 3 and Story 4 Independent Tests sufficient to validate the determinism contract in CI? [Measurability, Spec §Story 3 IT, Story 4 IT]
- [X] CHK028 Is the test-fixture format (initial snapshot + event sequence) implicit or explicitly specified? [Gap, Spec §SC-010]
- [X] CHK029 Are config-knob inputs (cycle interval, batch size, heartbeat interval) part of the determinism-input set? [Gap]
- [X] CHK030 Is the explicit exclusion of model-based/LLM-based decisions (per FR-053) sufficient to guarantee no nondeterministic dependencies? [Spec §FR-053]

## Coverage-Gap Remediation (added 2026-05-16 per coverage.md audit)

- [X] CHK031 Is SC-002's 100% threshold (100/100 fires with `sender.agent_id` equal to the lex-lowest active master at each fire moment) specified with explicit pass/fail criteria and a zero-tolerance for "different master" outcomes? [Measurability, Spec §SC-002]
- [X] CHK032 Is SC-002's auto-arbitration outcome re-verifiable on a fresh daemon process (cold start → fire N=100 events → shutdown) with byte-identical sender selection, demonstrating the SC-010 determinism contract specifically for arbitration? [Measurability, Spec §SC-002, SC-010]
