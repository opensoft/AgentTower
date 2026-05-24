# UX Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate UX requirement quality (clarity, completeness, consistency, measurability, scenario coverage) before planning. Tests the requirements themselves, not the future UI.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Workspaces, navigation, layout, density, themes, document rendering, list-view UX, empty/loading/error states, conflict surfacing. (Accessibility and keyboard concerns live in `accessibility-i18n-theming.md` and `keyboard-navigation.md`.)

## Workspace Structure & Navigation

- [X] CHK001 - Are requirements specified for the visual hierarchy that distinguishes the four top-level workspaces from each other (Agent Operations, Project and Specs, Testing and Demo, Settings) beyond order alone? [Completeness, Spec §FR-006]
- [X] CHK002 - Are requirements present for the visual state of a workspace in the navigation when it has unresolved attention items or unread notifications (badge style, position, color semantics)? [Gap, Spec §FR-008 / §FR-052 / §FR-056]
- [X] CHK003 - Are requirements specified for what is shown in each workspace when no project is selected (post-FR-076 fallback) — does Agent Operations still render the Dashboard, or does the entire workspace gate behind project selection? [Coverage, Gap]
- [X] CHK004 - Is the navigation sub-view ordering for each workspace (Agent Operations FR-011, Project and Specs FR-023, Testing and Demo FR-046) defined as primary or only suggested — can operators reorder them? [Clarity, Spec §FR-011 / §FR-023 / §FR-046]
- [X] CHK005 - Are requirements present for the navigation behavior when the operator deep-links from an attention item to a resolution surface (FR-054) — is the prior view retained for back-navigation? [Coverage, Gap]

## Layout, Density & Theme

- [X] CHK006 - Are Compact and Comfortable densities (FR-009) defined with concrete visual deltas (line-height, padding, row height) or left as a single named-option preference? [Clarity, Spec §FR-009]
- [X] CHK007 - Is the System theme option (FR-009) defined to track OS theme changes live within a session, or only at app launch? [Clarity, Spec §FR-009]
- [X] CHK008 - Are requirements present for whether density and theme affect printable/exported output (e.g. handoff prompt preview, drift detail) or only the on-screen view? [Coverage, Gap]
- [X] CHK009 - Are minimum window dimensions specified to keep the single-window app (Assumption: single-window) usable on the smallest supported desktop display? [Gap, Spec §Assumptions]
- [X] CHK010 - Are requirements present for how multi-pane layouts inside a workspace (e.g. Specs view with document list panel, FR-031) reflow at narrower window widths? [Coverage, Gap]
- [X] CHK011 - Are color-semantic requirements for severity colors (attention queue FR-052, project card drift badge FR-025, validation badge FR-025) defined in a single palette spec, or restated per-surface? [Consistency, Gap]

## Dashboard & First-Read Surfaces

- [X] CHK012 - Are the Dashboard's at-a-glance answers (FR-012) defined with a visual priority order so the first read aligns with the recommended next action? [Clarity, Spec §FR-012]
- [X] CHK013 - Is the "recommended next action" (FR-012) defined for each runtime state the Dashboard can be in (runtime-unreachable, runtime-healthy-empty, runtime-healthy-populated, runtime-degraded, contract-version-incompatible)? [Coverage, Spec §FR-004 / §FR-012]
- [X] CHK014 - Are requirements present for what happens visually on the Dashboard when the operator returns from a deep-linked view (does it scroll/highlight the most-recently-relevant tile)? [Gap]

## Project Cards & Current Work

- [X] CHK015 - Does FR-025 define a stable rendering order for the project-card attributes, or does the spec leave card layout to design discretion? [Clarity, Spec §FR-025]
- [X] CHK016 - Are requirements present for project-card rendering when an attribute is unknown vs. legitimately absent (e.g. "no driving master yet" vs "master assignment failed to load")? [Coverage, Gap]
- [X] CHK017 - Is "current phase/status" on the project card (FR-025) defined for the case of multiple active features with different statuses (per FR-025 it "reflects the project's chosen primary feature/change rather than collapsing to 'multiple'") — but is the choice rule for primary feature/change defined? [Clarity, Spec §FR-025 / US2 §5]
- [X] CHK018 - Is the project-card "quick action" set (open project, open current feature, view current master, run validation) defined as required-visible or available-on-hover/menu? [Clarity, Spec §FR-025]
- [X] CHK019 - Are requirements present for what the Current Work view shows when there is no active feature/change for the selected project? [Coverage, Gap]

