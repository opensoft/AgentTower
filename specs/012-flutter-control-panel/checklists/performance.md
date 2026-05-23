# Performance Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate that performance budgets, responsiveness, and live-update latency requirements (FR-062 to FR-065, SC-001 to SC-013) are clear, complete, consistent, measurable, and scenario-covered. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Cold-start budgets, list-render budgets, live-update latency, mutation completion budgets, success-criteria measurability, environmental preconditions.

## Cold-Start & Bootstrap

- [ ] CHK001 - Does FR-062 ("Dashboard operationally readable within 2 seconds of app launch") name what "operationally readable" means as a checklist of visible elements? [Clarity, Spec §FR-062]
- [ ] CHK002 - Is the 2-second budget (FR-062) preconditioned on machine class (CPU, RAM, SSD)? [Completeness, Gap, Spec §FR-062]
- [ ] CHK003 - Are requirements present for the worst-case cold-start when the persisted last-project no longer resolves (FR-076 path) — does the 2-second budget still apply? [Coverage, Gap, Spec §FR-062 / §FR-076]
- [ ] CHK004 - Are requirements present for the cold-start budget when contract-version-incompatible degradation triggers (FR-002) — is "operationally readable" defined differently in that state? [Coverage, Gap, Spec §FR-002 / §FR-062]

## List Rendering Budgets

- [ ] CHK005 - Does FR-063 ("first screenful of rows within 1 second") name the screen-size assumption for "first screenful"? [Clarity, Spec §FR-063]
- [ ] CHK006 - Is the "up to the daemon-supported pagination page size" qualifier in FR-063 reconciled with FR-080's virtualized infinite scroll — does the 1-second budget apply to the first virtualized page or to all subsequent pages too? [Consistency, Spec §FR-063 / §FR-080]
- [ ] CHK007 - Are requirements present for list-render performance when filters/sorts are applied (FR-078) — does the budget apply on filter change as well as on view entry? [Coverage, Gap, Spec §FR-063 / §FR-078]
- [ ] CHK008 - Are requirements present for list-render performance on the Drift, Available Validation, and Runs views when scoped to a project with many findings/entrypoints/runs? [Coverage, Gap, Spec §FR-063]

## Live-Update Latency

- [ ] CHK009 - Does FR-064 ("within 2 seconds of the event being observable on the daemon side") name a method to measure "daemon-observable timestamp" comparable to app-render timestamp? [Measurability, Spec §FR-064]
- [ ] CHK010 - Is the 2-second budget (FR-064) preconditioned on event class — does it apply equally to high-volume Events and to lower-volume attention queue items? [Coverage, Gap, Spec §FR-064]
- [ ] CHK011 - Is the FR-064 budget reconciled with FR-053's 2-second interaction-stability window — i.e. when the operator is interacting with the attention queue, can the live-update budget exceed 2 seconds because of the stability deferral? [Consistency, Spec §FR-053 / §FR-064]
- [ ] CHK012 - Are requirements present for backpressure when daemon events arrive faster than the app can render — does the app drop, batch, or queue? [Coverage, Gap, Spec §FR-064]

## Mutation Completion Budgets

- [ ] CHK013 - Does FR-065 ("Adopt-existing-pane completion within 5 seconds") name the success state precisely — is "confirmed registered-agent state" the agent appearing in the Agents view, or the daemon's response received? [Clarity, Spec §FR-065]
- [ ] CHK014 - Are completion budgets specified for Direct Send (FR-018), Cancel Run (FR-049), Submit Handoff (FR-042/043), Transition Drift (FR-034), or only for Adopt? [Coverage, Gap, Spec §FR-018 / §FR-042 / §FR-049 / §FR-065]
- [ ] CHK015 - Are completion budgets specified for batch/multi-item mutations (e.g. transitioning multiple drift findings, cancelling multiple queue rows)? [Coverage, Gap]

## Demo-Readiness & Drift Surfacing Latency

- [ ] CHK016 - Does SC-005 ("Drift findings ... visible on the affected project card within 60 seconds of the daemon emitting them") tie "emitted" to a measurable daemon-side timestamp? [Measurability, Spec §SC-005]
- [ ] CHK017 - Does SC-007 ("Demo Readiness summary updates within 5 seconds of a validation run resolving") differentiate between the in-view-update budget and the project-card budge update? [Clarity, Gap, Spec §SC-007 / §FR-050]
- [ ] CHK018 - Does SC-006 ("Validation runs reach `running` state in under 2 seconds") apply to runs queued behind other runs, or only to runs triggered when no other run is active? [Coverage, Gap, Spec §SC-006]

