# Scope, Assumptions & Dependencies Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for the Out of Scope, Assumptions, and dependency sections — boundary clarity, deferred-feature tracking, prerequisite verifiability.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Are all OOS items enumerated explicitly (the Out of Scope section lists 8 items; cross-check against the brief in the spec Input field)? [Completeness, Spec §Out of Scope, §Input]
- [X] CHK002 Are all deferred features explicitly labeled with their target feature (FEAT-012 for Flutter, FEAT-013 for managed sessions, "follow-up minor" for event subscribe)? [Completeness, Spec Assumptions]
- [X] CHK003 Are all assumed prerequisites enumerated (FEAT-001..FEAT-010 dependency tree)? [Completeness, Spec Assumptions]
- [X] CHK004 Is the platform target enumerated (Windows/macOS/Linux desktop; not mobile)? [Completeness, Spec Assumptions]
- [X] CHK005 Are the supported consumer-language assumptions documented (Flutter, but also Rust/Swift/Electron per Assumptions)? [Completeness, Spec Assumptions]

## Requirement Clarity

- [X] CHK006 Is "host-resident app is the only target consumer" testable — should the daemon refuse `app.*` calls from inside bench containers? [Clarity, Spec Assumptions]
- [X] CHK007 Is "Multi-user desktops are out of scope" defined operationally — does the daemon detect multiple OS users, or just assume a single one? [Ambiguity, Spec Assumptions]
- [X] CHK008 Is the deferred-feature boundary for event subscription precise — can a client probe `capability_flags` for `events_subscribe` (and what is the canonical key name)? [Clarity, Spec §FR-039, Assumptions]
- [X] CHK009 Is "FEAT-011 is post-MVP" (Summary) clearly aligned with the MVP feature sequence in `docs/mvp-feature-sequence.md`? [Clarity, Spec §Summary]
- [X] CHK010 Is "language-agnostic" (Assumptions) defined as "JSON over Unix socket" only, or does it imply any future protocol-level constraints? [Clarity, Spec Assumptions]

## Requirement Consistency

- [X] CHK011 Are the deferred features in Assumptions consistent with the explicit Out of Scope list? [Consistency, Spec §Out of Scope, Assumptions]
- [X] CHK012 Is "Flutter target is informational" (Assumptions) consistent with the spec's title and Summary, which both name Flutter? [Consistency, Spec §Summary, Assumptions]
- [X] CHK013 Are FEAT-001..FEAT-010 dependency assumptions consistent with the FRs that cross-reference them (FR-026 → FEAT-006, FR-031 → FEAT-009, FR-032 → FEAT-010)? [Consistency]
- [X] CHK014 Is "no Antigravity, no TUI, no mobile, no remote multi-host, no hosted SaaS" (Assumptions) consistent with the Out of Scope list? [Consistency, Spec Assumptions, §Out of Scope]

## Scenario Coverage

- [X] CHK015 Are requirements defined for the case where a prerequisite feature (e.g., FEAT-010 routing) is shipped but has a known bug — does FEAT-011 inherit the bug or surface it differently? [Gap]
- [X] CHK016 Are requirements defined for the case where an assumed-stable surface (CLI `register-self`) changes behavior in a future feature — does FEAT-011 freeze on a version? [Gap, Spec §FR-026]
- [X] CHK017 Is the "no Antigravity support" exclusion testable, or just declarative? [Coverage, Spec Assumptions]
- [X] CHK018 Are requirements defined for the case where a future minor adds a feature that conflicts with an existing OOS item (e.g., a notification push that resembles a "push subscription" — currently deferred)? [Gap, Spec §Out of Scope]
- [X] CHK019 Is the assumed concurrency model ("one user, one daemon, one or more concurrent app sessions") testable, and what happens if a second user attempts to open the socket? [Coverage, Spec Assumptions]

## Measurability

- [X] CHK020 Can "FEAT-011 builds on existing services rather than reimplementing them" (Assumptions) be objectively verified by code-import inspection in the plan? [Measurability, Spec Assumptions]
- [X] CHK021 Is "schema migration of existing SQLite tables purely for app-rendering convenience is out of scope" (OOS) testable — does FEAT-011 add any persisted column anywhere? [Measurability, Spec §Out of Scope]
- [X] CHK022 Is "Cross-host federation or cluster mode" (OOS) testable beyond declarative exclusion? [Measurability, Spec §Out of Scope]

## Ambiguities, Conflicts, Gaps

- [X] CHK023 Is the "FEAT-011 is post-MVP (depends on FEAT-001..FEAT-010)" claim consistent with the actual MVP feature sequence document? [Consistency, Gap]
- [X] CHK024 Is there a defined sunset path for any legacy CLI method that becomes redundant with `app.*` (currently FR-002 keeps them all, but no sunset rule is stated)? [Gap, Spec §FR-002]
- [X] CHK025 Is the rule defined for what happens when a deferred feature (e.g., FEAT-013 managed pane create) is shipped and the `app.*` namespace adds the matching method — does it require a major or minor bump? [Gap, Spec §FR-035, Assumptions]
- [X] CHK026 Is the assumption "two concurrent apps see the same mutations land in the same SQLite/JSONL" (Assumptions) consistent with the FR-018 dashboard-atomicity caveat? [Consistency, Spec §FR-018, Assumptions]
- [X] CHK027 Is the rule defined for whether bench-container clients can call any `app.*` method at all, given Assumptions explicitly exclude them but FR-040 allows callers "mounted into a bench container"? [Conflict, Spec §FR-040, Assumptions]
