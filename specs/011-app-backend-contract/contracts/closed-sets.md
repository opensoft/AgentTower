# Contract: Closed-Set Enumerations

**Feature**: FEAT-011 — Local App Backend Contract
**App contract version at FEAT-011 ship**: `1.0`

This file is the authoritative inventory of every closed-set enumeration in the `app.*` contract except `error.code` (which lives in `error-codes.md`) and entity-row state vocabularies inherited from upstream features (`container.state`, `pane.*`, `agent.role`, `queue.state`, `log_attachment.status`, `event.event_type`, `event.origin`, `route.*` — those remain owned by the FEAT they originate in).

Every closed set below is additive across minors per FR-035: new values may be appended, existing values may not be removed or renamed without a major bump.

---

## App Contract Version Format

`app_contract_version` is a string `"<major>.<minor>"`. At FEAT-011 ship:

```text
app_contract_version = "1.0"
supported_minor_range = {"min": "1.0", "max": "1.0"}
```

`major` and `minor` are non-negative integers when parsed; the string form is canonical for wire and for `error.details.daemon_app_contract_version`.

`client_app_contract_major` (in `app.hello` request) is an integer ≥ 1. Default 1 if absent.

---

## Top-Level Readiness State (FR-012)

```text
ready | degraded | unavailable
```

Aggregation rule (FR-012, FR-014):

| Subsystems status mix | Top-level `state` |
|---|---|
| Every required subsystem `ok` | `ready` |
| Any required subsystem `degraded` | `degraded` |
| Any required subsystem `unavailable` AND at least one other is `ok` or `degraded` | `degraded` |
| Every required subsystem `unavailable` | `unavailable` |

"No bench containers discovered" is **not** a degraded state — it produces a `start_bench_container` hint while keeping `state == "ready"` (FR-014).

---

## Subsystem Status (FR-012)

```text
ok | degraded | unavailable
```

Per subsystem row. `reason` is `""` when status is `ok`; non-empty short prose otherwise. `hint` is a free-form **subsystem-scoped** string (distinct from the top-level structured `hints[]` array — FR-014a).

---

## Subsystem Names (FR-013)

Required subsystems at v1.0, in the order they appear in `subsystems[]`:

```text
docker
tmux_discovery
sqlite
jsonl
routing_worker
log_attachment_workers
```

Adding a new subsystem in a minor is additive (FR-013 last sentence). Clients MUST ignore unknown subsystem rows (FR-037).

---

## Container State (FEAT-003 + FR-016a)

```text
active | inactive | degraded_scan
```

- `active` — container is up AND its most recent FEAT-004 pane discovery succeeded.
- `inactive` — container is down (FEAT-003 saw it stopped or not present).
- `degraded_scan` — container is up (FEAT-003 succeeded) BUT FEAT-004 pane discovery inside it failed or returned partial data (e.g., `docker exec` failed). FEAT-011-defined addition per FR-016a; reflected in both `app.container.list` row `state` and `app.dashboard.counts.containers.degraded_scan`.

---

## Hint Severity (FR-014a)

```text
info | warning | action_required
```

UI-friendly mapping (recommendation, not normative — the daemon emits the value, the client chooses presentation):

| severity | typical use |
|---|---|
| `info` | "You can do X next" — neutral guidance. |
| `warning` | "Something is suboptimal" — non-blocking. |
| `action_required` | "Daemon cannot do its job without operator action." |

---

## Hint Codes (FR-014a)

Initial v1.0 closed registry:

```text
start_bench_container
check_container_filter
register_first_agent
attach_logs
enable_first_route
docker_unavailable_hint
```

Per-code recommended `severity`:

| `code` | suggested `severity` |
|---|---|
| `start_bench_container` | `action_required` |
| `check_container_filter` | `warning` |
| `register_first_agent` | `info` |
| `attach_logs` | `info` |
| `enable_first_route` | `info` |
| `docker_unavailable_hint` | `action_required` |

The `target` field on a hint is optional; when present it is `{kind, id}`:

```text
kind ∈ {container, pane, agent, route, message, event}
```

---

## Agent Role (FEAT-006, reused)

```text
master | slave | swarm | test-runner | shell | unknown
```

### `role_priority` (FR-021a normative)

```text
master       = 1
slave        = 2
swarm        = 3
test-runner  = 4
shell        = 5
unknown      = 6
```

Used by `app.agent.list` default ordering `(role_priority, registered_at) ASC` (FR-021).

---

## Queue State (FEAT-009, reused — Round-5 corrected)

The shipped FEAT-009 `message_queue.state` CHECK set (`state/schema.py`)
is exactly these **five** values:

```text
queued | blocked | delivered | canceled | failed
```

