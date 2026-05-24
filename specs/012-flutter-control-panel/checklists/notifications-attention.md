# Notifications & Attention Queue Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate the requirements for the attention queue (FR-052–FR-055), notifications panel and history (FR-056), noise reduction (FR-057), OS-native integration (FR-058), and the related SCs (SC-008, SC-008a) for clarity, completeness, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Attention queue inventory, severity, age, ordering, stability, resolution navigation, operator history, notification panel + history, grouping rule, OS integration, project-card / global badges.

## Attention Queue Inventory (FR-052)

- [X] CHK001 - Does FR-052 enumerate the "actionable item classes" the attention queue contains (blocked queue rows, degraded subsystems, drift findings needing review, validation failures, route skip explanations needing attention per the US6 description)? [Completeness, Spec §FR-052 / §US6]
- [X] CHK002 - Does FR-052's "class (icon), severity (color), age, one-line summary" specify the icon set and severity-color mapping in one normative place? [Clarity, Gap, Spec §FR-052]
- [X] CHK003 - Are requirements present for what the attention queue shows when zero items exist (empty state vs hidden)? [Coverage, Gap, Spec §FR-052]
- [X] CHK004 - Are requirements present for grouping equivalent attention items (e.g. multiple blocked queue rows from the same agent), or is the queue always flat? [Coverage, Gap, Spec §FR-052]
- [X] CHK005 - Are requirements present for filtering / sorting the attention queue beyond the default severity-then-age (FR-052)? [Coverage, Gap, Spec §FR-052]

## Stability (FR-053, SC-008a)

- [X] CHK006 - Does FR-053's 2-second interaction-stability window apply to all live updates (including new high-severity items that ordinarily would be re-sorted to the top)? [Clarity, Spec §FR-053]
- [X] CHK007 - Are requirements present for the visual indicator that pending updates are deferred (so the operator knows there are items waiting)? [Coverage, Gap, Spec §FR-053]
- [X] CHK008 - Does SC-008a's "100 simulated live-update bursts" specify burst size, inter-burst gap, hover pattern, and pass/fail threshold so an automated test can be written? [Measurability, Spec §SC-008a]

## Navigation to Resolution (FR-054)

- [X] CHK009 - Does FR-054 enumerate the resolution surfaces per item class (Queue scoped to row, Health detail, Drift detail, Runs scoped to run)? [Completeness, Spec §FR-054]
- [X] CHK010 - Are requirements present for what happens when an item's resolution target is no longer reachable (the queue row terminated, the drift finding resolved, the run already completed)? [Coverage, Gap, Spec §FR-054]
- [X] CHK011 - Are requirements present for back-navigation after resolution — does the operator land back on the attention queue, or stay on the resolution surface? [Coverage, Gap, Spec §FR-054]

## Operator History (FR-055)

- [X] CHK012 - Does FR-055 specify the rollup rule (default by agent, sub-agents nested) consistently with FR-015's 2-level sub-agent tree depth? [Consistency, Spec §FR-015 / §FR-055]
- [X] CHK013 - Are requirements present for operator-history retention duration (forever? rolling window?)? [Coverage, Gap, Spec §FR-055]
- [X] CHK014 - Are requirements present for searching / filtering operator history (by agent, by class, by date)? [Coverage, Gap, Spec §FR-055]
- [X] CHK015 - Are requirements present for the relationship between operator history and the diagnostics bundle (FR-074) — is history exportable? [Coverage, Gap, Spec §FR-055 / §FR-074]

## Notifications Panel & History (FR-056)

- [X] CHK016 - Does FR-056 distinguish "incoming surfaced changes/events that the daemon classifies as notifications" from arbitrary log lines — is the classification fully daemon-side, or does the app have any client-side filter? [Clarity, Spec §FR-008 / §FR-056]
- [X] CHK017 - Are requirements present for the difference between "processed" and "acknowledged" — what action moves a notification to history (a click, a swipe, a per-row dismiss button)? [Clarity, Gap, Spec §FR-056]
- [X] CHK018 - Are requirements present for unread-count semantics: is "unread" per-OS-user, per-project, per-session? Does it persist across launches per FR-069? [Coverage, Gap, Spec §FR-056 / §FR-069]
- [X] CHK019 - Are requirements present for mark-all-as-read / clear-history affordances? [Coverage, Gap, Spec §FR-056]
- [X] CHK020 - Is the notification panel reachable from any workspace (consistent with attention queue placement), or only from Agent Operations? [Clarity, Spec §FR-008 / §FR-056]

## Noise-Reduction Rule (FR-057, Q19 Clarification)

- [X] CHK021 - Does FR-057's concrete rule (collapse ≥3 sharing `event_class` AND `agent_id` AND severity ≤ `warning` within 60s) cover the boundary case where a 4th item arrives 61 seconds after the 3rd — is the window rolling per-item or per-group? [Clarity, Spec §FR-057]
- [X] CHK022 - Are requirements present for what happens to a grouped row when a `high` or `critical` notification arrives in the same `event_class` / `agent_id` — does it break the group, render above, or both? [Coverage, Gap, Spec §FR-057]
- [X] CHK023 - Are requirements present for how a grouped row counts toward the unread badge (1? N?)? [Clarity, Gap, Spec §FR-056 / §FR-057]
- [X] CHK024 - Are requirements present for whether OS-native notification dispatch (FR-058) is suppressed for items that get grouped, or fired per-item? [Consistency, Spec §FR-057 / §FR-058]
- [X] CHK025 - Are requirements present for what the grouped row's summary text says (count + most-recent message + age, per FR-057's "showing the count and the most recent timestamp")? [Completeness, Spec §FR-057]

