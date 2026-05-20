# Phase 1 Data Model: Local App Backend Contract (FEAT-011)

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Research**: [research.md](./research.md)

FEAT-011 introduces **no persistent storage changes**. No new SQLite tables. No schema-version bump. No JSONL schema bump. The contract is a façade over the existing FEAT-001..010 service layer; durable state continues to live in the same tables/files those features own.

The new state lives **in memory only** as three short-lived registries and a set of read-only view models composed from existing data.

---

## In-Memory Entities

### 1. App Session

Per-connection identity issued by `app.hello`. Cleared when the underlying socket connection closes (FR-008). Never persisted (FR-006).

| Field | Type | Source | Description |
|---|---|---|---|
| `app_session_token` | `str` (uuid v4 hex, 36 chars) | generated on `app.hello` | Opaque, returned to client, redacted from logs (FR-009, SC-008) |
| `app_session_id` | `int` (monotonic ≥ 1) | daemon-internal counter | Audit-friendly; emitted in JSONL via `origin == "app"` rows |
| `client_id` | `str` (optional, ≤ 128 chars) | echoed from `app.hello` request | Informational, no auth role |
| `client_version` | `str` (optional, ≤ 64 chars) | echoed from `app.hello` request | Informational |
| `client_app_contract_major` | `int` (≥ 1) | request param, default 1 | Used for FR-036 major-mismatch check |
| `connection_id` | `int` | dispatcher handle | Owning connection; closure → invalidation |
| `host_user_id` | `str` (numeric UID as string) | resolved from SO_PEERCRED at accept | Returned in `app.hello`; matches host UID (FR-041) |
| `connection_started_at` | `int` (unix ms) | accept time | Audit, ordering |

**Lifecycle**: `created → invalidated` (terminal). No mid-lifetime transitions. Creation requires `app.hello`; invalidation triggers on connection close, daemon shutdown, or daemon-side error that closes the connection.

---

### 2. Scan Record

In-memory result store for `app.scan.containers` and `app.scan.panes` (FR-030c). Bounded at the last **100** scans per daemon process; FIFO eviction. Lost on daemon restart.

| Field | Type | Description |
|---|---|---|
| `scan_id` | `str` (uuid v4 hex) | Stable id returned to clients waiting / polling |
| `scan_kind` | `enum {"containers", "panes"}` | Which scan was issued |
| `state` | `enum {"running", "completed", "failed"}` | Lifecycle state (FR-030c v1.0 — `expired` is intentionally absent) |
| `started_at` | `int` (unix ms) | Set when scan worker accepts the job |
| `completed_at` | `int \| null` | Populated when `state ∈ {completed, failed}` |
| `result` | `object \| null` | Mirrors the `wait=true` post-scan summary when terminal; `null` while running |
| `issued_by_app_session_id` | `int` | Audit attribution (no token) |

**State transitions**: `running → completed` (normal), `running → failed` (scanner exception, captured in `result.error`). Eviction (FIFO at the 100-record cap) removes the record entirely; subsequent `app.scan.status` with that `scan_id` → `scan_not_found`. A future minor may introduce additional states (e.g., `expired` tied to wall-clock TTL) per FR-030c.

---

### 3. Idempotency Entry

Per-session dedupe map for `app.send_input` (FR-031a). Scope is `(app_session_id, idempotency_key)`. Cleared with the session.

| Field | Type | Description |
|---|---|---|
| `idempotency_key` | `str` (caller-supplied, ≤ 256 chars) | Map key |
| `message_id` | `str` | The original queue row id; replayed on duplicate |
| `deduplicated_response` | `object` | The full success envelope returned by the first call; replayed verbatim with `deduplicated: true` appended |
| `created_at` | `int` (unix ms) | LRU eviction support |

**Cap**: 256 entries per session, LRU eviction. No wall-clock TTL.

---

## Read-Only View Models

