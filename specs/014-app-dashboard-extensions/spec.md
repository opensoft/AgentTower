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

### Session 2026-05-24-r1

Post-implementation-design Round 1 — safety / contract-critical decisions. Source: `clarify-questions-r1.md`. Closes the 17 `NEEDS-CLARIFY-R1` items tagged across `checklists/`.

- Q: Aggregator compute-failure behavior — what does `app.dashboard` return if `counts.panes.by_state` or `counts.agents.by_state` cannot be computed? → A: Affected bucket keys emit `0`; the recommendation engine emits `subsystem_degraded` for the failing subsystem; the rest of the payload remains intact (FR-025 mirrors FR-021's recommendation-side null-fallback posture).
- Q: FEAT-010 routing worker failure propagation — what do `counts.routes.recently_skipped_*` report when the worker is stalled / crashed? → A: Last-known ring-buffer state continues to be returned; the recommendation engine separately emits `subsystem_degraded` for `routing_worker` (FR-008 extended).
- Q: FEAT-010 contract boundary — does FEAT-014 pin a FEAT-010 event shape? → A: No. `skip_counter` treats FEAT-010 as an opaque caller; the only contracted surface is `record_skip(monotonic_ms)`.
- Q: Recommendation compute-failure signal beyond WARN log — also a metric or JSONL event? → A: WARN log only in v1.1 (`app_dashboard_recommendation_compute_failed`); metric / counter / JSONL deferred to a future minor.
- Q: FEAT-010 stalled vs crashed threshold for `subsystem_degraded`? → A: Reuse FEAT-011 readiness-probe semantics. Crashed = process not running OR readiness reports unhealthy; stalled = readiness reports degraded. No new threshold introduced in v1.1.
- Q: "Cannot be computed" path for state buckets (vs "not yet populated") → A: Same as aggregator-failure rule above — emit `0` per bucket + `subsystem_degraded` recommendation (FR-025). Distinguish the two cases via the recommendation, not the bucket values.
- Q: Degraded subsystem effect on counts — authoritative or stale/partial? → A: Counts are best-effort during `subsystem_degraded`; the client renders them with a degraded badge; the daemon does not suppress (FR-026).
- Q: Partially-restarted daemon — may it emit inconsistent partial fields during bring-up? → A: No. The daemon MUST coherently emit `subsystem_degraded` for every still-down subsystem; counts remain best-effort (FR-026).
- Q: Latency budget quantile — p50, p95, p99, or worst-case? → A: **p95 ≤ 500 ms** at the FEAT-011 documented fixture scale (SC-006 tightened).
- Q: Behavior when the latency budget is missed → A: Return the response best-effort with whatever fields the daemon was able to compute, and log a WARN with the actual measured latency (FR-027). Do NOT promote to an error envelope solely on budget overrun.
- Q: SLO during `subsystem_degraded` — does the budget still apply? → A: Budget waived during degradation (SC-006 tightened). Degraded subsystems may cause SC-006 violation; the recommendation already signals that to clients.
- Q: Behavior beyond the FEAT-011 fixture scale (>10 containers / >200 agents / >100 routes) → A: Undefined / unsupported in v1.1. A future minor may set higher bounds. (Assumptions extended.)
- Q: CPU budget under sustained polling? → A: No separate CPU budget in v1.1. The per-call latency budget plus a polling expectation of ≤ 1 req/s implicitly bound daemon CPU. (Assumptions extended.)
- Q: `target.id` opacity — opaque or human-readable? → A: Opaque internal identifiers (FEAT-003/004/006/008/009/010 internal-id formats). Clients resolve a `target.id` to a display name via separate `app.<entity>.detail` calls. (FR-011 extended.)
- Q: `title` / `detail` scrubbing requirements → A: Template discipline IS the scrubbing rule. The per-code templates in `contracts/closed-sets-v1_1.md` §Per-code title/detail Templates allow only `{N}` integer + `{subsystem_name}` closed-set substitution — no free-form daemon prose can reach the wire, so the no-PII / no-secret guarantee falls out by construction. No additional scrubbing pass is required.
- Q: Per-caller suppression / reduced response → A: No per-caller suppression in FEAT-011 v1.0 or FEAT-014 v1.1. The dashboard shape is uniform for every caller that passes the host-only gate (FR-023). Compute-failure null fallback applies uniformly.

Additional notes:

- Keep dashboard reads resilient: state-bucket aggregation failures return zero-filled buckets and surface degradation through `subsystem_degraded` rather than breaking the whole response.
- Treat FEAT-010 as an opaque caller into the skip counter; no new skip-event wire shape or JSONL audit requirement for v1.1.
- Use FEAT-011 readiness semantics for routing-worker stalled / crashed detection; degraded counts are best-effort and rendered with degraded context.
- Interpret the dashboard latency budget as p95 ≤ 500 ms at documented fixture scale, waived during subsystem degradation; missed-budget calls still return best-effort and log WARN.
- Do not support scale beyond the FEAT-011 fixture envelope in v1.1; no separate CPU budget beyond per-call latency and normal polling expectations.
- Keep recommendation targets opaque and `title`/`detail` text template-bound so no free-form names, paths, credentials, host metadata, or PII are placed on the wire.
- FEAT-011 / FEAT-014 have no per-caller reduced dashboard response; the shape is uniform for callers that pass the local access gate.

### Session 2026-05-24-r2

Post-implementation-design Round 2 — lower-risk refinements (config tunability, future-version criteria, consumer scope, operator-guidance prose). Source: `clarify-questions-r2.md`. Closes the 7 `NEEDS-CLARIFY-R2` items tagged across `checklists/`.

- Q: Daemon-config-file tunability of `recently_skipped_window_ms` → A: Pure internal compile-time constant in v1.1. Not configurable via daemon config file, env var, CLI flag, or any other surface. Future-minor tunability is deferred. (Already implied by FR-022; this clarifies the specific constant.)
- Q: Future-raise of `title ≤ 128` / `detail ≤ 512` size caps → A: Future v1.x minors MAY raise these caps additively (clients tolerate larger values up to the new cap); MUST NOT shrink in any v1.x minor. (FR-014 extended.)
- Q: Symmetric forward compat (v1.1 daemon ignoring unknown future client-side request fields) → A: Yes. v1.1 daemon MUST gracefully ignore unknown request fields the client sends, mirroring the additive-minor model. (FR-012 extended with the daemon-side rule.)
- Q: Future capability-flag criterion → A: A future v1.x field requires a capability flag iff (a) it gates on a non-additive runtime behavior change, OR (b) clients need pre-adaptation knowledge before rendering. Plain additive read-side fields continue the always-emit pattern. (FR-028 added — governance for future minors; no v1.1 implementation impact.)
- Q: Other v1.1 consumers beyond FEAT-012 → A: The v1.1 dashboard fields are public read surface for any caller passing the host-only gate. FEAT-012 is the *primary* consumer in v1.1 but not the *sole* consumer; CLI / monitoring / future-app consumers receive the same contract guarantees. (FR-023 extended.)
- Q: Per-code operator guidance prose → A: The fixed `title` / `detail` templates in `contracts/closed-sets-v1_1.md` §Per-code title/detail Templates plus the T026 docs work are sufficient. No additional spec mandate.
- Q: Trend-inference prohibition on `recently_skipped_count` → A: The existing "telemetry, not durable audit history" Assumption is sufficient. No additional explicit prohibition needed.

Additional notes:

- Keep `recently_skipped_window_ms` as a pure internal v1.1 constant with no daemon config, env var, CLI flag, or client request override.
- Future v1.x minors may raise `title` / `detail` caps additively but must not shrink them.
- Establish symmetric forward compatibility now: v1.1 daemon ignores unknown future request fields.
- Capability flags are for non-additive runtime behavior or cases where clients need pre-adaptation knowledge; plain additive read-side fields do not need flags.
- Treat v1.1 dashboard fields as a public read surface for all callers that pass the host-only gate, with FEAT-012 as primary but not sole consumer.
- Fixed templates plus T026 documentation are sufficient operator guidance for v1.1.
- The existing telemetry-not-audit assumption is enough for `recently_skipped_count`; no extra trend-analysis prohibition is needed.

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
- **FR-003**: System MUST report empty pane-state buckets as integer `0`, not by omitting keys, returning `null`, or returning an empty map. This rule applies to any reserved-but-not-yet-implemented PaneState key a future v1.x minor introduces — the daemon emits `0` for the reserved key until the corresponding population logic ships, never `null` and never an omitted key.
- **FR-004**: System MUST extend the dashboard success result with `counts.agents.by_state` when the app contract version is at least v1.1.
- **FR-005**: `counts.agents.by_state` MUST include every v1.1 `AgentState` key: `active`, `inactive`, `partially_configured`, `log-attached`, and `log-detached`.
- **FR-006**: System MUST document that `log-attached` and `log-detached` agent buckets are orthogonal to active/inactive buckets and may cause the bucket sum to exceed total agents.
- **FR-007**: System MUST extend route counts with `recently_skipped_count` and `recently_skipped_window_ms` when the app contract version is at least v1.1.
- **FR-008**: System MUST count route skips only within the active sliding window of `300_000` ms (5 minutes) — fixed daemon-side and not client-tunable in v1.1 — and MUST make daemon restart reset the in-memory skip count to `0`. When the FEAT-010 routing worker is stalled or crashed (per Clarifications R1 Q5 — readiness probe semantics), `counts.routes.recently_skipped_*` MUST continue to return the last in-memory ring-buffer state (the skip counter is decoupled from worker liveness); the recommendation engine MUST separately emit `subsystem_degraded` for `routing_worker` in that state.
- **FR-009**: System MUST extend the dashboard success result with `recommended_next_action` and `recommended_next_action_refreshed_at` when the app contract version is at least v1.1.
- **FR-010**: System MUST compute the recommended next action server-side by evaluating a fixed deterministic precedence list top-to-bottom and returning the first matching code. The precedence order is: (1) `subsystem_degraded`, (2) `no_containers`, (3) `no_panes_discovered`, (4) `unadopted_panes_present`, (5) `blocked_queue_drain`, (6) `no_routes_configured`, (7) `all_clear`. When multiple conditions match simultaneously, the response MUST carry only the highest-precedence code; lower-precedence codes MUST NOT be emitted in its place or alongside it.
- **FR-011**: System MUST emit `recommended_next_action` with the object shape `{code: <closed-set string>, title: <string ≤128 chars>, detail: <string ≤512 chars> | null, target: {kind: <closed set>, id: <string>} | null}`, where `target.kind` reuses the v1.0 hint target closed set (`container`, `pane`, `agent`, `route`, `message`, `event`) plus `subsystem` added in v1.1. System MUST emit `target` per the per-recommendation-code table documented in `data-model.md` §RecommendedNextAction (per-code target rule) and `contracts/closed-sets-v1_1.md` §TargetKind (per-`kind` `target.id` format) — both tables are normative and incorporated by reference. System MUST emit `title` and `detail` per the fixed templates documented in `contracts/closed-sets-v1_1.md` §RecommendationCode §Per-code title/detail Templates — daemons do not author free-form recommendation prose at v1.1. `target.id` values MUST be opaque internal identifiers (Clarifications R1 Q14) — they MUST NOT contain operator-readable display names, host metadata, paths, credentials, or PII; clients resolve a `target.id` to a human-readable display name via separate `app.<entity>.detail` calls.
- **FR-012**: System MUST require clients to **silently** ignore unknown future values in **any** v1.1 closed set — `recommended_next_action.code`, `recommended_next_action.target.kind`, `counts.panes.by_state` keys, and `counts.agents.by_state` keys — without refusing the rest of the dashboard response and without displaying unknown values verbatim to operators. Future v1.x additions to these closed sets MUST NOT require a client update to be safe; clients render unknown values as nothing (the corresponding bucket / recommendation / target is skipped in the UI). Symmetrically (Clarifications R2 Q3), the v1.1 daemon MUST gracefully ignore unknown client-side request fields the client sends — the daemon MUST NOT respond with `validation_failed.unknown_field` or any other error solely because the client sent unrecognized fields. This establishes the symmetric forward-compat convention before a future v1.x minor introduces request parameters.
- **FR-013**: System MUST bump the app contract version from v1.0 to v1.1 and advertise a supported minor range whose maximum includes v1.1.
- **FR-014**: System MUST keep all v1.0 dashboard fields, methods, error-code behavior, and major-version rejection behavior compatible with v1.0 clients. Future v1.x minors MAY raise `title` / `detail` size caps (`≤ 128` / `≤ 512` in v1.1) additively (clients tolerate larger values up to the new cap); v1.x MUST NOT shrink the caps (Clarifications R2 Q2). The v1.1 caps are a minimum-guaranteed maximum: a v1.1 client safely renders strings within v1.1 caps; v1.x clients may need to handle larger values.
- **FR-015**: System MUST NOT introduce new capability flags for these fields because they are additive fields on an existing required dashboard method.
- **FR-016**: System MUST add or update contract documentation for dashboard next-action codes, closed sets, dashboard response shape, and v1.1 evolution rules.
- **FR-017**: System MUST include tests for per-state aggregation, recently skipped route counts, recommendation-code precedence, v1.0 compatibility, v1.1 response shape, and dashboard latency.
- **FR-018**: System MUST keep FEAT-012 UI renderer updates, push-based dashboard updates, customizable recommendation rules, and persisted recommendation history out of this feature's scope.
- **FR-019**: System MUST guarantee that v1.1 `counts.panes.by_state.discovered-and-registered` equals v1.0 `counts.panes.registered`, that the sum of `discovered-and-unmanaged` + `inactive-or-stale` + `discovery-degraded` equals v1.0 `counts.panes.unregistered`, and that the sum of all four v1.1 buckets equals v1.0 `counts.panes.total`. For the purpose of this cross-check, an agent classified as `partially_configured` (per FR-020) STILL counts as "registered" for its pane's `discovered-and-registered` bucket — incomplete agent configuration affects the agent's bucket only, not the pane's bucket. The pane bucket is a property of the pane and its container, not of the agent's configuration completeness.
- **FR-020**: System MUST treat a registered agent as `active` when its container `state == "active"` and as `inactive` when its container is `inactive` or `degraded_scan`. System MUST treat the agent as `partially_configured` — mutually exclusive with `active`/`inactive` — when one or more of `role`, `capability`, or `label` is missing/empty/`unknown`, such that `active` + `inactive` + `partially_configured` equals total agents. The `log-attached`/`log-detached` buckets remain orthogonal and may overlap any of the three.
- **FR-021**: System MUST set both `recommended_next_action` and `recommended_next_action_refreshed_at` to `null` and return the dashboard payload as success when recommendation computation itself fails. The failure MUST NOT propagate as an error code, empty payload, or partial omission of other v1.1 fields.
- **FR-022**: System MUST NOT introduce any new operator-facing configuration in v1.1 — no new environment variable, no new daemon-config-file key, no new CLI flag. v1.1 constants (`recently_skipped_window_ms`, `title` size cap, `detail` size cap, recently-skipped ring-buffer max length) are internal daemon constants in v1.1. Whether any of them become operator-tunable in a future minor is out of scope for FEAT-014.
- **FR-023**: System MUST inherit `app.dashboard` authorization and access control unchanged from FEAT-011 v1.0. v1.1 introduces no new authorization surface — no new permission, no new session-token semantics, no new client-major rejection criterion. A v1.0 client and a v1.1 client face the same auth gate; the same daemon response shape (modulo v1.1 additive fields) is emitted regardless of which one calls. The v1.1 dashboard fields are public read surface for any caller passing the host-only gate (Clarifications R2 Q5); FEAT-012 is the *primary* consumer in v1.1 but not the *sole* consumer — CLI `agenttower dashboard`, monitoring scripts, and future-app consumers receive the same contract guarantees.
- **FR-024**: System MUST NOT place any user-identifying data (PII) in any v1.1 field. This applies to `target.id`, `title`, `detail`, and every closed-set value. Detailed opacity and scrubbing rules are resolved in Clarifications §Session 2026-05-24-r1: `target.id` opacity is governed by FR-011; `title` / `detail` PII-freedom is guaranteed by the template-discipline rule in `contracts/closed-sets-v1_1.md` §Per-code title/detail Templates. The no-PII floor is unconditional.
- **FR-025**: System MUST emit `0` for every key in `counts.panes.by_state` and `counts.agents.by_state` when the corresponding service-layer aggregator fails to compute (e.g., FEAT-003 / FEAT-006 / FEAT-007 outage), AND System MUST emit `subsystem_degraded` as the recommendation when any v1.1 aggregator fails. The failure MUST NOT propagate as an error code, partial omission of other v1.1 fields, or null counts. This aggregator failure path mirrors FR-021's compute-failure null fallback for `recommended_next_action`. (Clarifications R1 Q1, Q6.)
- **FR-026**: Counts emitted during `subsystem_degraded` states are best-effort — System MUST NOT suppress `counts.panes.by_state` or `counts.agents.by_state` during degradation; counts are emitted with whatever data the still-up subsystems can produce, and the recommendation engine signals the degraded state. When the daemon is partially restarted (some subsystems up, others bringing up), System MUST coherently emit `subsystem_degraded` for every still-down subsystem — deterministic, no inconsistent partial fields without the corresponding degraded signal. (Clarifications R1 Q7, Q8.)
- **FR-027**: When a dashboard call would exceed the SC-006 latency budget, System MUST return the response best-effort (every field the daemon was able to compute within the call) AND MUST log a WARN line with the actual measured latency. System MUST NOT abort the dashboard call into an error envelope solely because the latency budget was exceeded. (Clarifications R1 Q10.)
- **FR-028**: Future v1.x minors that add a new field MUST require a capability flag in the `app.hello` `capability_flags` map if and only if (a) the field gates on a non-additive runtime behavior change (e.g., the daemon optionally enables a new mutation surface), OR (b) clients need to know whether the daemon supports the field BEFORE adapting their UI (vs. ignoring-unknown after the fact per FR-012). Plain additive read-side fields continue the v1.1 always-emit pattern and MUST NOT require a capability flag. (Clarifications R2 Q4 — governance for future v1.x evolution; no v1.1 implementation impact.)

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
- **SC-006**: Dashboard response latency remains within the existing FEAT-011 dashboard budget after the new fields are added. The budget is interpreted as **p95 ≤ 500 ms** at the FEAT-011 documented fixture scale (no-cache, ≥ 1 container, ≥ 1 agent, fixture caps ≤ 10 containers / ≤ 200 agents / ≤ 100 routes — Clarifications R1 Q9). The budget is waived during `subsystem_degraded` states; slowness during degradation is an expected symptom and the recommendation engine already signals it to clients (Clarifications R1 Q11).
- **SC-007**: Contract documentation names every new closed-set value, its evolution rule, and the forward-compatibility behavior for unknown next-action codes.

## Assumptions

- FEAT-011 app backend contract v1.0 is the base contract being evolved.
- FEAT-012 remains the primary consumer, but FEAT-012 UI contract-registry and tile-renderer changes happen on the FEAT-012 branch unless explicitly pulled into this feature later.
- The OpenSpec proposal `extend-app-dashboard-fields-for-feat012` is the governing proposal for this feature's scope.
- The recently skipped route window is operational telemetry, not durable audit history.
- The dashboard remains poll-based for this feature.
- New fields are additive and should be acceptable under FEAT-011's minor-version evolution rules.
- FEAT-014 behavior beyond the FEAT-011 documented fixture scale (> 10 containers, > 200 agents, > 100 routes) is undefined / unsupported in v1.1; operators should not deploy at scales above the documented fixture without expecting SC-006 violation. A future minor may set higher bounds. (Clarifications R1 Q12.)
- FEAT-014 introduces no separate CPU budget for `app.dashboard` calls in v1.1; the per-call latency budget plus a polling expectation of ≤ 1 req/s implicitly bound daemon CPU. (Clarifications R1 Q13.)
