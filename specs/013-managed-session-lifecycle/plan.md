# Implementation Plan: Managed Session Creation and Lifecycle

**Branch**: `013-managed-session-lifecycle` | **Date**: 2026-05-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/013-managed-session-lifecycle/spec.md`

## Summary

FEAT-013 adds operator-driven creation of standard multi-agent tmux layouts inside bench containers, on top of the FEAT-001..FEAT-012 stack. The host daemon learns how to:

- Create panes from two MVP templates ("1 master + 2 slaves", "2 masters + 2 slaves") and any operator-defined extension templates (FR-001).
- Auto-register each created pane through the existing FEAT-006 path so it joins the same agent / route / queue / event / health surfaces as adopted panes (FR-004, FR-008).
- Distinguish managed-created from adopted agents at the data-model level (FR-005), with a `predecessor_id` linkage for recreated panes (FR-011).
- Drive a five-state lifecycle (`creating`, `ready`, `degraded`, `failed`, `removed`) and a reserved `promoted_from_adopted` transition that is stubbed in MVP (FR-007, FR-018).
- Serialize layout creation per bench container (FR-019), reject tmux session-name collisions with a specific `managed_session_name_conflict` diagnostic (FR-016), and use a pending-managed marker (tmux pane-title prefix + SQLite column) to keep the FEAT-004 scan from double-registering in-flight panes (FR-014).
- Kill the underlying tmux pane on `remove` while preserving audit history (FR-010, FR-021).
- Survive `agenttowerd` restart by recovering managed-layout records from durable storage and reattaching to surviving tmux panes (FR-020 / SC-008).
- Preserve managed-layout and managed-pane lifecycle event records indefinitely in MVP (FR-021); pruning is a later feature.

The work splits into a new sub-package `src/agenttower/managed_sessions/` plus a single additive SQLite migration adding two tables (`managed_layout`, `managed_pane`) with FKs into the existing agent registry. One new tmux-adapter helper (`tmux_create.py`) composes `new-session` / `split-window` / `kill-pane` invocations through the existing FEAT-004 `docker exec` channel. The app-contract surface (FEAT-011) is extended **additively** with `app.managed_*` methods; the legacy CLI namespace gains a matching `managed_*` set. No FEAT-001..FEAT-012 surface is renamed, deleted, or rewired. **Out of scope for MVP**: non-tmux backends, semantic task planning, cross-host orchestration, adopted-to-managed pane promotion, and cancellation of in-flight layout creation (per spec §FR-018).

> **Provenance**: FR-022 (5-min pending-managed marker TTL), FR-023 (recreate-chain depth ≤ 16), FR-024 (operator YAML overrides), and SC-009 (post-restart visibility ≤ 5s) originated from spec §Clarifications "Session 2026-05-24 (post-plan review)"; their traceability to user stories was confirmed in spec §Clarifications "Session 2026-05-24 (alignment cleanup)" (FR-022 / FR-023 / SC-009 → US3; FR-024 → US1). New FR-025 (capacity ≤ 40 layouts), FR-026 (no-cascade-kill rollback), FR-027 (concurrent-recreate behavior) and amendments to FR-013/015/016/021/024 originate from spec §Clarifications "Session 2026-05-24 (pre-implement walk)".

## Technical Context

**Language/Version**: Python 3.11+ (matches existing daemon).
**Primary Dependencies**: existing daemon services — FEAT-002 (socket dispatcher), FEAT-003 (container discovery), FEAT-004 (tmux pane discovery + `docker exec` channel), FEAT-006 (agent registration), FEAT-007 (log attachment), FEAT-008 (event pipeline + JSONL audit), FEAT-009 (safe-prompt queue / permission gate / host-vs-container peer detection), FEAT-010 (routes catalog), FEAT-011 (`app.*` envelope, error registry, host-only gate). No new third-party Python dependencies are introduced.
**Storage**: SQLite, additive migration only. Two new tables:
  - `managed_layout` — `id` PK, `container_id`, `template_name`, `intended_pane_count`, `state`, `failed_stage NULL`, `idempotency_key NULL`, `created_at`, `updated_at`.
  - `managed_pane` — `id` PK, `layout_id` FK, `container_id` NOT NULL (denormalized from `managed_layout.container_id` at insert; enables per-container label uniqueness without a subquery in the index), `agent_id` FK NULL (filled after FEAT-006 registration), `role`, `capability`, `label`, `launch_command_ref NULL`, `tmux_session_name`, `tmux_pane_index`, `pending_marker_token NULL`, `state`, `failed_stage NULL`, `predecessor_id` self-FK NULL, `chain_depth INTEGER NOT NULL DEFAULT 0`, `created_at`, `updated_at`.
  Unique constraint: `UNIQUE(container_id, label) WHERE state IN ('creating','ready','degraded')` (label scope per FR-003 / Q4). Indexes on `state`, `predecessor_id`, `pending_marker_token`. **No existing table is altered.** Pending-managed marker lives in `managed_pane.pending_marker_token` **and** is mirrored to the tmux pane title as `@MANAGED:<token>:<label>` so the FEAT-004 scan can detect it through the existing `list-panes` formatter (research §R1, FR-014).
**Testing**: pytest. Contract tests under `tests/contract/test_managed_*.py` using the FEAT-011 synthetic Unix-socket client (no `agenttower` subprocess invocation). Integration tests under `tests/integration/test_story{1,2,3}_*.py` covering US1/US2/US3 acceptance scenarios. Adapter-level unit tests for the tmux-command composer. Failure-injection harness for partial-failure / restart-recovery flows (`tests/integration/test_managed_recovery.py`).
**Target Platform**: Linux primary; macOS host targets follow per the existing AgentTower assumptions. All FEAT-013 work is server-side. UI surfaces (e.g. control-panel wizard) are FEAT-012/014's domain.
**Project Type**: CLI daemon (single Python package `agenttower`).
**Performance Goals**: SC-001 layout-create p95 ≤ 120s on a healthy bench (≤4 panes); SC-003 log-attach failure visible ≤ 10s after layout completion (the failure event is enqueued synchronously inside the create-layout response path); SC-008 daemon-restart reattach ≤ 5s for ≤4 layouts (recovery runs once at boot, before the socket starts accepting requests); SC-009 post-restart recovery-outcome visibility ≤ 5s via M3/M5 detail surfaces (no log inspection required); FR-013 per-stage timeout 30s with 2x transient retry at 1s/2s back-off; FR-022 pending-managed marker TTL 5 minutes with periodic 60s sweep (research §R5); FR-023 recreate-chain depth bounded at 16 (research §R4); FR-025 capacity ≤ 40 concurrent managed layouts per daemon; per-container serializer waits are FIFO with no upper bound on wait time (a stuck create surfaces via the operator-facing `creating` state, not via a queue timeout — research §R2).
**Constraints**: Local-only — FR-017 forbids any non-Unix-socket listener, preserved from FEAT-011 SC-006. Host-only `app.managed_*` — reuse FEAT-011's bench-container peer gate (`host_only` rejection). Bench-container thin clients may invoke the legacy `managed.*` CLI namespace **only for operations that target their own container** (peer-detected). Launch commands are passed as **argv** to tmux `new-session` / `split-window` (no shell `-c`) wherever the tmux command surface allows it; otherwise arguments are escaped via `shlex.quote`. Per-container serialization: `asyncio.Lock` map keyed by `container_id`, FIFO via `asyncio.Queue` (research §R2). Recreate-chain depth bounded at 16 (FR-023, research §R4). Operator template / launch-profile overrides are loaded from canonical YAML paths under `~/.config/opensoft/agenttower/` (FR-024). No new persisted secret (FR-017).
**Scale/Scope**: Single-host, single-user. Typical workstation: ≤10 bench containers, ≤4 managed layouts per container, ≤4 panes per layout in MVP (template-defined). Pending-managed marker store sized at ≤4 in-flight per daemon (mirrors the FEAT-011 scan-coalesce cap). Indefinite audit retention (FR-021) bounded operationally by 16-deep recreate chains × ≤4 layouts × ≤10 containers ≈ low-thousands of records / week — comfortably within JSONL's append-only model.

## Constitution Check

*Gate: must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|---|---|---|
| **I. Local-First Host Control** | ✅ PASS | No new network listener (FR-017). Durable state lives in the existing SQLite under `~/.local/state/opensoft/agenttower/`; no new top-level dirs. Operator templates and launch profiles live under `~/.config/opensoft/agenttower/` (matches the constitution's path conventions — research §R8/R9). `app.managed_*` is host-only via the FEAT-011 gate. Thin-client `managed.*` calls are scoped to the caller's own container by peer detection. |
| **II. Container-First MVP** | ✅ PASS | Targets bench containers and tmux panes inside them. No host-only-tmux, no Antigravity, no Python-thread backends, no mailbox adapters. Tmux is invoked via `docker exec` through the existing FEAT-004 channel. |
| **III. Safe Terminal Input** | ✅ PASS | Operator-supplied launch commands are passed as argv to `tmux new-session <cmd...>` / `tmux split-window <cmd...>`; `send-keys` is **not** used for the first-line command (research §R6). When shell context is unavoidable (operator env-merge), arguments are escaped via `shlex.quote`. Launch commands are operator-configured one-shot spawns; they are not "prompts" and do not traverse the FEAT-009 prompt queue. The pending-managed marker prevents double-spawn under retry. |
| **IV. Observable and Scriptable** | ✅ PASS | Every action is reachable from the CLI (`managed.*` namespace mirrors `app.managed_*`). SQLite stores managed_layout / managed_pane current state; JSONL audit stores lifecycle events indefinitely (FR-021). Each failure produces an actionable diagnostic per FR-013 / FR-016 (closed-set error code + `failed_stage` enum + recovery hint). |
| **V. Conservative Automation** | ✅ PASS | No workflow decisions are added. The operator initiates create / remove / recreate; AgentTower does not auto-classify failures, auto-recreate, or auto-promote adopted panes. The reserved `promoted_from_adopted` transition is explicit operator action in a later feature; it is stubbed as `not_implemented` in MVP. |

**Post-design re-check** (after Phase 1 below): unchanged — all gates remain green. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/013-managed-session-lifecycle/
├── plan.md              # This file (/speckit.plan command output)
├── spec.md              # Feature specification (Clarifications §Session 2026-05-24, 15 Q/A)
├── research.md          # Phase 0 — research decisions for the 13 open questions
├── data-model.md        # Phase 1 — entities, SQLite DDL, state machine, closed sets
├── contracts/           # Phase 1 — wire-level contracts
│   ├── managed-methods.md   # CLI legacy + app.managed_* method shapes
│   ├── state-machine.md     # Formal lifecycle transition graph
│   └── error-codes.md       # New closed-set additions
├── quickstart.md        # Phase 1 — synthetic-client walkthrough for US1
├── checklists/          # 15 release-gate checklists (from /speckit.checklist deep-and-wide)
└── tasks.md             # Phase 2 — created by /speckit.tasks, NOT by this command
```