These are **response shapes** assembled from existing service-layer DAOs at read time. They are not stored; they are projected. Each row is a fresh dict built from the underlying SQLite row(s) by `view_models.py`. The DAOs that feed them are the same ones the CLI methods use (FR-004).

### ContainerViewModel

Source: FEAT-003 `containers` rows.

| Field | Type | Derived? | Description |
|---|---|---|---|
| `container_id` | `str` | no | Docker container ID prefix as stored |
| `name` | `str` | no | Container name |
| `state` | `enum {"active", "inactive", "degraded_scan"}` | yes | FR-016 bucket; computed from FEAT-003 row + last-scan health |
| `created_at` | `int (unix ms)` | no | From row |
| `last_seen_at` | `int (unix ms)` | no | From row |
| `image` | `str` | no | From row |
| `pane_count` | `int` | yes | Count of `panes` rows where `container_id` matches |
| `registered_agent_count` | `int` | yes | Count of `agents` rows matching panes in this container |

### PaneViewModel

Source: FEAT-004 `panes` rows + FEAT-006 `agents` rows.

| Field | Type | Derived? | Description |
|---|---|---|---|
| `pane_id` | `str` | no | tmux pane identity |
| `container_id` | `str` | no | Owning container |
| `container_name` | `str` | yes | Joined from containers |
| `tmux_socket` | `str` | no | From row |
| `session_name` | `str` | no | From row |
| `window_index` | `int` | no | From row |
| `pane_index` | `int` | no | From row |
| `registered` | `bool` | yes (FR-022) | True iff a non-deleted `agents` row links to this pane |
| `agent_id` | `str \| null` | yes (FR-022) | The linked agent's id when registered; null otherwise |
| `discovered_at` | `int (unix ms)` | no | From row |
| `last_seen_at` | `int (unix ms)` | no | From row |

### AgentViewModel

Source: FEAT-006 `agents` rows + FEAT-007 `log_attachments` rows + FEAT-004 `panes` row.

| Field | Type | Derived? | Description |
|---|---|---|---|
| `agent_id` | `str` | no | From row |
| `role` | `enum {"master","slave","swarm","test-runner","shell","unknown"}` | no | FEAT-006 closed set |
| `capability` | `str` | no | From row |
| `label` | `str` | no | From row |
| `project_path` | `str \| null` | no | From row |
| `parent_agent_id` | `str \| null` | no | From row |
| `container_id` | `str` | no | Via pane join |
| `pane_id` | `str` | no | From row |
| `registered_at` | `int (unix ms)` | no | From row |
| `log_attached` | `bool` | yes (FR-023) | True iff a `log_attachments` row exists for this agent |
| `pane_active` | `bool` | yes (FR-023) | True iff the linked pane was seen on the most recent scan |

### LogAttachmentViewModel

Source: FEAT-007 `log_attachments` rows.

| Field | Type | Derived? | Description |
|---|---|---|---|
| `agent_id` | `str` | no | Owning agent |
| `attached_at` | `int (unix ms)` | no | From row |
| `last_output_at` | `int (unix ms) \| null` | no | From row |
| `bytes_written` | `int` | no | From row |
| `status` | `enum {"active", "degraded", "stopped"}` | no | From row |

### EventViewModel

Source: FEAT-008 `events` rows (JSONL-backed or SQLite mirror, per FEAT-008).

| Field | Type | Description |
|---|---|---|
| `event_id` | `int` | Monotonic |
| `event_type` | `str` | From FEAT-008 closed set |
| `origin` | `str` | From row (now includes `"app"` as a permitted value) |
| `created_at` | `int (unix ms)` | From row |
| `agent_id` | `str \| null` | Subject agent |
| `payload` | `object` | Full payload as stored |
| `summary` | `str` | Short rendering for "Recent activity" rows (≤ 256 chars) |

### QueueViewModel

