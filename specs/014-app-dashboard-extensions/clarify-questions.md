# Clarification Questions — FEAT-014 App Dashboard Extensions

**Session date**: 2026-05-24
**Spec under clarification**: `specs/014-app-dashboard-extensions/spec.md`
**Mode**: block form (user-global rule, multi-question round)

Reply with one of:
- The option letter for the recommended (or any) choice (e.g., `Q1: B`)
- `yes` / `recommended` / `suggested` to accept the recommendation
- A short free-form answer (≤5 words) where allowed

You can answer all 12 in one reply, e.g.:
```
Q1: A
Q2: recommended
Q3: <short answer>
...
```

## Answers

Q1: A

Q2: A

Q3: A

Q4: A

Q5: A

Q6: A

Q7: A

Q8: A

Q9: A

Q10: A

Q11: A

Q12: A

Notes:

- FEAT-014 should stay an additive app-contract v1.1 minor. The new dashboard fields are emitted by a v1.1 daemon and old v1.0 clients keep working by ignoring unknown fields.
- The route-skip counter is intentionally process-local and resets on daemon restart; it is dashboard telemetry, not durable audit history.
- Recommendation computation is server-side, fixed-order, and recomputed per dashboard call. If recommendation computation itself fails, the dashboard response still succeeds with the recommendation fields set to `null` so the rest of the operator surface remains usable.
- Keep the hyphenated state values because FEAT-012 and the product UX language already refer to those exact labels.
- Recommendation precedence is a fixed deterministic order evaluated top-to-bottom; the daemon returns the first matching code and emits no lower-priority codes alongside it. The full precedence is:
  1. `subsystem_degraded`
  2. `no_containers`
  3. `no_panes_discovered`
  4. `unadopted_panes_present`
  5. `blocked_queue_drain`
  6. `no_routes_configured`
  7. `all_clear`

---

## Q1. PaneState bucket assignment rules

How are discovered/registered panes assigned to each v1.1 `PaneState` bucket?

**Recommended:** Option A — keeps existing FEAT-004/011 semantics intact and avoids introducing new time-based heuristics in a minor bump.

| Option | Description |
|--------|-------------|
| A | `discovered-and-unmanaged` = pane row exists but no agent registered; `discovered-and-registered` = pane row exists AND agent registered; `inactive-or-stale` = pane row whose container is `inactive` OR whose `last_seen_at` predates the most recent successful scan; `discovery-degraded` = pane row whose container is in `degraded_scan` state. |
| B | Same as A but `inactive-or-stale` uses an explicit wall-clock threshold (e.g., `last_seen_at` > N minutes ago) rather than container/scan state. |
| C | `discovery-degraded` is a per-pane signal computed independently of the container's `degraded_scan` state. |
| Short | Provide a different mapping (≤5 words). |

---

## Q2. AgentState `partially_configured` definition

When does a registered agent fall into the `partially_configured` bucket?

**Recommended:** Option A — aligns with the product UX doc's "configuration completeness" framing and uses fields the daemon already tracks.

| Option | Description |
|--------|-------------|
| A | Agent row exists but one or more of `role`, `capability`, `label` is missing/empty/`unknown`. |
| B | Agent row exists but no log attachment has ever succeeded. |
| C | Agent row exists but the underlying pane is no longer discoverable. |
| D | Reserved for future use; emit `0` at v1.1 until a follow-up feature defines it. |
| Short | Provide a different definition (≤5 words). |

---

## Q3. AgentState `active` vs `inactive` signal

What signal determines whether a registered agent is `active` vs `inactive`?

**Recommended:** Option A — derives from the container state the dashboard already exposes (no new heartbeat machinery for a minor bump).

| Option | Description |
|--------|-------------|
| A | The agent's container is in container `state == "active"` → agent `active`; container `inactive` OR `degraded_scan` → agent `inactive`. |
| B | The agent's log attachment is `active` (FEAT-007) → agent `active`; else `inactive`. |
| C | The agent's pane was seen in the most recent successful scan → `active`; else `inactive`. |
| Short | Provide a different signal (≤5 words). |

---

## Q4. Relationship between v1.0 `panes.{total,registered,unregistered}` and new `panes.by_state`

Must the new `by_state` buckets be consistent with the existing v1.0 fields?

**Recommended:** Option A — guarantees clients can cross-check, keeps semantics auditable, and matches the additive minor-evolution rule.

| Option | Description |
|--------|-------------|
| A | `discovered-and-registered` == v1.0 `registered`; `discovered-and-unmanaged` + `inactive-or-stale` + `discovery-degraded` == v1.0 `unregistered`; sum of all four buckets == v1.0 `total`. |
| B | The new buckets are orthogonal to v1.0 fields and may sum to a different total (like log-state overlap for agents). |
| C | The new buckets replace the v1.0 fields semantically; v1.0 fields are kept only for wire compatibility and may diverge. |
| Short | Provide a different rule (≤5 words). |

---

## Q5. `partially_configured` bucket overlap with `active`/`inactive`

Is `partially_configured` orthogonal to `active`/`inactive` (sum can exceed total) or mutually exclusive?

**Recommended:** Option A — keeps active/inactive a strict partition and avoids a second "sum may exceed total" caveat in the contract.

| Option | Description |
|--------|-------------|
| A | Mutually exclusive: `active` + `inactive` + `partially_configured` == total agents. |
| B | Orthogonal: `active` + `inactive` == total agents, and `partially_configured` overlaps both (sum may exceed total), same as `log-attached`/`log-detached`. |
| C | `partially_configured` agents are excluded from `active`/`inactive` (so `active` + `inactive` + `partially_configured` == total, like Option A) AND `log-attached`/`log-detached` still overlap. |
| Short | Provide a different rule (≤5 words). |