### Source Code (repository root)

FEAT-013 adds a new sub-package `src/agenttower/managed_sessions/` alongside the existing `routing/`, `agents/`, `panes/`, `events/`, `queue/`, `app_contract/` packages. **No existing module is renamed, deleted, or rewired.** The only existing-module touches are (1) FEAT-002's socket dispatcher registering the new legacy `managed.*` handlers, and (2) FEAT-011's `app_contract/dispatcher.py` registering the new `app.managed_*` handlers.

```text
src/agenttower/managed_sessions/
├── __init__.py
├── service.py              # Orchestrates create-layout / remove-pane / recreate-pane;
│                           #   owns the state machine and the per-container serializer
├── state_machine.py        # Five-state transition table (creating/ready/degraded/failed/removed)
│                           #   + transition validators; reserved promoted_from_adopted stub
├── templates.py            # Built-in template registry (1m+2s, 2m+2s); YAML loader for
│                           #   operator overrides under ~/.config/opensoft/agenttower/managed_templates/
├── launch_profiles.py      # YAML loader for ~/.config/opensoft/agenttower/launch_commands/*.yaml
├── tmux_create.py          # Composes tmux new-session/split-window/kill-pane through the
│                           #   FEAT-004 docker-exec channel; argv-first; shlex.quote fallback
├── pending_marker.py       # Writes/reads/clears the @MANAGED:<token> tmux pane-title prefix
│                           #   AND the SQLite pending_marker_token column; 5-minute TTL sweep
├── serializer.py           # asyncio.Lock map keyed by container_id; FIFO waiter queue
├── recovery.py             # Boot-time reconcile: load managed_layout/managed_pane, list-panes
│                           #   from tmux, reattach by tmux_session_name + tmux_pane_index;
│                           #   GC stale pending-managed markers
├── handlers/
│   ├── cli.py              # Legacy CLI namespace: managed.layout.create / managed.pane.remove / ...
│   │                       #   Peer-detection: thin-client callers may only target own container
│   └── app.py              # app.managed_* methods registered via FEAT-011 dispatcher; host-only
├── view_models.py          # Row shapes for managed_layout / managed_pane list/detail surfaces
├── events.py               # FEAT-008-pipeline emitters: managed_layout_*, managed_pane_*
├── errors.py               # Closed-set additions: managed_session_name_conflict,
│                           #   managed_layout_not_found, managed_pane_not_found,
│                           #   managed_pane_recreate_chain_too_deep, managed_pane_protected_adopted,
│                           #   managed_template_not_found
└── migration.py            # SQLite migration registration

migrations/00NN_managed_sessions.sql        # SQLite DDL for managed_layout + managed_pane

tests/contract/
├── test_managed_layout_create.py            # FR-001/002/003/019; managed_session_name_conflict
├── test_managed_pane_remove.py              # FR-010 + tmux kill-pane
├── test_managed_pane_recreate.py            # FR-011 + predecessor_id chain + chain_depth bound
├── test_managed_state_machine.py            # FR-007 transitions; illegal transitions rejected
├── test_managed_pending_marker.py           # FR-014 marker set/cleared; FEAT-004 scan ignores
├── test_managed_serializer.py               # FR-019 per-container FIFO; cross-container parallel
├── test_managed_log_attach_failure.py       # FR-006 → degraded; SC-003 10s visibility
├── test_managed_launch_failure.py           # Immediate-exit → degraded
├── test_managed_recovery.py                 # FR-020 reattach; SC-008 no operator intervention
├── test_managed_recovery_visibility.py      # SC-009 ≤5s post-restart visibility via M3/M5 detail surfaces (recovery_reattach failed_stage readable without log inspection)
├── test_managed_protect_adopted.py          # FR-012; adopted pane not removable via managed path
├── test_managed_templates.py                # FR-001 templates; YAML override merge
├── test_managed_launch_profiles.py          # FR-002 + FR-024 launch profile YAML; R9 argv-shape; managed_launch_command_not_found
├── test_managed_migration.py                # T007 migration idempotency smoke (CREATE ... IF NOT EXISTS; second-run no-op)
└── test_managed_promote_stub.py             # FR-018; not_implemented response shape

tests/integration/
├── test_story1_create_standard_layout.py    # US1 acceptance — 1m+2s and 2m+2s
├── test_story2_auto_prepare_operations.py   # US2 acceptance — managed in same surfaces as adopted
├── test_story3_lifecycle_operations.py      # US3 acceptance — remove + recreate + adopted protection
└── test_managed_edge_cases.py               # Edge Cases section bullets

tests/fixtures/
├── managed_template_fixtures.py             # canonical 1m+2s, 2m+2s templates
├── managed_clock.py                         # frozen clock for state-transition tests
└── managed_tmux_recorder.py                 # Records tmux command sequences for assertions
```

**Structure Decision**: Single-package extension. The existing `src/agenttower/` package gains one new sub-package (`managed_sessions/`). FEAT-011's `app_contract/dispatcher.py` registers the new `app.managed_*` handlers from `managed_sessions/handlers/app.py`. The FEAT-002 socket dispatcher registers the new legacy `managed.*` handlers from `managed_sessions/handlers/cli.py`. FEAT-004's `docker exec` adapter is reused for tmux command issuance via `tmux_create.py`. SQLite migration is the single point of schema change; **no existing table is altered**. This preserves FR-008 (managed agents reuse adopted-agent surfaces), Principle II (container-first), and the FEAT-011 contract additive-evolution rule.

## Complexity Tracking

No constitution violations; this table is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _(none)_  | —          | —                                   |
