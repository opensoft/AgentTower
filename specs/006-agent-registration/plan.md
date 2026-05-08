# Implementation Plan: Agent Registration and Role Metadata

**Branch**: `006-agent-registration` | **Date**: 2026-05-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-agent-registration/spec.md`

## Summary

Implement the AgentTower agent registry: a new SQLite table
`agents`, five new daemon socket methods (`register_agent`,
`list_agents`, `set_role`, `set_label`, `set_capability`), five new
`agenttower` CLI subcommands (`register-self`, `list-agents`,
`set-role`, `set-label`, `set-capability`), JSONL audit appendage on
every successful role transition, and one wiring change in the
FEAT-004 pane reconciliation path that updates each affected
agent's `last_seen_at` in the same SQLite transaction. The feature
turns a discovered FEAT-004 tmux pane (composite-key identified)
into a registered agent with a stable opaque id `agt_<12-hex>`,
binds the agent immutably to that pane composite key for life
(FR-002, FR-006), and materializes role-derived
`effective_permissions` for FEAT-009 / FEAT-010 to consume later
(FR-021).

The single highest-stakes property FEAT-006 introduces — that
master privilege MUST never be granted as a side effect of a
self-registration handshake (US2; FR-010, FR-011) — is enforced by
splitting role assignment across two surfaces: `register-self` MUST
reject `--role master` regardless of `--confirm` with closed-set
code `master_via_register_self_rejected`, and `set-role
--role master` MUST require `--confirm`, an `active=true` agent,
and an `active=true` bench container (FR-011). Demotion from master
is intentionally asymmetric — no `--confirm` (FR-013) — leaving
in-flight prompt arbitration to FEAT-009 / FEAT-010. Swarm parent
linkage is a one-time immutable binding set only by
`register-self --role swarm --parent <id>` (FR-015..FR-019);
`set-role --role swarm` MUST be rejected (FR-012) and re-registering
with a different `--parent` MUST be rejected with `parent_immutable`
(FR-018a, Clarifications 2026-05-07).

Idempotent re-registration follows a strict
"only-supplied-fields-overwrite" wire contract (Clarifications
2026-05-07 Q1): the CLI MUST NOT transmit argparse default values,
so unsupplied flags leave the stored row unchanged and a routine
re-`register-self` cannot silently demote a `master` or `slave` to
`unknown`. Re-activation of a previously inactive agent at the same
composite key preserves `agent_id`, `created_at`, and
`parent_agent_id` (FR-008). The default `list-agents` form is a
locked tab-separated table with a required header row and a fixed
nine-column schema `AGENT_ID, LABEL, ROLE, CAPABILITY, CONTAINER (12-hex short), PANE (session:window.pane), PROJECT, PARENT (12-hex short or '-'), ACTIVE` (FR-029, Clarifications 2026-05-07 Q5); future fields go to `--json` or
a separately-introduced `--wide` flag.

The on-the-wire surface adds five socket methods (FR-023) on top of
the existing FEAT-002 newline-delimited JSON envelope and inherits
the FEAT-002 `0600`-host-user-only socket-file authorization
verbatim (FR-043). The SQLite migration adds exactly one table
(`agents`) and bumps `CURRENT_SCHEMA_VERSION` from `3` (FEAT-004) to
`4`; FEAT-001/FEAT-002/FEAT-003/FEAT-004 schemas and persisted
shapes are untouched (FR-037, SC-010). The JSONL audit file is the
existing FEAT-001 `events.jsonl` with one new event-type
`agent_role_change` (FR-014, Clarifications 2026-05-07 Q4); no new
audit log file is introduced. `last_seen_at` is owned exclusively
by the FEAT-004 reconciliation path (FR-009a, Clarifications
2026-05-07 Q2) — CLI calls (`list_agents`, `set_role`, `set_label`,
`set_capability`) MUST NOT touch it. Concurrency is bounded by two
in-process advisory mutex maps: per-`(container_id,
pane_composite_key)` for `register_agent` (FR-038) and per-`agent_id`
for `set_role` / `set_label` / `set_capability` (FR-039). Failure
modes are a single closed-set error code set (FR-040, extended for
`parent_immutable`); every failure path exits non-zero with a code
that appears verbatim in `--json` output. The daemon stays alive
on every failure (FR-035), and every CLI inherits the FEAT-005
socket-resolution priority chain
(`AGENTTOWER_SOCKET` → in-container default → host default) and the
FEAT-002 daemon-unavailable exit-code-`2` behavior (FR-032).

The feature is testable end-to-end without a real Docker daemon,
real bench container, or real tmux server (FR-044), reusing the
existing FEAT-003 `AGENTTOWER_TEST_DOCKER_FAKE`, FEAT-004
`AGENTTOWER_TEST_TMUX_FAKE`, and FEAT-005
`AGENTTOWER_TEST_PROC_ROOT` test seams unchanged. No new test seam
is introduced.

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001 /
FEAT-002 / FEAT-003 / FEAT-004 / FEAT-005; pyproject pins
`requires-python>=3.11`). Standard library only — no third-party
runtime dependency added.

**Primary Dependencies**: Standard library only — `sqlite3`,
`secrets` (for `agent_id` 12-hex generation), `os`, `pathlib`,
`socket`, `argparse`, `json`, `dataclasses`, `typing`, `threading`
(for the per-key advisory mutex maps), `re` (for label / project
shape validation), `datetime` (for ISO-8601 timestamps consistent
with FEAT-002/003/004). Reuses the FEAT-002 socket server
(`socket_api/server.py`), client (`socket_api/client.py`), and error
envelope (`socket_api/errors.py`) verbatim. Reuses FEAT-005
in-container identity detection (`config_doctor/identity.py`,
`config_doctor/tmux_identity.py`, `config_doctor/socket_resolve.py`,
`config_doctor/sanitize.py`) for the CLI side of `register-self`.
Reuses FEAT-004 pane reconciliation (`discovery/pane_reconcile.py`)
to wire `last_seen_at` updates per FR-009a; reuses FEAT-004
`scan_panes` codepath bounded to a single container for the
FR-041 focused rescan. No `subprocess`, no new `tmux` invocation
shape, no new `docker` invocation shape introduced by FEAT-006.

**Storage**: One SQLite migration `v3 → v4` (FEAT-006), adding
exactly one new table `agents` and three indexes (active/order,
container/parent lookup, parent lookup); no other table is touched
(FR-037). `CURRENT_SCHEMA_VERSION` advances from `3` (FEAT-004) to
`4`. Migration is idempotent on re-open via `IF NOT EXISTS`, runs
under a single `BEGIN IMMEDIATE` transaction inside
`schema._apply_pending_migrations`, and refuses to serve the daemon
on rollback (FR-036). FEAT-001 / FEAT-002 / FEAT-003 / FEAT-004
schemas and persisted file modes (`0600`/`0700`) are unchanged
(SC-010). The `events.jsonl` audit log is the existing FEAT-001
file; one new event-type `agent_role_change` is appended on every
successful role transition (FR-014) — no new audit log path is
introduced.

**Testing**: pytest (≥ 7), reusing the FEAT-002 / FEAT-003 /
FEAT-004 / FEAT-005 daemon harness in
`tests/integration/_daemon_helpers.py` verbatim — every FEAT-006
integration test spins up a real host daemon under an isolated
`$HOME` and drives the `agenttower` console script as a subprocess.
The same three test seams (`AGENTTOWER_TEST_DOCKER_FAKE`,
`AGENTTOWER_TEST_TMUX_FAKE`, `AGENTTOWER_TEST_PROC_ROOT`) are reused
unchanged. Integration tests cover every US1 / US2 / US3 acceptance
scenario plus the spec's 18 edge cases. Unit tests cover every area
enumerated in SC-011: `agent_id` generation and uniqueness;
role / capability closed-set validation; label / project_path
sanitization and bounds; idempotent re-registration with
supplied-vs-default field handling (Clarifications 2026-05-07 Q1);
re-activation of previously inactive agents; swarm parent
validation across all five failure paths plus the success path;
`effective_permissions` derivation across all six roles;
master-promotion safety across no-`--confirm`, via-`register-self`,
via-`set-role`-swarm; JSONL audit-record shape including initial
`prior_role: null` (Clarifications 2026-05-07 Q4); per-key
registration mutex serialization; `parent_immutable` rejection
atomicity (Clarifications 2026-05-07 Q3); locked default
`list-agents` TSV column schema (Clarifications 2026-05-07 Q5).
Integration tests cover the SC-012 closed list of end-to-end paths
including the FR-041 focused rescan trigger, the daemon-unreachable
CLI path, and the host-shell `host_context_unsupported` path —
none of which require a real Docker daemon, real container, or
real tmux server. A backwards-compatibility test
(`test_feat006_backcompat.py`) gates SC-010 by re-running every
FEAT-001..005 CLI command and asserting byte-identical stdout,
stderr, exit codes, and `--json` shapes. A migration test
(`test_schema_migration_v4.py`) covers v3-only DB upgrade,
v4-already-current re-open, and forward-version refusal.

**Target Platform**: Linux/WSL developer workstations. The daemon
continues to run exclusively on the host (constitution principle I);
FEAT-006 introduces zero new in-container processes — the new CLI
commands run from inside a bench container as short-lived
read-only thin clients, and the only daemon-side `docker exec`
codepath FEAT-006 invokes is the FR-041 focused rescan that
already exists in FEAT-004.

**Project Type**: Single-project Python CLI + daemon. Extends
`src/agenttower/`. Two existing modules (`cli.py`,
`state/schema.py`) gain additive surfaces; one existing module
(`socket_api/methods.py`) gains five new dispatch entries; one
existing module (`socket_api/errors.py`) gains the new closed-set
error codes; one existing module (`discovery/pane_reconcile.py`)
gains a single side-effect that updates each touched agent's
`last_seen_at` in the same transaction; one new package
(`agents/`) is introduced for the registration domain logic,
mirroring the package-per-domain split established by FEAT-003's
`discovery/`, FEAT-004's `tmux/`, and FEAT-005's `config_doctor/`.

**Performance Goals**:
- SC-001 — A single `register-self` invocation against a healthy
  daemon, a healthy FEAT-004 pane lookup (no rescan), a healthy
  identity cross-check (FEAT-005), and an empty FEAT-006 `agents`
  table completes within 500 ms wall-clock p95 end-to-end including
  one `list_panes` round-trip (or one focused `scan_panes`
  round-trip on a miss), one `register_agent` round-trip, and one
  `list_agents` round-trip in the integration test harness.
- SC-008 — A focused FR-041 per-container rescan reuses the
  FEAT-004 `scan_panes` codepath bounded to a single container and
  inherits the FEAT-004 5-second per-call timeout exactly.
- `list-agents` is read-only, holds no registration mutex, and
  returns the latest committed SQLite state with the FR-025
  deterministic ordering. Expected steady-state usage at MVP scale
  is single-digit-millisecond per call.

**Constraints**:
- No network listener anywhere in FEAT-006; the new socket methods
  reuse FEAT-002's `AF_UNIX` socket-file authorization (`0600`,
  host user only) verbatim (FR-043; constitution principle I).
- No third-party runtime dependency; all `agent_id` generation,
  closed-set validation, sanitization, mutex coordination, and
  CLI/JSON rendering use Python stdlib only.
- `agent_id` is generated from `secrets.token_hex(6)` → 12 hex chars
  (48 bits of entropy) prefixed with `agt_`. Collisions are
  retried via a bounded loop (max 5 attempts) under the
  per-(container_id, pane_composite_key) registration mutex; an
  exhausted retry budget surfaces as `internal_error` and the
  daemon stays alive (FR-035).
- Mutable-field wire encoding: every mutable field
  (`role`, `capability`, `label`, `project_path`, `parent_agent_id`)
  in the `register_agent` request envelope MUST be either present
  with a value or absent (the JSON key MUST NOT exist when the user
  did not pass the flag). Argparse-style defaults
  (`--role unknown`, `--capability unknown`, `--label ""`,
  `--project ""`) MUST NOT be transmitted on idempotent
  re-registration; they are applied only on first registration of
  a brand-new pane. The CLI MUST distinguish "flag omitted" from
  "flag explicitly set to default value" via argparse `SUPPRESS`
  defaults plus an explicit per-flag sentinel (Clarifications
  2026-05-07 Q1).
- Master safety boundary: `register-self` MUST reject `--role master`
  regardless of `--confirm` (FR-010); `set-role --role master`
  MUST require `--confirm` AND target an active agent in an active
  container (FR-011); `set-role --role swarm` MUST be rejected
  (FR-012); demotion from master MUST NOT require `--confirm`
  (FR-013).
- Master-promotion atomic re-check (FR-011 / Clarifications
  session 2026-05-07-continued Q3): the `set-role --role master --confirm`
  active-state check MUST be performed *inside* the
  `BEGIN IMMEDIATE` write transaction (re-SELECT `agents.active`
  AND `containers.active`; ROLLBACK + `agent_inactive` on either
  flag being `0`), never read-then-write outside the transaction.
  SQLite `BEGIN IMMEDIATE` serializes the re-check against any
  concurrent FEAT-004 reconciliation transaction so the
  validate-then-write race window is closed at the SQLite level.
- Swarm parent immutability: `register-self` re-run with `--parent`
  matching the stored `parent_agent_id` is a no-op success;
  `register-self` re-run with a different `--parent` MUST be
  rejected with `parent_immutable` and MUST NOT update any other
  mutable field even if other fields were also supplied (FR-018a).
- `last_seen_at` ownership: every FEAT-004 pane scan that observes
  the bound pane as active updates `last_seen_at` in the same
  SQLite transaction as the pane reconciliation (FR-009a).
  CLI calls MUST NOT touch `last_seen_at` from any FEAT-006
  codepath.
- `effective_permissions` derivation: pure function of `role` only,
  recomputed on every write that mutates `role`; materialized as a
  JSON column with closed-set fields `{can_send: bool, can_receive: bool, can_send_to_roles: [<role>...]}`
  (FR-021).
- JSONL audit shape: every successful role transition appends
  exactly one row with `event_type=agent_role_change`, `agent_id`,
  `prior_role` (JSON literal `null` on first registration),
  `new_role`, `confirm_provided`, `socket_peer_uid`, and the daemon
  clock timestamp (FR-014; Clarifications 2026-05-07 Q4). No-op
  writes (re-registration with unchanged role; `set-*` calls with
  the same value the agent already has) MUST NOT append a new row
  (FR-027).
- Default `list-agents` form is a tab-separated table with a
  required header row and a fixed nine-column schema (FR-029;
  Clarifications 2026-05-07 Q5). Future fields go to `--json` or a
  separately-introduced `--wide` flag — never the default form.
  Snapshot tests lock this contract.
- Free-text bounds (FR-033): `label ≤ 64 chars`, `project_path ≤
  4096 chars`. Oversized values are rejected with `field_too_long`,
  never silently truncated.
- `project_path` shape (FR-034): non-empty absolute path starting
  with `/`, NUL-free, no `..` segment after normalization.
  Existence on the host filesystem is NOT checked.
- Per-(container_id, pane_composite_key) advisory mutex serializes
  concurrent `register_agent` requests addressing the same pane
  (FR-038); per-`agent_id` advisory mutex serializes
  `set_role` / `set_label` / `set_capability` (FR-039). Mutex maps
  live in-process and are released on transaction commit OR
  rollback. Concurrent calls addressing different keys / different
  agent_ids MUST proceed in parallel.
- Cross-subsystem concurrency (FR-038 / Clarifications session
  2026-05-07-continued Q4): the FEAT-006 per-key registration
  mutex covers `register_agent` against other `register_agent`
  calls only; FEAT-004 pane reconciliation MUST NOT acquire it.
  Cross-subsystem ordering between a `register_agent` transaction
  and a FEAT-004 reconciliation transaction touching the same
  `agents` row is provided **exclusively** by SQLite's
  `BEGIN IMMEDIATE` semantics — both transactions are atomic, the
  last committed transaction wins for overlapping mutable
  columns, and `SQLITE_BUSY` surfaces as `internal_error` without
  daemon-side retry.
- Single-transaction writes: every successful registration or
  set-* call commits the agent-row write and the
  `effective_permissions` recomputation in one SQLite transaction;
  rollback on failure leaves no audit row and no agent-row mutation
  (FR-035).
- Schema version forward-compat: every new CLI surfaces
  `schema_version_newer` and refuses the call without corrupting
  state, inheriting the FEAT-005 forward-compat policy verbatim
  (edge cases).
- All untrusted CLI inputs (`label`, `project_path`, `--parent`,
  `--target`, `--container` filter, `--role` filter) inherit
  FEAT-004 sanitization (NUL-stripped, C0-control-stripped) and the
  FR-033 bounds.
- Case-sensitivity (Clarifications session 2026-05-07-continued
  Q2): every closed-set token (`role`, `capability`) is lowercase
  and case-sensitive; every lowercase-hex identifier (`agent_id`,
  `parent_agent_id`, `container_id`) is case-sensitive. Mixed-case
  inputs (`Slave`, `MASTER`, `agt_ABC...`, `ABC123def456`) MUST
  be rejected with `value_out_of_set` and MUST NOT be normalized.
  Every validator, filter, lookup, and comparison site treats
  case differences as distinct values.
- The CLIs MUST NOT send any input into any tmux pane, MUST NOT
  call `docker exec` for any purpose other than the FR-041 focused
  rescan invoked daemon-side, MUST NOT modify any pane log, and
  MUST NOT install any tmux hook (FR-042). FEAT-006 is registry-only.

**Scale/Scope**: One host user, one daemon, one new SQLite table
(`agents`), three new SQLite indexes, one new JSONL event-type
(`agent_role_change`), five new socket methods, five new CLI
subcommands, one new closed-set error-code addition
(`parent_immutable`), one new domain package (`agents/`). Expected
steady-state usage: tens of registered agents per host at MVP
scale, sub-millisecond SQLite reads on indexed lookups, single-digit
KB JSON payloads on `list_agents`. The advisory mutex maps grow
with the number of distinct pane composite keys / agent_ids
observed per daemon lifetime; entries are not evicted (memory
overhead is bounded by MVP agent count).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                     | Status | Evidence |
| ----------------------------- | ------ | -------- |
| I. Local-First Host Control   | PASS   | The agent registry is owned exclusively by the host daemon; the new socket methods reuse FEAT-002's `AF_UNIX` socket-file authorization (`0600`, host user only) verbatim (FR-023, FR-043). FR-043 forbids any new network listener, in-container daemon, or relay; FEAT-006's tests assert the same harness invariant FEAT-002..005 do (no AF_INET/AF_INET6). Durable state stays under the host's `opensoft/agenttower` namespace; FR-042 forbids any new in-container disk write beyond the existing FEAT-004 / FEAT-005 read-only inspections. |
| II. Container-First MVP       | PASS   | This is the registration slice that turns FEAT-003 / FEAT-004 / FEAT-005 detection into a durable agent identity bound to a bench container's tmux pane composite key (FR-002). Host-only `register-self` calls are explicitly refused with `host_context_unsupported` (edge cases; FR-040). All new CLIs inherit FEAT-005's in-container socket-resolution chain (FR-032). |
| III. Safe Terminal Input      | PASS   | FR-042 forbids any input delivery, prompt queuing, log capture, tmux-hook installation, or `docker exec` invocation outside the FR-041 daemon-side focused rescan. The master safety boundary is the architecture-mandated split: `register-self` cannot grant master (FR-010); `set-role --role master` requires `--confirm`, an active agent, and an active container (FR-011); `set-role --role swarm` is rejected (FR-012). Demotion is asymmetric and intentionally simpler (FR-013) — in-flight prompt arbitration is FEAT-009 / FEAT-010's concern. The "no silent privilege escalation/de-escalation" rule is reinforced by Clarifications 2026-05-07 Q1: argparse defaults are NOT transmitted on idempotent re-registration, so a routine re-run cannot silently demote a master. All untrusted free-text fields (`label`, `project_path`) are sanitized + bounded per FR-033 / FR-034 and never interpolated into a shell string. |
| IV. Observable and Scriptable | PASS   | Every new CLI ships dual output: a locked human-readable form (TSV with header for `list-agents`, FR-029) and a `--json` form with stable closed-set error codes (FR-040). Every successful role transition appends exactly one JSONL audit row with `agent_id`, `prior_role`, `new_role`, `confirm_provided`, `socket_peer_uid`, and timestamp (FR-014; Clarifications 2026-05-07 Q4 — including initial creation with `prior_role: null`); the audit log is the existing FEAT-001 `events.jsonl`, no new file (Assumptions). `list-agents --json` exposes every immutable field (FR-002) and mutable field (FR-003) verbatim plus `effective_permissions` (FR-022). |
| V. Conservative Automation    | PASS   | FR-018 makes `parent_agent_id` immutable for life; re-parenting is deferred. FR-020 forbids nested swarms (slave → swarm only). FR-043 forbids prompt delivery, route configuration, log attachment, event ingestion, automatic swarm inference, multi-master arbitration, TUI, and web UI. The registry stores derived `effective_permissions` (FR-021) but FEAT-006 does NOT consume them for any decision (FR-022) — downstream features read them. Master promotion requires explicit human confirmation (FR-011) and never happens as a side effect (FR-010). Demotion is asymmetric (FR-013) by design — FEAT-006 does not pre-empt FEAT-009 / FEAT-010's design choices about in-flight prompts. |

| Technical Constraint                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Primary language Python                                                       | PASS   | Python 3.11+, stdlib only. No new runtime dependency. |
| Console entrypoints `agenttower` & `agenttowerd`                              | PASS   | Extends `agenttower` with five new subcommands (`register-self`, `list-agents`, `set-role`, `set-label`, `set-capability`). `agenttowerd run` is unchanged. |
| Files under `~/.config` / `~/.local/state` / `~/.cache` `opensoft/agenttower` | PASS   | The new `agents` SQLite table lives in the existing `state.db`. JSONL audit rows are appended to the existing FEAT-001 `events.jsonl`. No new path is introduced. |
| Docker default `name_contains = ["bench"]`, host `docker exec -u "$USER"`     | PASS (vacuously) | FEAT-006 calls neither `docker` nor `docker exec` directly. The FR-041 focused rescan reuses the FEAT-004 `scan_panes` codepath verbatim (no new `docker exec` shape). |
| CLI: human-readable defaults + structured output where it helps               | PASS   | Every new CLI ships a stable, scriptable default (`register-self` prints the assigned `agent_id` and resolved fields; `list-agents` is locked TSV with header; `set-*` print prior/new value pairs) and a `--json` form (FR-028, FR-029, FR-030, FR-031). |

| Development Workflow                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Build in `docs/mvp-feature-sequence.md` order                                 | PASS   | This is FEAT-006, immediately after FEAT-005 (`005-container-thin-client`). |
| Each feature CLI-testable                                                     | PASS   | Every US1 / US2 / US3 acceptance scenario maps to at least one named integration test invoking the real `agenttower` console script under the FEAT-002 daemon harness; see `tests/integration/test_cli_register_self.py`, `test_cli_register_idempotent.py`, `test_cli_register_swarm.py`, `test_cli_list_agents.py`, `test_cli_set_role_master.py`, `test_cli_set_role_swarm_rejected.py`, `test_cli_set_label_capability.py`, plus the closed-set edge-case suite (`test_cli_register_focused_rescan.py`, `test_cli_register_host_context.py`, `test_cli_register_pane_unknown.py`, `test_cli_register_no_daemon.py`, `test_cli_register_concurrent.py`, `test_cli_last_seen_at_updates.py`). |
| Tests proportional to risk; broader for daemon state, sockets, Docker/tmux adapters, permissions, and input delivery | PASS   | Master-promotion safety has dedicated unit and integration coverage (no-`--confirm`, via `register-self`, via `set-role` swarm). Swarm parent validation has unit coverage for all five failure paths (`parent_not_found`, `parent_inactive`, `parent_role_invalid`, `parent_role_mismatch`, `swarm_parent_required`) plus the success path. JSON contract stability is locked by `test_register_supplied_vs_default.py`, `test_list_agents_tsv_render.py`, and the `test_feat006_backcompat.py` snapshot. The schema migration has dedicated `test_schema_migration_v4.py` coverage including v3-only upgrade, v4-already-current re-open, and forward-version refusal. Concurrency is covered by `test_cli_register_concurrent.py` and the unit-level `test_register_mutex.py`. |
| Preserve existing docs and NotebookLM sync mappings                           | PASS   | This feature does not edit existing Markdown under `docs/`. New artifacts live entirely under `specs/006-agent-registration/`. |
| No TUI, web UI, or relay before the core slices work                          | PASS   | None introduced here. FEAT-006 is the registration slice on top of the four core slices (FEAT-002 daemon, FEAT-003 container discovery, FEAT-004 pane discovery, FEAT-005 thin client). |
| Decide explicitly whether `/speckit.checklist <topic>` is needed before tasks | DECISION | A `security` checklist is recommended before `/speckit.tasks` because FEAT-006 introduces the master safety boundary — the highest-stakes operation in the MVP — and a new privilege-derivation path (`effective_permissions`). The `--confirm` gate, the rejection of master via `register-self`, the rejection of swarm via `set-role`, the immutability of `parent_agent_id`, the supplied-vs-default wire contract that prevents silent demotion, and the audit-log shape (initial `prior_role: null`, no audit on no-op) are all worth a pre-tasks gate. A second `cli-contract` checklist is optional but worth considering because the FR-029 default `list-agents` TSV column schema and the FR-040 closed-set error codes are both new public surfaces that downstream features will consume. |

**Result**: Gates pass. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/006-agent-registration/
├── plan.md                        # This file (/speckit.plan output)
├── research.md                    # Phase 0 output: resolved decisions
├── data-model.md                  # Phase 1 output: agents table + entity shapes + JSONL schema
├── quickstart.md                  # Phase 1 output: end-to-end CLI walkthrough
├── contracts/
│   ├── cli.md                     # User-facing CLI contracts (C-CLI-601 register-self; C-CLI-602 list-agents; C-CLI-603 set-role; C-CLI-604 set-label; C-CLI-605 set-capability)
│   └── socket-api.md              # Socket-level contracts for the five new methods (register_agent, list_agents, set_role, set_label, set_capability) including request envelopes, response envelopes, error codes
├── checklists/                    # /speckit.checklist outputs (security recommended)
└── tasks.md                       # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

Only files actually touched by FEAT-006 are listed. FEAT-001 /
FEAT-002 / FEAT-003 / FEAT-004 / FEAT-005 files remain unchanged
unless an explicit "EXTENDS" note appears.

```text
src/agenttower/
├── cli.py                                # EXTENDS: add subparsers `register-self`, `list-agents`, `set-role`, `set-label`, `set-capability`; reuse FEAT-005 socket-resolution chain; argparse uses `argparse.SUPPRESS` default sentinel for every mutable flag so omitted flags are absent in the dict and not transmitted (FR-007, Clarifications Q1); `--json` flag on every new subcommand
├── state/
│   ├── schema.py                         # EXTENDS: bump CURRENT_SCHEMA_VERSION 3 → 4; add `_apply_migration_v4`; register migration in `_MIGRATIONS`; v3-only DBs upgrade in one BEGIN IMMEDIATE transaction (FR-036)
│   └── agents.py                         # NEW: SQLite reads/writes for the `agents` table; pure data-access layer mirroring `state/containers.py` and `state/panes.py`; closed-set INSERT/UPDATE/SELECT helpers; deterministic ordering helper for FR-025
├── agents/                               # NEW package: agent registration domain logic
│   ├── __init__.py                       # NEW: package marker; re-exports AgentRecord, RegisterAgentRequest, AgentService, EffectivePermissions
│   ├── identifiers.py                    # NEW: agent_id generation `agt_<12-hex>`; bounded retry-on-collision under registration mutex
│   ├── permissions.py                    # NEW: pure FR-021 derivation function `effective_permissions(role) -> dict` for all six roles; serialized to JSON for the SQLite column
│   ├── validation.py                     # NEW: closed-set validators (role, capability); label/project sanitization + bounds (FR-033, FR-034); --parent shape check; closed-set error code raising
│   ├── service.py                        # NEW: top-level orchestrator for register_agent / list_agents / set_role / set_label / set_capability daemon-side; consumes the per-(container_id, pane_composite_key) and per-agent_id mutex registries from `mutex.py` (FR-038, FR-039); single-transaction commit; rollback on failure; master-promotion atomic re-check inside BEGIN IMMEDIATE (FR-011 / Clarifications session 2026-05-07-continued Q3)
│   ├── mutex.py                          # NEW: per-key advisory mutex registries `RegisterLockMap` (keyed by pane composite key, FR-038) and `AgentLockMap` (keyed by agent_id, FR-039); thread-safe fetch-or-create under guard lock (research R-005); FEAT-004 reconciliation does NOT acquire these maps (cross-subsystem ordering via SQLite BEGIN IMMEDIATE; Clarifications session 2026-05-07-continued Q4)
│   ├── audit.py                          # NEW: JSONL audit-row writer for `event_type=agent_role_change` appended to events.jsonl; includes `prior_role: null` for initial creation (Clarifications Q4); literal `confirm_provided` value (Clarifications session 2026-05-07-continued Q5); skip on no-op (FR-027)
│   └── client_resolve.py                 # NEW: client-side resolver for `register-self`; reuses FEAT-005 identity + tmux-self-identity; calls `list_panes` then triggers focused rescan via `scan_panes(container=...)` on miss (FR-041); maps every failure to a closed-set error code
├── socket_api/
│   ├── methods.py                        # EXTENDS: add five new dispatch entries (`register_agent`, `list_agents`, `set_role`, `set_label`, `set_capability`); each handler routes to `agents/service.py`; existing entries unchanged byte-for-byte
│   ├── errors.py                         # EXTENDS: add new closed-set codes (`HOST_CONTEXT_UNSUPPORTED`, `CONTAINER_UNRESOLVED`, `PANE_UNKNOWN_TO_DAEMON`, `AGENT_NOT_FOUND`, `AGENT_INACTIVE`, `PARENT_NOT_FOUND`, `PARENT_INACTIVE`, `PARENT_ROLE_INVALID`, `PARENT_ROLE_MISMATCH`, `PARENT_IMMUTABLE`, `SWARM_PARENT_REQUIRED`, `SWARM_ROLE_VIA_SET_ROLE_REJECTED`, `MASTER_VIA_REGISTER_SELF_REJECTED`, `MASTER_CONFIRM_REQUIRED`, `VALUE_OUT_OF_SET`, `FIELD_TOO_LONG`, `PROJECT_PATH_INVALID`, `UNKNOWN_FILTER`, `NOT_IN_TMUX`, `TMUX_PANE_MALFORMED`, `SCHEMA_VERSION_NEWER`); extend `CLOSED_CODE_SET` accordingly; existing codes unchanged
│   └── client.py                         # EXTENDS (additive only): add typed wrappers `register_agent()`, `list_agents()`, `set_role()`, `set_label()`, `set_capability()`; reuse existing connect / framing logic
└── discovery/
    └── pane_reconcile.py                 # EXTENDS: every pane reconciliation transaction that observes a pane-composite-key as `active=true` MUST also UPDATE the bound agent's `last_seen_at` (FR-009a; Clarifications Q2); transition active→inactive cascades to the agent's `active=false` (FR-009); transition inactive→active does NOT auto-flip the agent's `active` flag

