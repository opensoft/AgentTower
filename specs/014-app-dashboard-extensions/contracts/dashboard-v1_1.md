# Contract: `app.dashboard` v1.1 Additive Fields

**Created**: 2026-05-24
**Plan**: [../plan.md](../plan.md)
**Base contract**: FEAT-011 `specs/011-app-backend-contract/contracts/app-methods.md` — `app.dashboard` v1.0.
**Closed sets**: [closed-sets-v1_1.md](./closed-sets-v1_1.md)

This document specifies *only* the v1.1 additions to the existing `app.dashboard` success envelope. Every v1.0 field — `counts.containers.{active,inactive,degraded_scan}`, `counts.panes.{total,registered,unregistered}`, `counts.agents.{total,by_role}`, `counts.log_attachments.{active,degraded,none}`, `counts.events.total`, `counts.queue.{queued,blocked,delivered,canceled,failed}`, `counts.routes.{enabled,disabled}`, the top-level `recent` object (`{events,queue,routes}`), and `hints[]` — is bit-identical to FEAT-011 v1.0 (FR-014). Error envelope, request shape, host-only gate, session token, and pagination are unchanged.

## Request

Identical to v1.0. `app.dashboard` takes no parameters in v1.0 and adds no parameters in v1.1 — there is no per-request `window_ms` override (Clarifications Q6 — fixed daemon-side; CHK005 in `configuration.md`).

## Response — v1.1 Success Envelope

The full v1.1 success envelope shape (valid JSON, v1.0 carry-over and v1.1 additions merged into a single object):

```json
{
  "ok": true,
  "app_contract_version": "1.1",
  "result": {
    "counts": {
      "containers": {
        "active":        "<int>",
        "inactive":      "<int>",
        "degraded_scan": "<int>"
      },
      "panes": {
        "total": "<int>",
        "registered": "<int>",
        "unregistered": "<int>",
        "by_state": {
          "discovered-and-unmanaged":  "<int ≥ 0>",
          "discovered-and-registered": "<int ≥ 0>",
          "inactive-or-stale":         "<int ≥ 0>",
          "discovery-degraded":        "<int ≥ 0>"
        }
      },
      "agents": {
        "total": "<int>",
        "by_role": {
          "master":      "<int>",
          "slave":       "<int>",
          "swarm":       "<int>",
          "test-runner": "<int>",
          "shell":       "<int>",
          "unknown":     "<int>"
        },
        "by_state": {
          "active":               "<int ≥ 0>",
          "inactive":             "<int ≥ 0>",
          "partially_configured": "<int ≥ 0>",
          "log-attached":         "<int ≥ 0>",
          "log-detached":         "<int ≥ 0>"
        }
      },
      "log_attachments": { "active": "<int>", "degraded": "<int>", "none": "<int>" },
      "events": { "total": "<int>" },
      "queue": {
        "queued":    "<int>",
        "blocked":   "<int>",
        "delivered": "<int>",
        "canceled":  "<int>",
        "failed":    "<int>"
      },
      "routes": {
        "enabled":  "<int>",
        "disabled": "<int>",
        "recently_skipped_count":     "<int ≥ 0>",
        "recently_skipped_window_ms": 300000
      }
    },
    "recent": {
      "events": [],
      "queue":  [],
      "routes": []
    },
    "hints":   [],
    "recommended_next_action": {
      "code":   "<closed_set_string>",
      "title":  "<string, ≤128 chars>",
      "detail": "<string, ≤512 chars or null>",
      "target": "<{kind, id} sub-object or null>"
    },
    "recommended_next_action_refreshed_at": "<ISO-8601 UTC ms string>"
  }
}
```

**How to read this sketch:**

