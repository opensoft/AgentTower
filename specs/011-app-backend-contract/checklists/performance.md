# Performance Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for latency budgets, throughput, scan timeout, and side-effect-free read paths.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are performance targets defined for every contract surface, or only `app.dashboard` (SC-002 ≤500ms) and the adopt round-trip (SC-004 ≤2s)? [Coverage, Spec §SC-002, §SC-004]
- [ ] CHK002 Are performance targets defined for `app.readiness`, `app.preflight`, `app.hello`, `app.<entity>.list`, `app.<entity>.detail`? [Gap]
- [ ] CHK003 Are performance targets defined under different scale assumptions (e.g., 10 vs 100 vs 1000 agents; 10 vs 10,000 events)? [Gap, Spec §FR-018]
- [ ] CHK004 Are performance targets defined for `app.scan.containers` / `app.scan.panes` under healthy vs slow Docker — beyond just the 30s `scan_timeout` cap? [Gap, Spec §FR-030b]
- [ ] CHK005 Is the SC-002 baseline fixture defined precisely (cold start, daemon running, ≥1 container, ≥1 agent — but how many specifically)? [Clarity, Spec §SC-002]
- [ ] CHK006 Is "no-cache test" (SC-002) defined operationally (which caches must be cleared — daemon-side dashboard cache? OS page cache?)? [Clarity, Spec §SC-002]

## Requirement Clarity

- [ ] CHK007 Is "cold start" (SC-002) defined — process start of the harness, or process start of the daemon? [Clarity, Spec §SC-002]
- [ ] CHK008 Is wall-clock measurement methodology specified for SC-002 and SC-004 (which clock — monotonic vs real)? [Clarity, Spec §SC-002, §SC-004]
- [ ] CHK009 Is "side-effect-free" (FR-045) implicitly a performance requirement (no I/O latency) or only a behavioral one? [Ambiguity, Spec §FR-045]
- [ ] CHK010 Is "≤ 500 ms" (SC-002) defined as p50, p95, p99, or worst-case across a defined number of trials? [Ambiguity, Spec §SC-002]
- [ ] CHK011 Is "≤ 2 s" (SC-004) for the adopt round-trip a sum across all four calls, or each call individually? [Ambiguity, Spec §SC-004]

## Requirement Consistency

- [ ] CHK012 Are FR-018 (no global lock on dashboard) and SC-002 (≤500ms) consistent under worst-case composition over many entities? [Consistency, Spec §FR-018, §SC-002]
- [ ] CHK013 Is the 30-second `scan_timeout` cap (FR-030b) consistent with SC-002 and SC-004 budgets — could an in-progress scan starve the dashboard? [Consistency, Spec §FR-030b]
- [ ] CHK014 Is "cheap and side-effect-free" (FR-045) consistent with the implementation effort of composing the dashboard (which reads many tables)? [Consistency, Spec §FR-045]

## Scenario Coverage

- [ ] CHK015 Are requirements defined for performance under concurrent app sessions (does SC-002 hold with N sessions hitting `app.dashboard` simultaneously)? [Gap]
- [ ] CHK016 Are requirements defined for performance regression detection (must the contract test suite record timings over time, or only assert pass/fail)? [Gap]
- [ ] CHK017 Is the behavior defined when an `app.*` call exceeds an expected latency budget (does the daemon return early with a closed-set code, or always wait)? [Gap]
- [ ] CHK018 Are throughput requirements defined (requests per second sustainable, max queue depth)? [Gap]
- [ ] CHK019 Is the polling cadence for `app.scan.status` recommended or required (to avoid pathological tight loops)? [Gap, Spec §FR-030b]

## Measurability

- [ ] CHK020 Are SC-002 and SC-004 measurable on a defined hardware class, or is "workstation" intentionally loose? [Ambiguity, Spec §SC-002, §SC-004]
- [ ] CHK021 Can SC-002's "wall-clock from `app.hello` request send to `app.dashboard` response receive" be reproduced by a deterministic harness? [Measurability, Spec §SC-002]
- [ ] CHK022 Can the 30s `scan_timeout` (FR-030b) be deterministically tested with a synthetic slow scan fixture? [Measurability, Spec §FR-030b]
- [ ] CHK023 Is "≤ 500 ms" (SC-002) testable on CI hardware, or only on a developer workstation? [Measurability, Spec §SC-002]

## Ambiguities, Conflicts, Gaps

- [ ] CHK024 Is there a worst-case bound for `app.events.list` when the JSONL is large (no pagination skip mechanism specified for very deep history)? [Gap, Spec §FR-019, §FR-021]
- [ ] CHK025 Is there an SLA defined for `app.scan.status` polling latency? [Gap]
- [ ] CHK026 Is the rule defined for performance budgets in degraded readiness states (does `app.dashboard` still meet SC-002 when Docker is unavailable)? [Gap, Spec §US4 acceptance 4, §SC-002]
