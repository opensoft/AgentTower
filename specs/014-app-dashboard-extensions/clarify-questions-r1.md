# Clarification Questions — FEAT-014 App Dashboard Extensions — Round 1 (post-impl-design)

**Path (canonical, top)**: `specs/014-app-dashboard-extensions/clarify-questions-r1.md`

**Session date**: 2026-05-24
**Spec under clarification**: `specs/014-app-dashboard-extensions/spec.md`
**Mode**: post-implementation-design Round 1 — safety / contract-critical decisions
**Source**: NEEDS-CLARIFY-R1 items tagged across the 13 checklist files in `checklists/`
**Question count**: 16 (covering 17 checklist items — sec CHK002 and CHK004 are merged into Q14)
**Cap**: ≤ 25 per user-global rule (under the cap)

Reply with one of:
- The option letter for the recommended (or any) choice (e.g., `Q1: A`)
- `yes` / `recommended` to accept the recommendation
- A short free-form answer (≤ 5 words) where allowed

Answers should be written **into this same file** under the `## Answers` section below
(per the user-global "Shared File Path Coordination" rule — answers inline,
not in a separate file, not only in chat).

You can answer all 16 in one reply, e.g.:

```
Q1: A
Q2: recommended
Q3: <short answer>
...
```

## Answers

Q1: A
Q2: A
Q3: A
Q4: A
Q5: A
Q6: A
Q7: A
Q8: A
Q9: C
Q10: A
Q11: A
Q12: A
Q13: A
Q14: A
Q15: A
Q16: A

Notes:

- Keep dashboard reads resilient: state-bucket aggregation failures return zero-filled buckets and surface degradation through `subsystem_degraded` rather than breaking the whole response.
- Treat FEAT-010 as an opaque caller into the skip counter; no new skip-event wire shape or JSONL audit requirement for v1.1.
- Use FEAT-011 readiness semantics for routing-worker stalled/crashed detection; degraded counts are best-effort and rendered with degraded context.
- Interpret the dashboard latency budget as p95 <= 500 ms at documented fixture scale, waived during subsystem degradation; missed-budget calls still return best-effort and log WARN.
- Do not support scale beyond the FEAT-011 fixture envelope in v1.1; no separate CPU budget beyond per-call latency and normal polling expectations.
- Keep recommendation targets opaque and title/detail text template-bound so no free-form names, paths, credentials, host metadata, or PII are placed on the wire.
- FEAT-011/014 have no per-caller reduced dashboard response; the shape is uniform for callers that pass the local access gate.

---

## Q1. Aggregator compute-failure behavior  *(closes requirements CHK005)*

If computing `counts.panes.by_state` or `counts.agents.by_state` fails (e.g., FEAT-003/006 service-layer outage), what does `app.dashboard` return?

