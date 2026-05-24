# State Persistence Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate persistence requirements (FR-069 UX state, FR-070 compatibility, FR-076 first-launch resolution, FR-077 project removal, FR-078 list-view persistence, FR-061a per-OS-user isolation, FR-003 session token exclusion) for clarity, completeness, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: What persists across launches, where it lives, when it is restored, when it is dropped, what is never persisted, and how persistence interacts with version skew, project removal, and multi-OS-user.

## Persisted Set Completeness (FR-069)

- [ ] CHK001 - Does FR-069 enumerate every persisted dimension exhaustively (window geometry, theme, density, notifications-grouping toggle, OS-native-notification toggle, last workspace, last sub-view per workspace, last project, per-view sort/filter, Settings values) without leaving room for an implementer to add or forget items? [Completeness, Spec §FR-069]
- [ ] CHK002 - Is "Settings values" (FR-069) tied back to the FR-009 Settings inventory so the two lists cannot drift? [Consistency, Spec §FR-009 / §FR-069]
- [ ] CHK003 - Are requirements present for persisting onboarding milestone-completion state (FR-010 requires "per-milestone completion state MUST be persisted") consistent with FR-069 — is onboarding completion in the FR-069 enumeration? [Consistency, Gap, Spec §FR-010 / §FR-069]
- [ ] CHK004 - Are requirements present for persisting the operator's command-palette recent-command history (if any) — or is it explicitly out-of-scope? [Coverage, Gap, Spec §FR-069 / §FR-075]
- [ ] CHK005 - Are requirements present for persisting "removed projects" memory so the same project is not silently re-inferred immediately on next event (vs FR-077 "MUST reappear if re-inferred")? [Coverage, Spec §FR-077]

## Exclusions (FR-069 + FR-003)

