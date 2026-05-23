# Configuration Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate Settings-surface requirements (FR-009), doctor/preflight (FR-009), socket discovery (FR-001, FR-009), and operator-controllable knobs for clarity, completeness, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Settings inventory, doctor/preflight, daemon socket path config, OS-native notification toggle, theme/density, notification-grouping toggle, contract-version display, persisted-state controls.

## Settings Inventory (FR-009)

- [ ] CHK001 - Does FR-009 enumerate every settable item the app exposes exhaustively, or does it list a minimum that other FRs add to (e.g. FR-058 OS-native notification toggle is named in both FR-009 and FR-058)? [Consistency, Spec §FR-009 / §FR-058 / §FR-057]
- [ ] CHK002 - Are settings grouped (Display, Notifications, Connection, Privacy, Diagnostics) in the spec, or only enumerated as a flat list? [Clarity, Gap, Spec §FR-009]
- [ ] CHK003 - Are requirements present for whether Settings changes apply immediately or require restart, per-setting? [Clarity, Gap, Spec §FR-009 / §FR-082]
- [ ] CHK004 - Are requirements present for a "reset to defaults" affordance per-setting and globally? [Coverage, Gap, Spec §FR-009]

## Socket Path Configuration

- [ ] CHK005 - Does FR-009's "daemon socket path" settings entry specify how it interacts with the OS-default discovery (Integration concerns) — does an explicit value override discovery? [Clarity, Spec §FR-001 / §FR-009]
- [ ] CHK006 - Are requirements present for validation of the socket-path field before save (existence check, peer-UID check)? [Coverage, Gap, Spec §FR-009 / §FR-061]
- [ ] CHK007 - Are requirements present for the in-app feedback when the socket path becomes unreachable after a save (does the Dashboard immediately flip to runtime-unreachable)? [Coverage, Spec §FR-004 / §FR-009]

## Doctor / Preflight (FR-009)

- [ ] CHK008 - Does FR-009's "config doctor / preflight check action" enumerate the checks it performs (socket reachable, contract version satisfied, file permissions, log directory writable, OS-native notification permission granted)? [Completeness, Gap, Spec §FR-009]
- [ ] CHK009 - Are requirements present for the doctor output format (per-check pass/fail with explanation, copy-to-clipboard, included in diagnostics bundle per FR-074)? [Clarity, Gap, Spec §FR-009 / §FR-074]
- [ ] CHK010 - Are requirements present for the doctor's behavior when a check fails (suggest a fix, link to documentation, or stop at the first failure)? [Coverage, Gap, Spec §FR-009]
- [ ] CHK011 - Is the doctor required to be runnable from the keyboard / command palette (FR-075), or only as a Settings button? [Coverage, Gap, Spec §FR-009 / §FR-075]

## Notifications-Grouping Toggle (FR-057, FR-009)

- [ ] CHK012 - Does the notifications-grouping toggle apply only to in-app notifications (FR-057) or also to OS-native notifications (FR-058)? [Clarity, Spec §FR-057 / §FR-058]
- [ ] CHK013 - Is the toggle's default state specified (on by default, per Q19 / FR-057)? [Completeness, Spec §FR-057]
- [ ] CHK014 - Are requirements present for the toggle's effect on already-grouped rows when toggled off (do they expand immediately or stay grouped for the session)? [Coverage, Gap, Spec §FR-057]

## OS-Native Notification Toggle (FR-058, FR-009)

- [ ] CHK015 - Is the OS-native notification toggle's default state specified (off per FR-058), and is the operator told when first enabling that OS-level permission may be required? [Clarity, Spec §FR-058]
- [ ] CHK016 - Are requirements present for the toggle being disabled (UI-greyed) when the OS reports notifications globally blocked at the OS level? [Coverage, Gap, Spec §FR-058]

## Theme & Density (FR-009, see also accessibility-i18n-theming.md)

- [ ] CHK017 - Are theme and density visible as Settings entries with a preview (so the operator can see the effect before committing)? [Coverage, Gap, Spec §FR-009]
- [ ] CHK018 - Are requirements present for whether changing theme or density triggers a full re-render or applies live? [Clarity, Gap, Spec §FR-009]

## Contract-Version Display

- [ ] CHK019 - Does the contract-version display in Settings show the same value as the Dashboard (FR-002) without divergence? [Consistency, Spec §FR-002 / §FR-009]
- [ ] CHK020 - Are requirements present for Settings showing the per-surface minimum-required version, or only the negotiated active version? [Coverage, Gap, Spec §FR-002 / §FR-009]

## App Version & Update Indicator

- [ ] CHK021 - Is the app version visible in Settings as well as on the Dashboard (FR-068)? [Coverage, Spec §FR-068]
- [ ] CHK022 - Is the "update available" indicator (FR-068) reachable from Settings with a link to the release page? [Coverage, Spec §FR-068]
- [ ] CHK023 - Are requirements present for an operator-triggered "check for updates now" affordance, or is the check only automatic-on-launch? [Coverage, Gap, Spec §FR-068]

## Diagnostics Controls (FR-074)

