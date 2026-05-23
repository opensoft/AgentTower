# Deployment, Distribution & Versioning Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate distribution, installation, update, and version-compatibility requirements (FR-068, FR-002, FR-070) for clarity, completeness, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Signed installer per OS, update indicator, version display, contract-version skew, downgrade handling, install-time prerequisites.

## Distribution Channel (FR-068)

- [ ] CHK001 - Does FR-068 specify per-OS installer formats (e.g. `.exe`/`.msi` Windows, `.dmg`/`.pkg` macOS, `.deb`/`.rpm`/`.AppImage` Linux), or only "signed installer per supported OS"? [Completeness, Spec §FR-068]
- [ ] CHK002 - Are requirements present for the code-signing certificate authority and key-rotation policy? [Coverage, Gap, Spec §FR-068]
- [ ] CHK003 - Are requirements present for the integrity verification chain (signature → published checksum → installer → installed binary)? [Coverage, Gap, Spec §FR-068]
- [ ] CHK004 - Does the spec name where installers are published (Opensoft internal release page? GitHub releases? Both)? [Completeness, Gap, Spec §FR-068]
- [ ] CHK005 - Are requirements present for installer behavior when a prior version is already installed (in-place upgrade, side-by-side, prompt)? [Coverage, Gap, Spec §FR-068]

## Update Indicator (FR-068)

- [ ] CHK006 - Does FR-068 specify the release-feed format (single-version field, full changelog, signed manifest)? [Completeness, Gap, Spec §FR-068]
- [ ] CHK007 - Is the "at most once per app launch" cadence (FR-068) reconciled with long-running sessions — does the indicator stay stale until restart? [Clarity, Spec §FR-068]
- [ ] CHK008 - Are requirements present for the indicator's visibility (Dashboard, Settings, both) and its dismissibility? [Coverage, Gap, Spec §FR-068]
- [ ] CHK009 - Are requirements present for handling release-feed unreachability — does the indicator stay silent, or surface a "could not check" state? [Coverage, Gap, Spec §FR-068]

## Version Display & Skew

- [ ] CHK010 - Is the displayed app version format defined (semver + commit + channel)? [Completeness, Gap, Spec §FR-068]
- [ ] CHK011 - Is the displayed `app_contract_version` format defined to align with daemon-side conventions? [Consistency, Spec §FR-002 / §FR-068]
- [ ] CHK012 - Are requirements present for what the app does when its installed version is newer than the release-feed-advertised "latest" (test build, pre-release)? [Coverage, Gap, Spec §FR-068]

## Downgrade / Rollback

- [ ] CHK013 - Are requirements present for a clean uninstall path that does NOT leak persisted state (so the operator can downgrade by uninstall+install)? [Coverage, Gap, Spec §FR-069]
- [ ] CHK014 - Are requirements present for forward-compatibility of persisted state (FR-070) so a downgrade to a prior compatible major can read forward-written state? [Coverage, Gap, Spec §FR-070]
- [ ] CHK015 - Are requirements present for explicitly refusing to launch on a major-version downgrade that would corrupt persisted state? [Coverage, Gap]

## Install-Time Prerequisites

- [ ] CHK016 - Are requirements present for what dependencies (system libraries, runtime versions) the installer checks for? [Coverage, Gap, Spec §FR-010]
- [ ] CHK017 - Are requirements present for what happens when `agenttowerd` is not yet installed at the time of app install (does the installer offer to install it, prompt, or silently rely on the operator)? [Coverage, Gap, Spec §FR-001 / §FR-010]
- [ ] CHK018 - Are requirements present for the installer's interaction with OS-level "open at login" or autostart settings? [Coverage, Gap]

## OS-Level Distribution Stores (Explicitly Out per Q3)

- [ ] CHK019 - Does the spec explicitly state that OS app-store distribution (Mac App Store / MSIX / Snap / Flatpak) is NOT a first-release commitment so an implementer does not pursue it? [Clarity, Spec §Clarifications Q3]
- [ ] CHK020 - Are requirements present for whether sideloading (manual `.dmg`/`.AppImage` etc.) needs additional notarization / verification on each OS? [Coverage, Gap, Spec §FR-068]

## Migration Across Versions

- [ ] CHK021 - Are requirements present for migrating Settings format across versions (additive fields tolerated, removed fields preserved as opaque keys)? [Coverage, Gap, Spec §FR-069 / §FR-070]
- [ ] CHK022 - Are requirements present for migrating onboarding-progress state (FR-010) across versions — does a completed milestone in v1 stay completed in v2 even if the milestone definition changed? [Coverage, Gap, Spec §FR-010]

## Network Posture During Update Check