- `queued` — enqueued and deliverable; the delivery worker will pick it up.
- `blocked` — held; carries a `block_reason` (permission violation,
  kill-switch off, or operator `delay`).
- `delivered` — terminal: the envelope reached the target pane.
- `canceled` — terminal: operator-cancelled (note the single-`l`
  FEAT-009 spelling).
- `failed` — terminal: delivery failed; carries a `failure_reason`.

There is **no** `pending` (it is `queued`), no `in_flight` state
(in-flight is a derived condition — a `queued` row whose
`delivery_attempt_started_at` is set), and no `expired` state.
(Round-5 correction — the earlier `pending/in_flight/expired/cancelled`
vocabulary was wrong; see spec.md Clarifications Session 2026-05-20.)

### `state_priority` (FR-021a normative)

```text
queued     = 1
blocked    = 2
failed     = 3
delivered  = 4
canceled   = 5
```

Operational-first: a live row (`queued`) and an operator-decision row
(`blocked`) sort ahead of terminal rows; among terminal rows `failed`
precedes `delivered` precedes `canceled`.

Used by `app.queue.list` default ordering `(state_priority, enqueued_at) ASC` (FR-021).

---

## Scan State (FR-030c)

```text
running | completed | failed
```

Lifecycle: `running → completed | failed`. v1.0 records remain until FIFO eviction (cap 100). The state on every `app.scan.status` response is exactly the current registry state. `expired` is intentionally absent from the v1.0 closed set; future minors may introduce it with an explicit wall-clock trigger.

---

## Scan Kind (FR-030c)

```text
containers | panes
```

---

## Mutation Origin (FEAT-008 audit, extended)

```text
cli | app | route | system
```

FEAT-011 adds the value `app` (FR-044). Existing FEAT-008..010 origins are preserved.

---

## Capability Flags (FR-039)

At v1.0:

```text
capability_flags = {}
```

The field is always present in `app.hello` but always empty in v1.0. Future minors may add named boolean keys (e.g., `events_subscribe: true`, `managed_pane_create: true`) additively. Clients MUST check the flag before invoking an optional method (FR-039).

---

## Order-By Closed Sets (FR-021)

Each list method accepts an optional `order_by` from a per-surface closed set. The default applied when `order_by` is omitted is the FR-021 / FR-021a normative default.

| List method | `order_by` closed set |
|---|---|
| `app.container.list` | `name`, `first_seen_at`, `last_scanned_at` |
| `app.pane.list` | `default` (the FR-021 composite), `discovered_at`, `last_seen_at` |
| `app.agent.list` | `default` (FR-021/021a composite), `registered_at`, `role` |
| `app.log_attachment.list` | `attached_at`, `last_status_at`, `status` |
| `app.event.list` | `event_id`, `observed_at` |
| `app.queue.list` | `default` (FR-021/021a composite), `enqueued_at`, `last_updated_at` |
| `app.route.list` | `default` (FR-021 composite), `created_at`, `updated_at` |

Each surface's `order_by` accepts an optional direction suffix `:asc` or `:desc` (e.g., `created_at:desc`). Default direction matches the FR-021 default (see plan.md / app-methods.md per-entity table).

Unknown `order_by` value → `validation_failed.details = {field: "order_by", reason: "unknown value"}`.

---

## Filter Operators (FR-024)

All filter fields use **exact match** at v1.0 (no operator vocabulary). Time ranges use `since` / `until` as paired params separately from filter exact-match. `since > until` → `validation_failed`.

Adding new filter fields or relational operators (range, prefix, etc.) is additive (FR-035), but no relational operators ship at v1.0.

---

## Pagination

```text
limit:           int, 1 ≤ limit ≤ 200, default 50           (FR-020a)
cursor_next:     opaque str, ≤ 512 chars, daemon-chosen     (FR-020, FR-020b)
total:           int OR null                                (FR-020)
total_estimate:  int OR null                                (FR-020)
```

Exactly one of `total` / `total_estimate` is non-null per list response. Implementations SHOULD prefer `total` for surfaces where a precise count is cheap (route, container, agent) and `total_estimate` for surfaces where counting is expensive at scale (event, queue history).

`cursor_next` rules (FR-020b):
- Clients MUST treat it as opaque (no parsing, no introspection).
- Hard cap **512 characters**. A value exceeding 512 → `validation_failed.details.field == "cursor_next"`.
- Daemon-chosen encoding (e.g., base64-encoded JSON, signed token).
- Reusing a `cursor_next` produced under one `order_by` / filter combination with a different `order_by` or filter → `validation_failed.details.field == "cursor_next"`.

---

## Recent Limit (FR-017)

