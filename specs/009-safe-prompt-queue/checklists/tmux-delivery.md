# tmux Delivery Mechanics Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the tmux paste-buffer delivery requirements — Protocol method signatures, buffer naming/scoping, paste-then-submit ordering, subprocess argv discipline, body-bytes typing, AST gate scope, failure-reason mapping. Tests whether the delivery mechanics are specified completely and tamper-resistant by construction — NOT whether the paste lands in the right pane.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-12
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [research.md](../research.md)

## Protocol Surface

- [X] CHK001 Four new Protocol methods declared with exact signatures in plan.md §"Implementation Notes" "tmux adapter Protocol extension".
- [X] CHK002 `body: bytes` typed as `bytes` (not `str`) in the Protocol signature; T036 enforces.
- [X] CHK003 `send_keys` `key` declared as a closed set ("Enter" only in production) inline in the Protocol signature note.
- [X] CHK004 Consistent argument ordering (`container_id, bench_user, socket_path, ...`) across the four methods (plan.md §"Implementation Notes").

## Buffer Lifecycle

- [X] CHK005 Buffer name `agenttower-<message_id>` declared as per-message scope in plan.md §"Delivery worker loop".
- [X] CHK006 `delete_buffer` required after every successful `paste_buffer` (FR-039 + plan delivery loop).
- [X] CHK007 Order `load_buffer → paste_buffer → send_keys → delete_buffer` declared in plan.md §"Delivery worker loop".
- [X] CHK008 Resolved by Group-A Q1: best-effort `delete_buffer` cleanup in a `finally` block on the failure path. Plan §"Delivery worker loop" pseudocode updated; T042 + T046 implement and test.
- [ ] CHK009 **Open**: simultaneous-worker buffer collision is implicitly impossible in MVP (single worker per Clarifications Q5) but not explicitly declared as an invariant. Could regress if a future feature spawns a worker pool.

## Subprocess Discipline

- [X] CHK010 `subprocess.run(args=[...], input=body if body else None, check=False, ...)` argv-only pattern declared in plan.md §"Implementation Notes".
- [X] CHK011 AST gate prohibited-pattern set enumerated in research §R-007.
- [X] CHK012 AST gate covers f-strings, `.format`, `%`-formatting, `.join`, `shell=True`, `os.system`, `os.popen` (research §R-007).
- [X] CHK013 `body` parameter required to appear ONLY as `input=` keyword value; enforced by AST gate (research §R-007 + T041).
- [X] CHK014 Subprocess timeouts bounded by `delivery_attempt_timeout_seconds`; `TimeoutExpired` maps to closed-set `failure_reason` (plan.md §"Implementation Notes" + spec §Assumptions "Per-attempt delivery timeout").

## Failure-Reason Mapping

- [X] CHK015 Five `failure_reason` values mapped to subprocess error categories with no semantic overlap (FR-018 + T037/T039/T040/T046).
- [X] CHK016 `tmux_paste_failed` (paste_buffer non-zero) vs `tmux_send_keys_failed` (send_keys non-zero) — distinct, T040 tests each.
- [X] CHK017 `docker_exec_failed` (docker missing / bench_user invalid) — distinct from tmux_* failures, T039 maps `FileNotFoundError`.
- [X] CHK018 `pane_disappeared_mid_attempt` (failure_reason, mid-attempt) vs `target_pane_missing` (block_reason, enqueue / re-check time) — distinguished in FR-017/FR-018 wording.
- [X] CHK019 Resolved by Group-A Q2: `delivered` is the terminal state (body has already reached the target pane); cleanup failure is logged and surfaced via `agenttower status` (orphaned-buffer warning). Plan §"Delivery worker loop" + T042 + T046 implement.

## Pre-Paste Re-check

- [X] CHK020 Three pre-paste re-check conditions declared in order (routing flag, target_active, container+pane) in research §R-006.
- [X] CHK021 Re-check runs BEFORE stamping `delivery_attempt_started_at` (plan.md §"Delivery worker loop" + research §R-006).
- [X] CHK022 Re-check data source = daemon cached state (not live `docker exec`); rationale in research §R-006.

## Test Surface

- [X] CHK023 `FakeTmuxAdapter` records every call; declared in T038 and plan.md §Testing.
- [X] CHK024 AST gate target file (`subprocess_adapter.py`) declared in research §R-007 + T041.
- [X] CHK025 Per-`failure_reason` tests declared in T046.
- [X] CHK026 SC-003 metacharacter set tests declared in T078.
- [X] CHK027 Process-tree before/after snapshot declared in T078 and SC-003 acceptance.

## Notes

- 26/27 items resolved (2 new Group-A walk resolutions appended); 1 remains open.
- **Outstanding decision for the user**: CHK009 (explicit single-worker invariant declaration to future-proof against a worker-pool change).