tests/
├── unit/
│   ├── test_agent_id_generation.py              # NEW: FR-001 — `agt_<12-hex>` shape; collision retry under mutex; entropy bound
│   ├── test_role_capability_validation.py       # NEW: FR-004 / FR-005 — closed-set validators; out-of-set rejection with `value_out_of_set`
│   ├── test_label_project_sanitize.py           # NEW: FR-033 / FR-034 — NUL strip, control-byte strip, label ≤ 64 chars, project_path ≤ 4096 chars, absolute-path requirement, no `..` segment, no NUL byte
│   ├── test_effective_permissions.py            # NEW: FR-021 — derivation across all six roles (master, slave, swarm, test-runner, shell, unknown); JSON column shape stability
│   ├── test_register_idempotency.py             # NEW: FR-007 — re-registration with same composite key returns same agent_id; mutable fields supplied replace stored; mutable fields not supplied left unchanged; created_at / parent_agent_id / pane composite key never change; last_registered_at updates
│   ├── test_register_supplied_vs_default.py     # NEW: Clarifications Q1 — argparse defaults NOT transmitted on re-registration; idempotent re-runs preserve role/capability/label/project; explicit `--role unknown` overwrites whereas omitted `--role` does not
│   ├── test_register_reactivation.py            # NEW: FR-008 — re-`register-self` on a previously inactive agent at the same composite key re-activates it preserving agent_id, created_at, parent_agent_id; mutable-field semantics from FR-007 still apply
│   ├── test_swarm_parent_validation.py          # NEW: FR-015 / FR-016 / FR-017 / FR-019 / FR-020 — all five failure paths (parent_not_found, parent_inactive, parent_role_invalid, parent_role_mismatch, swarm_parent_required) plus the success path; nested swarm rejection
│   ├── test_parent_immutable.py                 # NEW: Clarifications Q3 — re-registration with same `--parent` is no-op success; re-registration with different `--parent` rejected `parent_immutable`; on rejection no mutable field updated; transaction rolled back; no audit row appended
│   ├── test_master_promotion_safety.py          # NEW: FR-010 / FR-011 / FR-012 / FR-013 — register-self rejects --role master regardless of --confirm; set-role --role master without --confirm rejected; set-role --role swarm rejected; demotion does not require --confirm
│   ├── test_audit_record_shape.py               # NEW: FR-014 — exactly one JSONL row per successful role transition; agent_id, prior_role, new_role, confirm_provided, socket_peer_uid, timestamp; failures append no row
│   ├── test_initial_audit_record.py             # NEW: Clarifications Q4 — first successful register-self appends one row with prior_role: null regardless of role (incl. default unknown); idempotent re-registration with unchanged role appends no new row
│   ├── test_register_mutex.py                   # NEW: FR-038 / FR-039 — concurrent register_agent against same composite key serialized; concurrent against different keys parallel; per-agent_id mutex on set-* serialized
│   ├── test_list_agents_filters.py              # NEW: FR-026 — role / container_id / active_only / parent_agent_id filters; AND composition; unknown filter key rejected `unknown_filter`
│   ├── test_list_agents_tsv_render.py           # NEW: Clarifications Q5 — locked nine-column header row; TSV separator; CONTAINER 12-hex short; PARENT 12-hex short or `-`; PANE session:window.pane; ACTIVE true/false; future-field exclusion enforced by snapshot test
│   ├── test_list_agents_ordering.py             # NEW: FR-025 — deterministic order `active DESC, container_id ASC, parent_agent_id NULLS FIRST, label ASC, agent_id ASC`
│   ├── test_register_idempotent_audit.py        # NEW: FR-027 — set_role / set_label / set_capability with the same value the agent has succeed without error and append no new audit row
│   ├── test_register_transaction.py             # NEW: FR-035 — register / set-* failure rolls back agent-row write AND skips audit append; daemon stays alive; internal_error returned
│   ├── test_schema_v4_migration_unit.py         # NEW: FR-036 / FR-037 — v3 → v4 idempotent; `agents` table + indexes created on otherwise-unchanged FEAT-005 DB; FEAT-001..004 tables untouched
│   ├── test_pane_reconcile_last_seen.py         # NEW: FR-009a / Clarifications Q2 — every FEAT-004 pane reconciliation transaction that observes pane active updates `last_seen_at`; transition active→inactive cascades agent.active=false in the same transaction; inactive→active does NOT auto-flip; CLI calls do not touch last_seen_at
│   ├── test_register_value_out_of_set.py        # NEW: FR-004 / FR-005 — out-of-set role/capability/parent rejected with `value_out_of_set`; actionable message lists valid values
│   ├── test_register_field_too_long.py          # NEW: FR-033 — over-bound label/project_path rejected with `field_too_long` rather than truncated
│   ├── test_register_project_path_invalid.py    # NEW: FR-034 — relative path / `..` segment / NUL byte / empty rejected with `project_path_invalid`
│   ├── test_socket_api_register_agent.py        # NEW: FR-024 — daemon does NOT re-derive container identity from socket peer; CLI is responsible; daemon enforces shape
│   ├── test_socket_api_list_agents_filters.py   # NEW: FR-026 — filter envelope shape; AND semantics; unknown_filter rejection
│   └── test_set_role_swarm_rejection.py         # NEW: FR-012 — set-role --role swarm rejected `swarm_role_via_set_role_rejected`; documented re-registration path described in actionable message
└── integration/
    ├── test_cli_register_self.py                       # NEW: US1 AS1 / SC-001 — register-self from simulated in-container env returns 0, prints agent_id, persists exactly one row
    ├── test_cli_register_idempotent.py                 # NEW: US1 AS2 / AS3 / SC-002 — re-registration from same pane returns same agent_id; mutable-field updates persist; created_at unchanged; last_registered_at updates
    ├── test_cli_register_swarm.py                      # NEW: US3 AS1 / SC-005 — register-self --role swarm --parent <id> succeeds; list-agents shows parent linkage
    ├── test_cli_register_swarm_failure_paths.py        # NEW: US3 AS2..AS6 / SC-006 — every swarm parent failure path (parent_not_found, parent_inactive, parent_role_invalid, parent_role_mismatch, swarm_parent_required, parent_role_mismatch when --parent without --role swarm)
    ├── test_cli_register_master_rejected.py            # NEW: US2 AS3 / SC-003 — register-self --role master --confirm rejected `master_via_register_self_rejected`; no agent row created; no audit row appended
    ├── test_cli_set_role_master.py                     # NEW: US2 AS1 — set-role --role master --confirm promotes; effective_permissions.can_send_to_roles=["slave","swarm"]; one audit row appended
    ├── test_cli_set_role_master_no_confirm.py          # NEW: US2 AS2 / SC-004 — set-role --role master without --confirm rejected `master_confirm_required`; role unchanged
    ├── test_cli_set_role_swarm_rejected.py             # NEW: FR-012 — set-role --role swarm rejected; actionable message points to register-self
    ├── test_cli_set_label_capability.py                # NEW: US2 AS4 / AS5 — set-label / set-capability succeed; role and effective_permissions unchanged
    ├── test_cli_list_agents.py                         # NEW: US1 AS4 / SC-007 — list-agents and list-agents --json across multi-agent state; locked TSV column schema; every JSON field present per FR-002 / FR-003 / FR-021
    ├── test_cli_list_agents_filters.py                 # NEW: FR-026 — --role / --container / --active-only / --parent filters compose with AND
    ├── test_cli_register_focused_rescan.py             # NEW: SC-008 / FR-041 — pane composite key not yet known triggers exactly one focused FEAT-004 rescan scoped to the caller's container; after rescan pane appears, registration succeeds; otherwise refuses pane_unknown_to_daemon
    ├── test_cli_register_host_context.py               # NEW: SC-009 — host shell with FEAT-005 reporting host_context exits non-zero `host_context_unsupported`
    ├── test_cli_register_pane_unknown.py               # NEW: edge cases — pane composite key absent after focused rescan refused with `pane_unknown_to_daemon`
    ├── test_cli_register_no_daemon.py                  # NEW: SC-009 — daemon down → exit code 2 with FEAT-002 daemon-unavailable message; no daemon implicit start
    ├── test_cli_register_concurrent.py                 # NEW: edge cases — two concurrent register-self from same pane converge on same agent_id; concurrent from different panes proceed in parallel
    ├── test_cli_last_seen_at_updates.py                # NEW: FR-009a — FEAT-004 pane scan updates last_seen_at on bound agents; CLI calls (list-agents, set-role, set-label, set-capability) leave last_seen_at unchanged
    ├── test_cli_register_inactive_agent_then_reappears.py # NEW: FR-008 — pane disappears, agent.active=false; pane reappears at same composite key, register-self re-activates preserving agent_id / created_at / parent_agent_id
    ├── test_cli_register_supplied_vs_default.py        # NEW: Clarifications Q1 — re-registration without flags preserves stored role/capability/label/project; explicit --role unknown does overwrite
    ├── test_cli_register_parent_immutable.py           # NEW: Clarifications Q3 — re-registration with same --parent is no-op success; with different --parent rejected `parent_immutable`; no mutable field updated
    ├── test_cli_register_initial_audit.py              # NEW: Clarifications Q4 — first register-self with default --role unknown writes one audit row with prior_role: null; idempotent re-run with unchanged role writes no new row
    ├── test_cli_register_value_out_of_set.py           # NEW: edge cases — invalid role/capability/parent rejected `value_out_of_set` with valid values listed
    ├── test_cli_register_field_too_long.py             # NEW: FR-033 — oversized label / project_path rejected `field_too_long`
    ├── test_cli_register_project_path_invalid.py       # NEW: FR-034 — relative / `..` / NUL byte / empty rejected `project_path_invalid`
    ├── test_cli_register_concurrent_different_panes.py # NEW: FR-038 — concurrent register-self from different composite keys parallelize; both succeed; distinct agent_ids
    ├── test_cli_set_role_inactive_target.py            # NEW: edge cases — set-role on agent with active=false rejected `agent_inactive`; set-role --role master on agent in inactive container rejected `agent_inactive`
    ├── test_cli_set_role_unknown_target.py             # NEW: edge cases — set-role on unknown agent_id rejected `agent_not_found`
    ├── test_cli_register_schema_newer.py               # NEW: edge cases — daemon schema_version > CLI build → all five CLIs surface `schema_version_newer` and refuse
    ├── test_schema_migration_v4.py                     # NEW: SC-010 — v3-only DB upgrades to v4 cleanly; v4-already-current re-open is a no-op; forward-version refusal preserved; FEAT-001..004 tables untouched
    ├── test_feat006_backcompat.py                      # NEW: SC-010 — every FEAT-001..005 CLI command produces byte-identical output; no existing socket method gains a code or shape; existing tests still pass
    └── test_feat006_no_real_docker_or_tmux.py          # NEW: SC-012 — parallel to test_feat005_no_real_container.py; asserts no real docker / tmux / network call during the FEAT-006 test session beyond the FR-041 focused rescan that goes through the existing FEAT-004 fakes
