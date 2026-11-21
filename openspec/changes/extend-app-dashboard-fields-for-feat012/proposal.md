## Why

FEAT-012's FR-012 (Agent Operations Dashboard) requires five tiles —
daemon reachability, contract version, container count, **pane count by
state**, **registered-agent count by state**, blocked-queue count,
**recently-skipped-route count**, and **recommended next action**.
FEAT-011 v1.0's `app.dashboard` returns only flat per-entity totals
(`counts.panes.{total,registered,unregistered}`,
`counts.agents.{total,by_role}`, `counts.queue.{...}`,
`counts.routes.{enabled,disabled}`) — it exposes neither per-state
panes, nor per-state registered agents, nor a recently-skipped-route
counter, nor a recommended-next-action object. The FEAT-012 review
(2026-05-24) flagged this as CRITICAL C8: the Dashboard would render
zeros against a real daemon today.

This is a v1.x **minor** of FEAT-011 (additive, per FR-035 / FR-039 in
the FEAT-011 spec). No existing client breaks because every new field
is optional with a documented default. FEAT-012 stays unchanged —
FR-012's wording is already correct; the daemon just gains the fields
the FEAT-012 spec already references.

## What Changes

- **ADD** four optional fields on the `app.dashboard` success result
  `counts` object:
  - `counts.panes.by_state: Map<PaneState, int>` — keyed by the FR-014
    4-state vocabulary `{discovered-and-unmanaged,
    discovered-and-registered, inactive-or-stale, discovery-degraded}`.
  - `counts.agents.by_state: Map<AgentState, int>` — keyed by the
    vocabulary `{active, inactive, partially_configured, log-attached,
    log-detached}`.
  - `counts.routes.recently_skipped_count: int` — number of routes
    skipped by FEAT-010 arbitration within the last 5 minutes
    (recommended default window).
  - `counts.routes.recently_skipped_window_ms: int` — the window the
    daemon actually used (so clients can render "skipped 7 in the last
    300 s" verbatim instead of guessing).
- **ADD** a top-level optional field `recommended_next_action` on the
  same response, shaped as `{code, title, detail?, target?} | null`,
  where `code` is drawn from a new closed set documented in
  `contracts/dashboard-next-actions.md`. Initial v1.1 codes:
  `no_containers`, `no_panes_discovered`, `unadopted_panes_present`,
  `no_routes_configured`, `blocked_queue_drain`, `subsystem_degraded`,
  `all_clear`.
- **ADD** a sibling optional field `recommended_next_action_refreshed_at: ISO8601`
  alongside `recommended_next_action` so clients can render
  "recommended N seconds ago" without a second round-trip.
- **BUMP** `app_contract_version` from `1.0` → `1.1`. Clients reading
  FEAT-011 v1.0 are unaffected; they never read the new fields.
- **DOCUMENT** that both `by_state` maps MUST be present when reported
  and MAY be `{}` if no rows exist in any state; clients MUST treat
  absent keys as zero.
- **DOCUMENT** the forward-compat rule for `recommended_next_action.code`:
  clients MUST ignore unknown codes silently (per FR-035 additive-evolution).
- **OUT OF SCOPE** (intentionally deferred): operator-customizable
  recommendations, push-based dashboard updates, persisting next-action
  history.

## Capabilities

### New Capabilities
- `app-dashboard-extensions`: Adds optional per-state pane counts,
  per-state agent counts, recently-skipped-route count, recommendation
  refresh timestamp, and a daemon-computed `recommended_next_action`
  object to the `app.dashboard` response, plus the closed set of
  recommendation codes. Lives alongside the existing FEAT-011 v1.0 app
  contract documented at `specs/011-app-backend-contract/` and bumps
  `app_contract_version` from `1.0` to `1.1`.

### Modified Capabilities
<!-- No OpenSpec capability exists today for the FEAT-011 contract (it
     is managed under specs/011-app-backend-contract/ via Spec Kit, not
     openspec/specs/). The new fields are introduced as a v1.1 minor of
     that contract; the changes are captured under the new
     app-dashboard-extensions capability above. -->

## Impact

- **Affected file (this change's own delta artifact)**: `openspec/changes/extend-app-dashboard-fields-for-feat012/specs/app-dashboard-extensions/spec.md` — defines the new requirements (per-state buckets, recommendation engine, version bump).
- **Affected file (this change's design artifact)**: `openspec/changes/extend-app-dashboard-fields-for-feat012/design.md` — recommendation-engine rule order, sliding-window data source, ContractRegistry bump path.
- **Affected file (this change's tasks)**: `openspec/changes/extend-app-dashboard-fields-for-feat012/tasks.md` — daemon implementation breakdown.
- **Sibling artifacts in `specs/011-app-backend-contract/` (updated at apply time, not at proposal time)**:
  - `spec.md` — extend FR-015 dashboard requirements, bump `app_contract_version`-related FRs and clarifications to `1.1`, add a Round-7 clarifications block recording this minor.
  - `contracts/app-methods.md` — extend the `app.dashboard` response shape with the four new optional `counts.*` fields and the top-level `recommended_next_action{,_refreshed_at}` fields.
  - `contracts/dashboard-next-actions.md` — **NEW** file: closed set of `recommended_next_action.code` values with per-code `target.kind` rules.
  - `contracts/closed-sets.md` — register the new `PaneState` and `AgentState` closed sets and the `recommended_next_action.code` closed set; document the additive-minor rule for each.
  - `contracts/error-codes.md` — no change (no new error codes; the closed set is unchanged).
  - `tasks.md` — append the daemon impl tasks (compute `by_state` aggregations, sliding-window recently-skipped accumulator, recommendation engine).
- **Daemon code**: new aggregation queries (per-state pane and per-state agent counts), a sliding 5-minute counter of FEAT-010 skip decisions, a recommendation-engine module that consults readiness, queue, pane, and route state.
- **Tests**: contract tests asserting the new fields are present at v1.1, that v1.0 clients still receive a well-formed response (i.e., the new fields are additive and never break v1.0 readers), that `by_state` maps cover the closed set, that the recommendation engine emits the correct code per fixture (no-containers, no-panes, unadopted-panes, no-routes, blocked-queue, subsystem-degraded, all-clear), and that the daemon ignores unknown future codes round-trip.
- **Downstream (FEAT-012)**: FEAT-012's `ContractRegistry.declare("agent_ops/dashboard", ContractVersion(1, 0))` bumps to `ContractVersion(1, 1)` once this lands, which then drives the FR-002 banner / per-surface read-only mode against an older daemon. The bump is **out of scope** for this proposal (it lives in FEAT-012's repo / branch) but is the consumer that justifies the change.
- **Compatibility**: additive only; no breaking changes. Closes the FEAT-012 dashboard wire gap flagged by the parallel review on 2026-05-24 as CRITICAL C8.