```text
recent_limit: int, 1 ≤ recent_limit ≤ 50, default 10
```

Out of bounds → `validation_failed.details = {field: "recent_limit", reason: "out of bounds [1,50]"}`.

---

## Payload Size Caps (FR-003a)

```text
request_line_max_bytes:  1 MiB  =  1,048,576 bytes
response_line_max_bytes: 8 MiB  =  8,388,608 bytes
```

Request overflow → `payload_too_large` with `details = {size_limit_bytes: <enforced limit>, actual_size_bytes: <int>}`. Daemon rejects before handler dispatch.

> **Implementation note (T097):** FEAT-002's socket reader currently enforces an effective **64 KiB** per-line limit (`MAX_REQUEST_BYTES = 65536`), which binds before the 1 MiB contract cap. `size_limit_bytes` reports the value actually enforced (`65536`) until a separate FEAT-002 bump raises the read limit. The 1 MiB figure is the documented contract target. See spec.md FR-003a.

> **`app.send_input` payload sub-cap:** the `payload` object of `app.send_input` carries an additional field-level cap of **16 KiB** (16,384 bytes) on its serialized form → `validation_failed.details = {field: "payload", reason: "too large"}`.

Response overflow is a daemon-side invariant — at v1.0 the pagination cap (`limit ≤ 200`, FR-020a) and recent-limit cap (`recent_limit ≤ 50`, FR-017) keep responses well under 8 MiB. If a handler would build a larger response, the daemon emits `internal_error` rather than serialize an invalid envelope.

---

## Wire Framing (FR-003b)

NDJSON request line strictness (Round-4 Block A):

```text
line_terminator:        \n only (LF)
encoding:               UTF-8
forbidden_bytes:        \r anywhere, \x00 anywhere
trailing_content_rule:  exactly one JSON object per line; no whitespace/garbage after
empty_line:             rejected (no implicit "no-op")
```

Any violation → `malformed_request` with `details.reason ∈ {"stray CR", "embedded NUL", "trailing content", "json decode error", "empty line"}`.

The daemon emits `\n` only on response lines.

---

## Concurrency Caps (FR-008b, FR-030d, FR-030e)

```text
max_concurrent_app_sessions:   8 process-wide   (FR-008b, Round-4 Block D Q29)
max_concurrent_in_flight_scans: 4 across all sessions (FR-030e, Round-4 Block D Q25)
same_kind_scan_coalescing:     enabled — second caller joins existing scan_id (FR-030d, Round-4 Block D Q24)
scan_record_retention:         100 records per daemon process, FIFO eviction (FR-030c)
```

Cap-exceeded responses:

- 9th `app.hello` on a fresh connection → `validation_failed.details = {field: "app.hello", reason: "too_many_sessions"}`.
- 5th in-flight `app.scan.<kind>` → `validation_failed.details = {field: "scan_kind", reason: "too_many_scans_in_flight"}`.

---

## Audit Writer (FR-044, FR-044a, FR-044b, FR-044c)

```text
event_names:              upstream FEAT names byte-for-byte (queue_approved, route_created, agent_registered, …)
origin_marker:            "app" added to existing open-string field
serialization:            process-wide mutex around JSONL writer (FR-044a)
ordering:                 SQLite commit → JSONL write → response envelope sent (FR-044c)
failure_mode:             best-effort; on JSONL unwritable, drop row + stderr warning + readiness flag, mutation still commits (FR-044b)
preflight_hello_audited:  no (Round-4 Block G Q49)
client_id_in_audit:       no (Round-4 Block G Q50)
schema_version_bump:      no — `origin` field is already an open string (Round-4 Block G Q51)
```

---

## Capability Flags Cap (Round-4 Block J Q70)

```text
max_capability_flag_keys: 64
```

Daemon-side invariant. v1.0 ships with `{}` (0 keys), so the cap is forward-looking. Future minors adding flags MUST stay within this cap.

---

## Order-By Direction Syntax (FR-021b)

```text
<field>           = bare field, uses per-surface default direction (FR-021)
<field>:asc       = ascending
<field>:desc      = descending
```

Examples: `created_at`, `created_at:asc`, `created_at:desc`. Any other suffix → `validation_failed.details = {field: "order_by", reason: "<short rule violation>"}`.

---

## Filter Operator Vocabulary at v1.0 (FR-024a)

Exact match only. No `<`, `>`, `<=`, `>=`, `~`, `LIKE`, regex, IN-list, or set-membership operators on filter fields. Time ranges use the paired `since` / `until` unix-ms integer parameters separately from filter exact match. A v1.0 filter value containing operator-like syntax → `validation_failed.details.field == "<offending field>"`.