- [ ] CHK024 - Is "Open log folder" present in Settings (FR-074) with a platform-appropriate label (Show in Finder / Open in Explorer / xdg-open)? [Coverage, Spec §FR-074]
- [ ] CHK025 - Is "Copy diagnostics bundle" present in Settings (FR-074) with feedback after the action (e.g. "copied to clipboard" or "saved to ~/Downloads")? [Coverage, Gap, Spec §FR-074]
- [ ] CHK026 - Are requirements present for a "Clear logs" affordance, and what data integrity guarantees it provides (only rotated-out logs? all logs? a confirm step)? [Coverage, Gap, Spec §FR-074]

## Persistence Controls (FR-069, FR-077)

- [ ] CHK027 - Are requirements present for a "Reset persisted UX state" affordance in Settings (so the operator can drop persisted state without uninstall)? [Coverage, Gap, Spec §FR-069]
- [ ] CHK028 - Are requirements present for project-removal being reachable from Settings as well as from the Projects view (FR-077)? [Coverage, Gap, Spec §FR-077]

## Trust-Model Statement (FR-061)

- [ ] CHK029 - Is the in-Settings trust-model statement (FR-061) required to be visible (collapsed by default, or expanded), and is its copy pattern named in the spec? [Clarity, Spec §FR-061]
- [ ] CHK030 - Are requirements present for surfacing the per-OS-user isolation guarantee (FR-061a) alongside the trust-model statement in Settings? [Coverage, Spec §FR-061 / §FR-061a]

## Onboarding Re-Entry (FR-010)

- [ ] CHK031 - Are requirements present for re-entering onboarding from Settings (e.g. "Show onboarding again")? [Coverage, Gap, Spec §FR-010]

## Scenario Class Coverage (Configuration)

- [ ] CHK032 - Are Alternate-flow configuration requirements present (operator hand-edits the persisted Settings file directly while the app is closed)? [Coverage, Gap, Spec §FR-069]
- [ ] CHK033 - Are Exception-flow configuration requirements present (Settings save fails, doctor fails to complete)? [Coverage, Gap]
- [ ] CHK034 - Are Recovery-flow configuration requirements present (settings restored from backup, defaults applied after corrupt-state quarantine)? [Coverage, Gap]
- [ ] CHK035 - Are Non-Functional configuration requirements present (Settings surface meets a11y FR-066, kbd nav FR-075)? [Coverage, Spec §FR-066 / §FR-075]

## Measurability

- [ ] CHK036 - Can the FR-009 Settings inventory be verified against the actual Settings UI by a UI test that asserts each named entry is present? [Measurability, Spec §FR-009]
- [ ] CHK037 - Can the doctor's checks be enumerated and each one fired with a known-failure environment to verify per-check output? [Measurability, Gap, Spec §FR-009]

## Ambiguities

- [ ] CHK038 - Is there an ambiguity about whether Settings can override programmatic defaults like the FR-053 2-second interaction-stability window or the FR-057 60-second grouping window? [Ambiguity, Gap, Spec §FR-053 / §FR-057]

## Round 2 — Post-plan re-verification (2026-05-23)

Re-checks that `research.md` R-20 (doctor implementation) + spec F12 (FR-009 enumerated doctor checks) close Round-1 configuration gaps.

- [ ] CHK039 - Does spec FR-009 (post-F12) + research R-20 close CHK008 (doctor enumerated checks) by naming all 6 checks (socket reachable, peer UID match, contract version, app-data writable, log file writable, OS notification permission)? [Closure-check, Round-1 CHK008]
- [ ] CHK040 - Does research R-20 close CHK009 (doctor output format) by naming the DoctorReport model with per-check name/status/latency_ms/details? [Closure-check, Round-1 CHK009]
- [ ] CHK041 - Does research R-20 close CHK011 (doctor reachable from kbd / command palette) by naming the FR-075 palette entry? [Closure-check, Round-1 CHK011]
- [ ] CHK042 - Does spec FR-009 (post-F12) close CHK019 (contract version display consistency) by naming both Dashboard and Settings placement? [Closure-check, Round-1 CHK019]
- [ ] CHK043 - Does spec FR-009 (post-F12) close CHK024 (Open log folder + Copy diagnostics bundle in Settings)? [Closure-check, Round-1 CHK024]
- [ ] CHK044 - Does spec FR-009 (post-F12) close CHK029 (in-Settings trust-model statement)? [Closure-check, Round-1 CHK029]
- [ ] CHK045 - Are Round-1 gaps NOT closed by the plan: setting groups (CHK002), per-setting restart requirements (CHK003), reset-to-defaults (CHK004), socket-path validation (CHK006), socket-path-change feedback (CHK007), doctor on-failure suggestions (CHK010), grouping toggle scope (CHK012), grouped-row expand-on-toggle-off (CHK014), OS notification first-enable permission flow (CHK015), OS notification UI-disabled when OS blocks (CHK016), theme/density preview (CHK017), live-apply vs restart (CHK018), per-surface minimum required version (CHK020), check-for-updates-now button (CHK023), clear-logs affordance (CHK026), reset persisted UX state (CHK027), project removal from Settings (CHK028), per-OS-user isolation in Settings (CHK030), keyboard-only Settings (CHK031), settings-file-edited-while-closed (CHK032), settings save fails (CHK033), settings restored from backup (CHK034)? [Gap-tracking, Round-1 multi-CHK]
- [ ] CHK046 - Does the plan-side artifacts introduce ANY new configuration concern (e.g. FVM detection in doctor, log-rotation visibility in Settings)? [Coverage, Research R-07 / R-20]
