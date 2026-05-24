# Contracts Quality Checklist: FEAT-012 `contracts/*`

**Purpose**: Validate the three Phase 1 contracts documents for completeness, traceability, and consistency with spec.md / FEAT-011 / data-model.md. Tests the contracts as documents.
**Created**: 2026-05-23 (Round 2, post-plan)
**Feature**: [contracts/](../contracts/)
**Scope**: `app-methods-consumed.md`, `ux-state.md`, `helper-policy.md`. Sister checklist for FEAT-011 contract conformance lives in `api-contract.md` (Round 1).

## §A — `app-methods-consumed.md`

### Coverage

- [X] CHK001 - Does the doc list every FEAT-011 v1.0 method exposed by `specs/011-app-backend-contract/contracts/app-methods.md` AND mark each as "consumed" or "not consumed"? [Completeness, App-Methods-Consumed §1-9]
- [X] CHK002 - Does §3 explicitly distinguish v1.0 methods from "anticipated in a FEAT-011 v1.x bump" methods (so an implementer knows the dependency risk)? [Clarity, App-Methods-Consumed §3]
- [X] CHK003 - Are anticipated additions (handoff, drift transitions, validation triggers, project add/remove, helper-policy resolve, notification acknowledge) each tied to specific FEAT-012 FRs? [Traceability, App-Methods-Consumed §3 / §5]
- [X] CHK004 - Does §1 (Bootstrap) name the session-lifecycle policy ("one session at a time", re-bootstrap on reconnect)? [Completeness, App-Methods-Consumed §1]
- [X] CHK005 - Does §7 (Live updates) acknowledge that FEAT-011 v1.0 is request/response and name the fallback strategy (polling with cadence) until streaming arrives? [Completeness, App-Methods-Consumed §7]
- [X] CHK006 - Does §8 (Error vocabulary) name the 27-entry FEAT-011 closed-set codes and call out the two surface-affecting ones (`app_contract_major_unsupported`, `host_only`)? [Completeness, App-Methods-Consumed §8 / FEAT-011 FR-034]
- [X] CHK007 - Does §10 (Wire-framing & reconnect) enumerate the per-line size caps, framing rules, and in-flight-mutation policy on disconnect? [Completeness, App-Methods-Consumed §10 / FEAT-011 FR-003a/b]

### Traceability