---

## Q6. Default `recently_skipped_window_ms` and tunability

What is the canonical window size for `recently_skipped_count`, and can clients tune it per request?

**Recommended:** Option A — matches typical "recent operational friction" dashboards and avoids per-request configuration sprawl in a minor bump.

| Option | Description |
|--------|-------------|
| A | Fixed daemon-side default of 5 minutes (300_000 ms); not client-tunable in v1.1. |
| B | Fixed daemon-side default of 15 minutes (900_000 ms); not client-tunable in v1.1. |
| C | Default 5 minutes, client-tunable per `app.dashboard` request via an optional param (with documented min/max bounds). |
| D | Daemon-configurable (config file / env var) but not per-request tunable. |
| Short | Provide a different default (≤5 words). |

---

## Q7. Route-skip data source

What is the source of route-skip events for the `recently_skipped_count`?

**Recommended:** Option A — matches FR-008 "daemon restart resets to 0" and avoids a new query path against persisted audit data.

| Option | Description |
|--------|-------------|
| A | In-memory ring buffer / counter of recent FEAT-010 skip decisions, populated by the routing worker; cleared on daemon restart. |
| B | SQL query against the FEAT-008 audit log filtered by event type and time; survives daemon restart. |
| C | In-memory ring buffer primarily, with a JSONL audit-log fallback if the buffer is empty (e.g., right after restart). |
| Short | Provide a different source (≤5 words). |

---

## Q8. Recommendation refresh semantics

When is `recommended_next_action` recomputed, and what does `recommended_next_action_refreshed_at` timestamp?

**Recommended:** Option A — simplest model, no cache to invalidate, matches FR-009/FR-010 "computed server-side" intent.

| Option | Description |
|--------|-------------|
| A | Recomputed on every `app.dashboard` call; `refreshed_at` is the call's compute time. |
| B | Cached with a short TTL (e.g., 1s) shared across concurrent dashboard callers; `refreshed_at` is the cache-fill time. |
| C | Recomputed only when underlying state changes (event-driven); `refreshed_at` is the time of the last state change that altered the recommendation. |
| Short | Provide a different rule (≤5 words). |

---

## Q9. RecommendedNextAction object shape

What are the exact fields, types, and bounds of the `recommended_next_action` object?

**Recommended:** Option A — mirrors the existing v1.0 `Hint` shape (FR-014a) so clients can reuse renderers, and bounds match v1.0 norms.

| Option | Description |
|--------|-------------|
| A | `{code: <closed-set string>, title: <str ≤128>, detail: <str ≤512> \| null, target: {kind: <closed set>, id: <str>} \| null}`; `target.kind` reuses the v1.0 hint target closed set (`container, pane, agent, route, message, event`) plus `subsystem` added for v1.1. |
| B | Same as A but `target.kind` strictly reuses the v1.0 set (no `subsystem`); `subsystem_degraded` always has `target: null`. |
| C | Same as A but `title` and `detail` are unbounded (no length caps). |
| D | Just `{code, target?}` — clients render their own title/detail from the code (no daemon-supplied prose). |
| Short | Provide a different shape (≤5 words). |

---

## Q10. v1.1 field emission gating per client major

When a client connects with `client_app_contract_major = 1`, does the v1.1 daemon still emit the new fields in `app.dashboard`?

**Recommended:** Option A — matches FR-014/FR-015 and the existing FEAT-011 additive-minor model (clients ignore unknown fields).

| Option | Description |
|--------|-------------|
| A | Always emit v1.1 fields once the daemon advertises v1.1, regardless of `client_app_contract_major`; v1.0 clients ignore unknown fields per existing rules. |
| B | Suppress v1.1 fields when `client_app_contract_major == 1`; only emit when client also advertises ≥1. |
| C | Gate emission on a new `client_app_contract_minor` field in `app.hello` (would require a request-shape change). |
| Short | Provide a different rule (≤5 words). |

---

## Q11. Recommendation compute-failure fallback

If the daemon cannot compute a recommendation (transient internal error inside the recommendation logic), what does the dashboard response carry?

**Recommended:** Option A — keeps the dashboard read side-effect-free and degradation-tolerant; the rest of the payload remains usable.

| Option | Description |
|--------|-------------|
| A | Emit `recommended_next_action: null` and `recommended_next_action_refreshed_at: null`; the rest of the dashboard payload still returns success. |
| B | Emit a synthetic `subsystem_degraded` recommendation with a documented detail string. |
| C | Return the entire `app.dashboard` call as `internal_error`. |
| D | Emit the last successfully computed recommendation with its prior `refreshed_at`. |
| Short | Provide a different rule (≤5 words). |

---

## Q12. Closed-set naming convention for new state vocabularies

PaneState/AgentState in the spec uses hyphens (`discovered-and-unmanaged`, `log-attached`); existing v1.0 closed sets (`container.state`, queue states, hint codes) use snake_case or single words. Which form ships in v1.1?

**Recommended:** Option A — keeps the spec faithful to the product UX doc that originally enumerated these states and to FEAT-012's renderer expectations.

| Option | Description |
|--------|-------------|
| A | Keep hyphens as written in the spec (`discovered-and-unmanaged`, `discovered-and-registered`, `inactive-or-stale`, `discovery-degraded`, `log-attached`, `log-detached`). |
| B | Normalize to snake_case for v1.1 (`discovered_and_unmanaged`, `inactive_or_stale`, `log_attached`, etc.) to match existing v1.0 closed-set style. |
| C | Use shorter single-word forms (`unmanaged`, `registered`, `stale`, `degraded`; `active`, `inactive`, `partial`, `log_on`, `log_off`). |
| Short | Provide a different convention (≤5 words). |
