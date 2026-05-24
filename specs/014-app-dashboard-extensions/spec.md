# Feature Specification: App Dashboard Extensions

**Feature Branch**: `014-app-dashboard-extensions`
**Created**: 2026-05-23
**Status**: Draft
**Input**: User description: "Create FEAT-014 from the OpenSpec proposal `extend-app-dashboard-fields-for-feat012`: extend the FEAT-011 app dashboard contract as an additive v1.1 minor so FEAT-012 can render dashboard state accurately."

## Clarifications

### Session 2026-05-24

- Q: How are discovered/registered panes assigned to each v1.1 `PaneState` bucket? → A: `discovered-and-unmanaged` = pane row exists but no agent registered; `discovered-and-registered` = pane row exists AND agent registered; `inactive-or-stale` = pane row whose container is `inactive` OR whose `last_seen_at` predates the most recent successful scan; `discovery-degraded` = pane row whose container is in `degraded_scan`.
- Q: When does a registered agent fall into the `partially_configured` bucket? → A: Agent row exists but one or more of `role`, `capability`, or `label` is missing/empty/`unknown`.
- Q: What signal determines `active` vs `inactive` for a registered agent? → A: Agent's container `state == "active"` → `active`; container `inactive` or `degraded_scan` → `inactive`.
- Q: Must `panes.by_state` cross-check with the v1.0 panes fields? → A: Yes. `discovered-and-registered` == v1.0 `registered`; `discovered-and-unmanaged` + `inactive-or-stale` + `discovery-degraded` == v1.0 `unregistered`; sum of all four v1.1 buckets == v1.0 `total`.
- Q: Is `partially_configured` orthogonal to `active`/`inactive` or mutually exclusive? → A: Mutually exclusive: `active` + `inactive` + `partially_configured` == total agents. `log-attached`/`log-detached` remain orthogonal and may overlap any of the three.
- Q: What is the default `recently_skipped_window_ms` and is it client-tunable? → A: Fixed daemon-side default of `300_000` ms (5 minutes); not client-tunable in v1.1.
- Q: What is the data source for `recently_skipped_count`? → A: In-memory ring buffer / counter of recent FEAT-010 skip decisions populated by the routing worker; cleared on daemon restart (process-local telemetry, not durable audit history).
- Q: When is `recommended_next_action` recomputed, and what does `recommended_next_action_refreshed_at` timestamp? → A: Recomputed on every `app.dashboard` call; `refreshed_at` is the call's compute time. No cache to invalidate.
- Q: What is the `recommended_next_action` object shape? → A: `{code, title (string ≤128), detail (string ≤512) | null, target {kind, id} | null}`. `target.kind` reuses the v1.0 hint target closed set (`container`, `pane`, `agent`, `route`, `message`, `event`) plus `subsystem` added in v1.1.
- Q: Does a v1.1 daemon emit the new fields when a client connects with `client_app_contract_major = 1`? → A: Always emit v1.1 fields once the daemon advertises v1.1, regardless of `client_app_contract_major`; v1.0 clients ignore unknown fields per existing additive-minor rules.
- Q: What does the dashboard return if recommendation computation itself fails? → A: Both `recommended_next_action` and `recommended_next_action_refreshed_at` are emitted as `null`; the rest of the dashboard payload still returns success.
- Q: Hyphens or snake_case for the new closed-set values? → A: Keep the hyphens as written (`discovered-and-unmanaged`, `inactive-or-stale`, `log-attached`, etc.); FEAT-012 and the product UX language already use those labels.

Additional notes:

- FEAT-014 is an additive app-contract v1.1 minor: a v1.1 daemon emits the new fields; v1.0 clients keep working by ignoring unknown fields.
- The route-skip counter is intentionally process-local and resets on daemon restart; it is dashboard telemetry, not durable audit history.
- Recommendation computation is server-side, fixed-order, and recomputed per dashboard call; on compute failure the dashboard response still succeeds with the recommendation fields set to `null` so the rest of the operator surface remains usable.
- Hyphenated state values are intentional: FEAT-012 and product UX language already refer to those exact labels.
- Recommendation precedence is a fixed deterministic order evaluated top-to-bottom; the daemon returns the first matching code and emits no lower-priority codes alongside it. Order: (1) `subsystem_degraded`, (2) `no_containers`, (3) `no_panes_discovered`, (4) `unadopted_panes_present`, (5) `blocked_queue_drain`, (6) `no_routes_configured`, (7) `all_clear`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dashboard Shows Real Pane and Agent State (Priority: P1)