- Angle-bracket placeholders inside quotes (`"<int>"`, `"<int ≥ 0>"`, `"<closed_set_string>"`, etc.) are stand-ins for concrete wire values; the surrounding double-quotes are only there to keep the sketch as valid JSON. On the wire, `<int>` is a JSON integer literal (not a string), `<int ≥ 0>` is a non-negative JSON integer literal, and `<closed_set_string>` is a JSON string drawn from the closed sets documented in `closed-sets-v1_1.md`.
- **v1.0 carry-over (unchanged from FEAT-011, verbatim field names):** `counts.containers.{active, inactive, degraded_scan}`, `counts.panes.{total, registered, unregistered}`, `counts.agents.{total, by_role}`, `counts.log_attachments.{active, degraded, none}`, `counts.events.total`, `counts.queue.{queued, blocked, delivered, canceled, failed}`, `counts.routes.{enabled, disabled}`, the top-level `recent` object (`{events, queue, routes}` arrays), and `hints[]`. FR-014 forbids changing any v1.0 field's name, type, range, or semantics.
- **v1.1 additions (this feature):** `counts.panes.by_state` (4 keys), `counts.agents.by_state` (5 keys), `counts.routes.recently_skipped_count`, `counts.routes.recently_skipped_window_ms`, `recommended_next_action`, `recommended_next_action_refreshed_at`. These are the **only** new keys; v1.1 adds nothing to `containers`, `log_attachments`, `events`, `queue`, or `recent`.
- **Nullability:** the sketch above shows the populated/happy-path case. `recommended_next_action` and `recommended_next_action_refreshed_at` MAY both be `null` together on recommendation compute failure (FR-021 — see §Field-by-Field for the paired-null invariant). `recommended_next_action.detail` MAY be `null`. `recommended_next_action.target` MAY be `null`. The §Field-by-Field section below is authoritative on these union types.

## Field-by-Field Specification

### `counts.panes.by_state` (object, required)

- Type: object with exactly four integer-valued keys (closed set; see `closed-sets-v1_1.md` §PaneState).
- Empty buckets are present as `0`, never omitted, never `null` (FR-003).
- Cross-check invariants (FR-019, post-R3 one-sided per Clarifications §Session 2026-05-25-r3 Q1):
  - `by_state["discovered-and-registered"]` **≤** `counts.panes.registered` — strict gap when a registered agent sits on an inactive or `degraded_scan` container (Research §PB routes such panes to `inactive-or-stale` / `discovery-degraded` instead of `discovered-and-registered`).
  - `by_state["discovered-and-unmanaged"] + by_state["inactive-or-stale"] + by_state["discovery-degraded"]` **≥** `counts.panes.unregistered` — mirror of the gap above.
  - Sum of all four **==** `counts.panes.total` — the v1.1 partition is exhaustive; this invariant is strict on the aggregator-healthy path. On the FR-025 aggregator-compute-failure path (all four buckets emit `0` while the v1.0 carry-over `counts.panes.total` may stay non-zero from a still-up accessor) the equality is suspended; the failure is surfaced via the `subsystem_degraded` recommendation, not by mutating the buckets.

### `counts.agents.by_state` (object, required)

- Type: object with exactly five integer-valued keys (closed set; see `closed-sets-v1_1.md` §AgentState).
- Empty buckets are present as `0`, never omitted, never `null`.
- Partition invariant (FR-020), holds when the agent-state aggregator computed successfully: `active + inactive + partially_configured` == `counts.agents.total`. On aggregator compute failure (FR-025) all five keys are emitted as `0` while the v1.0 carry-over `counts.agents.total` may be non-zero, and this equality is intentionally NOT asserted; the `subsystem_degraded` recommendation signals the condition.
- Orthogonality (FR-006): `log-attached + log-detached` == `counts.agents.total` independently; sum of all five MAY exceed `counts.agents.total`.

### `counts.routes.recently_skipped_count` (integer, required)

- Type: non-negative integer.
- Window: counts FEAT-010 route-skip decisions within the most recent `recently_skipped_window_ms` (Research §CW; strict `>` window-edge check — events at exactly the edge are not counted).
- Reset on daemon restart (FR-008): the first post-restart `app.dashboard` returns `0` here regardless of pre-restart history.
- Routing-worker stall/crash (FR-008): the count is decoupled from worker liveness — the daemon keeps returning the **last in-memory ring-buffer state** (it does not zero or omit the field), and the recommendation engine separately emits `subsystem_degraded` for `routing_worker`. Clients MUST treat a non-zero count under that degraded signal as possibly stale.

### `counts.routes.recently_skipped_window_ms` (integer, required)

- Type: fixed integer `300000` (5 minutes; Clarifications Q6). The same value appears as `300_000` in the Python-audience documents (`data-model.md` §RecentlySkippedRoutesWindow, `research.md` §RB) — the two literals are **equivalent**, differing only in the optional underscore separator that JSON does not permit. The daemon constant is `300_000` in source; the wire transmits `300000`.
- Not client-tunable in v1.1; no per-request override.
- v1.x future minors MAY change this value (clients should read it, not hardcode 300000).

### `recommended_next_action` (object | null, required)