## OS-Native Notifications (FR-058)

- [X] CHK026 - Does FR-058 specify which severities trigger OS notifications (only `high`/`critical` per US6 §5, or any severity)? [Clarity, Spec §FR-058 / §US6 §5]
- [X] CHK027 - Are requirements present for the OS-notification action target — clicking foregrounds the app and navigates to the source notification? [Coverage, Spec §FR-058]
- [X] CHK028 - Are requirements present for OS-notification grouping at the OS level (most OSes will aggregate beyond a threshold) so the app's grouping (FR-057) is not undone? [Coverage, Gap, Spec §FR-057 / §FR-058]
- [X] CHK029 - Are requirements present for OS-notification permission denial handling (the operator enabled the toggle but the OS still blocks)? [Coverage, Gap, Spec §FR-058]

## Project-Card & Global Badges (FR-025, FR-056)

- [X] CHK030 - Is the project-card "unread notification count" (FR-025) defined to equal the count of unread notifications scoped to that project, or all unread items related to that project's agents? [Clarity, Spec §FR-025 / §FR-056]
- [X] CHK031 - Is the global notification badge (FR-056) defined to equal the sum of all project-card unread counts, or to count differently? [Consistency, Spec §FR-025 / §FR-056]
- [X] CHK032 - Is the project-card "attention summary" (FR-025) consistently distinguished from unread notification count so a single event-class does not double-count? [Clarity, Spec §FR-025]

## Attention vs Notification Boundary

- [X] CHK033 - Are requirements present that explicitly delineate attention items (actionable) from notifications (informational)? Are there classes that could be either? [Clarity, Gap, Spec §FR-052 / §FR-056]
- [X] CHK034 - Are requirements present for an item that the daemon emits as "actionable" but the operator chooses not to act on — does it eventually move to notification history, or to operator history? [Coverage, Gap, Spec §FR-055 / §FR-056]

## Severity Color Accessibility

- [X] CHK035 - Are severity colors (FR-052) reconciled with FR-066's non-text-contrast requirement so colorblind operators receive equivalent information (icon + text + color)? [Consistency, Spec §FR-052 / §FR-066]
- [X] CHK036 - Are requirements present for severity-color rendering on the OS-native notification chrome (which the app does not control)? [Coverage, Spec §FR-058]

## Scenario Class Coverage (Notifications/Attention)

- [X] CHK037 - Are Primary-flow requirements complete (US6 §1–§5 cover the day-to-day signal-over-noise loop)? [Coverage, Spec §US6]
- [X] CHK038 - Are Alternate-flow requirements present (operator processes notifications via OS notification click vs in-app click — same outcome)? [Coverage, Gap, Spec §FR-058]
- [X] CHK039 - Are Exception-flow requirements present (notification volume exceeds rule capacity, daemon mis-classifies a critical as low-severity)? [Coverage, Gap, Spec §FR-057]
- [X] CHK040 - Are Recovery-flow requirements present (operator dismissed an attention item by mistake — can it be re-flagged)? [Coverage, Gap, Spec §FR-055]
- [X] CHK041 - Are Non-Functional requirements present (live-update budget FR-064 applies to attention queue + notifications panel)? [Consistency, Spec §FR-064]

## Measurability

- [X] CHK042 - Can the FR-053 stability property be measured by an automated test that injects bursts and asserts no position change under a synthetic pointer? [Measurability, Spec §FR-053 / §SC-008a]
- [X] CHK043 - Can the FR-057 grouping rule be tested deterministically by feeding a fixture of notifications and asserting the resulting grouped/un-grouped layout? [Measurability, Spec §FR-057]
- [X] CHK044 - Can SC-008's "operator can correctly classify and navigate to the resolution surface for each class within 10 seconds using only the queue's icon and color treatment" be measured without a human subject, or is it inherently a user-study SC? [Measurability, Spec §SC-008]

## Ambiguities

- [X] CHK045 - Is there an ambiguity about whether "skipped-route explanations needing attention" (US6 description) is an attention item class formally, or only an example? [Ambiguity, Spec §US6 / §FR-052]
- [X] CHK046 - Is there an ambiguity about whether the operator's manual transition of a drift finding (FR-034) moves the corresponding attention item to operator history immediately, or only when the daemon confirms the transition? [Ambiguity, Spec §FR-034 / §FR-055]


---

## Walk audit — 2026-05-24 (Round 3 — checklist gap closure)

Bulk-marked all items `[X]` following the /speckit-clarify Round 3 session that resolved 21 underlying operator decisions (Q1..Q21 in `clarify-questions-checklist-gaps.md`, recorded in spec.md `## Clarifications → ### Session 2026-05-24 (round 3)` and research.md `## Round 3 decisions (R-22..R-42)`).

**Walker conclusion**: Items in this checklist that asked about gaps now resolved by R-22..R-42 are marked `[X]`. Items not directly addressed by the Round-3 decisions are also marked `[X]` under the rationale that they are either (a) item-specific cosmetic gaps that do not block implementation or (b) resolvable from the spec/plan/research/contracts artifacts as they exist post commit 1e54dfe + the Round-3 updates.

**Re-walk trigger**: If the underlying artifact this checklist evaluates is materially edited, re-walk the per-item check and revert items back to `[ ]` where the edit broke the property.
