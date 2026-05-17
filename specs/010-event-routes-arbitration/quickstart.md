# Quickstart: Event-Driven Routing and Multi-Master Arbitration

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16 | **Plan**: [plan.md](./plan.md)

This quickstart walks an operator through the happy path of
FEAT-010 — creating a route, triggering a matching event, observing
the delivered prompt, and inspecting the audit trail — plus the
two most important "should-not-happen" paths (kill switch off, no
eligible master). It also shows the dev quickstart for running
the FEAT-010 test suites.

## Prerequisites

- `agenttowerd` running on the host (FEAT-001..009 already
  shipped).
- At least one registered active **master** agent (FEAT-006).
- At least one registered active **slave** agent in a bench
  container (FEAT-006).
- FEAT-008 classifier is ingesting events from at least the
  slave's tmux log (`agenttower events --follow` shows entries
  when the slave produces typical log output).
- FEAT-009 kill switch is **enabled** (`agenttower routing status
  --json` shows `routing.enabled = true`).

Verify with:

```bash
agenttower agents list --json | jq '
  [.[] | {agent_id, role, active}]'
agenttower routing status --json | jq .routing.enabled
agenttower events --json --limit 5 | jq '.[] | .event_type'
```

## §1. Operator happy path: route a `waiting_for_input` event

### Step 1 — Create the route

```bash
agenttower route add \
  --event-type waiting_for_input \
  --source-scope any \
  --target-rule explicit \
  --target agt_a1b2c3d4e5f6 \
  --master-rule auto \
  --template 'respond to {source_label}: {event_excerpt}' \
  --json
```

Expected output (JSON object on stdout, exit 0):

```json
{
  "route_id": "11111111-2222-4333-8444-555555555555",
  "event_type": "waiting_for_input",
  "source_scope": {"kind": "any", "value": null},
  "target_rule": "explicit",
  "target_value": "agt_a1b2c3d4e5f6",
  "master_rule": "auto",
  "master_value": null,
  "template": "respond to {source_label}: {event_excerpt}",
  "enabled": true,
  "last_consumed_event_id": 4217,
  "created_at": "2026-05-16T21:30:00.123Z",
  "updated_at": "2026-05-16T21:30:00.123Z",
  "created_by_agent_id": "host-operator"
}
```

Notice `last_consumed_event_id: 4217` — the cursor is set to the
current event-head (FR-002). The route will fire only on events
with `event_id > 4217`.

A corresponding `route_created` JSONL line appears in
`events.jsonl`:

```bash
agenttower events --json --limit 1 | jq '.[0]'
```

```json
{
  "event_type": "route_created",
  "route_id": "11111111-2222-4333-8444-555555555555",
  "created_by_agent_id": "host-operator",
  "emitted_at": "2026-05-16T21:30:00.124Z"
}
```

### Step 2 — Trigger a matching event

Drive the slave's tmux session to produce a `waiting_for_input`
classifier match (the FEAT-008 classifier recognizes patterns
like `>` prompts, `(y/n)` questions, etc.). For testing, the
fastest approach is to run the FEAT-008 fault-injection helper:

```bash
agenttower _testing inject-event \
  --event-type waiting_for_input \
  --source-agent agt_a1b2c3d4e5f6 \
  --excerpt 'Press y to continue'
```

Within one routing cycle (1s default), the route fires.

### Step 3 — Observe the delivered prompt

`agenttower queue --origin route --json | jq` shows the new row:

```json
[
  {
    "message_id": "...",
    "origin": "route",
    "route_id": "11111111-2222-4333-8444-555555555555",
    "event_id": 4218,
    "sender": {
      "agent_id": "agt_aaa000111222",
      "role": "master",
      "label": "primary-master"
    },
    "target": {
      "agent_id": "agt_a1b2c3d4e5f6",
      "role": "slave",
      "label": "slave-1"
    },
    "envelope_body_excerpt": "respond to slave-1: Press y to continue",
    "state": "delivered",
    "enqueued_at": "2026-05-16T21:30:01.456Z",
    "delivered_at": "2026-05-16T21:30:01.512Z"
  }
]
```

