# Implementation Plan: Local App Backend Contract for Desktop Control Panel

**Branch**: `011-app-backend-contract` | **Date**: 2026-05-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-app-backend-contract/spec.md`

## Summary

FEAT-011 turns `agenttowerd` into a stable **local-only application backend** for a future packaged desktop control panel. It introduces the `app.*` socket method namespace as a **host-only façade** over the existing newline-delimited JSON Unix socket. Every `app.*` method dispatches into the same daemon-internal service layer used by the existing CLI-facing methods — there is no parallel write path, no new SQLite table, no schema migration, and no new persisted state.

The work splits into **seven additive layers** under a new sub-package `src/agenttower/app_contract/`:

1. **App-session layer** — in-memory per-connection sessions (`app_session_token` uuid v4, monotonic `app_session_id`), invalidated on socket close. No persistence.
2. **Host-only peer gate** — reuses the FEAT-009 host-vs-container peer detection (already required for the routing-toggle host-only rule). Every `app.*` call rejects bench-container peers with the closed-set code `host_only`.
3. **Bootstrap surface** — `app.preflight` (no session required, diagnostic codes only) and `app.hello` (issues the session, returns daemon/schema/contract versions, capability_flags as `{}` at v1.0).
4. **Readiness + dashboard surface** — `app.readiness` (probes docker, tmux_discovery, sqlite, jsonl, routing_worker, log_attachment_workers + structured `hints[]`) and `app.dashboard` (counts + recents + `hints[]`). Both read-only, side-effect-free, no global lock.
5. **Read surfaces** — `app.<entity>.list` / `.detail` for `container`, `pane`, `agent`, `log_attachment`, `event`, `queue`, `route`. Pagination default 50 / cap 200 per FR-020a. Normative `state_priority` / `role_priority` integer mappings per FR-021a back the default orderings.
6. **Mutation surface** — `app.agent.register_from_pane` (adopt-mode façade over FEAT-006 `register-self`), `app.agent.update`, `app.log.attach/detach`, `app.send_input` (with optional `idempotency_key`, FR-031a), `app.queue.approve/delay/cancel`, `app.route.add/remove/update`, `app.scan.containers/panes/status` (with 30s wait cap, FR-030b, and last-100 in-memory retention, FR-030c). Last-write-wins on entity updates (FR-030a); `stale_object` reserved for queue terminal-state guards.
7. **Envelope + error layer** — uniform `{ok, app_contract_version, result}` / `{ok, app_contract_version, error: {code, message, details}}` shapes (FR-033). 25-entry closed-set codes (FR-034) with per-code `details` registry (FR-034a). `details` is always an object, even when `{}`.

The contract is versioned `MAJOR.MINOR = "1.0"`. Within a major, only additive changes; clients ignore unknown fields, daemons ignore unknown request fields. A major mismatch returns `app_contract_major_unsupported` from `app.hello` with both versions in `details`; no session is issued. `capability_flags = {}` at v1.0 (every FEAT-011 method is required and inferred from version support).

The CLI surface (FEAT-002..FEAT-010 methods) is preserved bit-identically. Bench-container thin clients continue to use the legacy namespace; the `app.*` namespace is host-only.

## Technical Context

**Language/Version**: Python 3.11+ (matches existing daemon).
**Primary Dependencies**: existing daemon services from FEAT-002 (socket dispatcher), FEAT-003 (container discovery), FEAT-004 (pane discovery), FEAT-006 (agent registration), FEAT-007 (log attachment), FEAT-008 (event pipeline), FEAT-009 (message queue + permission gate), FEAT-010 (routes catalog). No new third-party Python dependencies are introduced.
**Storage**: In-memory only. No SQLite migration. No JSONL schema bump (the JSONL audit format adds an `origin = "app"` value to its existing `origin` field, which already accommodates string variants). Three in-memory stores added: app-session table, scan-result table (cap 100 per daemon process), per-session idempotency-key dedupe map.
**Testing**: pytest. The target test layout has contract tests under `tests/contract/test_app_*.py` using synthetic Unix-socket clients (no `agenttower` subprocess invocation — see SC-001) and integration tests under `tests/integration/test_story*.py`. The current PR ships a smoke-style equivalent at `tests/unit/test_app_contract_smoke.py` covering the same FRs/SCs at the function-call level; migrating the assertions into the structured `tests/contract/` + `tests/integration/` layout is tracked as tasks T019..T023 and is part of the US1 polish slice. Existing FEAT-002..010 test suite remains untouched.
**Target Platform**: Linux primary; macOS and Windows host targets follow per Assumptions. The daemon is Python; the packaged client is out of scope (FEAT-012). All FEAT-011 work is server-side.
**Project Type**: CLI daemon + structured-API façade. Single Python package (`agenttower`).
**Performance Goals**: SC-002 cold-start-to-dashboard ≤ 500 ms (no-cache, ≥1 container, ≥1 agent fixture); SC-004 adopt round-trip ≤ 2 s; `app.preflight` and `app.hello` < 50 ms (target); `app.readiness` < 100 ms; list/detail < 100 ms at default pagination.
**Constraints**: Local-only — FR-003 forbids any non-Unix-socket listener; SC-006 verifies via packet capture. Host-only `app.*` — FR-042 rejects bench-container peers with `host_only`. Pagination cap 200 (FR-020a). Synchronous scan wait cap 30 s (FR-030b). Per-session idempotency-key store is in-memory only; lost on daemon restart or session close (FR-031a). Per-line payload caps **1 MiB request / 8 MiB response** (FR-003a) — request overflow returns `payload_too_large`; response overflow is a daemon-side invariant guarded by the FR-020a pagination cap. No new persisted secret (FR-043).
**Scale/Scope**: Single-host, single-user. Typical workstation has ≤10 bench containers, ≤200 agents across them, ≤1k events / day, ≤100 routes, a handful of concurrent app sessions (1–3). Pagination tuned for "screenful" UI rendering (default 50). Scan results retained for the last 100 scans per daemon process.

## Constitution Check

*Gate: must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|---|---|---|
| **I. Local-First Host Control** | ✅ PASS | FR-003 forbids network listeners; FR-040/042 preserve socket-permission model and add a host-only restriction on the `app.*` namespace. No durable state outside the existing FEAT-001..010 SQLite/JSONL. |
| **II. Container-First MVP** | ✅ PASS (with note) | FEAT-011 is post-MVP per the brief; it still targets bench containers (the adopt-mode workflow exists to promote tmux panes inside containers). No host-only-tmux or Antigravity work is introduced. |
| **III. Safe Terminal Input** | ✅ PASS | `app.send_input` rides the FEAT-009 queue (FR-031), respects the permission gate and global routing kill switch. Per-message `idempotency_key` (FR-031a) prevents accidental double-delivery; it is not a security boundary. |
| **IV. Observable and Scriptable** | ✅ PASS | Legacy CLI methods unchanged (FR-002); SC-001 asserts the app never log-scrapes. `origin = "app"` + `app_session_id` flow to JSONL audit (FR-009, FR-044, SC-008). `app_session_token` never appears in JSONL (SC-008). |
| **V. Conservative Automation** | ✅ PASS | No workflow decisions added. The façade exposes the same actions a human operator can take from the CLI; no auto-routing, auto-master-promotion, or auto-classification is introduced. |

**Post-design re-check** (after Phase 1 below): unchanged — all gates remain green. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/011-app-backend-contract/
├── plan.md              # This file
├── spec.md              # Feature specification (with Clarifications §Session 2026-05-19, 10 Q/A)
├── research.md          # Phase 0 — open-question resolutions
├── data-model.md        # Phase 1 — entities, view models, closed sets
├── contracts/           # Phase 1 — wire-level contracts
│   ├── app-methods.md     # Per-method request/response shapes (30 methods)
│   ├── error-codes.md     # Closed-set codes + per-code `details` registry
│   └── closed-sets.md     # All other closed enumerations
├── quickstart.md        # Synthetic-client walkthrough for Story 1
├── checklists/          # 16 domain-quality checklists (from /speckit.checklist)
└── tasks.md             # Phase 2 — created by /speckit.tasks, NOT by this command
```

