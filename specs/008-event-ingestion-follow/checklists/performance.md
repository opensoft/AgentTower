# Performance Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that latency, throughput, scale, memory, and concurrency requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Are end-to-end latency requirements specified (write → reader cycle → SQLite commit → CLI render) for all three CLI surfaces (`events`, `events --follow`, `events --json`)? [Completeness, Spec §SC-001, SC-002]
- [ ] CHK002 Is the per-record classifier latency budget specified at the spec level (the plan §"Performance Goals" cites ≤ 1 ms; is this a spec-grade requirement)? [Completeness, Gap]
- [ ] CHK003 Are SQLite commit latency budgets specified (per emitted event under FR-006 atomicity)? [Completeness, Gap]
- [ ] CHK004 Are JSONL append latency budgets specified (per FR-025 / FR-029 success path)? [Completeness, Gap]
- [ ] CHK005 Are query-latency requirements specified for `events.list` against large tables (millions of rows)? [Completeness, Gap]
- [ ] CHK006 Are throughput requirements specified for the reader (events/second per attachment under upper-bound load)? [Completeness, Gap]
- [ ] CHK007 Are concurrency requirements specified for simultaneous `events --follow` sessions (target N, max N)? [Completeness, Gap]
- [ ] CHK008 Are memory bounds specified for per-attachment cycle state, debounce state, and the FR-040 in-memory buffer? [Completeness, Spec §FR-019, FR-040]
- [ ] CHK009 Are memory bounds specified for the follow-session registry under upper-bound concurrent-follower load? [Completeness, Gap]
- [ ] CHK010 Are degradation-under-load requirements specified (what happens at 2× / 5× MVP scale; graceful or hard-cap)? [Completeness, Gap]
- [ ] CHK011 Are CPU budgets specified for one reader cycle (% of one core under upper-bound load)? [Completeness, Gap]

## Requirement Clarity

- [ ] CHK012 Is "≤ 1 reader cycle (≤ 1 s wall-clock at MVP scale)" precise enough about whether the cycle bound is real wall-clock or a logical-clock model in tests? [Clarity, Spec §FR-001]
- [ ] CHK013 Is "within one reader cycle of the underlying log write" measurable from a deterministic wall-clock event (e.g., `fsync` completion) rather than from a soft notion like "log was written"? [Clarity, Spec §SC-002]
- [ ] CHK014 Is "MVP scale" defined unambiguously (≤ 50 agents, ≤ a few KB/s per agent — but what is "few", exactly)? [Clarity, Spec §Assumptions]
- [ ] CHK015 Is "documented MVP page size (≤ 50)" precise about default vs maximum (the plan locks both as 50)? [Clarity, Spec §FR-030, Plan]
- [ ] CHK016 Is "follow_long_poll_max_seconds" defined at the spec level as a contract, or is it solely a plan-level default? [Clarity, Plan §"Defaults locked", Gap]

## Requirement Consistency

- [ ] CHK017 Are the SC-001 (5 s) and SC-002 (1 s) latency targets consistent with the FR-001 (1 s) reader cycle cap (i.e., 1 reader cycle + commit + render fits within 5 s, easily)? [Consistency, Spec §SC-001, SC-002, FR-001]
- [ ] CHK018 Is the per-cycle byte cap (FR-019) consistent with the per-event excerpt cap (Edge Cases) for the worst-case fan-out (one cycle's bytes producing N events at excerpt cap)? [Consistency, Spec §FR-019, Edge Cases]
- [ ] CHK019 Are reader memory bounds consistent between the cycle buffer (≤ 64 KiB), the FR-040 degraded deque (≤ 64 KiB), and the upper-bound 50-agent scale (≤ 6.4 MiB total)? [Consistency, Plan §"Performance Goals"]
- [ ] CHK020 Is the follow-session idle timeout (5 min) consistent with the long-poll budget (30 s) such that a healthy follower never times out (idle ≤ poll budget × N polls between activity)? [Consistency, Plan §R9]

## Acceptance Criteria Quality

- [ ] CHK021 Is SC-001 measurable with a deterministic trigger (e.g., fixture line written → CLI returns within 5 s under controlled load)? [Measurability, Spec §SC-001]
- [ ] CHK022 Is SC-002 measurable without flaky timing assertions on slow CI runners? [Measurability, Spec §SC-002]
- [ ] CHK023 Are acceptance criteria specified for `events.list` query latency at large-table scale (e.g., median ≤ 50 ms at 1M rows)? [Measurability, Gap]
- [ ] CHK024 Are acceptance criteria specified for the reader's per-cycle CPU budget (e.g., median ≤ X% of one core)? [Measurability, Gap]
- [ ] CHK025 Are acceptance criteria specified for memory ceiling under upper-bound concurrent-follower load? [Measurability, Gap]

## Scenario Coverage

- [ ] CHK026 Are performance requirements defined for the BURST scenario (50 agents × peak rate simultaneously)? [Coverage, Gap]
- [ ] CHK027 Are performance requirements defined for the COLD-START scenario (daemon restart with N pending JSONL retries — FR-029)? [Coverage, Gap]
- [ ] CHK028 Are performance requirements defined for the LARGE-BACKLOG scenario (`events --follow --since` printing thousands of backlog rows before live)? [Coverage, Gap]
- [ ] CHK029 Are performance requirements defined for the DEGRADED-RECOVERY scenario (FR-040: how many pending events flush per recovery cycle)? [Coverage, Gap]
- [ ] CHK030 Are performance requirements defined for the QUERY-FILTER scenario (compound filter on `--target` + `--type` + `--since` + `--until`)? [Coverage, Gap]

## Edge Case Coverage

- [ ] CHK031 Are requirements specified for the case where one attachment's classify+commit exceeds half the cycle budget (per-attachment fairness)? [Edge Case, Plan §"Constraints"]
- [ ] CHK032 Are requirements defined for query latency when `idx_events_observedat_eventid` is contended with a writer cycle? [Edge Case, Gap]
- [ ] CHK033 Are requirements specified for the SIGPIPE case (downstream consumer closes the pipe; CLI must exit promptly without burning CPU)? [Edge Case, Plan §"Stream-flush behavior"]
- [ ] CHK034 Is the case "many attachments, all idle (no new bytes)" required to consume O(attachments) work per cycle, not O(log_size)? [Edge Case, Gap]
- [ ] CHK035 Is the case "one attachment producing very long lines (> excerpt cap × many)" bounded so it cannot starve other attachments? [Edge Case, Spec §FR-019, Gap]

## Non-Functional Requirements

- [ ] CHK036 Are SQLite WAL configuration requirements specified (e.g., WAL mode enabled, busy-timeout configured)? [NFR, Gap]
- [ ] CHK037 Are index-coverage requirements specified for every documented filter combination (the plan describes which index serves which query — is this a normative requirement)? [NFR, Plan §2.5]
- [ ] CHK038 Is the assumption of local-SSD storage performance documented (rotational disks would miss SC-002)? [NFR, Assumption]
- [ ] CHK039 Are requirements specified for the daemon's startup time impact (one new schema migration + reader thread spawn)? [NFR, Gap]

## Dependencies & Assumptions

- [ ] CHK040 Is the assumption that "Per-MVP scale: ≤ 50 attached agents, ≤ a few KB/s per agent" measurable enough to trigger a spec amendment if real load exceeds it (e.g., quantified upper bound for "few")? [Assumption, Spec §Assumptions]