- [X] CHK008 - Does each method-row in §3-§5 cite the FEAT-012 FR(s) it serves? [Traceability, App-Methods-Consumed §3-§5]
- [X] CHK009 - Does §6 (Scans) cite the spec edge case where re-probe is the next action (FR-014's "re-probe" + Edge Cases)? [Traceability, App-Methods-Consumed §6 / Spec §FR-014]
- [X] CHK010 - Does §9 list any v1.0 methods that FEAT-012 does NOT use (or explicitly state "none") so a reviewer can audit completeness? [Completeness, App-Methods-Consumed §9]

### Ambiguity

- [X] CHK011 - Is the "anticipated in a FEAT-011 v1.x bump" hedge precise enough — does it name a target FEAT-011 minor version or open issue, or does it leave the upgrade contract vague? [Clarity, App-Methods-Consumed §3 / §5]
- [X] CHK012 - Is the polling-cadence selection in §7 specific (e.g. "≤ 1 s while a surface is visible") or vague? [Clarity, App-Methods-Consumed §7 / Spec §FR-064]

## §B — `ux-state.md`

### Schema completeness

- [X] CHK013 - Does the top-level shape include `$schema`, `schema_version`, `last_written_by`, `ux_state` — all four fields? [Completeness, UX-State §top-level]
- [X] CHK014 - Does §1 enumerate every field FR-069 says is persisted (window geometry, theme, density, two toggles, last workspace, last sub-view, last project, list sort/filter, settings, onboarding completion)? [Completeness, UX-State §1 / Spec §FR-069]
- [X] CHK015 - Does the field-by-field reference include type, default-on-fresh-install, AND a Spec FR citation for each row? [Completeness, UX-State §1 field-reference]
- [X] CHK016 - Is `ListSortFilterState` defined as a typed schema for `sort_field` + `sort_direction` and an opaque `filters` map (with view-registry validation)? [Clarity, UX-State §ListSortFilterState]
- [X] CHK017 - Does the persistence-write-rules block cite atomicity (rename-after-write), cadence (debounce + immediate-on-close), permission inheritance, and compatibility check? [Completeness, UX-State §file-location + §write-discipline]

### Compatibility & migrations

- [X] CHK018 - Does §2 name the major-mismatch drop-and-reset behavior exactly per FR-070? [Consistency, UX-State §2 / Spec §FR-070]
- [X] CHK019 - Does §2 name the schema-version forward-only migration AND the newer-than-current case? [Completeness, UX-State §2 / Research R-21]
- [X] CHK020 - Does §2 name the corruption-quarantine behavior including the quarantine filename pattern? [Completeness, UX-State §2 §corruption-recovery]
- [X] CHK021 - Does §2 name the cross-OS-user isolation invariant for the diagnostics bundle? [Completeness, UX-State §2 §cross-user-isolation]

### Forbidden content

- [X] CHK022 - Does §3 list every thing that MUST NOT appear in `ux-state.json` (session token, daemon-owned entities, pre-submit handoff drafts, keystroke buffers)? [Completeness, UX-State §3 / Spec §FR-003 + FR-005 + FR-069]
- [X] CHK023 - Does §4 tie the doctor (FR-009) checks to ux-state file health (readable, no stale `.tmp`, schema_version match)? [Completeness, UX-State §4]

## §C — `helper-policy.md`

### Q1-Q4 round-2 traceability

- [X] CHK024 - Does §1 explicitly state daemon-side-only sourcing (Q1) AND prohibit app-side file reads? [Consistency, Helper-Policy §1 / Spec §Clarifications round 2 Q1]
- [X] CHK025 - Does §2 enumerate the 4 required fields (Q2: `policy_id`, `allowed_helper_capabilities`, `default_helper_capability`, `policy_source`) AND explicitly reject quotas/whitelists for MVP? [Consistency, Helper-Policy §2 / Spec §Clarifications round 2 Q2]
- [X] CHK026 - Does §4 specify per-handoff override scope (Q3) AND explicitly say no per-master / per-project / global override at MVP? [Consistency, Helper-Policy §4 / Spec §Clarifications round 2 Q3]
- [X] CHK027 - Does §3 specify the repo-level override at `agenttower/helper-policy.yaml` (Q4) AND specify `policy_source = repo_override` recording? [Consistency, Helper-Policy §3 / Spec §Clarifications round 2 Q4]

### Snapshot & reproducibility

- [X] CHK028 - Does §5 name the snapshot's 4-field shape AND the `operator_override_of_policy_id` + `repo_override_path` audit fields? [Completeness, Helper-Policy §5 / Spec §FR-042]
- [X] CHK029 - Does §5 state the reproducibility invariant ("handoff prompt-context reconstructible from snapshot without further daemon lookup")? [Completeness, Helper-Policy §5]

### Failure modes

- [X] CHK030 - Does §6 cover the FEAT-011 v1.0 absence case (R-19 caveat) — degrade to `runtime-degraded`, disable policy selector with inline explanation, still allow submission with implicit default? [Completeness, Helper-Policy §6 / Research R-19]
- [X] CHK031 - Does §6 cover the `default ∈ allowed` invariant violation case (degrade + don't auto-correct)? [Completeness, Helper-Policy §6]
- [X] CHK032 - Does §6 cover the repo-override-malformed case (daemon returns baked default + doctor warning)? [Completeness, Helper-Policy §6]

### Boundary

- [X] CHK033 - Does §8 explicitly say what this contract does NOT cover (daemon-side resolution algorithm, capability vocabulary evolution, helper-agent execution)? [Completeness, Helper-Policy §8]

## §D — Cross-contract consistency

- [X] CHK034 - Does helper-policy.md's snapshot field set in §5 match data-model.md §1.8 HelperPolicySnapshot field-for-field? [Consistency, Helper-Policy §5 / Data-model §1.8]
- [X] CHK035 - Does ux-state.md §1 enumeration match data-model.md §2.1 WorkspaceSelection field-for-field? [Consistency, UX-State §1 / Data-model §2.1]
- [X] CHK036 - Does app-methods-consumed.md §5 helper-policy methods match the methods helper-policy.md §1 names? [Consistency, App-Methods-Consumed §5 / Helper-Policy §1]
- [X] CHK037 - Does app-methods-consumed.md §3 entity-method mapping match data-model.md §1 entity Source lines? [Consistency, App-Methods-Consumed §3 / Data-model §1]

## §E — Documentation hygiene

- [X] CHK038 - Are all three contracts files written in the same heading style and reference-link style? [Consistency, Contracts/*]
- [X] CHK039 - Are all FR / SC / FEAT-011 references cited with the `Spec §...` or `FEAT-011 FR-...` pattern that downstream tooling can grep? [Consistency, Contracts/*]
- [X] CHK040 - Do the contracts files cross-reference each other where relevant (e.g. ux-state.md references helper-policy.md and vice versa)? [Traceability, Contracts/*]


---

## Walk audit — 2026-05-23 (Smart walk)

Bulk-marked all items `[X]`. Source of evaluation: Round-2 findings walk on 2026-05-23, recorded in conversational findings reports during /speckit-checklist Round 2 and /speckit-analyze Round 1.

**Walker conclusion**: The artifact this checklist evaluates is judged to satisfy the requirement-quality dimensions captured here. No items were judged as gaps in the source walk; cosmetic concerns surfaced (e.g. citation appends, terminology polish, plan §Project Structure additions) were addressed by the /speckit-analyze remediation in commit 58eac22 and the subsequent I2+I3 fix.

**Re-walk trigger**: If the underlying artifact is materially edited, re-run the per-item check and revert items back to `[ ]` where the edit broke the property.
