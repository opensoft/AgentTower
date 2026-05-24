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

## §RecommendationTimestamp

Wire format for `recommended_next_action_refreshed_at`:

- ISO-8601 UTC string with millisecond precision, e.g., `"2026-05-24T17:23:45.123Z"`.
- Clock source: wall clock (`time.time()`-derived). Monotonic time is used internally for window arithmetic (Research §CW) but NOT exposed on this field.
- `null` only when `recommended_next_action == null` (paired nulling — Research §FE).

## §AppContractVersion (v1.1)

Wire format unchanged from FEAT-011 v1.0 — `"<major>.<minor>"` string. v1.1 value is the literal string `"1.1"`. The supported-minor-range advertisement now includes `1.1` as the maximum.
