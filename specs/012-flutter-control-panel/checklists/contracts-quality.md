# Contracts Quality Checklist: FEAT-012 `contracts/*`

**Purpose**: Validate the three Phase 1 contracts documents for completeness, traceability, and consistency with spec.md / FEAT-011 / data-model.md. Tests the contracts as documents.
**Created**: 2026-05-23 (Round 2, post-plan)
**Feature**: [contracts/](../contracts/)
**Scope**: `app-methods-consumed.md`, `ux-state.md`, `helper-policy.md`. Sister checklist for FEAT-011 contract conformance lives in `api-contract.md` (Round 1).

## §A — `app-methods-consumed.md`

### Coverage

- [ ] CHK001 - Does the doc list every FEAT-011 v1.0 method exposed by `specs/011-app-backend-contract/contracts/app-methods.md` AND mark each as "consumed" or "not consumed"? [Completeness, App-Methods-Consumed §1-9]
- [ ] CHK002 - Does §3 explicitly distinguish v1.0 methods from "anticipated in a FEAT-011 v1.x bump" methods (so an implementer knows the dependency risk)? [Clarity, App-Methods-Consumed §3]
- [ ] CHK003 - Are anticipated additions (handoff, drift transitions, validation triggers, project add/remove, helper-policy resolve, notification acknowledge) each tied to specific FEAT-012 FRs? [Traceability, App-Methods-Consumed §3 / §5]
- [ ] CHK004 - Does §1 (Bootstrap) name the session-lifecycle policy ("one session at a time", re-bootstrap on reconnect)? [Completeness, App-Methods-Consumed §1]
- [ ] CHK005 - Does §7 (Live updates) acknowledge that FEAT-011 v1.0 is request/response and name the fallback strategy (polling with cadence) until streaming arrives? [Completeness, App-Methods-Consumed §7]
- [ ] CHK006 - Does §8 (Error vocabulary) name the 27-entry FEAT-011 closed-set codes and call out the two surface-affecting ones (`app_contract_major_unsupported`, `host_only`)? [Completeness, App-Methods-Consumed §8 / FEAT-011 FR-034]
- [ ] CHK007 - Does §10 (Wire-framing & reconnect) enumerate the per-line size caps, framing rules, and in-flight-mutation policy on disconnect? [Completeness, App-Methods-Consumed §10 / FEAT-011 FR-003a/b]

### Traceability

