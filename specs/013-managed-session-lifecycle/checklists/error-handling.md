# Error Handling & Resilience Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that error-handling and resilience requirements (failure categorization, recovery, rollback) are complete, clear, consistent, and measurable across the layout-creation, registration, log-attach, remove, and recreate pipelines.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Failure Categorization

- [ ] CHK001 Are error categories enumerated (transient/recoverable vs permanent/non-recoverable)? [Completeness, Spec §FR-013]
- [ ] CHK002 Is the mapping from each error category to the resulting lifecycle state (`degraded` vs `failed`) specified for every error type? [Coverage, Spec §FR-013]
- [ ] CHK003 Are error requirements specified for surfacing the failed stage to the operator with enough granularity for action (FR-013)? [Clarity, Spec §FR-013]
- [ ] CHK004 Are requirements specified for distinguishing `degraded` from `failed` to the operator via a single observable signal? [Clarity, Spec §FR-007]

## Pipeline Coverage

- [ ] CHK005 Are error handling requirements specified for every step of the layout creation pipeline (pane create, command launch, registration, log attach)? [Completeness, Spec §FR-013]
- [ ] CHK006 Are timeout requirements specified for each launch-command, log-attach, registration step? [Gap]
- [ ] CHK007 Are retry requirements specified for transient failures (network blip during scan, tmux command failure)? [Gap]
- [ ] CHK008 Are error requirements specified for the case where `tmux kill-pane` fails during remove (FR-010)? [Gap, Spec §FR-010]
- [ ] CHK009 Are error requirements specified for the case where the daemon detects state divergence after restart (FR-020 recovery)? [Gap, Recovery Flow]

## Edge Case Coverage

- [ ] CHK010 Are error requirements specified for the "bench container disappears mid-creation" edge case? [Coverage, Exception Flow, Spec §Edge Cases]
- [ ] CHK011 Are error requirements specified for "agent command prompts before registration completes"? [Coverage, Exception Flow, Spec §Edge Cases]
- [ ] CHK012 Are error requirements specified for "log path is not host-readable" mapped to the `degraded` outcome (FR-006)? [Coverage, Spec §FR-006]
- [ ] CHK013 Are error requirements specified for the case where a recreate attempt itself fails (recursive failure)? [Gap, Coverage, Spec §FR-011]
- [ ] CHK014 Are error requirements specified for the case where the periodic scan races with creation in a way the pending-managed marker cannot resolve (e.g., marker missing or corrupted)? [Gap, Spec §FR-014]
- [ ] CHK015 Are error requirements specified for the case where a recovered managed layout (FR-020) has lost panes (tmux pane killed externally during restart window)? [Gap, Recovery Flow]

## Recovery & Rollback

- [ ] CHK016 Are partial-failure rollback requirements specified (when one pane fails, do other panes in the layout remain or get cleaned up)? [Gap, Recovery Flow]
- [ ] CHK017 Is the operator's recovery path explicit for every Edge Case bullet? [Coverage, Spec §Edge Cases]
- [ ] CHK018 Are recovery sequences specified for cascading failures (one degraded pane causes a route to break, which causes another pane to fail)? [Gap, Recovery Flow]

## Error Format & Diagnostics

- [ ] CHK019 Are error message format requirements specified (machine-readable code + human-readable message + recovery hint)? [Gap, Spec §FR-016]
- [ ] CHK020 Is the `managed_session_name_conflict` error response shape specified beyond the diagnostic string (fields, suggestion)? [Gap, Spec §FR-016]
- [ ] CHK021 Is the audit/event content for failure events specified to be sufficient for post-mortem (which pane, which stage, which command output excerpt)? [Gap, Spec §FR-015]

## Non-Functional Resilience

- [ ] CHK022 Are non-functional resilience requirements specified (max time spent in `creating` before automatic transition to `failed`)? [Gap]
- [ ] CHK023 Are requirements specified for surfacing the rejection when the daemon/container is unhealthy (FR-016) with the same diagnostic format as other failures? [Consistency, Spec §FR-016]
- [ ] CHK024 Are circuit-breaker / back-off requirements specified for repeated immediate-exit failures of the same launch command? [Gap]
