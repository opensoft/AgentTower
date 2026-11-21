## 1. Spec & Contract Updates (FEAT-011 artifacts)

- [ ] 1.1 Add a Round-7 clarifications block to `specs/011-app-backend-contract/spec.md` recording the v1.1 minor: new `app.dashboard` fields (`counts.panes.by_state`, `counts.agents.by_state`, `counts.routes.recently_skipped_count`, `counts.routes.recently_skipped_window_ms`, `recommended_next_action`, `recommended_next_action_refreshed_at`), motivation (FEAT-012 review CRITICAL C8 / 2026-05-24), and FR-035 additive-minor classification.
- [ ] 1.2 Extend FR-015 in `specs/011-app-backend-contract/spec.md` to require the four new optional fields when `app_contract_version >= "1.1"` and cross-reference the new contract files; update FR-010's enumeration to mention the v1.1 bump path (`supported_minor_range.max = "1.1"`).
- [ ] 1.3 Add a v1.1 reserved-key note next to FR-016a / FR-014a in `spec.md` covering the reserved `discovery-degraded` `PaneState` bucket and the always-emitted-zero `partially_configured` `AgentState` bucket (same pattern as `degraded_scan` / `check_container_filter`).
- [ ] 1.4 Update `specs/011-app-backend-contract/contracts/app-methods.md` §`app.dashboard` to add the four new optional fields to the success-result example and document the per-field shape, presence rules (MUST be emitted at v1.1, all keys populated even when 0), and units (`recently_skipped_window_ms` is an integer milliseconds value; `recommended_next_action_refreshed_at` is ISO-8601 UTC).
- [ ] 1.5 Create new file `specs/011-app-backend-contract/contracts/dashboard-next-actions.md` enumerating the v1.1 `recommended_next_action.code` closed set, the fixed evaluation order, the per-code `target.kind` rules, the forward-compatibility rule (clients ignore unknown codes), and the FR-035 additive-minor note.
- [ ] 1.6 Extend `specs/011-app-backend-contract/contracts/closed-sets.md` with three new sections: `PaneState`, `AgentState` (including the "log-attached/log-detached overlap → sum MAY exceed total" note), and `RecommendedNextActionCode` (referencing `dashboard-next-actions.md` for the canonical list). Each section MUST include the FR-035 additive-evolution note.
- [ ] 1.7 Confirm `specs/011-app-backend-contract/contracts/error-codes.md` requires NO changes (no new error codes; the closed set is unchanged) and add a one-line "v1.1 minor — no change to this file" header comment.
- [ ] 1.8 Update `specs/011-app-backend-contract/data-model.md` to reference the new `PaneState` / `AgentState` derivation rules from Decision 6 (link the dashboard counts back to the underlying FEAT-004 panes table, FEAT-006 agents table, FEAT-007 log_attachments table).
- [ ] 1.9 Run `openspec validate extend-app-dashboard-fields-for-feat012` and resolve any reported issues before moving to implementation.

## 2. Daemon Code — Per-State Aggregations

- [ ] 2.1 Add a per-state pane aggregation query that returns one integer per `PaneState` value (`discovered-and-unmanaged`, `discovered-and-registered`, `inactive-or-stale`, `discovery-degraded`). Use a single GROUP-BY against the FEAT-004 `panes` table joined to `agents.pane_id` for the registration check and to `containers.active` for the inactive-or-stale check. `discovery-degraded` returns hard-coded `0` at v1.1 (reserved bucket).
- [ ] 2.2 Add a per-state agent aggregation query that returns one integer per `AgentState` value (`active`, `inactive`, `partially_configured`, `log-attached`, `log-detached`). Implement the join logic from Decision 6: pane discovery + container state for active/inactive, FEAT-007 `log_attachments.status` for log buckets, hard-coded `0` for `partially_configured` at v1.1.
- [ ] 2.3 Wire both aggregations into the `app.dashboard` response builder so they emit `counts.panes.by_state` and `counts.agents.by_state` with every closed-set key present (even when the bucket is 0).
- [ ] 2.4 Add a unit test fixture covering: empty daemon (all buckets 0), single registered agent (active + log-attached), multi-state daemon (mix of active/inactive/log-attached/log-detached) — assert per-bucket counts and assert every closed-set key is present in the response map.

## 3. Daemon Code — Sliding-Window Skipped-Routes Counter

- [ ] 3.1 Introduce a process-local `RecentlySkippedRoutes` in-memory structure (e.g., `collections.deque[float]` of unix-ms timestamps) with a `record_skip()` and a `count_within(window_ms)` method that prunes timestamps older than `now - window_ms` and returns the remaining length.
- [ ] 3.2 Hook `record_skip()` into the FEAT-010 arbitration code path so every skip decision (regardless of skip reason) appends a timestamp.
- [ ] 3.3 Surface `counts.routes.recently_skipped_count = window.count_within(300_000)` and `counts.routes.recently_skipped_window_ms = 300_000` on every `app.dashboard` response at v1.1.
- [ ] 3.4 Add tests covering: skips outside the window are excluded; restart resets the counter to 0; the window value emitted on the wire matches the daemon's configured constant.