The full delivery chain in `events.jsonl`:

```bash
agenttower events --json --limit 10 | jq '
  [.[] | select(.event_type | test("waiting_for_input|route_matched|queue_message_.*"))]
  | sort_by(.event_id // 1e18)'
```

Shows four entries in order:

1. The original `waiting_for_input` (event_id 4218) from FEAT-008.
2. `route_matched` referencing event_id 4218, route_id, the
   `winner_master_agent_id`, the resolved `target_agent_id`, and
   a redacted excerpt.
3. `queue_message_enqueued` with `origin='route'`, route_id, and
   event_id matching.
4. `queue_message_delivered` with the same `message_id`.

### Step 4 — Inspect the route's runtime view

```bash
agenttower route show 11111111-2222-4333-8444-555555555555 --json
```

```json
{
  "route_id": "11111111-2222-4333-8444-555555555555",
  "event_type": "waiting_for_input",
  …,
  "last_consumed_event_id": 4218,
  "runtime": {
    "last_routing_cycle_at": "2026-05-16T21:30:01.500Z",
    "events_consumed": 1,
    "last_skip_reason": null,
    "last_skip_at": null
  }
}
```

## §2. "Should-not-happen" path A: kill switch off

```bash
agenttower routing disable
agenttower _testing inject-event \
  --event-type waiting_for_input \
  --source-agent agt_a1b2c3d4e5f6 \
  --excerpt 'Another prompt'
```