Source: FEAT-009 `message_queue` rows. Field list corrected in Round-5
(2026-05-20) to match the shipped FEAT-009 schema — the earlier model
named `origin` / `route_id` / `event_id` columns that do not exist on
`message_queue`, used a wrong `state` vocabulary, and used
`source_agent_id` / `created_at` names that the row spells
`sender_agent_id` / `enqueued_at`.

| Field | Type | Description |
|---|---|---|
| `message_id` | `str` | From row |
| `state` | `enum {"queued","blocked","delivered","canceled","failed"}` | FEAT-009 `message_queue.state` closed set |
| `state_priority` | `int (1..5)` | Derived per FR-021a (`queued=1, blocked=2, failed=3, delivered=4, canceled=5`) |
| `block_reason` | `str \| null` | From row; non-null only when `state == "blocked"` |
| `failure_reason` | `str \| null` | From row; non-null only when `state == "failed"` |
| `sender_agent_id` | `str` | From row |
| `target_agent_id` | `str` | From row |
| `payload_preview` | `str` | Redacted preview of `envelope_body` (FEAT-009 redaction rules); the raw body bytes are NOT exposed |
| `enqueued_at` | `int (unix ms)` | From row |
| `last_updated_at` | `int (unix ms)` | From row |

Dropped vs. the pre-Round-5 model: `origin`, `route_id`, `event_id`
(no such columns on `message_queue`). Renamed: `source_agent_id` →
`sender_agent_id`; `created_at` → `enqueued_at`; `payload` (structured
object) → `payload_preview` (redacted string, since the row stores raw
`envelope_body` bytes).

### RouteViewModel

Source: FEAT-010 `routes` rows.

| Field | Type | Description |
|---|---|---|
| `route_id` | `str` | From row |
| `enabled` | `bool` | From row |
| `source_scope` | `object` | FEAT-010 source-scope dict |
| `template` | `object` | FEAT-010 template dict |
| `target` | `object` | FEAT-010 target dict |
| `last_consumed_event_id` | `int \| null` | From row |
| `created_at` | `int (unix ms)` | From row |
| `last_used_at` | `int (unix ms) \| null` | From row |

---

## Closed Sets (Normative)

### App contract version

`app_contract_version = "1.0"` at FEAT-011 ship.

### Top-level readiness state

```text
ready | degraded | unavailable
```

### Subsystem status

```text
ok | degraded | unavailable
```

### Subsystem names (FR-013)

```text
docker | tmux_discovery | sqlite | jsonl | routing_worker | log_attachment_workers
```

### Hint severity (FR-014a)

```text
info | warning | action_required
```

### Hint codes (FR-014a)

```text
start_bench_container | check_container_filter | register_first_agent | attach_logs | enable_first_route | docker_unavailable_hint
```

### Agent role (FEAT-006, reused)

```text
master | slave | swarm | test-runner | shell | unknown
```

### `role_priority` (FR-021a normative)

```text
master = 1
slave = 2
swarm = 3
test-runner = 4
shell = 5
unknown = 6
```

### Queue state (FEAT-009, reused — Round-5 corrected)

```text
queued | blocked | delivered | canceled | failed
```

The shipped FEAT-009 `message_queue.state` CHECK set. There is no
`pending` (it is `queued`), no `in_flight` state (in-flight is a
derived condition — a `queued` row with `delivery_attempt_started_at`
set), and no `expired` state.

### `state_priority` (FR-021a normative)

```text
queued    = 1
blocked   = 2
failed    = 3
delivered = 4
canceled  = 5
```

### Scan state (FR-030c)

```text
running | completed | failed
```

`expired` is intentionally absent from the v1.0 closed set; a future minor may introduce it with an explicit wall-clock trigger.

### Scan kind (FR-030c)

```text
containers | panes
```

### Mutation origin (FEAT-008 audit, reused)

```text
cli | app | route | system
```

### Capability flags at v1.0 (FR-039)

```text
{}  (empty object, no flags advertised)
```

