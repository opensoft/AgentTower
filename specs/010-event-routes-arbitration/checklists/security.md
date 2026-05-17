# Security Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for FEAT-010's security surface — redaction enforcement, permission-gate reuse, kill-switch preservation, template-injection safety, and DoS-bounding.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## Redaction Enforcement

- [X] CHK001 Is FEAT-007 redaction non-bypassable for `{event_excerpt}` template substitution? [Clarity, Spec §FR-026]
- [X] CHK002 Are the raw-pass template fields (`event_id`, `event_type`, `source_agent_id`, `source_label`, `source_role`, `source_capability`, `observed_at`) explicitly designated as non-sensitive with justification? [Gap, Spec §FR-008]
- [X] CHK003 Is the redaction outcome guaranteed identical between the queue body and the audit excerpt for the same event? [Consistency, Spec §FR-026, FR-036]
- [X] CHK004 Are post-redaction body validations (UTF-8, NUL, encoding) specified to catch redaction-residue characters? [Spec §FR-027, FR-037]
- [X] CHK005 Is the redaction failure mode (FEAT-007 errors) mapped to a `route_skipped` reason? [Gap, Spec §FR-037]
- [X] CHK006 Is operator-controlled vs user-controlled data clearly delineated in the template-field whitelist rationale? [Gap]

## Permission Gate & Kill Switch

- [X] CHK007 Is the FEAT-009 permission gate non-bypassable from FEAT-010's enqueue path? [Clarity, Spec §FR-024, FR-032]
- [X] CHK008 Is "FEAT-010 may restrict but never broaden FEAT-009 permission rules" testable? [Measurability, Spec §FR-055]
- [X] CHK009 Is the kill-switch behavior preserved for route-generated rows (lands in `blocked` with `block_reason=kill_switch_off`)? [Spec §FR-032, Story 5 #1]
- [X] CHK010 Is the cursor-advance-during-kill-switch-off specified (route consumes the event regardless of delivery)? [Consistency, Spec §Story 5, Edge Cases]
- [X] CHK011 Is `target_rule=source` against a master-role source mapped to `target_role_not_permitted` (FEAT-009 inheritance)? [Spec §FR-022, Story 5 #4]

## Authorization Boundaries

- [X] CHK012 Is the authorization model for `route` CRUD (host-user only? bench-container too?) explicitly documented? [Gap, Spec §Assumptions]
- [X] CHK013 Is the `agenttower routing enable/disable` host-only restriction from FEAT-009 honored by FEAT-010? [Consistency, Spec §Story 5]
- [X] CHK014 Is the `host-operator` sentinel collision-free with real `agt_*` UUIDs (per FEAT-009 inheritance)? [Spec §FR-001]
- [X] CHK015 Are bench-container callers' read-access boundaries for `route list` / `route show` specified? [Gap]
- [X] CHK016 Is the threat model (untrusted slave events → trusted operator routes → daemon enqueue → trusted master sender) explicit? [Gap]

## Template-Injection Safety

- [X] CHK017 Is template grammar restricted to a closed `{field}` whitelist (no expressions, no nested interpolation, no function calls)? [Clarity, Spec §FR-025]
- [X] CHK018 Is the absence of shell-style or escape-sequence interpretation explicit? [Spec §FR-025, Gap]
- [X] CHK019 Are unknown-field references rejected at `route add` time (closed-set `route_template_invalid`), not at fire time? [Spec §FR-008, FR-028, Story 6 #2]
- [X] CHK020 Are missing-field-at-render-time errors mapped to `route_skipped(template_render_error/missing_field)` without silent placeholder substitution? [Spec §FR-028]

## Audit Integrity

- [X] CHK021 Are FEAT-010 audit entries free of unredacted secrets even when source events contain sensitive substrings? [Spec §FR-026, FR-036]
- [X] CHK022 Is the audit-tamper resistance specified (append-only JSONL, no in-place edit)? [Gap, FEAT-008 inheritance]
- [X] CHK023 Are operator catalog operations (`route_created`, `route_deleted`) sufficient to reconstruct security-relevant history? [Coverage, Spec §FR-035]
- [X] CHK024 Is the `created_by_agent_id` field on `route_created` adequately scoped to identify the responsible caller? [Spec §FR-001, Gap]

## Denial-of-Service Bounds

- [X] CHK025 Are route-flood DoS vectors (operator creates 1M routes) bounded by storage or rate-limit requirements? [Gap, Spec §SC-006]
- [X] CHK026 Is template body size at `route add` time capped to prevent storage exhaustion via oversized templates? [Gap]
- [X] CHK027 Are routing-cycle-DoS vectors (one route generates millions of skips per cycle) bounded by FR-041 batch cap? [Coverage, Spec §FR-041]
- [X] CHK028 Is the audit JSONL growth rate bounded against an attacker spamming `route_skipped` reasons? [Gap, Spec §FR-039]

## Trust Boundaries with Other Features

- [X] CHK029 Is FEAT-008 event-source authenticity (events can't be forged by slaves) inherited and documented? [Gap]
- [X] CHK030 Is the "no model-based decisions" requirement (FR-053) enforceable as a security boundary against prompt-injection-driven routing? [Spec §FR-053]

## Coverage-Gap Remediation (added 2026-05-16 per coverage.md audit)

- [X] CHK031 Is the explicit exclusion of non-event triggers (timers, polling of arbitrary state, file watchers, external webhooks) documented as a scope boundary that prevents accidental scope creep into the routing worker? [Boundary, Spec §FR-052]
- [X] CHK032 Is SC-005's 100% threshold (100% of route-generated rows under kill-switch-off land in `blocked` with `block_reason=kill_switch_off` AND 0% reach the target pane AND the route's cursor advances exactly once per matching event) specified with explicit pass/fail criteria for each clause? [Measurability, Spec §SC-005, FR-032]