## 4. Daemon Code — Recommended-Next-Action Engine

- [ ] 4.1 Implement a `RecommendationEngine` module that consumes the readiness state, container counts, pane counts (including the new `by_state` map), agent counts, queue blocked count, route counts, and the recently-skipped-routes count. Apply the fixed rule order from design Decision 3 and return the first matching code (or `all_clear`).
- [ ] 4.2 For each code that carries a `target`, implement the target-resolution helper documented in design Decision 3 (e.g., `subsystem_degraded` → first degraded subsystem name; `unadopted_panes_present` → first `discovered-and-unmanaged` pane id ordered by the FEAT-011 default pane sort; `blocked_queue_drain` → oldest blocked `message_id`).
- [ ] 4.3 Define short English `title` (≤ 80 chars) and optional `detail` (≤ 280 chars) for every code; centralize them as module constants so the contract test can assert lengths.
- [ ] 4.4 Wire the engine into the `app.dashboard` response builder so it always emits `recommended_next_action` (non-null at v1.1; the rule order guarantees at least `all_clear` matches) and `recommended_next_action_refreshed_at` (request-handling-time ISO-8601 UTC string).
- [ ] 4.5 Add per-rule fixture tests covering every code: an empty-daemon fixture → `no_containers`; a containers-but-no-panes fixture → `no_panes_discovered`; an unadopted-panes fixture → `unadopted_panes_present`; a blocked-queue fixture → `blocked_queue_drain`; an agents-but-no-routes fixture → `no_routes_configured`; a degraded-subsystem fixture → `subsystem_degraded` (even when other conditions also apply, asserting precedence); a healthy fixture → `all_clear`.

## 5. Contract Version Bump

- [ ] 5.1 Bump the daemon's `APP_CONTRACT_VERSION` constant from `"1.0"` to `"1.1"` and extend `SUPPORTED_MINOR_RANGE` to `{"min": "1.0", "max": "1.1"}`. Update every call site that returns either field (`app.hello` response builder, FR-033 envelope writer, any contract-test fixtures).
- [ ] 5.2 Update the FR-035 / SC-029 dispatcher smoke-test guard so it exercises `app.dashboard` at v1.1 and asserts every new field (`counts.panes.by_state`, `counts.agents.by_state`, `counts.routes.recently_skipped_count`, `counts.routes.recently_skipped_window_ms`, `recommended_next_action`, `recommended_next_action_refreshed_at`) is present in a single response.
- [ ] 5.3 Confirm `capability_flags` is unchanged (`{}`) and add a regression test asserting that the v1.1 daemon does NOT introduce any new capability flag (per FR-039: new fields on required methods do not need flags).
- [ ] 5.4 Verify the existing `app_contract_major_unsupported` path still rejects `client_app_contract_major = 2` against the v1.1 daemon (the major-mismatch behavior is unchanged by this minor).

## 6. Contract & Integration Tests

- [ ] 6.1 Add a v1.0-compat contract test: spin a v1.1 daemon, replay the full v1.0 contract-test suite, assert every existing assertion still passes (no v1.0 field removed, no v1.0 type changed).
- [ ] 6.2 Add a v1.1 contract test asserting the response shape from Sections 2 / 3 / 4 round-trips byte-for-byte through the FR-033 envelope (`{ok: true, app_contract_version: "1.1", result: {...new fields...}}`).
- [ ] 6.3 Add a forward-compat test asserting that a client treating an unknown `recommended_next_action.code` as a no-op still parses the rest of the response without error (simulates a future v1.2 code the v1.1 client doesn't know).
- [ ] 6.4 Re-run the FEAT-011 SC-002 dashboard latency test (≤ 500 ms) on the v1.1 response shape and confirm the per-state aggregations don't regress the budget. Capture the measured p95 in the test output for review.
- [ ] 6.5 Add an integration test exercising the full happy path: `app.hello` → reads v1.1 contract → `app.dashboard` → asserts all v1.1 fields populated against a seeded daemon (1 container, 2 panes — one adopted one unadopted, 1 active log attachment, 1 blocked queue row, 1 enabled route, 2 skips inside the 5-min window, readiness `ready`).

## 7. Handoff & FEAT-012 Follow-Up

- [ ] 7.1 Open a tracking issue on FEAT-012's branch / spec referencing this change: once merged, FEAT-012 bumps `ContractRegistry.declare("agent_ops/dashboard", ContractVersion(1, 0))` to `ContractVersion(1, 1)` and updates the Dashboard tile renderers to consume the new fields. Include the merged commit SHA and the v1.1 contract-version string in the issue body.
- [ ] 7.2 Update `docs/mvp-feature-sequence.md` (or the post-MVP roadmap doc, whichever currently lists FEAT-011) with a one-line note recording the v1.1 minor and its motivating consumer (FEAT-012 FR-012).
- [ ] 7.3 Run `openspec validate extend-app-dashboard-fields-for-feat012 --strict` (or the project's equivalent strict validator) and confirm zero findings before requesting review.
- [ ] 7.4 Run `openspec archive extend-app-dashboard-fields-for-feat012` once the change is merged so the additive-minor delta is folded into `openspec/specs/app-dashboard-extensions/spec.md`.
