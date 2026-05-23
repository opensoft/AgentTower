# Observability Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate the requirements about what the app records, surfaces, and exports about its own behavior (FR-074 diagnostics, FR-068 version display, FR-059 explainability for daemon state). Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Local rotating log, diagnostics bundle, action-latency capture, version surfacing, daemon-state surfacing (Health view), explainability of daemon-side decisions, app-self-health visibility.

## Local Logging (FR-074)

- [ ] CHK001 - Does FR-074 enumerate the log levels the app captures (error/warn/info/debug) so operators can size diagnostic bundles? [Completeness, Spec §FR-074]
- [ ] CHK002 - Does FR-074 specify the log format (plain text, JSON-lines, structured) so the diagnostics bundle is machine-parseable for an Opensoft helper? [Completeness, Gap, Spec §FR-074]
- [ ] CHK003 - Does FR-074 specify the "documented threshold" for "operator-action latency above a documented threshold" as a concrete value? [Clarity, Spec §FR-074]
- [ ] CHK004 - Are requirements present for log rotation policy (max file size, max retained files, age-based purge)? [Completeness, Gap, Spec §FR-074]
- [ ] CHK005 - Are requirements present for sensitive-data redaction in logs (no session tokens FR-003, no handoff prompt bodies, no operator notes)? [Coverage, Gap, Spec §FR-003 / §FR-074]
- [ ] CHK006 - Are requirements present for log entry timestamps (monotonic, wall-clock, both) so the bundle can be correlated with daemon-side logs? [Coverage, Gap]

## Diagnostics Bundle (FR-074)

- [ ] CHK007 - Does "Copy diagnostics bundle" specify what is included beyond the log file (app version, contract version, socket path, OS user) — and does the spec enumerate every field? [Completeness, Spec §FR-074]
- [ ] CHK008 - Are requirements present for the bundle's format (zip, tar.gz, single text file) and its destination (clipboard, file picker, fixed location)? [Clarity, Gap, Spec §FR-074]
- [ ] CHK009 - Are requirements present for a preview / redaction step before the operator copies the bundle off-machine? [Coverage, Gap, Spec §FR-074]
- [ ] CHK010 - Are requirements present for bundle size limits or pagination if logs are very large? [Coverage, Gap]

## Version Surfacing (FR-068, FR-002)

- [ ] CHK011 - Does the spec require the app version to be visible from both the Dashboard and Settings (FR-068), and is the format defined (e.g. semver + commit short hash)? [Completeness, Spec §FR-068]
- [ ] CHK012 - Does the spec require the `app_contract_version` to be visible from the Dashboard (FR-002) and Settings (FR-009 mentions "contract version display"), and is the format consistent across surfaces? [Consistency, Spec §FR-002 / §FR-009]
- [ ] CHK013 - Are requirements present for surfacing the daemon's version (separate from the contract version) anywhere in the app? [Coverage, Gap, Spec §FR-002]
- [ ] CHK014 - Are requirements present for how "update available" indicator from FR-068 reconciles with the version display — same surface, separate badge? [Consistency, Gap, Spec §FR-068]

## Daemon-State Surfacing (Health View, FR-022)

- [ ] CHK015 - Does FR-022 enumerate the subsystems the Health view shows (discovery, log attachment, classifier, queue, routing) with consistency between this list and the FR-004 runtime state list? [Consistency, Spec §FR-004 / §FR-022]
- [ ] CHK016 - Are requirements present for surfacing a per-subsystem "last successful event timestamp" so operators can spot subsystems that have gone quiet? [Coverage, Gap, Spec §FR-022]
- [ ] CHK017 - Are requirements present for the Health view's relationship to the project-card validation badge / drift badge — does Health roll up to project-level indicators? [Coverage, Gap, Spec §FR-022 / §FR-025]
- [ ] CHK018 - Are requirements present for what the Health view shows when a subsystem the daemon reports on is not yet supported by the app's contract version (FR-002)? [Coverage, Gap, Spec §FR-002 / §FR-022]

## Explainability (FR-059) as Observability

- [ ] CHK019 - Does FR-059's "what / why / source / rule" pattern get classified as observability (helping operators understand daemon decisions) — and is it consistent with the FR-074 log content? [Consistency, Spec §FR-059 / §FR-074]
- [ ] CHK020 - Are requirements present for whether explainability surfaces can be exported (text, copy-as-link) so an operator can share a decision trace in a bug report? [Coverage, Gap, Spec §FR-059 / §FR-074]
- [ ] CHK021 - Are requirements present for explainability on the handoff lifecycle — why a handoff is `blocked` or `waiting`, who set the state? [Coverage, Gap, Spec §FR-044 / §FR-059]
- [ ] CHK022 - Are requirements present for explainability on the validation Demo Readiness summary — why `overall_state` is `at_risk` vs `not_ready` for the same set of runs? [Coverage, Spec §FR-050 / §FR-059]

## Telemetry Posture

- [ ] CHK023 - Does FR-074's "MUST NOT upload any diagnostics, telemetry, or logs to any remote service" cover all forms of phone-home (release-feed check FR-068, OS-level crash reporters)? [Coverage, Spec §FR-068 / §FR-074 / §SC-009]
- [ ] CHK024 - Are requirements present for ensuring third-party libraries the app may use do not add background telemetry (a no-telemetry transitive-dependency policy)? [Coverage, Gap, Spec §FR-074]
- [ ] CHK025 - Are requirements present for surfacing to the operator (e.g. on first launch FR-061) that the app does not phone home, as a trust statement? [Coverage, Spec §FR-061 / §FR-074]

## Action-Latency Capture

