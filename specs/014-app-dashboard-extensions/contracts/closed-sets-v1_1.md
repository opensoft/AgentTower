# Contract: v1.1 Closed Sets

**Created**: 2026-05-24
**Plan**: [../plan.md](../plan.md)
**Companion**: [dashboard-v1_1.md](./dashboard-v1_1.md)

This document is the **canonical** location for every closed-set string the v1.1 dashboard contract introduces. Other docs reference these sets by name; they MUST NOT re-enumerate (Consistency rule, `data-model.md` CHK004–CHK007).

## §PaneState

Values for `counts.panes.by_state` keys (exactly 4, hyphenated, Clarifications Q12):

| Value | Hyphenated |
|---|---|
| 1 | `discovered-and-unmanaged` |
| 2 | `discovered-and-registered` |
| 3 | `inactive-or-stale` |
| 4 | `discovery-degraded` |

Bucket-assignment priority is in `data-model.md` §PaneState. Cross-check invariants vs v1.0 are in `dashboard-v1_1.md` §counts.panes.by_state.

**Future evolution**: v1.x MAY add keys additively; clients ignore unknown per FR-012. v1.x MUST NOT rename, renumber, or remove existing keys. Additive-only — no capability flag required per FR-028 (the new key carries operational meaning but is not an opt-in feature flag).

## §AgentState

Values for `counts.agents.by_state` keys (exactly 5, hyphenated for state vocab + log-state):

| Value | Hyphenated | Partition group |
|---|---|---|
| 1 | `active` | configuration partition |
| 2 | `inactive` | configuration partition |
| 3 | `partially_configured` | configuration partition |
| 4 | `log-attached` | log-attachment partition |
| 5 | `log-detached` | log-attachment partition |

The two partitions are independent (FR-006, FR-020). Sum-of-five MAY exceed total agents.

**Future evolution**: v1.x MAY add keys to either partition additively (e.g., a new configuration-partition bucket alongside `active`/`inactive`/`partially_configured`, or a new log-attachment bucket); clients ignore unknown per FR-012. v1.x MUST NOT rename, renumber, or remove existing keys, and MUST NOT redefine the partition boundary (the configuration partition stays mutually exclusive within itself; the log-attachment partition stays orthogonal). Additive-only — no capability flag required per FR-028.

## §RecommendationCode

Values for `recommended_next_action.code` (exactly 7, snake_case, in precedence order — FR-010):

| # | Code | Operator meaning |
|---|---|---|
| 1 | `subsystem_degraded` | One or more FEAT-011 readiness subsystems are not healthy; investigate before relying on other dashboard signals. |
| 2 | `no_containers` | The daemon sees no bench containers; start a container before doing anything else. |
| 3 | `no_panes_discovered` | Containers exist but no panes have been discovered inside them; check tmux discovery. |
| 4 | `unadopted_panes_present` | Panes are discovered but not yet adopted by an agent; adopt them to unlock routing. |
| 5 | `blocked_queue_drain` | The queue has blocked rows that need operator action (approval / cancellation). |
| 6 | `no_routes_configured` | The catalog has no routes; configure routes to enable arbitration. |
| 7 | `all_clear` | Nothing blocking action; the daemon is operating normally. |

**Evaluation rule** (FR-010, Clarifications precedence note): the daemon evaluates these top-to-bottom against current state; the **first matching code is returned**. When multiple conditions match simultaneously, lower-precedence codes MUST NOT be emitted in place of or alongside the highest-precedence code.

**Future evolution**: v1.x MAY add codes (clients ignore unknown — FR-012). v1.x MUST NOT renumber, rename, or remove existing codes.

### Per-code `title` / `detail` Templates

The daemon emits `title` and `detail` strings per recommendation code from the following **fixed templates**. `{N}` is the per-code count source defined in `data-model.md` §RecommendedNextAction `RecommendationState` (for `unadopted_panes_present`, the unadopted-pane total `unadopted_pane_count` = v1.0 `counts.panes.unregistered`, **not** the `discovered-and-unmanaged` `by_state` bucket — the §PB priority rule can route unregistered panes on degraded/inactive containers into other buckets, so the bucket value can be strictly smaller; for `blocked_queue_drain`, `blocked_queue_count` = v1.0 `counts.queue.blocked`, which has no `by_state` bucket). `{subsystem_name}` is one of the values from §TargetKind's `target.kind == subsystem` row. Templates MUST NOT be altered free-form by daemon implementers — all v1.1 daemons emit identical prose for the same code so two operators observing the same daemon state see identical recommendation text (this is what FR-011 §Per-code title/detail Templates incorporates by reference).