- [ ] CHK008 - Does each method-row in §3-§5 cite the FEAT-012 FR(s) it serves? [Traceability, App-Methods-Consumed §3-§5]
- [ ] CHK009 - Does §6 (Scans) cite the spec edge case where re-probe is the next action (FR-014's "re-probe" + Edge Cases)? [Traceability, App-Methods-Consumed §6 / Spec §FR-014]
- [ ] CHK010 - Does §9 list any v1.0 methods that FEAT-012 does NOT use (or explicitly state "none") so a reviewer can audit completeness? [Completeness, App-Methods-Consumed §9]

### Ambiguity

- [ ] CHK011 - Is the "anticipated in a FEAT-011 v1.x bump" hedge precise enough — does it name a target FEAT-011 minor version or open issue, or does it leave the upgrade contract vague? [Clarity, App-Methods-Consumed §3 / §5]
- [ ] CHK012 - Is the polling-cadence selection in §7 specific (e.g. "≤ 1 s while a surface is visible") or vague? [Clarity, App-Methods-Consumed §7 / Spec §FR-064]

## §B — `ux-state.md`

### Schema completeness

- [ ] CHK013 - Does the top-level shape include `$schema`, `schema_version`, `last_written_by`, `ux_state` — all four fields? [Completeness, UX-State §top-level]
- [ ] CHK014 - Does §1 enumerate every field FR-069 says is persisted (window geometry, theme, density, two toggles, last workspace, last sub-view, last project, list sort/filter, settings, onboarding completion)? [Completeness, UX-State §1 / Spec §FR-069]
- [ ] CHK015 - Does the field-by-field reference include type, default-on-fresh-install, AND a Spec FR citation for each row? [Completeness, UX-State §1 field-reference]
- [ ] CHK016 - Is `ListSortFilterState` defined as a typed schema for `sort_field` + `sort_direction` and an opaque `filters` map (with view-registry validation)? [Clarity, UX-State §ListSortFilterState]
- [ ] CHK017 - Does the persistence-write-rules block cite atomicity (rename-after-write), cadence (debounce + immediate-on-close), permission inheritance, and compatibility check? [Completeness, UX-State §file-location + §write-discipline]

### Compatibility & migrations

- [ ] CHK018 - Does §2 name the major-mismatch drop-and-reset behavior exactly per FR-070? [Consistency, UX-State §2 / Spec §FR-070]
- [ ] CHK019 - Does §2 name the schema-version forward-only migration AND the newer-than-current case? [Completeness, UX-State §2 / Research R-21]
- [ ] CHK020 - Does §2 name the corruption-quarantine behavior including the quarantine filename pattern? [Completeness, UX-State §2 §corruption-recovery]
- [ ] CHK021 - Does §2 name the cross-OS-user isolation invariant for the diagnostics bundle? [Completeness, UX-State §2 §cross-user-isolation]

### Forbidden content

- [ ] CHK022 - Does §3 list every thing that MUST NOT appear in `ux-state.json` (session token, daemon-owned entities, pre-submit handoff drafts, keystroke buffers)? [Completeness, UX-State §3 / Spec §FR-003 + FR-005 + FR-069]
- [ ] CHK023 - Does §4 tie the doctor (FR-009) checks to ux-state file health (readable, no stale `.tmp`, schema_version match)? [Completeness, UX-State §4]

## §C — `helper-policy.md`

### Q1-Q4 round-2 traceability

- [ ] CHK024 - Does §1 explicitly state daemon-side-only sourcing (Q1) AND prohibit app-side file reads? [Consistency, Helper-Policy §1 / Spec §Clarifications round 2 Q1]
- [ ] CHK025 - Does §2 enumerate the 4 required fields (Q2: `policy_id`, `allowed_helper_capabilities`, `default_helper_capability`, `policy_source`) AND explicitly reject quotas/whitelists for MVP? [Consistency, Helper-Policy §2 / Spec §Clarifications round 2 Q2]
- [ ] CHK026 - Does §4 specify per-handoff override scope (Q3) AND explicitly say no per-master / per-project / global override at MVP? [Consistency, Helper-Policy §4 / Spec §Clarifications round 2 Q3]
- [ ] CHK027 - Does §3 specify the repo-level override at `agenttower/helper-policy.yaml` (Q4) AND specify `policy_source = repo_override` recording? [Consistency, Helper-Policy §3 / Spec §Clarifications round 2 Q4]

### Snapshot & reproducibility

- [ ] CHK028 - Does §5 name the snapshot's 4-field shape AND the `operator_override_of_policy_id` + `repo_override_path` audit fields? [Completeness, Helper-Policy §5 / Spec §FR-042]
- [ ] CHK029 - Does §5 state the reproducibility invariant ("handoff prompt-context reconstructible from snapshot without further daemon lookup")? [Completeness, Helper-Policy §5]

### Failure modes

- [ ] CHK030 - Does §6 cover the FEAT-011 v1.0 absence case (R-19 caveat) — degrade to `runtime-degraded`, disable policy selector with inline explanation, still allow submission with implicit default? [Completeness, Helper-Policy §6 / Research R-19]
- [ ] CHK031 - Does §6 cover the `default ∈ allowed` invariant violation case (degrade + don't auto-correct)? [Completeness, Helper-Policy §6]
- [ ] CHK032 - Does §6 cover the repo-override-malformed case (daemon returns baked default + doctor warning)? [Completeness, Helper-Policy §6]

### Boundary

- [ ] CHK033 - Does §8 explicitly say what this contract does NOT cover (daemon-side resolution algorithm, capability vocabulary evolution, helper-agent execution)? [Completeness, Helper-Policy §8]

## §D — Cross-contract consistency

- [ ] CHK034 - Does helper-policy.md's snapshot field set in §5 match data-model.md §1.8 HelperPolicySnapshot field-for-field? [Consistency, Helper-Policy §5 / Data-model §1.8]
- [ ] CHK035 - Does ux-state.md §1 enumeration match data-model.md §2.1 WorkspaceSelection field-for-field? [Consistency, UX-State §1 / Data-model §2.1]
- [ ] CHK036 - Does app-methods-consumed.md §5 helper-policy methods match the methods helper-policy.md §1 names? [Consistency, App-Methods-Consumed §5 / Helper-Policy §1]
- [ ] CHK037 - Does app-methods-consumed.md §3 entity-method mapping match data-model.md §1 entity Source lines? [Consistency, App-Methods-Consumed §3 / Data-model §1]

## §E — Documentation hygiene

- [ ] CHK038 - Are all three contracts files written in the same heading style and reference-link style? [Consistency, Contracts/*]
- [ ] CHK039 - Are all FR / SC / FEAT-011 references cited with the `Spec §...` or `FEAT-011 FR-...` pattern that downstream tooling can grep? [Consistency, Contracts/*]
- [ ] CHK040 - Do the contracts files cross-reference each other where relevant (e.g. ux-state.md references helper-policy.md and vice versa)? [Traceability, Contracts/*]
