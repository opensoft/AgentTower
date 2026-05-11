# Data Model & State Vocabulary Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the `message_queue` schema, identity capture, timestamp completeness, closed-set vocabularies (state, block_reason, failure_reason), transition graph, operator metadata, and routing-flag entity. Tests whether the data model itself is fully specified, closed, and integrity-checkable — NOT whether the SQLite implementation is correct.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## `message_queue` Schema Completeness

- [ ] CHK001 Are all columns of `message_queue` enumerated with their roles (primary key, identity, body, timestamps, reason, operator metadata)? [Completeness, Spec §FR-012]
- [ ] CHK002 Is the primary key (`message_id`, UUIDv4) declared with collision-resistance rationale, not just type? [Clarity, Spec §FR-001, §FR-012]
- [ ] CHK003 Is the requirement that `envelope_body` is always raw bytes (never redacted at storage) stated explicitly to override any prior wording? [Clarity, Spec §FR-012, §FR-012a, §Clarifications]
- [ ] CHK004 Is `envelope_body_sha256` defined with hex encoding and a defined integrity-check role (e.g., delivery-time tamper detection)? [Completeness, Spec §FR-012]
- [ ] CHK005 Is `envelope_size_bytes` clearly applied to the serialized envelope (not just the raw body) to align with the FR-004 size cap? [Consistency, Spec §FR-004, §FR-012]
- [ ] CHK006 Are nullable vs non-null columns distinguished explicitly per column? [Gap, Clarity]

## Identity Capture

- [ ] CHK007 Are sender identity fields (`sender_agent_id`, `sender_label`, `sender_role`, `sender_capability`) captured at enqueue and frozen for the row's lifetime? [Completeness, Spec §FR-012, §Edge Cases]
- [ ] CHK008 Are target identity fields (`target_agent_id`, `target_label`, `target_role`, `target_capability`, `target_container_id`, `target_pane_id`) captured at enqueue, distinct from the live registry? [Completeness, Spec §FR-012, §Edge Cases]
- [ ] CHK009 Are requirements specified for handling identity fields when the referenced agent is later hard-deleted from the FEAT-006 registry? [Coverage, Spec §Edge Cases]
- [ ] CHK010 Is the precedence between stored identity and live-registry identity declared (stored wins for audit/listing; live wins for re-check eligibility)? [Clarity, Spec §FR-025, §Edge Cases]

## Timestamp Completeness

- [ ] CHK011 Is every state transition required to update a specific timestamp column with no shared-column ambiguity? [Clarity, Spec §FR-012]
- [ ] CHK012 Is `last_updated_at` required to monotonically advance on every transition? [Completeness, Spec §FR-012]
- [ ] CHK013 Is timestamp resolution (seconds vs ms vs ns) specified or explicitly left to implementer choice with a stable display contract? [Gap, Clarity]
- [ ] CHK014 Is timezone handling (UTC required, ISO 8601 display format) specified for all timestamp columns and audit/JSON outputs? [Gap, Clarity]
- [ ] CHK015 Is the relationship between `delivery_attempt_started_at` and the terminal stamps (`delivered_at` / `failed_at`) declared as a strict ordering invariant? [Clarity, Spec §FR-040, §FR-041, §FR-042]

## State & Reason Closed Sets

- [ ] CHK016 Is the `state` closed set enumerated exhaustively with no implicit synonyms (e.g., "in-progress", "pending")? [Completeness, Spec §FR-012, §FR-013]
- [ ] CHK017 Is the `block_reason` closed set enumerated exhaustively, with each value mapped to a specific check that produces it? [Completeness, Spec §FR-017, §FR-020]
- [ ] CHK018 Is the `failure_reason` closed set enumerated exhaustively, with each value mapped to a specific failure mode in the delivery worker? [Completeness, Spec §FR-018, §FR-043]
- [ ] CHK019 Are `block_reason` and `failure_reason` declared mutually exclusive on a single row, or is co-occurrence explicitly allowed? [Clarity, Gap]
- [ ] CHK020 Is `block_reason` required to be null when `state` is anything other than `blocked`? [Clarity, Gap]
- [ ] CHK021 Is `failure_reason` required to be null when `state` is anything other than `failed`? [Clarity, Gap]

## Allowed Transitions

- [ ] CHK022 Is the allowed-transitions graph closed (every valid transition listed; everything else implicitly forbidden)? [Completeness, Spec §FR-015]
- [ ] CHK023 Are operator-initiated transitions (`blocked → queued` via approve, `blocked → canceled` via cancel, `queued → blocked` via delay, `queued → canceled` via cancel) explicit and distinct from worker-initiated transitions? [Clarity, Spec §FR-015]
- [ ] CHK024 Is the `queued → blocked` transition from delivery-time re-check explicitly distinguished from operator `delay` (different `block_reason` allowed; same transition kind)? [Clarity, Spec §FR-015, §FR-025]
- [ ] CHK025 Is there a defined invariant against backward transitions from terminal states (e.g., `delivered → queued` is impossible by construction)? [Clarity, Spec §FR-014]

## Operator Metadata

- [ ] CHK026 Are `operator_action` and `operator_action_at` defined with the closed set of action values (`approved`, `delayed`, `canceled`)? [Completeness, Spec §FR-012]
- [ ] CHK027 Is the operator identity (which `agent_id` or "host-operator" sentinel performed the action) captured in addition to the action itself? [Gap, Coverage]
- [ ] CHK028 Is operator metadata required to be append-style (latest action wins, prior actions in audit) or list-style (every action retained on the row)? [Clarity, Gap]

## Routing Flag Entity

- [ ] CHK029 Are the routing flag's persisted fields (`enabled`, `last_toggled_at`, `last_toggled_by_agent_id`) enumerated as a closed set? [Completeness, Spec §Key Entities]
- [ ] CHK030 Is `last_toggled_by_agent_id` defined for the host-only case — does it use a special `host-operator` sentinel, the host user name, or null? [Gap, Clarity, §Clarifications]
- [ ] CHK031 Is the routing flag's default value on a freshly initialized state directory specified (`enabled=true`) with no implicit migration? [Completeness, Spec §FR-026]

## Notes

- Items test the data model's specification, not its SQL DDL.
- Any item flagged as `Gap` should either be made explicit in FR-012 / Key Entities, or pushed to `/speckit.plan` as a documented design-time choice.
- Check items off as completed: `[x]`.