| Code | `title` (≤ 128 chars) | `detail` (≤ 512 chars or `null`) |
|---|---|---|
| `subsystem_degraded` (target non-null — attributed) | `"Subsystem degraded: {subsystem_name}"` | `"The {subsystem_name} subsystem is reporting degraded health. Inspect daemon readiness or the relevant subsystem before relying on other dashboard signals."` |
| `subsystem_degraded` (target null — unattributed, Research §SS) | `"Subsystem health degraded"` | `"One or more readiness subsystems are reporting degraded health, but the specific subsystem could not be attributed. Inspect daemon readiness before relying on other dashboard signals."` |
| `no_containers` | `"No bench containers"` | `"The daemon does not see any bench containers. Start a container (or check Docker connectivity)."` |
| `no_panes_discovered` | `"No panes discovered"` | `"Containers exist but no tmux panes were discovered. Check tmux discovery health and the container's bench user."` |
| `unadopted_panes_present` | `"Unadopted panes need attention"` | `"{N} pane(s) are discovered but not yet registered with an agent. Adopt them to enable routing."` |
| `blocked_queue_drain` | `"Blocked queue rows"` | `"{N} queue row(s) are blocked and need operator action (approve, delay, or cancel)."` |
| `no_routes_configured` | `"No routes configured"` | `"The route catalog is empty. Configure at least one route to enable arbitration."` |
| `all_clear` | `"All clear"` | `null` |

**Substitution rules**:

- `{N}` — the daemon performs integer substitution once per response with the actual count. There is no plural agreement on the wire ("pane(s)" / "row(s)" is literal); clients localize for plural if they wish.
- `{subsystem_name}` — drawn from §TargetKind `target.kind == subsystem` row. When multiple subsystems are degraded, the daemon picks the first in that probe-name order (deterministic per Research §SS).
- `subsystem_degraded` with `target == null` (the unattributed/aggregate case, Research §SS) carries **no** substitution token: it uses the fixed null-target template above verbatim (no `{subsystem_name}`), satisfying the "`title` Never null" rule without inventing a non-closed-set subsystem name.

**Future evolution**: v1.x MAY refine the prose but MUST keep the `code` → `(title template, detail template)` mapping deterministic per-code (no per-call randomness, no localization in v1.x — English only).

## §TargetKind

Values for `recommended_next_action.target.kind` (the v1.0 hint-target closed set + one v1.1 addition):

| Source | Value |
|---|---|
| FEAT-011 v1.0 hint-target closed set | `container` |
| FEAT-011 v1.0 hint-target closed set | `pane` |
| FEAT-011 v1.0 hint-target closed set | `agent` |
| FEAT-011 v1.0 hint-target closed set | `route` |
| FEAT-011 v1.0 hint-target closed set | `message` |
| FEAT-011 v1.0 hint-target closed set | `event` |
| **v1.1 addition** | `subsystem` |

### `target.id` format per `target.kind`

| `target.kind` | `target.id` format |
|---|---|
| `container` | FEAT-003 container id (string). |
| `pane` | FEAT-004 pane id (string). |
| `agent` | FEAT-006 agent id (string). |
| `route` | FEAT-010 route id (string). |
| `message` | FEAT-009 queue message id (string). |
| `event` | FEAT-008 event id (string). |
| `subsystem` (v1.1) | One of the FEAT-011 readiness probe names: `docker`, `tmux_discovery`, `sqlite`, `jsonl`, `routing_worker`, `log_attachment_workers` (Research §SS). When multiple subsystems are degraded, the daemon picks the first one in that order (deterministic). |

**Future evolution**: v1.1's addition of `subsystem` is itself the precedent — v1.x MAY add new `target.kind` values additively (e.g., a new entity type introduced by a future FEAT-* lineage); clients ignore unknown per FR-012. v1.x MUST NOT rename, renumber, or remove existing kinds, and MUST NOT change the `target.id` format for an existing kind. A new `target.kind` value MUST come with a stable `target.id` format spec in the same minor. Additive-only — no capability flag required per FR-028.

## §RecommendationTimestamp

Wire format for `recommended_next_action_refreshed_at`:

- ISO-8601 UTC string with millisecond precision, e.g., `"2026-05-24T17:23:45.123Z"`.
- Clock source: wall clock (`time.time()`-derived). Monotonic time is used internally for window arithmetic (Research §CW) but NOT exposed on this field.
- `null` only when `recommended_next_action == null` (paired nulling — Research §FE).

**Future evolution**: the wire format (ISO-8601 UTC ms) and pairing semantics are frozen for v1.x. v1.x MUST NOT switch to a different timestamp encoding (e.g., epoch ms, Unix-seconds, local-timezone) or break the paired-null invariant. A future minor MAY add a SEPARATE timestamp field for a different surface (e.g., `dashboard_refreshed_at` over the whole envelope) — that would be additive — but MUST NOT redefine this one.

## §AppContractVersion (v1.1)

Wire format unchanged from FEAT-011 v1.0 — `"<major>.<minor>"` string. v1.1 value is the literal string `"1.1"`. The supported-minor-range advertisement now includes `1.1` as the maximum.

**Future evolution**: the wire format (`"<major>.<minor>"` string) is frozen for v1.x. v1.x MUST NOT switch to a different encoding (e.g., integer pair, semver-with-patch, dotted-quad). The `supported_minor_range` advertisement grows additively — the `max` widens as future minors land, `min` stays at `"1.0"` for the v1.x lineage. Major-version rejection behavior (FR-035 / FR-036 / FR-014 — `client_major != APP_CONTRACT_MAJOR` → rejected) is preserved for v1.x; a v2.x bump would be a separate breaking-change PR, not an additive evolution.
