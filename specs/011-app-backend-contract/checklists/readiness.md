# Readiness Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for `app.readiness` — subsystem coverage, state aggregation rules, hint semantics, side-effect freedom.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Is every named subsystem (docker, tmux_discovery, sqlite, jsonl, routing_worker, log_attachment_workers) defined with precise probe semantics (what predicate determines `ok` vs `degraded` vs `unavailable`)? [Completeness, Spec §FR-013]
- [X] CHK002 Are the rules for aggregating subsystem statuses into a top-level `state` defined (any `unavailable` → `unavailable`? any `degraded` → `degraded`? thresholds)? [Gap, Spec §FR-012]
- [X] CHK003 Is `hint` field's content shape defined — free-form string, closed-set hint codes, or structured object? [Clarity, Spec §FR-012]
- [X] CHK004 Are the readiness subsystem-row ordering rules specified (alphabetical, stable, mirroring FR-013 order)? [Gap]
- [X] CHK005 Is the response defined for "no bench containers discovered" — is it a subsystem row, a top-level hint, or both? [Ambiguity, Spec §US4 acceptance 5..7, §FR-014]
- [X] CHK006 Is the response defined for "no panes discovered when containers exist"? [Coverage, Spec §US4 acceptance 6]
- [X] CHK007 Is the response defined for "panes discovered but none registered"? [Coverage, Spec §US4 acceptance 7]

## Requirement Clarity

- [X] CHK008 Is "ready" vs "degraded" distinguishable when only optional subsystems fail (which subsystems are mandatory for `ready`)? [Clarity, Spec §FR-014]
- [X] CHK009 Is "containers_discovered" / "panes_discovered" a subsystem name, a top-level hint, or a row attribute? [Ambiguity, Spec §US4]
- [X] CHK010 Is "no bench containers discovered → state == ready" consistent with the dashboard returning `containers.active == 0` and a hints[] entry? [Clarity, Spec §FR-014, §US4]
- [X] CHK011 Is "cheap and side-effect-free" (FR-045) defined with a measurable budget (target latency or absence of I/O)? [Ambiguity, Spec §FR-045]

## Requirement Consistency

- [X] CHK012 Do FR-012's state values `{ready, degraded, unavailable}` match Story 1 step 3's enumeration? [Consistency, Spec §FR-012, §US1]
- [X] CHK013 Is the subsystem status closed set `{ok, degraded, unavailable}` consistent everywhere it appears? [Consistency, Spec §FR-012]
- [X] CHK014 Are FR-013's listed subsystems consistent with the subsystems referenced in user stories (esp. Story 4)? [Consistency, Spec §FR-013, §US4]
- [X] CHK015 Is "MUST NOT trigger a discovery scan" (FR-045) consistent with the spec's separation between `app.readiness` and `app.scan.*`? [Consistency, Spec §FR-045, §FR-030]

## Scenario Coverage

- [X] CHK016 Are requirements defined for partial subsystem health (e.g., Docker reachable but slow, SQLite reachable but read-only)? [Gap]
- [X] CHK017 Are requirements defined for transient subsystem failures and status flapping (does the daemon debounce, or always reflect instantaneous state)? [Gap]
- [X] CHK018 Is the behavior defined when `app.readiness` is called during an in-flight scan? [Gap, Spec §FR-045]
- [X] CHK019 Is the rule defined for when a new subsystem is added in an additive minor — must older clients ignore the extra row without breaking? [Coverage, Spec §FR-013, §FR-037]

## Measurability

- [X] CHK020 Can each subsystem's `status` rule be encoded as a deterministic test fixture (mock docker unavailable, mock tmux missing)? [Measurability, Spec §SC-007]
- [X] CHK021 Can "MUST NOT trigger a discovery scan" (FR-045) be objectively verified (no scan_id emitted, no scan worker invoked)? [Measurability, Spec §FR-045]
- [X] CHK022 Is the `reason` field's "empty string when status == ok" rule (FR-012) testable byte-for-byte (vs. just falsy)? [Measurability, Spec §FR-012]

## Ambiguities, Conflicts, Gaps

- [X] CHK023 Is the `reason` field's length cap or content rule defined (e.g., max chars, no embedded newlines)? [Gap, Spec §FR-012]
- [X] CHK024 Is there a defined upper bound on the time `app.readiness` may take? [Gap, Spec §FR-045]
- [X] CHK025 Is the `subsystems` array order required to be stable across calls, or may it reorder? [Gap, Spec §FR-012]
- [X] CHK026 Is the policy defined for subsystems whose existence depends on platform (e.g., Docker on Windows vs. Linux — does `docker.status` exist on every OS)? [Gap]
