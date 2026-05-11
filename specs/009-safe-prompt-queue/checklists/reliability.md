# Reliability & Durability Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the state machine, crash recovery, delivery-worker invariants, per-target FIFO, concurrency model, and shutdown lifecycle. Tests whether the durability requirements themselves are complete, deterministic, and operator-verifiable — NOT whether the implementation crashes.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## State Machine Invariants

- [ ] CHK001 Are the five queue states declared as the only valid values, with no implicit "draft" / "pending" / "in-progress" intermediate state slipped in elsewhere? [Completeness, Spec §FR-013]
- [ ] CHK002 Is the set of allowed state transitions enumerated as a closed list (everything else implicitly forbidden), not just illustrated by examples? [Completeness, Spec §FR-015]
- [ ] CHK003 Are terminal states explicitly distinguished from non-terminal states with an enforceable invariant ("no further transitions allowed")? [Clarity, Spec §FR-014]
- [ ] CHK004 Is the requirement that terminal-state mutations exit non-zero with `terminal_state_cannot_change` stated as a hard MUST? [Clarity, Spec §FR-014]
- [ ] CHK005 Is the `queued → blocked` transition from delivery-time re-check explicitly distinguished from operator-initiated `delay`, with different `block_reason` values? [Clarity, Spec §FR-015, §FR-025]
- [ ] CHK006 Are operator-initiated transitions distinguished from worker-initiated transitions in the spec's transition table? [Consistency, Spec §FR-015]

## Crash Recovery Requirements

- [ ] CHK007 Is the crash-recovery trigger condition defined precisely (`delivery_attempt_started_at` set AND all terminal stamps unset)? [Clarity, Spec §FR-040]
- [ ] CHK008 Is the recovery transition ordering requirement explicit (recovery completes BEFORE worker begins picking up new work)? [Clarity, Spec §FR-040]
- [ ] CHK009 Is the recovery transition required to produce exactly one audit entry, in the same format as non-recovery transitions? [Completeness, Spec §US6 #2, §FR-046]
- [ ] CHK010 Are non-interrupted rows (`queued`/`blocked`/`delivered`/`failed`/`canceled` without in-flight ambiguity) required to be preserved byte-for-byte across restart? [Completeness, Spec §FR-016, §US6 #3]
- [ ] CHK011 Is preservation of deliverability for `queued` rows whose delivery never started — across a clean restart — explicitly stated? [Clarity, Spec §FR-012a, §Clarifications]
- [ ] CHK012 Is the recovery transition required to NOT issue a second tmux paste under any circumstances? [Clarity, Spec §FR-040, §SC-004]

## Delivery Worker Invariants

- [ ] CHK013 Is the commit ordering of `delivery_attempt_started_at` (committed to SQLite BEFORE any tmux invocation) stated as a hard MUST with rationale? [Clarity, Spec §FR-041]
- [ ] CHK014 Is the commit ordering of the terminal stamp (BEFORE the worker picks up the next row for the same target) stated explicitly? [Clarity, Spec §FR-042]
- [ ] CHK015 Are `failure_reason` closed-set values mapped to specific tmux/docker error categories, with no catch-all "other" value? [Completeness, Spec §FR-018, §FR-043]
- [ ] CHK016 Is the delivery worker's source of truth for `envelope_body` specified as the persisted SQLite row (re-read at the start of each attempt), not in-memory state carried from enqueue? [Clarity, Spec §FR-012a, §Clarifications]
- [ ] CHK017 Are requirements specified for the worker's behavior when `docker exec` fails before any tmux command is invoked (does the row still get `delivery_attempt_started_at`)? [Coverage, Gap]

## Per-Target FIFO

- [ ] CHK018 Is per-target FIFO defined with a measurable invariant ("at most one row with `delivery_attempt_started_at` set and terminal stamps unset, per `target_agent_id`, at any moment")? [Measurability, Spec §FR-044]
- [ ] CHK019 Is the per-target FIFO requirement stated independently of the chosen concurrency model so it survives a future worker-pool change? [Clarity, Spec §FR-044, §FR-045]
- [ ] CHK020 Is the FIFO success criterion stated in externally observable terms (`delivered`-order matches `enqueued_at`-order modulo non-delivered states)? [Measurability, Spec §SC-010]
- [ ] CHK021 Are tie-breaking rules for identical `enqueued_at` timestamps specified (e.g., `message_id` lexical order)? [Clarity, Spec §FR-031, §Edge Cases]

## Concurrency Model

- [ ] CHK022 Is the MVP concurrency model fixed to a single delivery worker, with rationale, and true cross-target parallelism explicitly deferred? [Clarity, Spec §FR-045, §Clarifications]
- [ ] CHK023 Is the worker's ready-row selection ordering specified deterministically (`(enqueued_at, message_id)` ascending)? [Clarity, Spec §FR-045, §Clarifications]
- [ ] CHK024 Is the worker's wakeup / polling cadence defined, or explicitly left as an implementation detail with bounded operator-visible latency? [Gap, Coverage]

## Shutdown & Lifecycle

- [ ] CHK025 Is the behavior of `send-input` during daemon shutdown defined with a specific closed-set error (`daemon_shutting_down`)? [Coverage, Spec §Edge Cases, §FR-049]
- [ ] CHK026 Are requirements specified for graceful shutdown's handling of in-flight delivery attempts (drain to terminal vs abort and rely on restart recovery)? [Gap, Coverage]
- [ ] CHK027 Are requirements defined for the daemon's behavior when SQLite is locked or unwritable at startup (does it refuse to serve, or serve read-only)? [Gap, Coverage]
- [ ] CHK028 Are the operator-visible signals during a degraded JSONL-buffering state defined (so the operator can detect a daemon that is "delivering but not auditing")? [Coverage, Spec §FR-048]
- [ ] CHK029 Is the durability boundary for `daemon_state` (kill-switch flag) defined with the same restart-survival guarantees as `message_queue` rows? [Consistency, Spec §FR-026, §FR-016]
- [ ] CHK030 Are requirements specified for what counts as a "successful tmux paste plus submit keystroke" (e.g., does paste return code suffice, or is a pane-content read required)? [Clarity, Spec §FR-042]

## Notes

- These items test the durability spec, not the running system. A failing item indicates a requirement that an operator could not verify, a worker that could be implemented two ways, or a recovery path that is not pinned down.
- Resolution path: clarify FRs, add Edge Cases, or convert assumptions into measurable success criteria.
- Check items off as completed: `[x]`.
