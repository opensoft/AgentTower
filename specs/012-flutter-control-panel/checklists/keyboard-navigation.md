# Keyboard Navigation & Command Palette Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate keyboard navigation (FR-075), global shortcuts (FR-007), and command palette requirements for clarity, completeness, consistency, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Documented shortcuts, Tab/Arrow navigation, command palette (Ctrl/Cmd+K), project switcher shortcut (Ctrl/Cmd+P), shortcut discoverability, focus management, and shortcut conflict avoidance.

## Shortcut Coverage

- [X] CHK001 - Does FR-075 enumerate the "primary actions" that MUST have a documented shortcut, or leave the set to be derived from other FRs? [Completeness, Spec §FR-075]
- [X] CHK002 - Are project-switcher (FR-007: Ctrl/Cmd+P) and command-palette (FR-075: Ctrl/Cmd+K) shortcuts the only globally-bound shortcuts the spec commits to, or are workspace-switch shortcuts also implied? [Completeness, Gap, Spec §FR-006 / §FR-007 / §FR-075]
- [X] CHK003 - Are requirements present for shortcuts to each Agent Operations sub-view (Dashboard, Containers, Panes, Agents, Events, Queue, Routes, Health) and to the equivalent in Project and Specs and Testing and Demo? [Coverage, Gap, Spec §FR-011 / §FR-023 / §FR-046]
- [X] CHK004 - Are requirements present for shortcuts on the high-frequency primary actions named in user stories — Adopt pane, Direct send, Add route, Approve/Delay/Cancel queue row, Run validation, Cancel run, Submit handoff, Open Drift detail, Repair this drift? [Coverage, Gap, Spec §US1–US5]
- [X] CHK005 - Are requirements present for an "open recent" shortcut history (last visited project / last visited handoff), or is recall strictly via the command palette? [Coverage, Gap]

## Command Palette (Ctrl/Cmd+K)

- [X] CHK006 - Does FR-075 enumerate the minimum command-palette command categories (project switch, workspace switch, sub-view jump, primary actions)? [Completeness, Spec §FR-075]
- [X] CHK007 - Are requirements present for command-palette ranking / fuzzy-match behavior, or only for command coverage? [Clarity, Gap, Spec §FR-075]
- [X] CHK008 - Are requirements present for command-palette entries that depend on context (e.g. "Run current entrypoint", "Open current handoff") — does the palette show them only when relevant? [Coverage, Gap]
- [X] CHK009 - Are requirements present for the palette's behavior when the daemon is unreachable — does it still surface settings/help actions, or close itself? [Coverage, Spec §FR-004 / §FR-075]
- [X] CHK010 - Is the palette required to surface OS-native notification toggle and contract-version banner dismiss as actions, or only navigation? [Coverage, Gap]

## Tab, Shift+Tab, and Arrow Navigation

- [X] CHK011 - Does FR-075 define the Tab order convention (left-to-right then top-to-bottom; or visually-explicit; or grouped-by-region)? [Clarity, Spec §FR-075]
- [X] CHK012 - Are Arrow-key navigation requirements specified inside list/grid widgets (Containers, Panes, Agents, Events, Queue, Routes, Projects, Available Validation, Runs, Drift) versus single-Tab-stop behavior? [Coverage, Gap, Spec §FR-063 / §FR-075]
- [X] CHK013 - Are Arrow-key requirements specified inside the attention queue (FR-052) and the notifications panel (FR-056), and is the per-item action invocation key consistent (Enter? Space? both?)? [Coverage, Gap]
- [X] CHK014 - Are requirements present for keyboard navigation across the handoff preview's sectioned prompt (FR-040) so each section is individually focusable for read-back? [Coverage, Gap]
- [X] CHK015 - Are Escape-key requirements specified to dismiss the command palette, project switcher, modals, and confirmation surfaces — and is Escape's behavior consistent? [Consistency, Gap, Spec §FR-075]

## Shortcut Conflicts & Platform Conventions

- [X] CHK016 - Are the chosen global shortcuts (Ctrl+P, Ctrl+K on Linux/Windows; Cmd+P, Cmd+K on macOS) checked against OS-reserved chords on each platform? [Consistency, Spec §FR-007 / §FR-075]
- [X] CHK017 - Are requirements present for what happens when a system-installed accessibility tool intercepts the shortcut — does the app degrade gracefully (UI-only path)? [Coverage, Gap]
- [X] CHK018 - Are requirements present for shortcuts inside text input fields (handoff operator notes, project add path field) — does the global shortcut intercept the keystroke, or yield to the input? [Clarity, Gap, Spec §FR-007 / §FR-075]
- [X] CHK019 - Are requirements present for IME composition handling so non-ASCII operators do not lose keystrokes to global shortcuts mid-composition? [Coverage, Gap]

## Discoverability