As an AgentTower operator using the app dashboard, I want pane and registered-agent counts broken down by meaningful state so the dashboard reflects the real daemon instead of showing flat totals or placeholder zeros.

**Why this priority**: FEAT-012 depends on these fields for its Agent Operations Dashboard. Without them, the dashboard cannot render pane state, agent state, or the adoption gap accurately against a real daemon.

**Independent Test**: Can be tested by seeding a daemon with active containers, registered panes, unadopted panes, active agents, inactive agents, and log attachment variations, then calling `app.dashboard` and verifying every state bucket is present with the expected count.

**Acceptance Scenarios**:

1. **Given** a daemon advertising dashboard contract v1.1 with one registered pane and two unadopted panes, **When** the dashboard payload is requested, **Then** pane state counts include two `discovered-and-unmanaged`, one `discovered-and-registered`, zero `inactive-or-stale`, and zero `discovery-degraded`.
2. **Given** a daemon advertising dashboard contract v1.1 with active, inactive, log-attached, and log-detached agents, **When** the dashboard payload is requested, **Then** agent state counts include every defined agent-state key and allow log-state buckets to overlap with active/inactive totals.
3. **Given** a daemon with no panes or agents, **When** the dashboard payload is requested, **Then** every pane-state and agent-state key is still present with value `0`.

---

### User Story 2 - Dashboard Highlights Routing Friction (Priority: P2)

As an operator, I want the dashboard to show recently skipped route decisions so I can quickly tell when route arbitration is blocking expected automation.

**Why this priority**: FEAT-010 route arbitration can silently skip delivery for valid safety reasons. The dashboard needs a short-window count to make that operational friction visible without turning skips into queue failures.

**Independent Test**: Can be tested by recording route-skip decisions at known times, requesting the dashboard payload, and verifying only skips inside the configured window are counted.

**Acceptance Scenarios**:

1. **Given** three route skips occurred two, four, and ten minutes ago, **When** the dashboard payload is requested with a five-minute window, **Then** the recently skipped count is `2` and the response states the window size in milliseconds.
2. **Given** no skips have occurred since daemon start, **When** the dashboard payload is requested, **Then** the recently skipped count is present as `0`.
3. **Given** the daemon restarts after route skips occurred, **When** the dashboard payload is requested before any new skips, **Then** the recently skipped count is `0`.

---

### User Story 3 - Dashboard Recommends the Next Operator Action (Priority: P3)

As an operator, I want the daemon to recommend the next dashboard action from a documented closed set so each app surface can present the same operational nudge.

**Why this priority**: The recommendation prevents every client from reimplementing readiness, queue, pane, route, and container logic differently.

**Independent Test**: Can be tested by loading fixture states for each recommendation code and verifying the dashboard returns the expected code, title, optional detail, optional target, and refresh timestamp.

**Acceptance Scenarios**:

1. **Given** the daemon is degraded, **When** the dashboard payload is requested, **Then** the recommendation is `subsystem_degraded` even if other lower-priority conditions are also true.
2. **Given** the daemon is ready with no containers, **When** the dashboard payload is requested, **Then** the recommendation is `no_containers`.
3. **Given** the daemon is healthy, has active containers, adopted panes, configured routes, no blocked queue rows, and no unadopted panes, **When** the dashboard payload is requested, **Then** the recommendation is `all_clear`.

---

### User Story 4 - Existing v1.0 Clients Keep Working (Priority: P4)

As a client built against the existing app contract, I want the v1.1 dashboard fields to be additive so my existing reads keep working without code changes.

**Why this priority**: FEAT-011 explicitly allows additive minor evolution, but the feature must prove that no v1.0 fields, error codes, or methods were removed or renamed.

