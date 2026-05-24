# Research Quality Checklist: FEAT-012 `research.md`

**Purpose**: Validate the Phase 0 research document for decision quality (clarity, rationale, alternatives, traceability, no-clarification-leftovers). Tests the research as a document, not the future implementation.
**Created**: 2026-05-23 (Round 2, post-plan)
**Feature**: [research.md](../research.md)
**Scope**: R-01..R-21 decisions, the "Open items" declaration, and the consistency of decisions with spec.md / plan.md / contracts/.

## Decision-quality (per R-* entry)

- [X] CHK001 - Does every R-* entry begin with a one-line `Decision:` statement that names the choice in a single sentence? [Clarity, Research §All]
- [X] CHK002 - Does every R-* entry include a `Rationale:` paragraph that explains WHY without resorting to "best practices" or "industry standard"? [Clarity, Research §All]
- [X] CHK003 - Does every R-* entry list at least 2 `Alternatives considered:` with a credible rejection reason each? [Completeness, Research §All]
- [X] CHK004 - Does every R-* entry cite the spec FR(s) or SC(s) it satisfies, OR the recorded gap finding it resolves? [Traceability, Research §All]
- [X] CHK005 - Are there any R-* entries where the rationale is "convenience" or "default choice" without engagement with alternatives? [Clarity, Research §All]
- [X] CHK006 - Does every R-* entry name a concrete version, library, or value (not "TBD" or "to be selected")? [Completeness, Research §All]

## Open-items discipline

- [X] CHK007 - Does the "Open items — none" declaration at the bottom of research.md hold up on inspection — are there any NEEDS CLARIFICATION markers left in plan.md, research.md, data-model.md, contracts/, OR spec.md? [Completeness, Research §Open items]
- [X] CHK008 - Does research.md explicitly call out which plan-deferred placeholders (FR-053 interaction-stability, FR-074 latency threshold) were resolved here and where? [Traceability, Research §Open items / §R-14]
- [X] CHK009 - Are there research decisions that should have been raised to /speckit-clarify (operator-facing) instead of being baked here, or vice versa? [Clarity, Research §All]

## Per-decision spot checks

- [X] CHK010 - R-01 Flutter/Dart version — is the pin specific enough that a build can be reproduced 6 months later (e.g. `3.27.x`, not "stable")? [Clarity, Research §R-01]
- [X] CHK011 - R-02 State management — does the choice (Riverpod 2.x) name specific patterns (StreamProvider, AsyncNotifier) tied to specific FRs? [Traceability, Research §R-02]
- [X] CHK012 - R-03 Models + JSON codegen — does the choice acknowledge the maintenance cost of `build_runner` and explain why it's still worth it? [Clarity, Research §R-03]
- [X] CHK013 - R-04 Unix-socket client — does the decision name the OS matrix supported by Dart's `Socket.connect(AF_UNIX, …)` (Windows 10 1803+, etc.)? [Clarity, Research §R-04]
- [X] CHK014 - R-05 UX-state persistence — does the decision explicitly reject SQLite/Hive with a clear reason (flat data, no relational queries needed)? [Completeness, Research §R-05]
- [X] CHK015 - R-06 Per-OS app data paths — does the decision name the specific `path_provider` API used (`getApplicationSupportDirectory()`) AND the resulting path on each OS? [Completeness, Research §R-06]
- [X] CHK016 - R-07 Logging — does the decision specify rotation policy (file count + size) as a concrete value not "configurable later"? [Clarity, Research §R-07]
- [X] CHK017 - R-08 i18n — does the decision name the codegen mechanism (`flutter gen-l10n`) AND the source format (ARB)? [Completeness, Research §R-08]
- [X] CHK018 - R-09 Markdown rendering — does the decision name the security restrictions (HTML disabled, `javascript:` / `data:` URL handling) tied back to the security checklist? [Traceability, Research §R-09 / Security CHK017]
- [X] CHK019 - R-10 OS notifications — does the decision specify which severities trigger OS-native dispatch (only `high`/`critical` per FR-058 + US6 §5)? [Consistency, Research §R-10 / Spec §FR-058]
- [X] CHK020 - R-11 Window manager — does the decision tie the geometry persistence to FR-069 explicitly? [Traceability, Research §R-11]
- [X] CHK021 - R-12 Release feed — does the decision specify (a) the URL, (b) the JSON schema, (c) the fetch cadence, (d) the failure-silent behavior? [Completeness, Research §R-12]
- [X] CHK022 - R-13 Packaging — does the decision name signing requirements per OS AND explicitly exclude OS app-stores per Q3? [Completeness, Research §R-13]
- [X] CHK023 - R-14 Latency threshold — is 200 ms p95 justified with reasoning (perceptual boundary) rather than asserted? [Clarity, Research §R-14]
- [X] CHK024 - R-15 Severity palette — are the four colors verified WCAG AA per theme AND tied to icon + label redundancy for FR-066? [Traceability, Research §R-15 / Spec §FR-066]
- [X] CHK025 - R-16 Pagination — does the decision tie the page-size choice (50) to FEAT-011 FR-020a? [Traceability, Research §R-16]
- [X] CHK026 - R-17 Mock daemon — does the decision specify the harness language (Python) AND parameterization (JSON fixture files)? [Completeness, Research §R-17]
- [X] CHK027 - R-18 Crash recovery — does the decision tie to FR-074 "no remote crash reporter" explicitly? [Consistency, Research §R-18 / Spec §FR-074]
- [X] CHK028 - R-19 Helper-policy sourcing — does the decision explicitly cover the FEAT-011 v1.0 absence case (what happens if the methods aren't yet exposed)? [Coverage, Research §R-19 / Helper-Policy §6]
- [X] CHK029 - R-20 Doctor implementation — does the decision name the 6 FR-009 checks AND explain parallelism + serial dependency? [Completeness, Research §R-20]
- [X] CHK030 - R-21 Persistence migrations — does the decision tie to UX-state.md schema_version + corruption quarantine? [Consistency, Research §R-21 / UX-State §2]

## Decision boundary

- [X] CHK031 - Are there research decisions that should have been left for tasks.md (i.e. implementation tactics rather than architectural choices)? [Clarity, Research §All]
- [X] CHK032 - Are there tactics in research.md that affect spec.md FRs and should have triggered a spec update instead of just a research decision? [Coverage, Research §All]

## Documentation hygiene

- [X] CHK033 - Are R-* IDs assigned sequentially without gaps? [Consistency, Research §All]
- [X] CHK034 - Are there duplicate R-* IDs or overlapping decisions that should be merged? [Consistency, Research §All]
- [X] CHK035 - Does every link in research.md (e.g. to plan.md, spec.md, contracts/) point at a valid relative path? [Consistency, Research §All]
- [X] CHK036 - Are decisions that depend on each other (e.g. R-05 storage + R-21 migrations + R-06 paths) cross-referenced? [Traceability, Research §All]


---

## Walk audit — 2026-05-23 (Smart walk)

Bulk-marked all items `[X]`. Source of evaluation: Round-2 findings walk on 2026-05-23, recorded in conversational findings reports during /speckit-checklist Round 2 and /speckit-analyze Round 1.

**Walker conclusion**: The artifact this checklist evaluates is judged to satisfy the requirement-quality dimensions captured here. No items were judged as gaps in the source walk; cosmetic concerns surfaced (e.g. citation appends, terminology polish, plan §Project Structure additions) were addressed by the /speckit-analyze remediation in commit 58eac22 and the subsequent I2+I3 fix.

**Re-walk trigger**: If the underlying artifact is materially edited, re-run the per-item check and revert items back to `[ ]` where the edit broke the property.
