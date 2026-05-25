# Phase 0 Research: App Dashboard Extensions (v1.1)

**Created**: 2026-05-24
**Plan**: [plan.md](./plan.md)
**Source of open questions**: `[Gap]` and `[Ambiguity]` items flagged in `checklists/*` from the `/speckit.checklist` max-coverage re-verify run.

The Clarifications session in `spec.md` (2026-05-24) already resolved 12 questions. This file records decisions for the remaining open items the checklist audit surfaced. None of them block implementation; they would otherwise sit as "implementer reads the code and infers" — recording them up-front keeps the v1.1 contract auditable.

## §TS — Timestamp Format for `recommended_next_action_refreshed_at`

- **Decision**: ISO-8601 UTC string with millisecond precision, e.g., `"2026-05-24T17:23:45.123Z"`. Wall-clock source (`time.time()`-derived), not monotonic.
- **Rationale**: Matches FEAT-011's existing timestamp convention for `app.dashboard` `recents[].at` and `hints[].at` (uniform serialization across the contract). Monotonic clocks are correct for *interval* measurement (where the skip-counter window arithmetic already uses them — see §CW) but wrong for *publishing* timestamps that other systems may compare across processes or hosts.
- **Alternatives considered**: epoch milliseconds (rejected: existing field shape is ISO string), monotonic seconds (rejected: not comparable across daemon restarts).
- **Resolves**: `requirements.md` CHK009, `observability.md` CHK004.

## §CW — Clock Source for `recently_skipped_window_ms` Boundary Arithmetic

- **Decision**: `time.monotonic_ns()` for both insertion timestamps in `skip_counter.py` and the per-call read filter. Each ring-buffer entry stores `monotonic_ms` (computed once at `record_skip()` time). The dashboard reads `now_ms = time.monotonic_ns() // 1_000_000` and counts entries with `entry_ms > now_ms - 300_000`.
- **Rationale**: The window is a *bounded interval* check, not a wall-clock publish. Monotonic avoids drift from `ntp`/`systemd-timesyncd` jumps and avoids edge cases where wall-clock-backward could double-count or skip events. Daemon restart resets the monotonic origin anyway — the ring buffer dies with the process per FR-008, so cross-restart comparability is not a requirement.
- **Alternatives considered**: wall clock (rejected: NTP step / DST can corrupt counts), event timestamps from FEAT-010 (rejected: introduces a contract coupling between FEAT-010 event schema and this counter — better to record on receipt).
- **Resolves**: `requirements.md` CHK009, `testing-strategy.md` CHK015.

## §RB — Ring Buffer Sizing and Overflow Policy

- **Decision**: `collections.deque(maxlen=N)` with `N = 10_000`. Drop-oldest on overflow (free property of `deque(maxlen=…)`). Entries are stored as integer `monotonic_ms` only (no FEAT-010 event payload retained — telemetry, not audit per Assumptions).
- **Rationale**: At the FEAT-011 fixture scale (≤ 100 routes, ≤ 1k events/day) realistic skip throughput is ≪ 1 / second; 10 000 entries over a 300_000 ms window allows ~33 skips/second sustained before drop-oldest kicks in, which is multiple orders of magnitude above realistic load. Bounded memory (~80 KB) prevents the resource-exhaustion failure mode flagged by `security.md` CHK006 even if a malfunctioning FEAT-010 worker emits at high rate. Drop-oldest is the correct semantic: the dashboard shows *recent* skips, so dropping the oldest first matches the user-visible meaning.
- **Alternatives considered**: unbounded list (rejected: unbounded growth on misbehaving worker), time-keyed dict pruned per call (rejected: per-call O(n) prune cost vs deque O(1) insert; deque also gives drop-oldest for free).
- **Resolves**: `data-model.md` CHK018, `security.md` CHK006, `performance.md` CHK006.

## §CO — Recommendation Compute Cost & No-Cache Rationale

