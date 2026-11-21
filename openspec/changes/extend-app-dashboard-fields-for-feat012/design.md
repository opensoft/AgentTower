## Context

`agenttowerd` exposes `app.dashboard` (FEAT-011 v1.0, see
`specs/011-app-backend-contract/contracts/app-methods.md` §`app.dashboard`)
as the single home-view payload a packaged desktop control panel (today
a planned Flutter app, near-term a CLI/TUI surface) calls to render
counts, top-line health, and recent activity without scraping
human-readable CLI output. The v1.0 payload returns:

- `counts.containers.{active, inactive, degraded_scan}`
- `counts.panes.{total, registered, unregistered}`
- `counts.agents.{total, by_role}`
- `counts.log_attachments.{active, degraded, none}`
- `counts.events.{total}`
- `counts.queue.{queued, blocked, delivered, canceled, failed}`
- `counts.routes.{enabled, disabled}`
- `recent.{events, queue, routes}`
- `hints[]`

FEAT-012's FR-012 ("Agent Operations Dashboard") names tiles that this
payload cannot fill:

1. **Pane count by state** — uses a richer 4-state vocabulary
   (`discovered-and-unmanaged`, `discovered-and-registered`,
   `inactive-or-stale`, `discovery-degraded`) than v1.0's flat
   `total / registered / unregistered`.
2. **Registered-agent count by state** — uses a 5-state agent vocabulary
   (`active`, `inactive`, `partially_configured`, `log-attached`,
   `log-detached`) that v1.0's `by_role` cannot express.
3. **Recently-skipped-route count** — a sliding short-window
   (recommended 5 min) counter of FEAT-010 arbitration skips; not
   derivable from v1.0's `routes.{enabled,disabled}` or from any other
   `app.*` read surface today.
4. **Recommended next action** — a daemon-computed nudge keyed by a
   closed set of codes (`no_containers`, `no_panes_discovered`,
   `unadopted_panes_present`, `no_routes_configured`,
   `blocked_queue_drain`, `subsystem_degraded`, `all_clear`).

These gaps were flagged on 2026-05-24 as FEAT-012 review **CRITICAL C8**:
the Dashboard renders zeros against a real daemon today.

Constraints:

- FEAT-011 v1.0 ships under `app_contract_version = "1.0"`. Per FR-035,
  only **additive** changes are allowed within a major; any new field,
  closed-set code, or capability flag MUST land as a minor bump
  (`1.0` → `1.1`), and existing v1.0 readers MUST keep working.
- Per FR-039, optional methods/features are advertised via
  `capability_flags`; new **fields** on existing required methods are
  carried by the `app_contract_version` bump itself, not by a flag.
- The daemon owns all SQLite state, the FEAT-009 queue, the FEAT-010
  route registry, and the FEAT-004 pane-discovery cache. Clients do
  not have direct visibility into any of these; recomputing the
  new buckets client-side would require fetching every list per
  dashboard refresh — unacceptable cost and inconsistent across CLI /
  GUI surfaces.
- No new external dependencies. No new persistence required (the
  sliding-skip window is in-memory, see Decision 4).

## Goals / Non-Goals

**Goals:**

- Land the four new fields (`counts.panes.by_state`,
  `counts.agents.by_state`, `counts.routes.recently_skipped_count` +
  `counts.routes.recently_skipped_window_ms`,
  `recommended_next_action` + `recommended_next_action_refreshed_at`)
  on `app.dashboard` as **optional, additive** v1.1 fields.
- Define and document the closed sets they reference:
  `PaneState`, `AgentState`, and `recommended_next_action.code`.
- Bump `app_contract_version` from `1.0` to `1.1` (FR-035 minor) and
  extend the dispatcher's `supported_minor_range` to `1.0–1.1`.
- Keep the existing v1.0 response shape byte-for-byte. v1.0 readers
  MUST NOT see any removed or renamed field.
- Compute the recommendation server-side so it stays consistent across
  every client surface (current CLI, planned Flutter app, future TUI).

**Non-Goals:**

- Operator-customizable next-action recommendations (the engine is
  daemon-computed and shipping with a fixed rule order; user-supplied
  rules deferred).
- Push-based dashboard updates / live tiles (still poll-based; lands
  with `app.subscribe` if FEAT-011 ever picks that up).
- Persisting the recommended-action history (out of scope; not needed
  for FR-012 rendering).