### Error codes (FR-034)

See [contracts/error-codes.md](./contracts/error-codes.md) for the closed set of 25 codes and their per-code `details` registry.

---

## Validation Rules (cross-FR)

Rules that span multiple entities, captured here as the system-of-record:

- **Session lifetime**: An `App Session` exists iff its owning connection is open. Closing the connection invalidates the session immediately (FR-008). Reconnect requires a new `app.hello`.
- **Token never persisted, never logged**: `app_session_token` MUST NOT appear in any JSONL row (SC-008). Only `app_session_id` is durable in the audit trail.
- **Adopt parity**: An agent row created by `app.agent.register_from_pane` MUST be byte-for-byte identical (modulo `origin`/`app_session_id` metadata in the audit trail) to one created by CLI `register-self` for the same pane (SC-004, SC-010).
- **Pagination bounds**: Every `app.<entity>.list` call validates `1 ≤ limit ≤ 200`, default 50 (FR-020a). Out of bounds → `validation_failed` with `details.field == "limit"`.
- **Mutation post-state**: Every mutation response carries the full post-mutation row of the affected entity (FR-030, FR-030a). The post-state is a fresh read after commit, not the request payload echoed back.
- **Idempotency scope**: `(app_session_id, idempotency_key)` is the unique key for `app.send_input` dedupe (FR-031a). The same `idempotency_key` from two different sessions are independent.
- **Host-only**: Every `app.*` call (including `app.preflight` and `app.hello`) rejects bench-container peers with `host_only` (FR-042). The check runs at the dispatcher gate, before any handler executes.
- **Closed-set codes only**: `error.code` matches `^[a-z][a-z0-9_]*$` AND is in the FR-034 registry. Contract test asserts both regex and membership (SC-003).
- **`details` is always an object**: `error.details` is never `null`, never an array, never a primitive (FR-033). For codes without registry entries, `details == {}`.
- **Payload size caps**: Single NDJSON request line ≤ **1 MiB** (FR-003a); overflow → `payload_too_large` with `details = {size_limit_bytes: 1048576, actual_size_bytes}`. Single NDJSON response line ≤ **8 MiB**; daemon-side invariant guarded by pagination/recent_limit caps.
- **`agent.update` field semantics** (FR-029a): absent field = no change; empty string clears only `project_path` and `label`; empty string on `role`/`capability` → `validation_failed.details.field == "<role|capability>"`.
- **`log.detach` idempotency** (FR-029b): detaching a never-attached log returns success with `log_attached: false` in the post-state row. No closed-set error code is emitted for the "already detached" case.
- **`order_by` direction syntax** (FR-021b): every `app.<entity>.list` accepts `field`, `field:asc`, or `field:desc`. Bare field uses the per-surface default direction.
- **Filter operators** (FR-024a): exact-match only at v1.0. No relational, prefix, regex, or set-membership operators.
- **`cursor_next` format** (FR-020b): opaque string, ≤ 512 chars, daemon-chosen encoding. Clients pass it back verbatim. Malformed, oversized, or order/filter-mismatched cursors → `validation_failed.details.field == "cursor_next"`.
- **`degraded_scan` container semantics** (FR-016a): container counts as `degraded_scan` iff FEAT-003 container discovery succeeded AND FEAT-004 pane discovery inside the container failed/returned partial data. Distinct from `inactive` (container down) and `active` (container up + pane scan complete).
- **`unknown_method` uniform behavior** (FR-034b): any `app.*` method name not implemented at the daemon's current minor → `unknown_method` with `details == {}`. No daemon state mutation; clients differentiate future-minor methods by reading `capability_flags` before invoking.
- **FEAT-008 `event_id` monotonicity** (Assumption): `event_id` is monotonically non-decreasing within a daemon process. FR-021's `events by event_id DESC` default ordering and SC-016 normative ordering tests depend on this upstream invariant.
