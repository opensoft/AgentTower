# Research Rationale Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality of `research.md` — decision traceability, rationale strength, alternatives consideration.
**Created**: 2026-05-19
**Feature**: [research.md](../research.md), [plan.md](../plan.md), [spec.md](../spec.md)

## Decision Completeness

- [ ] CHK001 Does **R-001 (host-vs-container peer detection)** name the concrete reuse target (FEAT-009 routing-toggle mechanism) rather than just say "reuse existing"? [Traceability, Research §R-001]
- [ ] CHK002 Does **R-002 (macOS SO_PEERCRED variant)** specify both Linux and macOS code paths concretely, and document Windows as out-of-scope with a forward-pointer? [Completeness, Research §R-002]
- [ ] CHK003 Does **R-003 (async vs threading)** confirm the existing daemon's threading model is reused, with a clear "no asyncio bridge" non-goal? [Clarity, Research §R-003]
- [ ] CHK004 Does **R-004 (envelope validation)** justify rejecting `pydantic` / `jsonschema` with concrete trade-off (cold start, drift, FR alignment)? [Clarity, Research §R-004]
- [ ] CHK005 Does **R-005 (token + scan_id generation)** specify all three identifier formats (token = uuid v4 hex 36 chars; app_session_id = monotonic int from 1; scan_id = uuid v4 hex)? [Completeness, Research §R-005]
- [ ] CHK006 Does **R-006 (idempotency TTL/eviction)** quantify both the cap (256) and the eviction policy (LRU), with concrete rationale? [Clarity, Research §R-006]
- [ ] CHK007 Does **R-007 (JSONL `origin` threading)** assert that the existing audit writer already accepts the `origin` keyword, and identify which file/function (`src/agenttower/events/audit.py`, `src/agenttower/routing/audit_writer.py`)? [Traceability, Research §R-007]
- [ ] CHK008 Does **R-008 (view model assembly + no global lock)** trace each design choice back to FR-018 (no global lock), FR-004 (same DAO layer), SC-002 (latency budget)? [Traceability, Research §R-008]
- [ ] CHK009 Does **R-009 (scan worker integration)** describe both `wait=true` blocking and `wait=false` polling paths, including disconnect-and-resume semantics (FR-030b)? [Completeness, Research §R-009]
- [ ] CHK010 Does **R-010 (synthetic client design)** justify the bare-metal socket approach against SC-001's "zero CLI parsing" requirement? [Traceability, Research §R-010]

## Alternatives Consideration

- [ ] CHK011 For each research decision, does the doc enumerate **at least one rejected alternative** with concrete reason? [Clarity, Research §all]
- [ ] CHK012 Are the rejected alternatives **realistic candidates**, not strawmen? (e.g., R-004 rejects pydantic, which is a real choice; not a strawman.) [Clarity, Research §R-004]
- [ ] CHK013 Are there decisions where the **alternatives are missing or weak**? [Gap]
- [ ] CHK014 Are decisions where **a single clear winner exists** marked explicitly so future readers don't relitigate? [Clarity]

## Traceability to FRs

- [ ] CHK015 Does each research item **cross-reference at least one FR or SC** it satisfies or implements? [Traceability, Research §all]
- [ ] CHK016 Are research decisions that introduce **new constraints not in the spec** clearly marked as plan-time defaults (e.g., 256 dedupe cap, LRU policy)? [Clarity, Research §R-006]
- [ ] CHK017 Does the research doc state explicitly that **no `NEEDS CLARIFICATION` items remain** before Phase 1? [Completeness, Research §Summary]

## Ambiguities & Gaps

- [ ] CHK018 Is there a research decision needed for **JSONL `origin` enumerated set extension** (does the existing audit writer accept any string for `origin`, or does it validate against a closed set today)? [Gap, Research §R-007]
- [ ] CHK019 Is there a research item covering **how `app.scan.containers` and `app.scan.panes` coexist with FEAT-003/004's existing scan triggers** (do they share a worker queue, or run independently)? [Gap]
- [ ] CHK020 Is there a research item covering **how `app.send_input` interacts with FEAT-009's existing CLI `send-input` permission gate** (same code path? duplicated?)? [Gap]
- [ ] CHK021 Is there a research item covering **how the dashboard composes counts under heavy concurrent CLI/app load** (FR-018 says "best-effort consistent" but the budget for SC-002 is tight)? [Gap]
- [ ] CHK022 Is there a research item for **how `host_only.py` will detect a peer in a Docker/Podman/LXC container** (all three are possible bench-container backends)? [Gap, Research §R-001, §R-002]

## Verifiability of Research Claims

- [ ] CHK023 Can **R-001's "reuse FEAT-009 mechanism"** be verified by import inspection at plan time? [Measurability]
- [ ] CHK024 Can **R-007's claim that the existing JSONL writer accepts `origin`** be verified by reading the existing code today (before implementation begins)? [Measurability]
- [ ] CHK025 Can **R-008's "no global lock" assertion** be tested by a stress fixture (concurrent dashboard reads vs CLI mutations)? [Measurability]