- New audit events for next-action emission (read-only side effect, no
  state mutation, so nothing audit-worthy per FR-044).
- Changes to FEAT-012's `ContractRegistry.declare("agent_ops/dashboard",
  ContractVersion(1, 0))` — the bump to `(1, 1)` happens in FEAT-012's
  branch once this lands.

## Decisions

### Decision 1 — `recently_skipped_count` lives under `counts.routes` (not `counts.queue`)

A FEAT-010 arbitration skip is conceptually a routing decision (the
queue successfully delivered; the route rejected the delivery for
this master / target pair). It is NOT a queue terminal state. Placing
the count under `counts.queue` would confuse it with the five
FEAT-009 queue states already there.

The recommendation engine's `no_routes_configured` code also lives
in the routing problem-space, so keeping skip telemetry adjacent to
route counts keeps a UI tile and its data source co-located.

Alternative considered: promoting it to `counts.queue.recently_skipped_count`.
Rejected — would force a future reader to know that a "queue skip" is
really a route decision; bad for discoverability.

### Decision 2 — `recommended_next_action_refreshed_at` is a sibling of `recommended_next_action`

When the daemon last recomputed the recommendation matters more than
when the dashboard call returned, because:

- Skip counts and queue state are computed at-request-time; they're
  always fresh.
- The recommendation engine MAY (in a future minor) cache its result
  for a short TTL to avoid recomputing on every dashboard call. The
  refresh timestamp lets the client render "recommended 12 s ago"
  honestly even when the engine cached.

For v1.1 with no caching, `recommended_next_action_refreshed_at`
equals the request-handling time. The field is still emitted so
clients don't break when the caching minor lands.

Alternative considered: embed the timestamp inside `recommended_next_action`
(as `recommended_next_action.refreshed_at`). Rejected — it would be
absent whenever `recommended_next_action` is `null`, forcing clients
to special-case absence; siblings stay present independently.

### Decision 3 — `recommended_next_action.code` rule order is fixed and ranked, not configurable

The engine evaluates rules in a fixed priority order and emits the
**first** matching code. The order is, highest precedence first:

1. `subsystem_degraded` — readiness state is `degraded` or
   `unavailable`. Operator action (fix the subsystem) precedes any
   other action because every other action depends on the subsystem
   being healthy.
2. `no_containers` — `counts.containers.active == 0` AND
   `counts.containers.inactive == 0` AND
   `counts.containers.degraded_scan == 0`.
3. `no_panes_discovered` — at least one active container exists but
   `counts.panes.total == 0`.
4. `unadopted_panes_present` — at least one pane in the
   `discovered-and-unmanaged` state.
5. `blocked_queue_drain` — `counts.queue.blocked > 0`. (Operator must
   approve, delay, or cancel before further automation runs.)
6. `no_routes_configured` — `counts.agents.total > 0` AND
   `counts.routes.enabled == 0`.
7. `all_clear` — none of the above.

The result `target` field, when present, points at the most relevant
entity per code:

| Code | `target.kind` | `target.id` |
|---|---|---|
| `subsystem_degraded` | `subsystem` | the first degraded subsystem name from readiness |
| `no_containers` | (omitted) | (omitted) |
| `no_panes_discovered` | `container` | first active container's id |
| `unadopted_panes_present` | `pane` | first `discovered-and-unmanaged` pane's id (ordered by FEAT-011 `pane.list` default) |
| `blocked_queue_drain` | `queue_message` | oldest blocked `message_id` |
| `no_routes_configured` | (omitted) | (omitted) |
| `all_clear` | (omitted) | (omitted) |

`recommended_next_action` MAY be `null` if the daemon explicitly
declines to make a recommendation (e.g., a future minor adds a "quiet
hours" toggle). At v1.1 a non-null result is always emitted (always
at least `all_clear`).

Alternative considered: allow operator-supplied rules. Rejected for
MVP — adds configuration surface area, divergence between CLI / app
recommendations, and a persistence story. Revisit once a real
operator asks for it.

### Decision 4 — Sliding-window recently-skipped counter is in-memory only

A `collections.deque[float]` keyed by the daemon process holds the
unix-ms timestamps of every FEAT-010 arbitration skip in the last
N ms (`N = 5 * 60 * 1000` at v1.1). On each `app.dashboard` call
the daemon drops timestamps older than `now - N` and returns the
remaining length as `recently_skipped_count`. The actual window in
use is returned as `recently_skipped_window_ms` so a future minor
can change the default without breaking client tile labels.

Why in-memory (vs. persisting to SQLite):

- The window is short (5 min) and the metric is purely a UI nudge;
  a daemon restart resetting the counter to zero is acceptable
  (the post-restart counter will refill within one window).
- Persisting would couple every FEAT-010 skip to a SQLite write,
  raising arbitration latency for no functional benefit.
- The deque has a hard upper bound — even at 1 skip / second
  sustained the window holds 300 entries, well under any RAM
  concern.

Risk: a multi-process daemon (out of MVP scope) would lose
cross-process visibility. Mitigation: noted in Risks below.

### Decision 5 — Both `by_state` maps MUST include every closed-set key when reported

The contract says: when the daemon emits `counts.panes.by_state`, the
map MUST contain a key for every member of `PaneState`, with `0` for
empty buckets. Same for `counts.agents.by_state` and `AgentState`.
The map MAY be `{}` only when the entire field is omitted (i.e., the
daemon is built without the v1.1 fields, which won't happen post-bump
but stays valid for the contract).

Why: a client that gets back `{"discovered-and-unmanaged": 3}` cannot
distinguish "no rows in other states" from "daemon doesn't know about
those states." Forcing every key present makes the rendering code
trivial (`counts.panes.by_state[state] ?? 0` is OK, but the keys are
guaranteed there) and keeps closed-set extensions explicit (new key →
v1.2 minor bump, every v1.1+ daemon emits the full v1.1 key set).

Alternative considered: sparse maps. Rejected — client code becomes
"is this key missing because the daemon is old or because the bucket
is empty?" which defeats the additive-minor model.

### Decision 6 — `PaneState` and `AgentState` are NEW closed sets registered in `closed-sets.md`

Both vocabularies are introduced by this change; nothing in FEAT-011
v1.0 used them. They land in
`specs/011-app-backend-contract/contracts/closed-sets.md` under new
sections, alongside the existing closed sets (agent role, queue state,
container state, hint code). Each new closed set carries the explicit
note: "Adding a new value is an additive minor bump per FR-035; renaming
or removing a value requires a major bump."

The values themselves are taken from the FEAT-012 spec wording:

- `PaneState` = `{discovered-and-unmanaged, discovered-and-registered,
  inactive-or-stale, discovery-degraded}`. Derivation:
  - `discovered-and-unmanaged` — pane row exists with no matching
    `agents.pane_id`.
  - `discovered-and-registered` — pane row exists with a matching
    `agents.pane_id`.
  - `inactive-or-stale` — pane was registered but its container is
    inactive OR its last pane-discovery sighting is older than the
    FEAT-004 staleness threshold.
  - `discovery-degraded` — pane is inside a container in
    `degraded_scan` state (FR-016a). Reserved at v1.1 (see Risk 2).
- `AgentState` = `{active, inactive, partially_configured, log-attached,
  log-detached}`. Derivation:
  - `active` — agent row registered AND its pane is currently
    discovered AND its container is `active`.
  - `inactive` — agent row registered AND (pane no longer discovered
    OR container is `inactive`).
  - `partially_configured` — agent row registered but missing one of
    the required adopt-mode fields (e.g., no `capability`). This is
    rare with FEAT-011's adopt validation and may be `0` at v1.1 in
    practice; the bucket exists for forward compatibility.
  - `log-attached` — agent has an active row in `log_attachments`
    (FEAT-007).
  - `log-detached` — agent has no active row in `log_attachments` (or
    its only attachment is `detached` / `stale` / `superseded`).
  - Note: `log-attached` and `log-detached` are **orthogonal** to
    `active` / `inactive`; the count is a per-state bucket count
    keyed by the **primary** lifecycle state, with `log-attached`/
    `log-detached` reported as additional first-class buckets so the
    sum may exceed `counts.agents.total`. This is intentional and
    documented in `closed-sets.md`.

Alternative considered: collapse `log-attached`/`log-detached` into a
secondary `by_log_state` map. Rejected — FEAT-012's tile renders all
five buckets in one cluster; splitting them into two maps adds two
client-side joins for zero readability win.

### Decision 7 — Contract version bump path

`app_contract_version` becomes `"1.1"` and `supported_minor_range`
becomes `{"min": "1.0", "max": "1.1"}` (FR-010, FR-035 normative).
Three call sites need to change:

1. `app.hello` response builder — return the bumped version + range.
2. The shared `app_contract_version` envelope key (FR-033) — every
   `app.*` response includes the new version string.
3. The dispatcher smoke-test guard (FR-035 Q22 override, SC-029) —
   every method declared at the daemon's `supported_minor_range.max`
   must be wired and answer non-`unknown_method`. At v1.1, the test
   exercises `app.dashboard` and asserts the new fields are present.

No new methods, no new error codes, no `capability_flags` changes
(per FR-039: optional methods need flags, new fields on required
methods do not).

## Risks / Trade-offs

- **[Risk: client treats unknown future `recommended_next_action.code` as fatal]** → Mitigation: spec MUST normatively require clients to render no tile (or fall back to `all_clear` semantics) for unknown codes. Add a contract test that round-trips an unknown code to make sure the daemon doesn't reject it on the way out (defensive, since the daemon controls the value, but cheap to assert).
- **[Risk: `discovery-degraded` pane bucket is always 0 at v1.1]** → Mitigation: same pattern as FEAT-011's reserved `degraded_scan` container state (FR-016a) and reserved `check_container_filter` hint code (FR-014a). The bucket key is present and always `0`; a later minor flips it on once FEAT-004 surfaces per-pane discovery health. Document this in `closed-sets.md`.
- **[Risk: in-memory sliding-skip counter resets on daemon restart]** → Mitigation: accepted. Documented as "post-restart the count refills within one window." Persisting is a future minor if operators complain.
- **[Risk: recommendation rule order disagrees with operator intuition]** → Mitigation: rule order is documented in `contracts/dashboard-next-actions.md` and exercised by per-rule fixture tests. A future minor can re-rank or add codes; clients ignoring unknown codes is already part of the contract.
- **[Risk: sum of `counts.agents.by_state` buckets ≠ `counts.agents.total`]** → Mitigation: intentional (log-attached / log-detached overlap with active / inactive). Documented in `closed-sets.md` AgentState note; contract test asserts the documented relationship rather than equality.
- **[Risk: per-state aggregations slow the dashboard SLA]** → Mitigation: per-state pane counts and per-state agent counts are single-pass GROUP BY queries on already-indexed columns (FEAT-004 `panes.container_id`, FEAT-006 `agents.role` + `agents.pane_id`, FEAT-007 `log_attachments.status`). The dashboard SLA (SC-002 ≤ 500 ms) holds; contract test re-asserts the SLA with the new fields.
- **[Risk: closed-set drift between FEAT-011 v1.1 daemon and FEAT-012 v1.0 client]** → Mitigation: FEAT-012 declares the dashboard contract at `ContractVersion(1, 0)` today, which means it ignores unknown v1.1 fields. After this lands, FEAT-012 bumps to `ContractVersion(1, 1)` to actually consume the new fields — that bump is in FEAT-012's branch, **not** in this proposal's tasks. This proposal's only obligation is to make the new fields safe to ignore.

## Migration Plan

This is an additive minor. No client migration required:

- v1.0 clients keep working byte-for-byte (they never read the new
  optional fields).
- v1.1 clients (FEAT-012 once it bumps) read the new fields.
- Mixed deployments (old client / new daemon, old daemon / new client)
  are explicitly supported by FR-035; no flag day needed.

Rollback strategy: revert the daemon code that emits the new fields;
revert `app_contract_version` to `"1.0"`. No state migration to undo;
no audit rows to back out. The change is in-memory + read-path only.

## Open Questions

- **OQ1** — Should `recently_skipped_window_ms` be tunable per
  deployment (e.g., from `config.yaml`)? Proposal: no for v1.1, hard-coded
  to 5 min. Tunability lands in a later minor if real operators ask.
- **OQ2** — Should the recommendation engine consider the in-flight
  `app.scan.*` state (e.g., suppress `no_panes_discovered` while a
  pane scan is still running)? Proposal: no for v1.1. The dashboard
  is best-effort consistent (FR-018); a refresh after the scan
  completes will flip the recommendation naturally.
- **OQ3** — Should `recommended_next_action.detail` be localized?
  Proposal: no for v1.1; the daemon emits English. FEAT-012 client may
  override per-code locally (the code is the closed-set key the client
  needs; `title`/`detail` are advisory English fallbacks).