**Independent Test**: Can be tested by replaying the v1.0 contract tests against a daemon that advertises v1.1 and confirming every old assertion still passes.

**Acceptance Scenarios**:

1. **Given** a daemon advertising app contract v1.1, **When** a v1.0-compatible client reads the existing dashboard fields, **Then** all v1.0 fields remain present with the same types.
2. **Given** a client sends an unsupported major version, **When** it calls the app contract handshake, **Then** the existing major-version rejection behavior remains unchanged.
3. **Given** the daemon advertises v1.1, **When** capability flags are read, **Then** no new capability flag is required for these added dashboard fields.

### Edge Cases

- A v1.1 dashboard payload has zero rows for every pane-state or agent-state bucket.
- Log-state buckets overlap with active/inactive agent buckets, so the sum can exceed total agents.
- A future recommendation code appears to an older client.
- A degraded daemon also has no containers or blocked queue rows; degraded subsystem must win by precedence.
- A route skip is just outside the active window.
- The daemon restarts and loses the in-memory route-skip window.
- A reserved state bucket exists before the daemon can populate it with non-zero values.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST extend the dashboard success result with `counts.panes.by_state` when the app contract version is at least v1.1.
- **FR-002**: `counts.panes.by_state` MUST include every v1.1 `PaneState` key: `discovered-and-unmanaged`, `discovered-and-registered`, `inactive-or-stale`, and `discovery-degraded`. When a pane row qualifies for multiple buckets simultaneously, bucket assignment follows the first-match priority order documented in `data-model.md` §PaneState (`discovery-degraded` > `inactive-or-stale` > `discovered-and-registered` > `discovered-and-unmanaged`).
- **FR-003**: System MUST report empty pane-state buckets as integer `0`, not by omitting keys, returning `null`, or returning an empty map.
- **FR-004**: System MUST extend the dashboard success result with `counts.agents.by_state` when the app contract version is at least v1.1.
- **FR-005**: `counts.agents.by_state` MUST include every v1.1 `AgentState` key: `active`, `inactive`, `partially_configured`, `log-attached`, and `log-detached`.
- **FR-006**: System MUST document that `log-attached` and `log-detached` agent buckets are orthogonal to active/inactive buckets and may cause the bucket sum to exceed total agents.
- **FR-007**: System MUST extend route counts with `recently_skipped_count` and `recently_skipped_window_ms` when the app contract version is at least v1.1.
- **FR-008**: System MUST count route skips only within the active sliding window of `300_000` ms (5 minutes) — fixed daemon-side and not client-tunable in v1.1 — and MUST make daemon restart reset the in-memory skip count to `0`.
- **FR-009**: System MUST extend the dashboard success result with `recommended_next_action` and `recommended_next_action_refreshed_at` when the app contract version is at least v1.1.
- **FR-010**: System MUST compute the recommended next action server-side by evaluating a fixed deterministic precedence list top-to-bottom and returning the first matching code. The precedence order is: (1) `subsystem_degraded`, (2) `no_containers`, (3) `no_panes_discovered`, (4) `unadopted_panes_present`, (5) `blocked_queue_drain`, (6) `no_routes_configured`, (7) `all_clear`. When multiple conditions match simultaneously, the response MUST carry only the highest-precedence code; lower-precedence codes MUST NOT be emitted in its place or alongside it.
- **FR-011**: System MUST emit `recommended_next_action` with the object shape `{code: <closed-set string>, title: <string ≤128 chars>, detail: <string ≤512 chars> | null, target: {kind: <closed set>, id: <string>} | null}`, where `target.kind` reuses the v1.0 hint target closed set (`container`, `pane`, `agent`, `route`, `message`, `event`) plus `subsystem` added in v1.1, and MUST document target rules for each recommendation code (subsystem, container, pane, queue message, or no target as appropriate).
- **FR-012**: System MUST require clients to ignore unknown future recommendation codes without refusing the rest of the dashboard response.
- **FR-013**: System MUST bump the app contract version from v1.0 to v1.1 and advertise a supported minor range whose maximum includes v1.1.
- **FR-014**: System MUST keep all v1.0 dashboard fields, methods, error-code behavior, and major-version rejection behavior compatible with v1.0 clients.
- **FR-015**: System MUST NOT introduce new capability flags for these fields because they are additive fields on an existing required dashboard method.
- **FR-016**: System MUST add or update contract documentation for dashboard next-action codes, closed sets, dashboard response shape, and v1.1 evolution rules.
- **FR-017**: System MUST include tests for per-state aggregation, recently skipped route counts, recommendation-code precedence, v1.0 compatibility, v1.1 response shape, and dashboard latency.
- **FR-018**: System MUST keep FEAT-012 UI renderer updates, push-based dashboard updates, customizable recommendation rules, and persisted recommendation history out of this feature's scope.
- **FR-019**: System MUST guarantee that v1.1 `counts.panes.by_state.discovered-and-registered` equals v1.0 `counts.panes.registered`, that the sum of `discovered-and-unmanaged` + `inactive-or-stale` + `discovery-degraded` equals v1.0 `counts.panes.unregistered`, and that the sum of all four v1.1 buckets equals v1.0 `counts.panes.total`.
- **FR-020**: System MUST treat a registered agent as `active` when its container `state == "active"` and as `inactive` when its container is `inactive` or `degraded_scan`. System MUST treat the agent as `partially_configured` — mutually exclusive with `active`/`inactive` — when one or more of `role`, `capability`, or `label` is missing/empty/`unknown`, such that `active` + `inactive` + `partially_configured` equals total agents. The `log-attached`/`log-detached` buckets remain orthogonal and may overlap any of the three.
- **FR-021**: System MUST set both `recommended_next_action` and `recommended_next_action_refreshed_at` to `null` and return the dashboard payload as success when recommendation computation itself fails. The failure MUST NOT propagate as an error code, empty payload, or partial omission of other v1.1 fields.