- [ ] CHK006 - Is the "MUST NOT persist the session token" rule (FR-003 + FR-069) consistent across both FRs, and does FR-069 explicitly list cached domain data items it excludes (containers, panes, agents, events, queue, routes, drift findings, validation runs, demo readiness, handoffs)? [Consistency, Spec §FR-003 / §FR-069]
- [ ] CHK007 - Are requirements present for ensuring transient in-memory caches the app may build for UI rendering do not silently end up on disk (e.g. via Flutter's image cache, font cache)? [Coverage, Gap, Spec §FR-069]
- [ ] CHK008 - Are requirements present for a drafted-but-unsubmitted handoff — is its draft state considered domain data (per FR-072) or UX state (per FR-069)? [Ambiguity, Spec §FR-069 / §FR-072]

## Storage Location & Format

- [ ] CHK009 - Are requirements present for the per-OS user-scoped config-store location on each supported OS (XDG_CONFIG_HOME on Linux, ~/Library/Application Support on macOS, %APPDATA% on Windows)? [Completeness, Gap, Spec §FR-061a / §FR-069]
- [ ] CHK010 - Are requirements present for the on-disk format (JSON, TOML, SQLite, key-value store) so an implementer can choose without an architecture-impacting interpretation? [Clarity, Gap, Spec §FR-069]
- [ ] CHK011 - Are requirements present for atomicity of writes (rename-after-write, fsync) so an interrupted save does not leave a half-written persisted state? [Coverage, Gap, Spec §FR-069]
- [ ] CHK012 - Are requirements present for file permissions on the persisted state (mode 0600 / equivalent) consistent with FR-061a per-OS-user isolation? [Consistency, Spec §FR-061a / §FR-069]

## Compatible App Launch (FR-070)

- [ ] CHK013 - Does FR-070's definition of "compatible app launch" (same app major + same `app_contract_version` major) handle the case where the app major increments without a contract change (UX-only release)? [Clarity, Spec §FR-070]
- [ ] CHK014 - Are requirements present for what specifically is dropped on incompatibility — only "last project / last workspace / last sub-view / list sort/filter" per FR-070, or also Settings, theme, window geometry? [Clarity, Spec §FR-069 / §FR-070]
- [ ] CHK015 - Are requirements present for migrating persisted state across compatible versions (forward-compatible schema, additive fields ignored gracefully)? [Coverage, Gap, Spec §FR-070]
- [ ] CHK016 - Are requirements present for what the operator sees when persisted state is dropped (silent, banner per FR-076, dedicated explanation)? [Consistency, Spec §FR-070 / §FR-076]

## First-Launch Project Resolution (FR-076)

- [ ] CHK017 - Does FR-076 define what counts as "still resolves" (project registered with daemon? or inferable from any current adopted agent's `project_path`)? [Clarity, Spec §FR-076]
- [ ] CHK018 - Are requirements present for the banner copy and lifetime — does the banner clear on operator dismiss, on next project selection, or on next launch? [Coverage, Gap, Spec §FR-076]
- [ ] CHK019 - Are requirements present for the case where multiple projects exist and the last-active is gone — does the app preserve sort/filter state from the lost project (it goes nowhere), or apply it to the new selection? [Coverage, Gap, Spec §FR-076 / §FR-078]
- [ ] CHK020 - Are requirements present for first-launch when no project has ever been selected — does the app land on onboarding (FR-010) or on an empty Projects view? [Coverage, Gap, Spec §FR-010 / §FR-076]

## Project Removal (FR-077)

- [ ] CHK021 - Does FR-077 define what is included in "project-scoped UI persistence" — does it cover last sub-view, sort/filter, AND any project-specific Settings overrides? [Completeness, Spec §FR-077]
- [ ] CHK022 - Are requirements present for the project-removal confirmation — what is shown (project name + repo path + summary of what is being cleared)? [Coverage, Gap, Spec §FR-077]
- [ ] CHK023 - Are requirements present for what happens to the global "last project" pointer when the operator removes the currently-selected project? [Coverage, Gap, Spec §FR-076 / §FR-077]
- [ ] CHK024 - Are requirements present for whether the operator can "undo" project removal within the session, or is removal immediate and final? [Coverage, Gap, Spec §FR-077]

## List-View Persistence (FR-078)

- [ ] CHK025 - Does FR-078 enumerate every list view it applies to (the FR-063 ten lists) and is the scope of "sort and filter selections" defined per list (e.g. for Events, is the active "event class" filter persisted)? [Completeness, Spec §FR-078]
- [ ] CHK026 - Are requirements present for what happens when a persisted filter references an enum value the daemon no longer recognizes (stale filter on version skew)? [Coverage, Gap, Spec §FR-078]
- [ ] CHK027 - Are requirements present for the size of per-project persisted filter state — is there a cap so a runaway count of saved filters cannot grow without bound? [Coverage, Gap, Spec §FR-078]
- [ ] CHK028 - Is the per-project scoping for Drift / Available Validation / Runs (FR-078) consistent with FR-077's "clears that project's UI-side persistence" — are the same filters cleared on removal? [Consistency, Spec §FR-077 / §FR-078]
- [ ] CHK029 - Are requirements present for whether per-project persistence is cleared on contract-version-incompatible state (FR-002 / FR-070), or retained? [Consistency, Gap, Spec §FR-002 / §FR-070 / §FR-078]

## Persistence vs. Per-OS-User Isolation (FR-061a)

- [ ] CHK030 - Is FR-061a's "stores its UX state ... in that OS user's standard config / data directories" tied to FR-069's "local user-scoped config store" — do both reference the same location? [Consistency, Spec §FR-061a / §FR-069]
- [ ] CHK031 - Are requirements present for ensuring the diagnostics bundle (FR-074) for User A cannot include persisted state from User B's directory? [Coverage, Spec §FR-061a / §FR-074]

## Crash & Corruption Recovery

- [ ] CHK032 - Are requirements present for what happens when persisted state cannot be read on launch (corrupt, permissions error, schema mismatch)? [Coverage, Gap, Spec §FR-069]
- [ ] CHK033 - Are requirements present for a "reset to defaults" affordance the operator can trigger from Settings to clear persisted state without uninstall? [Coverage, Gap, Spec §FR-069]
- [ ] CHK034 - Are requirements present for whether a corrupted persisted state is quarantined for later inspection (renamed aside) or deleted outright? [Coverage, Gap]

## Write Cadence & Performance

- [ ] CHK035 - Are requirements present for how frequently UX state writes happen (every change, debounced, on close, on heartbeat)? [Clarity, Gap, Spec §FR-069 / §FR-082]
- [ ] CHK036 - Are requirements present for ensuring persistence writes do not stall the UI thread (especially on immediate-close per FR-082)? [Coverage, Gap, Spec §FR-069 / §FR-082]
- [ ] CHK037 - Are requirements present for what happens to unwritten UX state at the moment of FR-082 immediate close — is there a "flush before exit" guarantee? [Coverage, Spec §FR-082]

## Scenario Class Coverage (Persistence)

- [ ] CHK038 - Are Alternate-flow persistence requirements present (operator opens app, immediately closes — does anything new persist)? [Coverage, Gap]
- [ ] CHK039 - Are Exception-flow persistence requirements present (disk full mid-write, write succeeds but read fails)? [Coverage, Gap, Spec §FR-069]
- [ ] CHK040 - Are Recovery-flow persistence requirements present for the cross-version migration path? [Coverage, Spec §FR-070]
- [ ] CHK041 - Are Non-Functional persistence requirements present for the on-disk footprint (size budget)? [Coverage, Gap]

## Measurability

- [ ] CHK042 - Can the FR-069 inclusion/exclusion list be verified by inspecting the on-disk config store and asserting each named field is present and no excluded field (session token, domain data) is present? [Measurability, Spec §FR-069]
- [ ] CHK043 - Can the FR-070 compatibility check be measured by an automated test that flips the app version major or contract version major and asserts persisted UX is dropped? [Measurability, Spec §FR-070]
- [ ] CHK044 - Can the FR-061a per-OS-user isolation be measured by a two-user test on a single OS? [Measurability, Spec §FR-061a]

## Round 2 — Post-plan re-verification (2026-05-23)

Re-checks that the plan-side artifacts (`research.md` R-05/R-06/R-21, `contracts/ux-state.md`, `data-model.md` §2.1) actually close the Round-1 gaps and that the persisted-state contract is now load-bearingly specified.

- [ ] CHK045 - Does research R-05 + ux-state.md cover state-persistence CHK010 (on-disk format)? [Closure-check, Round-1 CHK010]
- [ ] CHK046 - Does research R-05 + ux-state.md cover state-persistence CHK011 (atomicity)? [Closure-check, Round-1 CHK011]
- [ ] CHK047 - Does ux-state.md §file-location cover state-persistence CHK009 (per-OS paths)? [Closure-check, Round-1 CHK009]
- [ ] CHK048 - Does research R-21 + ux-state.md §2 cover state-persistence CHK015/CHK040 (cross-version migration path)? [Closure-check, Round-1 CHK015/CHK040]
- [ ] CHK049 - Does ux-state.md §2 §corruption-recovery cover state-persistence CHK032 (corrupt persisted state launch behavior)? [Closure-check, Round-1 CHK032]
- [ ] CHK050 - Does ux-state.md §3 / data-model.md §2.1 explicitly list "Onboarding milestone completion" as persisted, closing CHK003? [Closure-check, Round-1 CHK003]
- [ ] CHK051 - Does ux-state.md §3 / data-model.md §2.1 explicitly state "settings file permissions" (CHK012) — note: deferred to OS-inherited; verify the deferral is intentional and documented? [Closure-check, Round-1 CHK012]
- [ ] CHK052 - Does ux-state.md §2 §cross-user-isolation address CHK031 (diagnostics bundle cross-user isolation)? [Closure-check, Round-1 CHK031]
- [ ] CHK053 - Does data-model.md §2.1 §write-rules name the immediate-flush-on-close behavior so CHK037 (FR-082 flush guarantee) is addressed? [Closure-check, Round-1 CHK037]
- [ ] CHK054 - Are there Round-1 gaps NOT closed by the plan artifacts: removed-projects memory (CHK005), multi-project lost last-active behavior (CHK019), global last-project pointer on removal (CHK023), per-list filter dimensions (CHK025), stale-filter on version skew (CHK026)? [Gap-tracking, Round-1 CHK005/019/023/025/026]
- [ ] CHK055 - Does the plan-side artifacts introduce ANY new persistence-related gap not covered by Round-1 (e.g. window-geometry on monitor disconnect, settings drift between memory and disk during settings edit)? [Coverage]


---

## Walk audit — 2026-05-23 (Smart walk)

**Items intentionally left `[ ]`**. This checklist captured a Round-1 audit of the spec.md authoring quality before the plan/research/data-model artifacts existed. Many items surfaced real gaps that were triaged into Tier 1 / Tier 2 / Tier 3 / Tier 4 backlogs during the subsequent /speckit-checklist Round-2 walkthrough.

**Closure status**:
- **Tier 1 items** (F1..F12 — 12 findings): CLOSED by the Codex spec-quality-pass change archived at `openspec/changes/archive/2026-05-23-spec-quality-pass-feat-012/`. The CHK items in this file that correspond to F1..F12 are now satisfied by the post-Codex spec.md but remain `[ ]` here as a historical audit record.
- **Tier 2 items** (F-A1..F-A11 from /speckit-checklist Round 2): MOSTLY CLOSED. F-A1 + F-A2 + F-A11 were fixed in commit 78d3ad8 (Tier-1 plan-side fixes); F-A6 was fixed by plan.md Complexity Tracking row 3. F-A3, F-A4, F-A5, F-A9, F-A13 remain open as cosmetic spec/data-model polish (see `alignment.md` reverted items for the canonical record).
- **Tier 3 / Tier 4 items**: DEFERRED. Documented in the prior `/speckit-checklist` and `/speckit-analyze` findings reports; non-blocking; expected to be addressed opportunistically during /speckit-implement or as a follow-on Spec Kit feature.

**Why not bulk-mark `[X]`**: Bulk-marking would hide the historical audit value. This checklist is honest about the gaps it surfaced; gap closure is tracked in the commit log + the alignment.md walk audit + the /speckit-analyze remediation notes in commit 58eac22.

**Re-walk trigger**: Re-run this checklist only if doing a fresh requirement-quality audit of spec.md from scratch (e.g. after a major spec rewrite).