```

**Structure Decision**: Keep the FEAT-001..005 single-project
layout. The new `agents/` package mirrors the package-per-domain
split established by FEAT-003's `discovery/` and `docker/`,
FEAT-004's `tmux/` and `discovery/pane_reconcile.py`, and
FEAT-005's `config_doctor/`: `service.py` orchestrates,
`identifiers.py`, `permissions.py`, `validation.py`, `audit.py`,
and `client_resolve.py` keep each FR's logic in one testable unit.
The SQLite layer mirrors FEAT-003 / FEAT-004's split between
`state/schema.py` (migrations) and `state/<table>.py` (typed
read/write helpers) by adding `state/agents.py`. The dispatch
table in `socket_api/methods.py` gains exactly five new entries
(`register_agent`, `list_agents`, `set_role`, `set_label`,
`set_capability`); existing entries (`ping`, `status`, `shutdown`,
`scan_containers`, `list_containers`, `scan_panes`, `list_panes`)
are unchanged byte-for-byte. `socket_api/errors.py` adds the
FEAT-006 closed-set codes; existing codes are unchanged.
`socket_api/client.py` gets five new typed wrappers; the framing /
connect path is unchanged. `discovery/pane_reconcile.py` gains the
single side-effect of updating `last_seen_at` on every observed
agent in the same SQLite transaction (FR-009a). `cli.py` gets
five new subparsers, each using `argparse.SUPPRESS` defaults so
omitted flags are *absent* from the parsed dict and not
transmitted on the wire (Clarifications Q1). `state/schema.py`
gains exactly one new migration function `_apply_migration_v4`,
registered in `_MIGRATIONS[4]`, and `CURRENT_SCHEMA_VERSION` moves
from `3` to `4`. FR-043's no-new-listener / no-new-relay clause is
enforced by the absence of any edit to
`socket_api/server.py`, `socket_api/lifecycle.py`, or
`daemon.py` beyond optional plumbing of the new method handlers
into the dispatch context.

## Complexity Tracking

> No constitutional violations to justify. This section is intentionally empty.