- [ ] CHK026 - Does FR-074 specify which actions get latency capture — only mutations, or also reads (e.g. list fetches)? [Completeness, Gap, Spec §FR-074]
- [ ] CHK027 - Are requirements present for whether latency capture writes a log entry for every action above threshold, or aggregates to a rolling summary? [Clarity, Gap, Spec §FR-074]
- [ ] CHK028 - Are requirements present for what the operator can do with the captured latency data (display in Settings, included in diagnostics bundle, viewable as a panel)? [Coverage, Gap, Spec §FR-074]

## Operator History as Observability

- [ ] CHK029 - Does FR-055 ("operator history MUST be durable and reviewable across sessions") tie to the FR-069 persistence policy — is operator history persisted by the app or by the daemon? [Clarity, Spec §FR-055 / §FR-069]
- [ ] CHK030 - Are requirements present for what operator-history search/filter capabilities exist (date range, agent, severity, project)? [Coverage, Gap, Spec §FR-055]
- [ ] CHK031 - Are requirements present for whether operator history is included in the diagnostics bundle for an incident review? [Coverage, Gap, Spec §FR-055 / §FR-074]

## Scenario Class Coverage (Observability)

- [ ] CHK032 - Are Alternate-flow observability requirements present for verifying state after recovery (operator wants to confirm the app reconnected after an outage)? [Coverage, Gap, Spec §SC-010]
- [ ] CHK033 - Are Exception-flow observability requirements present for capturing app-internal errors that did not surface visibly (silent-render failure, queued live update never applied)? [Coverage, Gap, Spec §FR-074]
- [ ] CHK034 - Are Recovery-flow observability requirements present for the post-incident export bundle (FR-074) being self-contained — does the operator need to attach other context manually? [Coverage, Spec §FR-074]
- [ ] CHK035 - Are Non-Functional observability requirements present for the log/bundle subsystem itself (does it have a latency budget, does it survive disk-full)? [Coverage, Gap, Spec §FR-074]

## Measurability

- [ ] CHK036 - Can the diagnostics bundle be generated in CI against a known scenario and diffed against an expected schema for completeness? [Measurability, Spec §FR-074]
- [ ] CHK037 - Can FR-074's redaction guarantees be verified by a grep-based test that scans the bundle for known-sensitive-token patterns? [Measurability, Gap, Spec §FR-074]
- [ ] CHK038 - Can the FR-002 / FR-068 version-surface consistency be tested by a UI test that loads the Dashboard and Settings and compares the rendered values? [Measurability, Spec §FR-002 / §FR-068]

## Ambiguities

- [ ] CHK039 - Is there an ambiguity between FR-074 ("no telemetry uploaded") and FR-068 ("compares against latest released version") — could a release-feed check be classified as telemetry by a reviewer? [Ambiguity, Spec §FR-068 / §FR-074]
- [ ] CHK040 - Does the absence of an explicit "app self-health" surface in FR-022 (Health view is daemon-side health) leave a gap — how does the operator know the app itself is healthy beyond it rendering? [Ambiguity, Gap, Spec §FR-022]

## Round 2 — Post-plan re-verification (2026-05-23)

Re-checks that `research.md` R-07 (logger), R-14 (latency threshold), R-18 (crash recovery), R-20 (doctor) close Round-1 observability gaps.

- [ ] CHK041 - Does research R-07 close CHK001 (log levels) by naming error/warn/info/debug? [Closure-check, Round-1 CHK001]
- [ ] CHK042 - Does research R-07 close CHK004 (log rotation policy) by naming 5 × 10 MiB? [Closure-check, Round-1 CHK004]
- [ ] CHK043 - Does research R-14 close CHK003 (latency threshold value) by naming 200 ms p95? [Closure-check, Round-1 CHK003]
- [ ] CHK044 - Does spec FR-074 + research R-07 close CHK023 (no telemetry covers all phone-home including OS-level crash reporters)? [Closure-check, Round-1 CHK023 / Research R-18]
- [ ] CHK045 - Does research R-18 close CHK033 (silent-render failure / queued-update-never-applied) by naming runZonedGuarded crash capture to the rotating log? [Closure-check, Round-1 CHK033]
- [ ] CHK046 - Does spec FR-009 (post-F12) close CHK030 (Settings discoverability of accessibility surfaces) — Note: F12 names "Open log folder" + "Copy diagnostics bundle"; does it cover the doctor's accessibility/kbd reachability? [Closure-check, Round-1 CHK030 / Spec §FR-009/§FR-075]
- [ ] CHK047 - Does research R-20 close CHK024 (bundle format) — Note: R-20 says "captured as DoctorReport" but bundle file format may still be unspecified? [Closure-check, Round-1 CHK024]
- [ ] CHK048 - Are Round-1 gaps NOT closed by the plan: log format JSON-lines vs plain (CHK002), redaction in logs (CHK005), monotonic-vs-wall-clock timestamps (CHK006), bundle field enumeration (CHK007), redaction preview before copy (CHK009), bundle size limits (CHK010), daemon-version display (CHK013), version-update-indicator-vs-version-display reconciliation (CHK014), Health per-subsystem timestamps (CHK016), Health roll-up to project badges (CHK017), explainability export (CHK020), handoff lifecycle explainability (CHK021), demo readiness explainability (CHK022), transitive-dependency no-telemetry policy (CHK024), trust-statement visibility (CHK025), operator history search (CHK030), operator history in bundle (CHK031), bundle latency budget (CHK035), redaction grep test (CHK037), app self-health surface (CHK040)? [Gap-tracking, Round-1 multi-CHK]
- [ ] CHK049 - Does the plan-side artifacts introduce ANY new observability concern (e.g. R-07 logger output's stdout vs file fallout; R-20's DoctorReport schema needing first-class typing)? [Coverage, Research R-07 / R-20]