## Daemon-Outage Transition Budgets

- [ ] CHK019 - Does SC-010 ("On daemon unreachability, every live-data surface transitions ... within 2 seconds and reverts within 5 seconds") specify how "daemon unreachability" is detected — heartbeat? socket close? [Clarity, Spec §SC-010]
- [ ] CHK020 - Are requirements present for the in-flight mutation transition at the moment unreachability is detected — does the mutation's pending indicator flip to "failed (daemon unreachable)" within the same 2-second budget? [Coverage, Gap, Spec §SC-010 / §FR-072]

## Memory & Resource Footprint

- [ ] CHK021 - Are requirements present for the app's memory footprint at idle (no open project, just bootstrap complete)? [Coverage, Gap]
- [ ] CHK022 - Are requirements present for the app's memory footprint with the FR-024 "~5 or fewer" projects all loaded? [Coverage, Gap, Spec §FR-024]
- [ ] CHK023 - Are requirements present for CPU at idle (live-update polling, contract heartbeat) so the app does not warm an operator's laptop? [Coverage, Gap]
- [ ] CHK024 - Are requirements present for log file growth / rotation cadence so FR-074 logs do not affect disk I/O on long sessions? [Coverage, Spec §FR-074]

## Concurrency

- [ ] CHK025 - Are requirements present for concurrent operator actions (e.g. submitting a handoff while a validation run is being triggered) so the app remains responsive? [Coverage, Gap]
- [ ] CHK026 - Are requirements present for the responsiveness of the UI while a virtualized list (FR-080) is fetching the next page — does the app remain interactive on other surfaces? [Coverage, Gap, Spec §FR-080]

## Power & Background Behavior

- [ ] CHK027 - Are requirements present for the app's behavior when the OS reports low power / battery saver mode (does the app reduce polling, defer live-updates)? [Coverage, Gap]
- [ ] CHK028 - Are requirements present for the app's behavior when minimized / occluded — does it pause live-update rendering until foregrounded? [Coverage, Gap, Spec §FR-082]
- [ ] CHK029 - Are requirements present for the app's behavior when the OS sleeps and wakes (does it re-bootstrap per FR-003)? [Coverage, Gap, Spec §FR-003]

## Scenario Class Coverage (Performance)

- [ ] CHK030 - Are Alternate-flow performance requirements present for the cold-start path through onboarding (FR-010) vs the cold-start path skipping onboarding? [Coverage, Gap, Spec §FR-010 / §FR-062]
- [ ] CHK031 - Are Exception-flow performance requirements present for the degraded-daemon path (FR-004 runtime-degraded) — do FR-062 / FR-063 / FR-064 budgets relax? [Coverage, Gap, Spec §FR-004]
- [ ] CHK032 - Are Recovery-flow performance requirements present for daemon-reconnect re-fetch (does the app refresh all live data within a budget after reconnect)? [Coverage, Spec §SC-010]
- [ ] CHK033 - Are Non-Functional performance requirements covered by both FRs (FR-062..FR-065) and SCs (SC-001..SC-013) without redundancy or conflict? [Consistency, Spec §FR-062 / §SC-001]

## Measurability

- [ ] CHK034 - Can every performance budget (FR-062, FR-063, FR-064, FR-065) be measured with an automated harness, or do they require manual stopwatch testing? [Measurability, Spec §FR-062 / §FR-063 / §FR-064 / §FR-065]
- [ ] CHK035 - Are the success-criteria timings (SC-001 10 min, SC-002 5 sec/project, SC-003 30 sec, SC-005 60 sec, SC-006 2 sec, SC-007 5 sec, SC-010 2/5 sec) tied to a specific test environment definition? [Measurability, Spec §Success Criteria]
- [ ] CHK036 - Can SC-013 ("returning operator can name (a)..(d) within 30 seconds") be tested without a human subject, or is it inherently user-study-only? [Measurability, Spec §SC-013]

## Ambiguities & Conflicts

- [ ] CHK037 - Does FR-053's 2-second stability window conflict with FR-064's 2-second live-update budget for the attention queue specifically — i.e. could both be technically satisfied with a 4-second visible delay? [Conflict, Spec §FR-053 / §FR-064]
- [ ] CHK038 - Does FR-064's 2-second live-update budget for the "master summary 'last activity'" surface include propagation through any aggregation step the daemon performs? [Ambiguity, Spec §FR-064]
- [ ] CHK039 - Does SC-003 ("Generating a handoff for a single feature with auto-filled context completes in under 30 seconds") count operator review time of the preview, or only generation? [Ambiguity, Spec §SC-003]
