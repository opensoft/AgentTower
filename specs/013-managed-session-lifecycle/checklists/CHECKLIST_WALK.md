# Checklist Walk — Pre-Implement Audit (Session 2026-05-24)

**Purpose**: Bucket every incomplete checklist item against the current artifact set (spec.md + plan.md + research.md + data-model.md + contracts/* + tasks.md + quickstart.md) before `/speckit.implement` runs. Each item is one of:

- **RESOLVED** — already answered by a downstream artifact; the checklist item was written against an earlier (pre-plan or pre-tasks) snapshot.
- **DEFERRED** — explicitly out of scope for FEAT-013 (UX is FEAT-012/014's domain, MVP scoping per spec §Assumptions and FR-018), or operator-of-implementation-only with no spec-level decision needed.
- **OPEN** — genuinely needs a spec-level decision; surfaced into the post-walk clarify round.

This file is a snapshot — the underlying checklist files are not retroactively ticked (they remain authoritative pre-{plan, tasks} audit artifacts).

## Per-file buckets

| File | Total | Resolved | Deferred | Open | Open items (CHK IDs) |
|---|---:|---:|---:|---:|---|
| ux.md | 25 | 0 | 25 | 0 | — (all UX deferred to FEAT-012/014) |
| api.md | 29 | 24 | 1 | 4 | CHK016, CHK022, CHK023, CHK027 |
| data-model.md | 33 | 30 | 0 | 3 | CHK023, CHK032, CHK033 |
| security.md | 23 | 11 | 6 | 6 | CHK009, CHK010, CHK011, CHK012, CHK014, CHK020 |
| performance.md | 17 | 11 | 4 | 2 | CHK001, CHK008 |
| accessibility.md | 13 | 0 | 13 | 0 | — (a11y deferred to FEAT-012/014) |
| error-handling.md | 24 | 13 | 3 | 8 | CHK002, CHK006, CHK007, CHK008, CHK014, CHK016, CHK018, CHK024 |
| observability.md | 21 | 12 | 3 | 6 | CHK002, CHK006, CHK007, CHK008, CHK010, CHK019 |
| integration.md | 21 | 17 | 1 | 3 | CHK008, CHK012, CHK013 |
| configuration.md | 17 | 8 | 3 | 6 | CHK005, CHK006, CHK009, CHK010, CHK014, CHK017 |
| idempotency.md | 17 | 12 | 0 | 5 | CHK005, CHK012, CHK013, CHK014, CHK017 |
| testing-strategy.md | 19 | 17 | 0 | 2 | CHK015, CHK019 |
| deployment.md | 13 | 7 | 3 | 3 | CHK006, CHK008, CHK010 |
| concurrency.md | 19 | 12 | 1 | 6 | CHK003, CHK006, CHK009, CHK011, CHK013, CHK016 |
| plan-review.md | 53 | 47 | 0 | 0 | resolved by analyze rounds + amendments |
| alignment-check.md | 38 | 38 | 0 | 0 | resolved by alignment-cleanup + analyze remediation |
| alignment-recheck.md | 24 | 21 | 3 | 0 | post-tasks forward-pointing items resolved on implement |
| tasks-readiness.md | 60 | 53 | 0 | 0 | 7 ticked; remaining resolved by tasks.md content |
| requirements.md | 51 | 50 | 0 | 1 | CHK001 cross-cutting (informational, no decision needed) |
| **Total** | **517** | **383** | **66** | **54** | |

## Open items grouped by clarify topic

After dedup, the 54 open items collapse to **8 distinct clarification topics** that warrant operator decisions before implementation. Each topic affects operator-visible behavior, FR/SC testability, or contract shape:

| Topic | CHK refs | Why it matters |
|---|---|---|
| **A. Per-step timeouts + retry policy** | error-handling.md CHK006, CHK007, CHK008 | FR-013 enum names `failed_stage` values but the spec is silent on how long the daemon waits at each stage before transitioning to `failed`, and whether transient failures retry. Tests can't be deterministic without this. |
| **B. Partial-layout-failure rollback** | error-handling.md CHK016, CHK018; api.md CHK023, CHK026 | When one pane fails mid-create-layout, do other in-flight panes continue, get cleaned up, or stay as-is? FR-013 says "leaves a recoverable lifecycle state" but doesn't define which. |
| **C. Event redaction policy** | security.md CHK012, CHK014; observability.md CHK019 | Lifecycle events contain launch-command argv, env, working_dir. What gets redacted in JSONL audit? Affects FR-015 / FR-021 + security posture. |
| **D. Operator-input validation** | security.md CHK010, CHK011; configuration.md CHK009; api.md CHK016 | Allowed character set / length limits for `tmux_session_name`, `label_pattern`, and `launch_command_overrides` keys. Currently no explicit constraints; sanitization needed before tmux RPC. |
| **E. Event stream ordering guarantees** | concurrency.md CHK016; observability.md CHK002, CHK013 | FR-015 says "emit observable lifecycle events" but no ordering guarantee (per-pane FIFO? per-layout FIFO? cross-pane best-effort?). Consumers (FEAT-008, FEAT-013 detail surfaces) need this. |
| **F. Concurrent recreates of same predecessor** | concurrency.md CHK003, CHK011; idempotency.md CHK014, CHK017 | Two `recreate_pane(predecessor_id=X)` calls in flight. R10 covers create-layout idempotency-key replay, but recreate is silent. Behavior options: one wins / both replay via key / `LOCK_BUSY` error. |
| **G. Spec-level scale limits** | performance.md CHK001, CHK008; integration.md CHK008 | Plan §Scale informally says ≤4 layouts × ≤10 containers × ≤4 panes. Should max concurrent managed layouts per daemon be promoted to spec as a quantified constraint, or stay plan-informational? |
| **H. First-run operator-config experience** | configuration.md CHK005, CHK006, CHK010, CHK014, CHK017; deployment.md CHK006, CHK008, CHK010 | Operator overrides via YAML under `~/.config/opensoft/agenttower/`. First install: ship example YAMLs (per T003 already references `examples/`), leave empty dirs, or auto-create with TEMPLATE comments? Plus hot-reload behavior. |

The remaining 54 − (∑items in 8 topics) ≈ 12 individual items are either narrow edge-case clarifications subsumed by the 8 topics' answers, or implementer-level decisions safely deferred to `/speckit.implement` with reasonable defaults (e.g., observability metrics, trace IDs, deployment rollback — all post-MVP).

## What this means for /speckit.implement

- **0 implementation-blocking gaps**: every FR/SC traces to ≥1 task; the 8 open topics affect *quality* of the implementation, not whether it's executable.
- **8 clarifications would tighten test design**: per-step timeouts (A), rollback semantics (B), redaction (C), input validation (D), event ordering (E), recreate concurrency (F) — each makes 1–3 tasks more deterministic.
- **2 are documentation hardening**: scale limits in spec (G), first-run experience (H) — operator-visible polish.

The clarify round below covers all 8 topics.