### Source Code (repository root)

FEAT-011 adds a new sub-package `src/agenttower/app_contract/` alongside the existing `routing/`, `agents/`, `panes/`, `events/`, `queue/` packages. **No existing module is renamed, deleted, or rewired.**

```text
src/agenttower/app_contract/
├── __init__.py
├── dispatcher.py            # Registers app.* method handlers with the FEAT-002 dispatcher;
                             # routes every app.* request through host-only gate + session check
├── sessions.py              # In-memory app-session table (uuid v4 tokens, monotonic ids,
                             # connection-scoped lifetime, audit-attribution helpers)
├── host_only.py             # Host-vs-container peer detection — wraps the existing
                             # FEAT-009 mechanism so app_contract has a single import point
├── preflight.py             # app.preflight (no session, diagnostic codes only)
├── hello.py                 # app.hello (issues session, returns versions, capability_flags={})
├── readiness.py             # app.readiness — subsystem probes + state aggregation + hints[]
├── dashboard.py             # app.dashboard — counts + recents + hints[]
├── reads.py                 # app.<entity>.list / .detail (7 entities) — pagination, ordering,
                             # filtering, derived fields (registered, log_attached, pane_active)
├── mutations.py             # app.agent.register_from_pane, app.agent.update, app.log.attach/detach,
                             # app.send_input, app.queue.approve/delay/cancel, app.route.add/remove/update
├── scans.py                 # app.scan.containers/panes/status — wait=true cap, in-memory scan store
                             # capped at last 100, scan_not_found on unknown/evicted scan_id
├── idempotency.py           # Per-session idempotency-key dedupe map for app.send_input
├── envelope.py              # Success/failure envelope builders, app_contract_version stamping,
                             # details registry validation
├── errors.py                # Closed-set error code constants + per-code details schema
├── versioning.py            # MAJOR.MINOR constant, capability_flags={}, major-mismatch check
├── view_models.py           # Read-surface row shapes (container/pane/agent/log_attachment/event/
                             # queue/route view models) with derived fields
└── audit.py                 # JSONL audit emission for app-driven mutations
                             # (origin="app", app_session_id; never the token)

tests/contract/
├── test_app_preflight.py
├── test_app_hello.py
├── test_app_readiness.py
├── test_app_dashboard.py
├── test_app_reads.py                  # list/detail per entity
├── test_app_pagination.py             # FR-020a default/cap/invalid limit
├── test_app_orderings.py              # FR-021/021a normative orderings
├── test_app_adopt.py                  # register_from_pane + races
├── test_app_mutations.py              # update, log.attach/detach, queue, route
├── test_app_send_input.py             # FR-031 + FR-031a idempotency
├── test_app_scans.py                  # wait, timeout, status, retention, scan_not_found
├── test_app_errors.py                 # closed-set registry + details registry
├── test_app_versioning.py             # major mismatch, capability_flags, additive evolution
├── test_app_host_only.py              # bench-container peer rejection
├── test_app_security.py               # no network listener (SC-006), no new secrets
├── test_app_audit.py                  # origin attribution, token redaction
└── test_app_parity.py                 # SC-010 fixture comparison CLI vs app.*

tests/integration/
├── test_story1_dashboard_bootstrap.py # SC-002 cold-start-to-dashboard ≤ 500ms
├── test_story2_adopt_roundtrip.py     # SC-004 ≤ 2s
├── test_story3_operator_actions.py    # queue, route, log, send_input, update flows
├── test_story4_degraded_states.py     # SC-007 every readiness failure mode
└── test_story5_version_drift.py       # SC-005 + SC-009 synthetic clients

tests/fixtures/
├── app_synthetic_client.py            # Bare-metal NDJSON socket client (no agenttower subprocess)
├── app_clock.py                       # Frozen-clock helper for deterministic ordering tests
└── app_peer_simulators.py             # Host vs bench-container peer for host_only tests
```

**Structure Decision**: Single-package extension. The existing `src/agenttower/` package gains one new sub-package (`app_contract/`). No existing module changes shape; the only existing-module touch is FEAT-002's socket dispatcher registering the new `app.*` handlers via `dispatcher.py`'s `register()` entry point. This preserves SC-006 (no other I/O surface), FR-002 (legacy methods unchanged), and FR-004 (app.* dispatches into the same service layer the CLI uses — concretely, `mutations.py` calls `src/agenttower/agents/service.py`, `src/agenttower/routing/service.py`, `src/agenttower/queue/service.py`, etc. directly).

## Complexity Tracking

No constitution violations; this table is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _(none)_  | —          | —                                   |
