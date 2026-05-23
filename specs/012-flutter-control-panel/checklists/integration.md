# Integration & External Dependencies Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate integration requirements with FEAT-011 (`app.*` contract), upstream FEAT-001..010 capabilities, downstream FEAT-013 reverse dependency, OS-native surfaces, file system, and the release feed. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: FEAT-011 contract surface, indirect FEAT dependencies, FEAT-013 coexistence, OS notifications, OS file/editor integration, distribution release feed.

## FEAT-011 Backend Contract (`app.*`)

- [ ] CHK001 - Is the FEAT-011 dependency stated as a hard normative dependency in functional requirements (FR-001, FR-002), and is the Dependencies section consistent with the FR statements? [Consistency, Spec §FR-001 / §FR-002 / §Dependencies]
- [ ] CHK002 - Is the rule that "any operation not yet covered by an `app.*` method MUST NOT be invoked from the app" (Dependencies) tied to a per-surface "hidden or marked unavailable" rule with consistent UI treatment? [Clarity, Spec §Dependencies / §FR-002]
- [ ] CHK003 - Are requirements present for what version-skew tolerance the spec commits to (e.g. is the app required to work against any minor version newer than its minimum, or only against exact-major equality)? [Coverage, Gap, Spec §FR-002]
- [ ] CHK004 - Does the spec name the canonical artifact where the FEAT-011 `app.*` contract is documented, so an implementer can resolve "the method called by FR-016" without ambiguity? [Completeness, Gap, Spec §Dependencies]

## Indirect FEAT Dependencies (FEAT-001..010)

- [ ] CHK005 - Are the indirect dependencies enumerated by capability (containers, panes, agents, log attachment, events, queue, routes, arbitration) sufficient to trace each FR to the responsible upstream FEAT? [Completeness, Spec §Dependencies]
- [ ] CHK006 - Is the dependency on FEAT-009's safe prompt queue restated in functional requirements (FR-043) rather than only in Assumptions / Dependencies? [Consistency, Spec §FR-043 / §Dependencies / Assumptions]
- [ ] CHK007 - Are requirements present for the app's behavior when a transitively-depended FEAT is degraded but the `app.*` surface still responds (e.g. classifier down but events still arrive unclassified)? [Coverage, Gap, Spec §FR-022 / §Edge Cases]

## FEAT-013 Coexistence (Reverse Dependency)

- [ ] CHK008 - Is the reverse-dependency rule "FEAT-012 surfaces MUST be designed so adopted and managed agents can coexist without UI restructuring when FEAT-013 lands" tied to specific surfaces and acceptance criteria, or only stated as a general guideline? [Clarity, Spec §Dependencies / Out of Scope]
- [ ] CHK009 - Are requirements present for whether the data model's Adopted Agent entity has space for a future `created_by: adopted | managed` discriminator without breaking surfaces? [Coverage, Gap, Spec §Dependencies / Key Entities]
- [ ] CHK010 - Are requirements present for how the Panes view's "Adopt" action will coexist with a future "Create pane" action — i.e. does the spec reserve UX real estate? [Coverage, Gap, Spec §FR-014 / §FR-016 / Dependencies]

## OS-Native Notifications

- [ ] CHK011 - Does FR-058 name the OS notification surfaces it commits to integrate with on each supported OS (Windows Toast, macOS Notification Center, Linux freedesktop.org notifications)? [Completeness, Spec §FR-058]
- [ ] CHK012 - Are requirements present for OS-notification permission acquisition flows (where the OS gates permission, like macOS) and for first-use behavior? [Coverage, Gap, Spec §FR-058]
- [ ] CHK013 - Are requirements present for what happens when the operator clicks an OS-native notification — does the app focus a specific surface, or only foreground the window? [Coverage, Gap, Spec §FR-058]
- [ ] CHK014 - Are requirements present for OS-notification fallback when the OS layer reports failure (e.g. notifications disabled at OS level) — does the in-app surface still fire? [Coverage, Spec §FR-058]
- [ ] CHK015 - Are requirements present for OS-notification de-duplication so the FR-057 grouping rule does not produce a flood of OS notifications? [Consistency, Gap, Spec §FR-057 / §FR-058]

## OS File System & Default-Editor Integration