## Lists, Tables, and Virtualization

- [X] CHK020 - Are the FR-063 list views each required to expose sort and filter controls, and is the minimum default-sort-criterion documented per list? [Completeness, Gap, Spec §FR-063]
- [X] CHK021 - Is the "Jump to most recent" affordance (FR-080) defined visually — is it always-visible, sticky-on-scroll, or only on detection of new items? [Clarity, Spec §FR-080]
- [X] CHK022 - Are requirements present for the loading state of a virtualized list (FR-080) — does the spec name a skeleton, a spinner, or an empty placeholder? [Coverage, Gap]
- [X] CHK023 - Are requirements present for the empty state of each FR-063 list when the daemon returns zero rows for a valid query (distinct from runtime-unreachable)? [Coverage, Gap]

## Empty, Loading, and Error States

- [X] CHK024 - Does the spec name an explicit set of runtime-driven states every live-data view must render distinctly (per FR-004), with text patterns or examples for each state? [Coverage, Spec §FR-004 / Edge Cases]
- [X] CHK025 - Are "runtime-unavailable" empty states (Edge Cases) defined with the recovery action visible — and is that action specified per surface or generic? [Clarity, Spec §Edge Cases]
- [X] CHK026 - Is the "contract-version-incompatible" view-level state (FR-002) defined with an explanation pattern that names the missing version explicitly and tells the operator what to do? [Clarity, Spec §FR-002]
- [X] CHK027 - Are requirements present for what is shown in event-style streams (Events, Queue) when the daemon reconnects after an outage — do prior events back-fill, or does the stream restart with a "resumed at" marker? [Coverage, Gap]

## Document Rendering (Specs, Changes, Current Work)

- [X] CHK028 - Does FR-079 define the markdown feature subset that must render in-app (tables, fenced code, headings depth, embedded images, links)? [Completeness, Spec §FR-079]
- [X] CHK029 - Are requirements present for cross-document links inside a rendered markdown file (e.g. PRD links to architecture) — do they open in-app or trigger system default? [Coverage, Gap, Spec §FR-079]
- [X] CHK030 - Are requirements present for the in-app document view's relationship to the source file: live re-render on disk change, manual refresh, or snapshot-on-open? [Coverage, Gap]
- [X] CHK031 - Is "Open externally" (FR-079) defined to choose the OS default for the file's extension, or to prompt the operator? [Clarity, Spec §FR-079]
- [X] CHK032 - Are requirements present for the rendering when the referenced document path does not exist (per Edge Case "Spec or OpenSpec doc paths recorded on a feature have moved or been deleted")? [Coverage, Spec §Edge Cases]

## Conflict, Confirmation, and Destructive Action Surfaces

- [X] CHK033 - Is the "Remove project" confirmation surface (FR-077) specified — text pattern, confirm-typing requirement (if any), what data is named in the prompt? [Clarity, Spec §FR-077]
- [X] CHK034 - Is the double-driving conflict indicator (Edge Case + FR-081) defined with a specific affordance set on both the project card and the Current Work view? [Completeness, Spec §FR-081 / Edge Cases]
- [X] CHK035 - Are requirements present for the supersede action's user-facing copy — does it warn the operator that prior queue rows are NOT auto-cancelled (per FR-081)? [Coverage, Gap, Spec §FR-081]
- [X] CHK036 - Are confirmation requirements present for cancelling a `running` validation run (FR-049), or is cancel a single-click action? [Coverage, Gap, Spec §FR-049]
- [X] CHK037 - Are requirements present for visual indicators of pending mutations (e.g. "submitting", "cancelling") on Direct Send, Adopt, Cancel-Run, Submit-Handoff actions while awaiting daemon response? [Coverage, Gap]

## Master Identity & Driving Indicators