- **Decision**: Recompute on every `app.dashboard` call. No cache. Expected additive cost at FEAT-011 fixture scale: < 5 ms (precedence list is 7 short predicates; each predicate is O(1) or O(n) over a small bucket count — agents ≤ 200, panes ≤ ~500, routes ≤ 100). Concurrent calls observe the same code given identical underlying state (the function is pure; no per-call internal randomness).
- **Rationale**: Caching adds invalidation complexity and a stale-read failure mode that has no operational benefit at this scale. Per Clarifications Q8 the design is explicitly cache-free; this section records *why* that's affordable. The 500 ms FEAT-011 latency budget (SC-002) has > 100× headroom over the 5 ms estimate.
- **Alternatives considered**: per-daemon-process cache with state-change invalidation (rejected: invalidation surface = every mutation in FEAT-006/007/009/010, fragile); short TTL cache (rejected: introduces a wall-clock failure mode without a corresponding load problem).
- **Resolves**: `api.md` CHK011, `performance.md` CHK004–CHK005.

## §SS — `target.kind == subsystem` Enumeration

- **Decision**: When `recommended_next_action.code == "subsystem_degraded"` and the daemon can identify *which* subsystem is degraded, emit `target = {kind: "subsystem", id: <subsystem_name>}` where `<subsystem_name>` is one of the FEAT-011 readiness-probe names: `"docker"`, `"tmux_discovery"`, `"sqlite"`, `"jsonl"`, `"routing_worker"`, `"log_attachment_workers"`. When multiple subsystems are degraded, pick the first one in that same probe order (deterministic). When the degraded condition cannot be attributed to a specific subsystem (e.g., aggregate health-check failure), emit `target: null`.
- **Rationale**: Reuses FEAT-011's authoritative subsystem closed set rather than minting a new one. The probe-order rule mirrors the precedence-list pattern used at the recommendation level (deterministic first-match), so two implementers do not produce different `target.id` values for the same state.
- **Alternatives considered**: always `target: null` (rejected — Clarifications Q9 chose Option A which allows the new `subsystem` kind; null-only would defeat that choice); free-form string (rejected — fails the closed-set discipline checklist item).
- **Resolves**: `error-handling.md` CHK009, `data-model.md` CHK016, `observability.md` CHK007.

## §PB — Pane Bucket Priority When a Pane Qualifies for Multiple Buckets

- **Decision**: Bucket precedence is checked top-down in this order, first match wins:
  1. `discovery-degraded` (container in `degraded_scan` state)
  2. `inactive-or-stale` (container `inactive` OR `last_seen_at` predates the most recent successful scan)
  3. `discovered-and-registered` (pane row + agent registered)
  4. `discovered-and-unmanaged` (pane row, no agent)

  Concretely: a pane belonging to a `degraded_scan` container that ALSO has `last_seen_at` predating the latest successful scan goes into `discovery-degraded`, not `inactive-or-stale`. A registered pane on an `inactive` container goes into `inactive-or-stale`, not `discovered-and-registered`.
- **Rationale**: Operators acting on the dashboard need to see *operational* problems first (degraded > stale > healthy buckets); making the bucket assignment one-of-N keeps FR-019's panes cross-check trivially testable (no double-counting, no overlap).
- **Alternatives considered**: orthogonal buckets that may overlap (rejected — Clarifications Q4 chose Option A which is the "strict partition into v1.0 `total`" rule; orthogonal would break FR-019).
- **Resolves**: `data-model.md` CHK011, `observability.md` CHK006.

## §PR — `partially_configured` Agent vs Pane-Bucket Assignment

- **Decision**: An agent in `partially_configured` (per FR-020) is still counted as *registered* for the purpose of its pane's `PaneState` bucket. That is, the pane goes into `discovered-and-registered` regardless of whether the registered agent's `role`/`capability`/`label` are complete. The `partially_configured` signal lives purely in the `counts.agents.by_state` view.
- **Rationale**: `PaneState` is a property of *the pane and its container*, not of the agent occupying it. Two clarifications align on this: Clarifications Q1 defines `discovered-and-registered` as "pane row exists AND agent registered" (no configuration-completeness requirement); Clarifications Q2 defines `partially_configured` purely as an agent-attribute condition. Cross-checking against FR-019: if `partially_configured` panes were excluded from `discovered-and-registered`, the v1.0 `registered` count would no longer equal the v1.1 `discovered-and-registered` bucket, violating the cross-check.
- **Alternatives considered**: route `partially_configured` panes into a new `discovered-and-partial` bucket (rejected — would require an FR change, would break FR-019, and Clarifications Q1 chose Option A which is the 4-bucket model).
- **Resolves**: `requirements.md` CHK023.