- [ ] CHK016 - Does FR-079 specify how the app determines the OS default for a file extension (system shell? language-runtime API? hard-coded handler map)? [Clarity, Spec §FR-079]
- [ ] CHK017 - Are requirements present for what happens when the OS has no default for a file type (the operator never set one) — does the app prompt for one or refuse to open? [Coverage, Gap, Spec §FR-079]
- [ ] CHK018 - Are requirements present for opening containing folders (Reveal in Finder / Show in Files / xdg-open on parent dir) as an alternative to opening the file itself? [Coverage, Gap, Spec §FR-079]
- [ ] CHK019 - Are requirements present for the app data / log directory location on each supported OS (FR-074 mentions `~/.local/share/agenttower-app/logs/` as an example for Linux)? [Completeness, Spec §FR-074]

## Daemon Socket Discovery & Configuration

- [ ] CHK020 - Are requirements present for how the app discovers the daemon socket path on each OS (well-known path, env var, Settings config)? [Completeness, Gap, Spec §FR-001 / §FR-009]
- [ ] CHK021 - Are requirements present for what the app does when multiple sockets are present (multi-daemon attempt) given FR-060 forbids non-local but does not explicitly forbid multiple local sockets? [Coverage, Gap, Spec §FR-060]
- [ ] CHK022 - Are requirements present for socket-path validation in Settings (does the app probe before accepting, or accept blindly then surface unreachable on the Dashboard)? [Coverage, Gap, Spec §FR-009]

## Release Feed Integration (FR-068)

- [ ] CHK023 - Does FR-068 name where the release feed lives (URL? signed file path? OS package manager hook)? [Completeness, Spec §FR-068]
- [ ] CHK024 - Are requirements present for the format the feed must publish (a single latest-version field? a changelog? signing chain)? [Completeness, Gap, Spec §FR-068]
- [ ] CHK025 - Are requirements present for the feed-unreachable behavior — does the app surface a warning, or silently skip the check? [Coverage, Gap, Spec §FR-068]
- [ ] CHK026 - Is the release feed reconciled with FR-001's "MUST NOT include any code path that opens network sockets" — is the release feed explicitly exempted? [Conflict, Spec §FR-001 / §FR-068]

## Cross-Cutting OS Integration

- [ ] CHK027 - Are requirements present for OS-level "open at login" behavior (auto-start), or is it explicitly excluded? [Coverage, Gap]
- [ ] CHK028 - Are requirements present for OS-level dock/taskbar integration (badge counts mirroring unread notification count) given FR-008 + FR-058? [Coverage, Gap]
- [ ] CHK029 - Are requirements present for OS dark/light theme tracking integration consistent with FR-009's "System" theme option? [Consistency, Spec §FR-009]
- [ ] CHK030 - Are requirements present for OS-level keyboard layout handling so global shortcuts (FR-007, FR-075) work on non-US layouts? [Coverage, Gap]

## Scenario Class Coverage (Integration)

- [ ] CHK031 - Are Alternate-flow integration requirements present (running with no OS notification support, running with no default markdown handler)? [Coverage, Gap]
- [ ] CHK032 - Are Exception-flow integration requirements present (daemon socket exists but is owned by a different OS user — should the app refuse to connect)? [Coverage, Spec §FR-061a]
- [ ] CHK033 - Are Recovery-flow integration requirements present (OS notification permission revoked mid-session, file handler unregistered mid-session)? [Coverage, Gap]
- [ ] CHK034 - Are Non-Functional integration requirements present (release feed check completes within X ms, OS notification dispatch completes within Y ms)? [Coverage, Gap]

## Measurability

- [ ] CHK035 - Can the FR-068 "compares against the latest released version available from the configured release feed at most once per app launch" be objectively measured (one HTTP request per app process lifecycle)? [Measurability, Spec §FR-068]
- [ ] CHK036 - Can the FEAT-013 coexistence rule (Dependencies) be tested before FEAT-013 lands — is there a defined "design assertion" the app's UI structure can be evaluated against? [Measurability, Gap, Spec §Dependencies]

## Assumptions & Ambiguities

- [ ] CHK037 - Is the assumption "Document path discovery ... conventional locations" (Assumptions) reflected in an integration requirement, or only described as a behavior? [Assumption, Spec §Assumptions]
- [ ] CHK038 - Is there an ambiguity about whether the release feed counts as a "non-local daemon target" under FR-060 (which says the app MUST refuse to operate against any non-local daemon target)? [Ambiguity, Spec §FR-060 / §FR-068]
- [ ] CHK039 - Is the integration with FEAT-009's safe prompt queue tested against any acceptance scenario beyond US3 §4 ("the prompt is delivered ... with the handoff id retained as correlation context")? [Coverage, Spec §US3 / §FR-043]