### Key Entities *(include if feature involves data)*

- **PaneState**: Closed set describing how discovered or registered panes should be grouped for dashboard rendering.
- **AgentState**: Closed set describing active/inactive and log attachment states for registered agents.
- **RecommendedNextAction**: Daemon-computed dashboard recommendation with a closed-set code, title, optional detail, optional target, and refresh timestamp.
- **RecentlySkippedRoutesWindow**: Short-lived process-local count source for route-skip decisions inside the active dashboard window.
- **App Contract Version**: The advertised dashboard contract version and supported minor range used by clients to understand additive fields.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A v1.1 dashboard response includes every v1.1 pane-state and agent-state key with integer values in seeded empty, single-agent, and mixed-state fixtures.
- **SC-002**: A route-skip fixture with skips inside and outside the active window reports the exact expected recently skipped count and window size.
- **SC-003**: Recommendation fixture tests cover all seven v1.1 codes and verify the fixed precedence order is observed when multiple conditions match simultaneously, including (a) a degraded subsystem coexisting with any lower-priority condition still resolving to `subsystem_degraded`, and (b) at least one additional adjacent-pair check (e.g., `no_containers` winning over `no_panes_discovered`) to demonstrate the first-match rule is applied, not just the top-of-list rule.
- **SC-004**: The full v1.0 app contract test suite passes unchanged against a v1.1 daemon.
- **SC-005**: A v1.1 dashboard contract test asserts all new fields are present in a single successful response envelope.
- **SC-006**: Dashboard response latency remains within the existing FEAT-011 dashboard budget after the new fields are added.
- **SC-007**: Contract documentation names every new closed-set value, its evolution rule, and the forward-compatibility behavior for unknown next-action codes.

## Assumptions

- FEAT-011 app backend contract v1.0 is the base contract being evolved.
- FEAT-012 remains the primary consumer, but FEAT-012 UI contract-registry and tile-renderer changes happen on the FEAT-012 branch unless explicitly pulled into this feature later.
- The OpenSpec proposal `extend-app-dashboard-fields-for-feat012` is the governing proposal for this feature's scope.
- The recently skipped route window is operational telemetry, not durable audit history.
- The dashboard remains poll-based for this feature.
- New fields are additive and should be acceptable under FEAT-011's minor-version evolution rules.