## §FE — Failure Isolation Boundary for the Recommendation Engine

- **Decision**: The dashboard handler wraps `recommendations.compute_recommendation(state)` in a try/except. Caught exceptions are logged at WARN with a stable event name `app_dashboard_recommendation_compute_failed` and result in both `recommended_next_action` and `recommended_next_action_refreshed_at` being set to `null` in the response envelope. The rest of the v1.1 payload (`counts.panes.by_state`, `counts.agents.by_state`, route counts) is unaffected (FR-021). No new error code on the wire (the response is still a success envelope with nulls inside).
- **Rationale**: FR-021 is explicit on the response shape; this section records the corresponding daemon-side observability so an operator can correlate a `null` recommendation with a log line. Stable event name lets operators write an alert. `WARN` not `ERROR` because the dashboard remained operational.
- **Alternatives considered**: re-raise to the dispatcher (rejected — would surface as an error envelope, violates FR-021); silent null (rejected — operator can't diagnose); emit a synthetic `subsystem_degraded` (rejected — Clarifications Q11 explicitly chose Option A which is the null-fallback).
- **Resolves**: `error-handling.md` CHK006, `security.md` CHK009.

## §LB — Latency-Budget WARN Event (FR-027)

- **Decision**: When `app.dashboard` end-to-end latency exceeds `_LATENCY_BUDGET_MS` (= 500), the handler emits a single WARN log line with the stable event name `app_dashboard_latency_exceeded` and includes the actual measured latency in milliseconds plus the budget value: `app_dashboard_latency_exceeded latency_ms=<N> budget_ms=500`. The response is returned best-effort — no error code, no missing v1.1 fields, no abort of the response path. The WARN emission lives in a `try/finally` block around the full handler body so it fires regardless of success/error/exception paths.
- **Rationale**: FR-027 mandates "best-effort response + WARN log". Stable event name is required so operators can write alerts / dashboards that grep for it. Per-call emission (not throttled) is intended — each budget miss is an operator-visible datum. The WARN level (not ERROR) matches §FE's posture for the recommendation-compute-failed event: the dashboard remained operational; the latency is telemetry, not a failure.
- **Alternatives considered**: 
  - error envelope (`latency_budget_exceeded` code) — rejected: violates FR-027 best-effort.
  - throttled WARN (one-per-N-seconds) — rejected: operators want the per-call latency datum for tail-distribution analysis; FEAT-011's audit-stderr throttle exists for a different problem (sustained JSONL write failure, not per-call telemetry).
  - silent fail-soft — rejected: operators must be able to detect SC-006 regressions.
- **Stability guarantee**: the event name `app_dashboard_latency_exceeded` is frozen for v1.x. Future minors MAY add structured fields (the current line is space-delimited `key=value` pairs) but MUST NOT rename, change message-level (WARN), or drop the `latency_ms=` token.
- **Resolves**: `testing-strategy.md` CHK029 (post-FEAT-014 latency-WARN event-name canonicalization).

## §CC — Concurrent Dashboard Calls and Recommendation Determinism

- **Decision**: Two concurrent `app.dashboard` calls observing identical underlying daemon state MUST receive identical recommendation codes (same-input-same-output). The recommendation function reads state through the same service-layer accessors the dashboard already uses for the other counts; there is no per-call randomness, no global mutex, and no per-call internal cache.
- **Rationale**: The FR-010 precedence list is deterministic, the function is pure, and the recommendation reads state through the FEAT-002 socket dispatcher's single-request-per-connection model (no shared mutable per-call scratch). Concurrent calls can observe *different* state if a mutation interleaves between them, but never different recommendations for the same observed state.
- **Resolves**: `api.md` CHK011, `requirements.md` CHK024, `testing-strategy.md` CHK016.