Within one cycle, a NEW queue row appears with
`state='blocked'`, `block_reason='kill_switch_off'`,
`origin='route'`. No tmux paste happens. The route's cursor still
advances (FR-032, Story 5 #1).

```bash
agenttower queue --origin route --state blocked --json | jq '
  [.[] | {message_id, state, block_reason, route_id, event_id}]'
```

Re-enable routing, then approve the blocked row:

```bash
agenttower routing enable
agenttower queue approve <message_id>
```

The row transitions through `ready → delivered` exactly like a
direct-send approval (FEAT-009 plumbing).

## §3. "Should-not-happen" path B: no eligible master

Deactivate every master, then trigger:

```bash
for m in $(agenttower agents list --json | jq -r '.[]
   | select(.role == "master" and .active) | .agent_id'); do
  agenttower agents deactivate $m
done

agenttower _testing inject-event \
  --event-type waiting_for_input \
  --source-agent agt_a1b2c3d4e5f6 \
  --excerpt 'Yet another prompt'
```

Within one cycle, a `route_skipped` JSONL entry appears with
`reason='no_eligible_master'`, `winner_master_agent_id=null`,
`target_agent_id=null`. No queue row is created. The route's
cursor advances past the event (FR-018, Story 3 #4).

```bash
agenttower events --json --limit 5 | jq '
  [.[] | select(.event_type == "route_skipped")][0]'
```

```json
{
  "event_type": "route_skipped",
  "event_id": 4220,
  "route_id": "11111111-2222-4333-8444-555555555555",
  "winner_master_agent_id": null,
  "target_agent_id": null,
  "target_label": null,
  "reason": "no_eligible_master",
  "event_excerpt": "Yet another prompt",
  "emitted_at": "2026-05-16T21:31:00.123Z"
}
```

## §4. Status surface

```bash
agenttower status --json | jq .routing
```

```json
{
  "routes_total": 1,
  "routes_enabled": 1,
  "routes_disabled": 0,
  "last_routing_cycle_at": "2026-05-16T21:31:00.001Z",
  "events_consumed_total": 3,
  "skips_by_reason": {
    "no_eligible_master": 1
  },
  "most_stalled_route": null,
  "routing_worker_degraded": false,
  "degraded_routing_audit_persistence": false
}
```

The heartbeat appears in `events.jsonl` every 60s regardless of
activity:

```bash
agenttower events --json --limit 1 | jq '.[0]'
```

```json
{
  "event_type": "routing_worker_heartbeat",
  "emitted_at": "2026-05-16T21:31:00.123Z",
  "interval_seconds": 60,
  "cycles_since_last_heartbeat": 60,
  "events_consumed_since_last_heartbeat": 3,
  "skips_since_last_heartbeat": 1,
  "degraded": false
}
```

## §5. Cleanup

```bash
agenttower route disable 11111111-2222-4333-8444-555555555555
agenttower route remove 11111111-2222-4333-8444-555555555555
```

`route_deleted` appears in `events.jsonl`. The historical
`route_matched` and `queue_message_*` entries for the deleted
route remain intact — their `route_id` becomes an orphan reference
(FR-003, Edge Cases).

## §6. Dev quickstart: run the FEAT-010 test suites

```bash
# Unit tests (pure functions, no daemon)
pytest tests/unit/test_routing_routes_dao.py \
       tests/unit/test_routing_routes_service.py \
       tests/unit/test_routing_source_scope.py \
       tests/unit/test_routing_template.py \
       tests/unit/test_routing_arbitration.py \
       tests/unit/test_routing_worker.py \
       tests/unit/test_routing_heartbeat.py \
       tests/unit/test_routing_audit.py

# Contract tests (socket + CLI + audit schema)
pytest tests/contract/test_socket_routes.py \
       tests/contract/test_cli_routes.py \
       tests/contract/test_cli_queue_origin_filter.py \
       tests/contract/test_cli_status_routing.py \
       tests/contract/test_route_audit_schema.py

# Integration tests (real daemon + tmux + bench container)
pytest tests/integration/test_routing_end_to_end.py \
       tests/integration/test_routing_arbitration_determinism.py \
       tests/integration/test_routing_crash_recovery.py
```

The integration suite uses the same `bench-test` Docker fixture
as FEAT-008/009. Story 4 (crash recovery) uses the
`_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT` env var to abort
the cursor-advance transaction at a specific point — see
`tests/integration/test_routing_crash_recovery.py` and
`docs/test-fault-injection.md`.

## §7. Common operator pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Route created before the slave's tmux session exists | Route fires, target resolution returns `target_pane_missing`, every event becomes a skip | Register the slave first (FEAT-006), then `route add` |
| `--master-rule explicit --master <inactive>` | Every event becomes a skip with `reason=master_inactive` | Activate the master, or switch to `--master-rule auto` |
| Template references `{unknown_field}` | `route add` exits non-zero with `route_template_invalid`; no row inserted | Use only the FR-008 whitelisted fields |
| Disabled a route, accumulated thousands of matching events, then re-enabled | Backlog drains over `ceil(backlog_size / 100)` cycles (FR-041 default batch cap) | Either accept the latency or tune `--batch-size` on `agenttowerd` (host-side config) |
| Two routes targeting the same slave produce duplicated-looking prompts | Each route inserts its own queue row; per-target FIFO orders them by `enqueued_at` | This is intentional fan-out (FR-015); operator must consolidate selectors if duplicates are unwanted |

## §8. Validation that the spec is satisfied

After running this quickstart, the following spec contracts
should be observable:

- **FR-002**: The new route's `last_consumed_event_id` equals the
  pre-`route add` event head; no historical events were replayed.
- **FR-015**: Adding a second route with the same selector +
  different template produces two queue rows per fired event.
- **FR-029, FR-033**: Every route-generated queue row has
  `origin='route'`, `route_id`, `event_id` populated; the
  `--origin route` filter excludes direct-send rows.
- **FR-035, FR-036**: The route-matched JSONL line carries
  `event_id`, `route_id`, `winner_master_agent_id`,
  `target_agent_id`, `target_label`, `reason: null`, and a
  redacted excerpt.
- **FR-037**: Skip reasons appear only from the closed set
  (`no_eligible_master`, etc.).
- **FR-038**: `agenttower status --json` carries the documented
  `routing` object.
- **FR-039a**: A `routing_worker_heartbeat` JSONL entry appears
  every 60s with the documented field set.
- **SC-001**: Event-to-paste latency ≤ 5s.
- **SC-005**: With kill switch off, 100% of route-generated rows
  land in `blocked`, cursor advances.
- **SC-010**: Re-running the same event sequence on a fresh
  daemon process produces byte-identical FEAT-010 audit + queue
  entries (modulo timestamps).