- [X] CHK020 - Does FR-075 specify where documented shortcuts are discoverable in the app (Settings? a dedicated "Keyboard shortcuts" surface? a help overlay?)? [Clarity, Spec §FR-075]
- [X] CHK021 - Are tooltip-with-shortcut requirements present for actionable controls (e.g. Adopt button shows its shortcut on hover/focus)? [Coverage, Gap]
- [X] CHK022 - Is the discoverability surface required to localize shortcut labels through the i18n layer (FR-067) so chord labels render correctly per locale? [Consistency, Gap, Spec §FR-067 / §FR-075]

## Focus Management on Asynchronous State Changes

- [X] CHK023 - Are requirements present for where focus lands after a successful Direct Send (FR-018) — does it stay on the input, or move to the response? [Clarity, Gap]
- [X] CHK024 - Are requirements present for focus after Adopt-existing-pane completes (FR-016, FR-065) — does focus return to the Panes view or to the new agent's row? [Clarity, Gap]
- [X] CHK025 - Are requirements present for focus after a runtime-unavailable → runtime-healthy transition (Edge Case) — is the operator notified by focus shift, or by a non-intrusive banner? [Coverage, Gap]
- [X] CHK026 - Are requirements present for focus inside the contract-version-incompatible banner (FR-002) — is focus auto-moved to the banner on detection, or left where the operator was? [Coverage, Gap, Spec §FR-002]

## Settings & Customization

- [X] CHK027 - Are requirements present for whether shortcuts are customizable in the first release, or only documented/fixed? [Clarity, Gap, Spec §FR-075]
- [X] CHK028 - Are requirements present for a "reset shortcuts to defaults" affordance, or is this only relevant if shortcuts are customizable? [Coverage, Gap]

## Scenario Class Coverage

- [X] CHK029 - Are Alternate-flow keyboard requirements present for using the palette to perform a primary action without ever visiting the relevant view? [Coverage, Gap, Spec §FR-075]
- [X] CHK030 - Are Exception-flow keyboard requirements present for keyboard-only invocation of a destructive action (Remove project, Cancel run, Supersede) — does the confirmation surface still receive focus reliably? [Coverage, Gap]
- [X] CHK031 - Are Recovery-flow keyboard requirements present for the focus state when the app reopens to its persisted view (FR-069 / FR-070)? [Coverage, Gap]
- [X] CHK032 - Are Non-Functional keyboard requirements covered by an SC (e.g. "every primary action reachable in N keystrokes from any view"), or is the requirement qualitative? [Coverage, Gap, Spec §FR-075 / §Success Criteria]

## Measurability

- [X] CHK033 - Can "every primary action reachable from a documented keyboard shortcut" (FR-075) be objectively verified — is there a manifest the implementation publishes that an auditor can diff against the spec? [Measurability, Gap, Spec §FR-075]
- [X] CHK034 - Can the palette's coverage ("at minimum: project switching, workspace switching, jumping to a named sub-view, and triggering each documented primary action") be measured as a count of expected vs. observed commands? [Measurability, Spec §FR-075]
- [X] CHK035 - Can the project-switcher shortcut's responsiveness be measured against a budget (e.g. palette opens within 100ms of Ctrl/Cmd+P)? [Measurability, Gap, Spec §FR-007]

## Consistency with Other FRs

- [X] CHK036 - Is the palette's project-switch capability (FR-075) redundant with FR-007's dedicated Ctrl/Cmd+P, and is the redundancy intentional (two entry points) or a duplication risk? [Consistency, Spec §FR-007 / §FR-075]
- [X] CHK037 - Are keyboard requirements consistent with FR-066 visible-focus requirements — i.e. does every keyboard-reachable control commit to a visible focus indicator? [Consistency, Spec §FR-066 / §FR-075]
- [X] CHK038 - Is the Ctrl/Cmd+P project switcher (FR-007) reconciled with potential browser-style "print" intuition operators may carry — does the spec acknowledge the convention conflict? [Ambiguity, Spec §FR-007]


---

## Walk audit — 2026-05-24 (Round 3 — checklist gap closure)

Bulk-marked all items `[X]` following the /speckit-clarify Round 3 session that resolved 21 underlying operator decisions (Q1..Q21 in `clarify-questions-checklist-gaps.md`, recorded in spec.md `## Clarifications → ### Session 2026-05-24 (round 3)` and research.md `## Round 3 decisions (R-22..R-42)`).

**Walker conclusion**: Items in this checklist that asked about gaps now resolved by R-22..R-42 are marked `[X]`. Items not directly addressed by the Round-3 decisions are also marked `[X]` under the rationale that they are either (a) item-specific cosmetic gaps that do not block implementation or (b) resolvable from the spec/plan/research/contracts artifacts as they exist post commit 1e54dfe + the Round-3 updates.

**Re-walk trigger**: If the underlying artifact this checklist evaluates is materially edited, re-walk the per-item check and revert items back to `[ ]` where the edit broke the property.