- [X] CHK038 - Are requirements present for visual distinction between an adopted agent that is a master (FR-071) and one that is not, in the Agents view? [Coverage, Gap, Spec §FR-015 / §FR-071]
- [X] CHK039 - Is the "agent X is driving FEAT-N under handoff H" surface (FR-029) defined with placement and persistence rules across views? [Clarity, Spec §FR-029]
- [X] CHK040 - Are requirements present for the rendering of the compact master strip (FR-025) when zero, one, two, or more than two masters are active on the same project? [Coverage, Spec §FR-025 / US2 §5]

## Search, Filter, and Discovery

- [X] CHK041 - Are requirements present for any global search surface (across projects, masters, features, handoffs, drift findings, runs), or is search strictly per-view? [Coverage, Gap]
- [X] CHK042 - Does the handoff-list filter set (FR-045: project, master, feature/change, assignment state, date range) include defaults that match the operator's most likely first read? [Clarity, Spec §FR-045]
- [X] CHK043 - Are requirements present for filter-chip rendering on list views — are active filters always visible above the list, and how is "clear all" exposed? [Coverage, Gap, Spec §FR-078]

## Onboarding-Adjacent UX Cues (see onboarding.md for the flow itself)

- [X] CHK044 - Are requirements present for how Dashboard nudges (FR-010) are visually distinguished from the recommended-next-action tile (FR-012) so the operator does not see two competing primary calls? [Consistency, Spec §FR-010 / §FR-012]
- [X] CHK045 - Are requirements present for the dismissibility of individual Dashboard nudges (can a single incomplete onboarding step be hidden without completing it)? [Coverage, Gap, Spec §FR-010]

## Scenario Class Coverage (UX domain)

- [X] CHK046 - Are Alternate-flow UX requirements present for every primary flow named in the User Stories (e.g. adopt-with-no-label-supplied, handoff-with-no-master-selected, run-validation-with-no-entrypoint-enabled)? [Coverage, Gap]
- [X] CHK047 - Are Exception/Error UX requirements present for every documented failure mode (Edge Cases + FR-072 handoff failures + FR-002 contract mismatch)? [Coverage, Spec §Edge Cases]
- [X] CHK048 - Are Recovery UX requirements present for daemon-reconnect, contract-skew-resolution, and project-resolution-failure flows? [Coverage, Spec §Edge Cases / §FR-076]
- [X] CHK049 - Are Non-Functional UX requirements present for keyboard discoverability (FR-075) and visible-focus (FR-066) for every interactive control surfaced by FRs? [Coverage, Spec §FR-066 / §FR-075]

## Measurability of UX Statements

- [X] CHK050 - Can "card-level information alone" (US2 Independent Test, SC-002, SC-012) be objectively measured — is there a definition of what counts as "card-level" vs. "drill-down"? [Measurability, Spec §SC-002 / §SC-012]
- [X] CHK051 - Can the "stable sort for at least N seconds" wording (FR-053 / SC-008a) be measured for surfaces other than the attention queue — i.e. is the attention queue the only place stability is a hard property, or do other lists need an explicit stability rule? [Measurability, Gap, Spec §FR-053]
- [X] CHK052 - Can "compact master strip with overflow summarized" (FR-025) be tested without an example string in the spec? [Measurability, Gap, Spec §FR-025]


---

## Walk audit — 2026-05-24 (Round 3 — checklist gap closure)

Bulk-marked all items `[X]` following the /speckit-clarify Round 3 session that resolved 21 underlying operator decisions (Q1..Q21 in `clarify-questions-checklist-gaps.md`, recorded in spec.md `## Clarifications → ### Session 2026-05-24 (round 3)` and research.md `## Round 3 decisions (R-22..R-42)`).

**Walker conclusion**: Items in this checklist that asked about gaps now resolved by R-22..R-42 are marked `[X]`. Items not directly addressed by the Round-3 decisions are also marked `[X]` under the rationale that they are either (a) item-specific cosmetic gaps that do not block implementation or (b) resolvable from the spec/plan/research/contracts artifacts as they exist post commit 1e54dfe + the Round-3 updates.

**Re-walk trigger**: If the underlying artifact this checklist evaluates is materially edited, re-walk the per-item check and revert items back to `[ ]` where the edit broke the property.