**Recommended:** Option A — Return `0` for every affected bucket key (consistent with FR-003) AND trigger the `subsystem_degraded` recommendation. Operator sees zeros plus a degraded signal; rest of payload remains intact (analogous to FR-021's compute-failure null fallback for `recommended_next_action`).

| Option | Description |
|--------|-------------|
| A | Affected buckets emit `0`; recommendation engine emits `subsystem_degraded` for the failing subsystem; rest of payload intact. |
| B | Affected buckets emit `null`; client must distinguish "0 means empty" from "null means failure". |
| C | Entire `app.dashboard` call returns an error envelope. |
| D | Return last-known-good state with a `stale_at` timestamp. |
| Short | Provide a different rule (≤ 5 words). |

---

## Q2. FEAT-010 routing worker failure propagation  *(closes integration CHK010)*

If the FEAT-010 routing worker is stalled or crashed, what do `counts.routes.recently_skipped_count` and `counts.routes.recently_skipped_window_ms` report?

**Recommended:** Option A — Ring buffer continues to be queried (returning whatever's in it); the recommendation engine separately triggers `subsystem_degraded` for `routing_worker`. Operator sees count + degraded signal.

| Option | Description |
|--------|-------------|
| A | Last-known buffer state returned; `subsystem_degraded` recommendation signals the issue. |
| B | Counts emit `0`; recommendation emits `subsystem_degraded`. |
| C | Counts emit `null`; recommendation emits `subsystem_degraded`. |
| D | Entire dashboard call returns an error envelope. |
| Short | Provide a different rule. |

---

## Q3. FEAT-010 contract boundary  *(closes integration CHK015)*

Does FEAT-014 require a contract guarantee at the FEAT-010 boundary (event shape, emission timing), or does the `skip_counter` ring buffer treat FEAT-010 as a trusted opaque caller that only needs to call `record_skip(monotonic_ms)`?

**Recommended:** Option A — Opaque caller; the ring buffer's contract is just the function signature `record_skip(now_ms: int) -> None`. No FEAT-010 event-shape pinning.

| Option | Description |
|--------|-------------|
| A | Opaque caller; only the `record_skip(monotonic_ms)` interface is contracted. |
| B | Pin FEAT-010 skip-event shape so the ring buffer can validate the payload. |
| C | Require FEAT-010 to also emit a JSONL audit event so dashboard data and audit data can be cross-checked. |
| Short | Provide a different rule. |

---

## Q4. Recommendation compute-failure signal beyond WARN log  *(closes observability CHK021)*

Is the WARN log line `app_dashboard_recommendation_compute_failed` the only operator-visible signal of compute failure, or should there be a separate metric/counter?

**Recommended:** Option A — WARN log only in v1.1. A metric/counter is deferred to a future minor; the WARN log is greppable and sufficient for alerting at v1.1 scale.

| Option | Description |
|--------|-------------|
| A | WARN log only in v1.1; defer metric to a future minor. |
| B | Add a `recently_failed_count` field to `counts.recommendation` (parallel to `recently_skipped_count`). |
| C | Add a JSONL audit event for each compute failure (durable trail). |
| D | Both B and C. |
| Short | Provide a different rule. |

---

## Q5. FEAT-010 worker: stalled vs crashed threshold  *(closes error-handling CHK001)*

What threshold distinguishes "stalled" (alive but not making progress) FEAT-010 worker from "crashed" for the purpose of triggering `subsystem_degraded`?

**Recommended:** Option A — Reuse FEAT-011 readiness probe semantics. Crashed = process not running OR readiness reports unhealthy; stalled = readiness reports degraded. No new threshold in v1.1.

| Option | Description |
|--------|-------------|
| A | Reuse FEAT-011 readiness probe semantics (no new threshold in v1.1). |
| B | Define an explicit heartbeat-staleness threshold (e.g., no event in 60 s when routing should be active). |
| C | No distinction; both stalled and crashed trigger `subsystem_degraded` identically. |
| Short | Provide a different rule. |

---

## Q6. "Cannot be computed" path for state buckets  *(closes error-handling CHK002)*

When the daemon cannot compute `counts.panes.by_state` or `counts.agents.by_state` (vs "not yet populated" which returns 0), what's the wire shape? (Tightly coupled to Q1 — same posture for consistency.)

**Recommended:** Option A — Treat as if the daemon CAN compute but with no data: return `0` per bucket, let the recommendation engine handle the degraded signal. Matches Q1.

| Option | Description |
|--------|-------------|
| A | Same as Q1: return `0` per bucket + `subsystem_degraded` recommendation. |
| B | Return `null` per bucket; client distinguishes by null vs 0. |
| C | Omit the `by_state` object entirely (violates additive-minor rule — probably wrong). |
| Short | Provide a different rule. |

---

## Q7. Degraded subsystem effect on counts  *(closes error-handling CHK008)*

When `recommended_next_action.code == "subsystem_degraded"` (e.g., container scanner is degraded), should clients trust `counts.panes.by_state` as authoritative, or treat it as potentially stale/partial?

**Recommended:** Option A — Counts are best-effort during degradation. Clients SHOULD render them but display a degraded-state badge alongside. Daemon does not suppress.

| Option | Description |
|--------|-------------|
| A | Counts are best-effort; client UI shows them with a degraded badge; no daemon suppression. |
| B | Daemon suppresses `counts.*.by_state` to all-0 during `subsystem_degraded`. |
| C | Daemon returns `null` for affected counts during degradation. |
| D | Counts are guaranteed authoritative; `subsystem_degraded` ONLY reflects recommendation logic, not data quality. |
| Short | Provide a different rule. |

---

## Q8. Partially-restarted daemon coherence  *(closes error-handling CHK011)*

May a partially-restarted daemon (some subsystems up, others bringing up) emit inconsistent partial fields during the bring-up window, or must it coherently report `subsystem_degraded` for every still-down subsystem?

**Recommended:** Option A — Must coherently report `subsystem_degraded` for every still-down subsystem. Partial bring-up is a degraded state; the recommendation reflects it. Counts are best-effort per Q7.

| Option | Description |
|--------|-------------|
| A | Coherent: `subsystem_degraded` for every down subsystem; counts best-effort. |
| B | May emit partial fields without `subsystem_degraded` if the down subsystem isn't required for THIS dashboard request. |
| C | Must reject dashboard calls during bring-up window (error envelope until fully up). |
| Short | Provide a different rule. |

---

## Q9. Latency budget quantile  *(closes performance CHK002)*

Is the SC-006 / FEAT-011 SC-002 ≤ 500 ms latency budget a p50, p95, p99, or worst-case bound?

**Recommended:** Option C — p95 (matches typical SLO conventions; allows tail-spikes during scan refreshes without violating the SLO).

| Option | Description |
|--------|-------------|
| A | p50 (median) ≤ 500 ms. |
| B | p99 ≤ 500 ms (strict). |
| C | p95 ≤ 500 ms. |
| D | Worst-case ≤ 500 ms (no tail allowed). |
| Short | Provide a different quantile. |

---

## Q10. Behavior when latency budget is missed  *(closes performance CHK008)*

If a dashboard call exceeds the SC-006 latency budget, what does the daemon do?

**Recommended:** Option A — Return anyway (best-effort); log a WARN with the actual latency. The dashboard is operational-visibility, so partial slowness should still surface data.

| Option | Description |
|--------|-------------|
| A | Return anyway, best-effort; log WARN with the latency. |
| B | Return partial fields (truncate slow aggregations). |
| C | Return an error envelope (e.g., `latency_budget_exceeded`). |
| D | Return cached older state with a stale-at timestamp. |
| Short | Provide a different rule. |

---

## Q11. SLO during degraded subsystem  *(closes performance CHK009)*

Does the SC-006 ≤ 500 ms budget hold during `subsystem_degraded` states, or is the budget waived during degradation?

**Recommended:** Option A — Budget waived during degradation; the recommendation already signals degraded state to the client, so slower response is an expected symptom of degradation.

| Option | Description |
|--------|-------------|
| A | Budget waived during `subsystem_degraded`. |
| B | Budget still applies; daemon must return partial/fast even when degraded. |
| C | Budget loosens to 2× (≤ 1000 ms) during degradation. |
| Short | Provide a different rule. |

---

## Q12. Behavior beyond FEAT-011 fixture scale  *(closes performance CHK012)*

What's the expected behavior when daemon state exceeds the FEAT-011 fixture scale (e.g., 500 agents instead of ≤ 200)?

**Recommended:** Option A — Undefined / unsupported in v1.1; future minor may set higher bounds. Operators should not deploy at scales above the documented fixture without expecting SC-006 violation.

| Option | Description |
|--------|-------------|
| A | Undefined in v1.1; do not deploy beyond fixture without expecting SLO violation. |
| B | Graceful degradation: SLO loosens linearly with scale. |
| C | Hard error envelope above fixture scale (`scale_exceeded`). |
| D | Document an informal "up to 2× fixture" tolerance. |
| Short | Provide a different rule. |

---

## Q13. CPU budget under sustained polling  *(closes performance CHK014)*

Is there a daemon CPU budget for dashboard calls under sustained polling (e.g., 1 req/s for an hour), or is CPU bounded only by the per-call latency budget?

**Recommended:** Option A — No separate CPU budget in v1.1; per-call latency budget + Research §CO recompute-cost model implicitly bound CPU. Operators should not poll faster than 1 req/s.

| Option | Description |
|--------|-------------|
| A | No separate CPU budget; per-call latency budget implicitly bounds CPU. |
| B | Set an explicit per-second CPU budget (e.g., ≤ 5% CPU on the FEAT-011 fixture). |
| C | Set a daemon-side polling-rate cap (e.g., reject more than 1 req/s per session). |
| Short | Provide a different rule. |

---

## Q14. `target.id` opacity  *(closes security CHK002 AND CHK004 — same question)*

Are `target.id` values opaque internal identifiers (must not contain operator-readable names or sensitive metadata), or are they human-readable identifiers?

**Recommended:** Option A — Opaque internal identifiers. `target.id` follows FEAT-003/004/006/etc. internal id format; the client resolves the id to a display name via separate `app.<entity>.detail` calls. PII-by-construction.

| Option | Description |
|--------|-------------|
| A | Opaque internal identifiers; client resolves to display name via separate calls. |
| B | Human-readable identifiers (e.g., container names directly on the wire). |
| C | Mixed — per kind: containers human-readable, panes/agents/messages opaque. (Specify per kind in answer.) |
| Short | Provide a different rule. |

---

## Q15. `title` / `detail` scrubbing requirements  *(closes security CHK003)*

Must `title` / `detail` strings be scrubbed of any operator-only data (paths, credentials, host metadata) before being placed on the wire? (Note: the FR-011 EDIT + `contracts/closed-sets-v1_1.md` §Per-code title/detail Templates already pin these to fixed templates with only `{N}` and `{subsystem_name}` substitution; this question confirms that template discipline IS the scrubbing rule, vs. wanting an additional pass.)

**Recommended:** Option A — Template discipline IS the scrubbing rule. `title` / `detail` are drawn from the per-code templates in `contracts/closed-sets-v1_1.md` §Per-code title/detail Templates (only `{N}` integer + `{subsystem_name}` closed-set substitutions). No free-form daemon prose can reach the wire, so the no-PII / no-secret guarantee falls out by construction. No additional scrubbing pass needed.

| Option | Description |
|--------|-------------|
| A | Template discipline IS the scrubbing rule (no free-form prose; no additional pass). |
| B | Add an explicit scrubbing pass at the wire boundary in addition to template discipline. |
| C | Allow free-form per-deployment overrides of templates (with required scrubbing). |
| Short | Provide a different rule. |

---

## Q16. Per-caller suppression / reduced response  *(closes security CHK010)*

Is there ever a case where v1.0 fields are suppressed per-caller (e.g., a less-privileged client gets a reduced response), and if so, does FEAT-014's compute-failure null fallback preserve that suppression?

**Recommended:** Option A — No per-caller suppression in FEAT-011 v1.0 (`app.dashboard` returns the same shape to all callers who pass the host-only gate). FR-023 (auth inherited unchanged) implies no per-caller suppression in v1.1. Compute-failure null fallback applies uniformly.

| Option | Description |
|--------|-------------|
| A | No per-caller suppression in v1.0 or v1.1; uniform shape; uniform null fallback. |
| B | Per-caller suppression exists in FEAT-011 — please identify it so FEAT-014 can verify it's preserved. |
| C | Document a future per-caller suppression mechanism (out of scope for v1.1; affirm here). |
| Short | Provide a different rule. |

---

**Path (canonical, bottom)**: `specs/014-app-dashboard-extensions/clarify-questions-r1.md`

**Awaiting answers above under `## Answers`.** Once filled in, re-invoke `/speckit-clarify` (or just ping the next session) and I'll fold these into `spec.md` as a new `### Session 2026-05-24-r1` block under the existing `## Clarifications` section, then update the affected FRs / contracts / data-model accordingly.