- [ ] CHK023 - Is the update-check HTTPS endpoint subject to the FR-061 trust-model statement (e.g. is it pinned, validated)? [Coverage, Gap, Spec §FR-061 / §FR-068]
- [ ] CHK024 - Is the update check reconciled with FR-001's "MUST NOT include any code path that opens network sockets" and SC-009's "never opens a non-local network socket" — is the update check explicitly exempted in both? [Conflict, Spec §FR-001 / §FR-068 / §SC-009]

## Scenario Class Coverage (Deployment)

- [ ] CHK025 - Are Alternate-flow deployment requirements present (first install on a fresh OS user, install over an existing install with custom Settings)? [Coverage, Gap, Spec §FR-068]
- [ ] CHK026 - Are Exception-flow deployment requirements present (installer signature invalid, OS quarantine refuses to launch, partial install)? [Coverage, Gap, Spec §FR-068]
- [ ] CHK027 - Are Recovery-flow deployment requirements present (re-install over corrupt install, repair-install)? [Coverage, Gap]
- [ ] CHK028 - Are Non-Functional deployment requirements present (installer size budget, install time budget)? [Coverage, Gap, Spec §FR-068]

## Measurability

- [ ] CHK029 - Can FR-068's "compares against the latest released version available from the configured release feed at most once per app launch" be objectively measured (one HTTPS request per process lifecycle)? [Measurability, Spec §FR-068]
- [ ] CHK030 - Can FR-068's "MUST NOT auto-download or auto-install updates" be verified by an automated test that runs for a full release cycle with a newer version in the feed? [Measurability, Spec §FR-068]
- [ ] CHK031 - Can the per-OS installer signature be verified deterministically in CI before release? [Measurability, Gap, Spec §FR-068]

## Ambiguities

- [ ] CHK032 - Is there an ambiguity about who owns the release feed (Opensoft? a specific team? a contract with a third-party host)? [Ambiguity, Spec §FR-068]
- [ ] CHK033 - Is there an ambiguity about whether "manual installer" (FR-068) implies the operator must have admin/root rights on their workstation? [Ambiguity, Gap, Spec §FR-068]
- [ ] CHK034 - Is there an ambiguity about whether updates can be staged (downloaded for next-launch) or strictly "operator must download from the release page each time"? [Ambiguity, Spec §FR-068]

## Round 2 — Post-plan re-verification (2026-05-23)

Re-checks that `research.md` R-12 (release feed) and R-13 (packaging per OS) close the Round-1 deployment gaps.

- [ ] CHK035 - Does research R-13 close CHK001 (per-OS installer formats) by naming MSIX / DMG / AppImage + DEB? [Closure-check, Round-1 CHK001]
- [ ] CHK036 - Does research R-13 close CHK002 (signing certificate) by naming EV cert / Apple Developer ID / GPG? [Closure-check, Round-1 CHK002]
- [ ] CHK037 - Does research R-12 close CHK004 (where installers are published) — Note: R-12 names releases.opensoft.one but is that the installer host too? [Closure-check, Round-1 CHK004]
- [ ] CHK038 - Does research R-12 close CHK006 (release-feed format) by naming the JSON schema? [Closure-check, Round-1 CHK006]
- [ ] CHK039 - Does research R-12 close CHK008 (indicator visibility) — Note: R-12 says "in-app 'update available' indicator + link to release page" but does it name Dashboard vs Settings placement? [Closure-check, Round-1 CHK008]
- [ ] CHK040 - Does research R-12 close CHK009 (release-feed unreachable behavior) by stating "Failure to fetch is silent at MVP"? [Closure-check, Round-1 CHK009]
- [ ] CHK041 - Does research R-13 close CHK019 (OS app-store explicit exclusion) by naming the deferred stores? [Closure-check, Round-1 CHK019]
- [ ] CHK042 - Are Round-1 gaps NOT closed by the plan: code-signing key-rotation (CHK002 sub), integrity verification chain (CHK003), in-place vs side-by-side upgrade (CHK005), at-most-once-per-launch cadence reconciliation with long-running sessions (CHK007), pre-release / test-build handling (CHK012), clean uninstall (CHK013), forward-compat persisted state on downgrade (CHK014), refuse-launch on major-downgrade (CHK015), install-time prerequisites (CHK016/017/018), settings migration (CHK021), onboarding-progress migration (CHK022), HTTPS pinning (CHK023), staged-download behavior (CHK034)? [Gap-tracking, Round-1 multi-CHK]
- [ ] CHK043 - Does the plan-side artifacts introduce ANY new deployment concern (e.g. FVM pin for repro builds, R-13 signing infrastructure ownership)? [Coverage, Plan §Technical Context / Research R-13]