- Type: closed-shape object as above, OR `null` when recommendation computation fails (FR-021 / Research §FE).
- `code`: one of the seven closed-set strings in `closed-sets-v1_1.md` §RecommendationCode, evaluated top-to-bottom by the daemon, first match wins.
- `title`: short operator-facing label, ≤ 128 chars. Never null.
- `detail`: longer operator-facing prose, ≤ 512 chars, or `null`. The value is NOT daemon-authored per call — it is fixed per `code` by the templates in `closed-sets-v1_1.md` §RecommendationCode (Per-code title/detail Templates). `detail` is `null` only for codes whose template specifies `null` (currently `all_clear`); all other codes carry their fixed non-null detail.
- `target`: closed-shape sub-object or `null`. The per-code target rule is documented in `data-model.md` §RecommendedNextAction. When the target value would be ambiguous (e.g., multiple unadopted panes), the daemon picks the first per FEAT-011's normative orderings. **`target.id` opacity** (FR-011, Clarifications R1 Q14): `target.id` values are opaque internal identifiers — clients MUST NOT assume any human-readable structure. For entity kinds (`container`/`pane`/`agent`/`route`/`message`/`event`) a client MAY resolve a `target.id` to a display name via the corresponding `app.<entity>.detail` call, or render it opaquely. For `kind == "subsystem"` there is no `app.<entity>.detail` method; the probe-name `target.id` is rendered as-is.
- When `recommended_next_action == null`, the rest of the v1.1 fields are still required and well-typed.

### `recommended_next_action_refreshed_at` (string | null, required)

- Type: ISO-8601 UTC string with millisecond precision (e.g., `"2026-05-24T17:23:45.123Z"`), or `null` when `recommended_next_action == null`.
- The two fields MUST be nulled or populated together — never one without the other (Research §FE).
- Reflects wall-clock time on the daemon host, NOT monotonic time (Research §TS).

## Versioning Behavior

- A daemon advertising `app_contract_version == "1.1"` MUST emit every v1.1 field on every `app.dashboard` response, regardless of `client_app_contract_major` (Clarifications Q10, FR-013).
- A v1.0 client receives the v1.1 fields and ignores unknown keys per FEAT-011's additive-minor rule (FR-012, FR-014).
- A v1.0 daemon advertising `"1.0"` MUST NOT emit any v1.1 field — the new keys appear if and only if the advertised version is ≥ 1.1.
- A v1.1-aware client connecting to a v1.0 daemon receives only the v1.0 fields (no `by_state`, no `recently_skipped_*`, no `recommended_next_action`). Per FEAT-011 FR-033, **every** response — including this `app.dashboard` response and `app.hello` — carries top-level `app_contract_version`; the client adapts its UI from that field (graceful degradation in that direction is the client's responsibility per FEAT-011's additive-minor rules). Reading it at session start from `app.hello` is sufficient under the session-token model, since a daemon restart invalidates the session and forces a fresh `app.hello`.

## Error Behavior

- v1.1 introduces **no new error codes**. The closed set of error codes remains FEAT-011's 27-entry registry.
- Compute failure inside the recommendation engine surfaces as nulls inside a *success* envelope (FR-021), not as a new error code.
- Method-level errors (host-only rejection, session invalid, malformed_request, etc.) are unchanged from v1.0.

## Latency Budget

- FEAT-014's binding dashboard-latency criterion is **SC-006** (spec.md), not FEAT-011's SC-002. SC-006 reframes the budget as **p95 ≤ 500 ms** at the documented FEAT-011 fixture scale (no-cache, ≥ 1 container, ≥ 1 agent; caps ≤ 10 containers / ≤ 200 agents / ≤ 100 routes — Clarifications R1 Q9) and MUST hold with all v1.1 fields populated. Expected additive cost of the four new aggregations plus the recommendation call is < 5 ms at fixture scale (Research §CO).
- The budget is **waived during `subsystem_degraded` states** (Clarifications R1 Q11): slowness during degradation is an expected symptom and the recommendation engine already signals it. The waiver applies to the **p95 ≤ 500 ms assertion** (not asserted while degraded); the per-call `app_dashboard_latency_exceeded` WARN still fires on any >500 ms call as operator telemetry (Research §LB).
- On overrun, the daemon returns the response **best-effort** with every field it could compute and logs a WARN (`app_dashboard_latency_exceeded`) with the measured latency — it does **not** convert the call into an error envelope (FR-027, Clarifications R1 Q10).
