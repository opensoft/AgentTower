# Error Handling & Resilience Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that error-handling and resilience requirements (failure categorization, recovery, rollback) are complete, clear, consistent, and measurable across the layout-creation, registration, log-attach, remove, and recreate pipelines.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Failure Categorization

- [x] CHK001 Are error categories enumerated (transient/recoverable vs permanent/non-recoverable)? [Completeness, Spec §FR-013]
- [x] CHK002 Is the mapping from each error category to the resulting lifecycle state (`degraded` vs `failed`) specified for every error type? [Coverage, Spec §FR-013]
- [x] CHK003 Are error requirements specified for surfacing the failed stage to the operator with enough granularity for action (FR-013)? [Clarity, Spec §FR-013]
- [x] CHK004 Are requirements specified for distinguishing `degraded` from `failed` to the operator via a single observable signal? [Clarity, Spec §FR-007]

## Pipeline Coverage

- [x] CHK005 Are error handling requirements specified for every step of the layout creation pipeline (pane create, command launch, registration, log attach)? [Completeness, Spec §FR-013]
- [x] CHK006 Are timeout requirements specified for each launch-command, log-attach, registration step? [Gap]
- [x] CHK007 Are retry requirements specified for transient failures (network blip during scan, tmux command failure)? [Gap]
- [x] CHK008 Are error requirements specified for the case where `tmux kill-pane` fails during remove (FR-010)? [Gap, Spec §FR-010]
- [x] CHK009 Are error requirements specified for the case where the daemon detects state divergence after restart (FR-020 recovery)? [Gap, Recovery Flow]

## Edge Case Coverage

- [x] CHK010 Are error requirements specified for the "bench container disappears mid-creation" edge case? [Coverage, Exception Flow, Spec §Edge Cases]
- [x] CHK011 Are error requirements specified for "agent command prompts before registration completes"? [Coverage, Exception Flow, Spec §Edge Cases]
- [x] CHK012 Are error requirements specified for "log path is not host-readable" mapped to the `degraded` outcome (FR-006)? [Coverage, Spec §FR-006]
- [x] CHK013 Are error requirements specified for the case where a recreate attempt itself fails (recursive failure)? [Gap, Coverage, Spec §FR-011]
- [x] CHK014 Are error requirements specified for the case where the periodic scan races with creation in a way the pending-managed marker cannot resolve (e.g., marker missing or corrupted)? [Gap, Spec §FR-014]
- [x] CHK015 Are error requirements specified for the case where a recovered managed layout (FR-020) has lost panes (tmux pane killed externally during restart window)? [Gap, Recovery Flow]

## Recovery & Rollback

- [x] CHK016 Are partial-failure rollback requirements specified (when one pane fails, do other panes in the layout remain or get cleaned up)? [Gap, Recovery Flow]
- [x] CHK017 Is the operator's recovery path explicit for every Edge Case bullet? [Coverage, Spec §Edge Cases]
- [x] CHK018 Are recovery sequences specified for cascading failures (one degraded pane causes a route to break, which causes another pane to fail)? [Gap, Recovery Flow]

## Error Format & Diagnostics

- [x] CHK019 Are error message format requirements specified (machine-readable code + human-readable message + recovery hint)? [Gap, Spec §FR-016]
- [x] CHK020 Is the `managed_session_name_conflict` error response shape specified beyond the diagnostic string (fields, suggestion)? [Gap, Spec §FR-016]
- [x] CHK021 Is the audit/event content for failure events specified to be sufficient for post-mortem (which pane, which stage, which command output excerpt)? [Gap, Spec §FR-015]

## Non-Functional Resilience

- [x] CHK022 Are non-functional resilience requirements specified (max time spent in `creating` before automatic transition to `failed`)? [Gap]
- [x] CHK023 Are requirements specified for surfacing the rejection when the daemon/container is unhealthy (FR-016) with the same diagnostic format as other failures? [Consistency, Spec §FR-016]
- [x] CHK024 Are circuit-breaker / back-off requirements specified for repeated immediate-exit failures of the same launch command? [Gap]

---

## Walk closure (2026-05-25)

24/24 items resolved by FR-013 amendment (30s per-stage timeout + 2x retry with 1s/2s back-off + the closed transient set from spec §Assumptions, all from pre-implement walk topic A) + R7 (failed_stage closed enum) + FR-026 (no-cascade-kill rollback from pre-implement walk topic B) + FR-016 (validation_failed before tmux RPC) + error-codes.md (13 closed-set codes with operator-action prose) + R13 (transient vs non-recoverable mapping to degraded/failed).
