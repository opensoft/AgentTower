# Coverage Verification Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Audit whether the 8 existing domain checklists (cli, data-model, audit, observability, determinism, concurrency, security, performance) collectively cover every FR, SC, Clarification, and edge case the spec defines. Surface and name every uncovered item as a [Gap] so it can be addressed before `/speckit.tasks`.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep (meta-coverage audit)
**Reads**: spec.md, plan.md, research.md, data-model.md, contracts/, checklists/*.md

---

## Coverage Map (Informational)

The table below lists every spec FR / SC and the domain checklist(s) that reference it. **Bolded** items are uncovered by every existing checklist — they appear as `[Gap]` items below.

| ID | Topic | Covered by |
|---|---|---|
| FR-001 | Routes table schema | cli, data-model, security |
| FR-002 | Cursor at creation | data-model |
| FR-003 | route remove + orphan refs | data-model |
| FR-004 | CLI command set | cli |
| FR-005 | event_type validation | cli, data-model, audit |
| FR-006 | target-rule validation + source symmetry | cli |
| **FR-007** | **master-rule validation** | **(none)** |
| FR-008 | template field whitelist | security |
| FR-009 | enable/disable idempotency | cli, audit, observability |
| FR-009a | route immutability | cli |
| FR-010 | per-cycle event matching | data-model, performance |
| FR-011 | event_id ascending order | audit, determinism |
| FR-012 | cursor-advance-with-enqueue atomicity | concurrency |
| FR-013 | transient-error no-advance | concurrency |
| FR-014 | one cycle in flight (single-threaded) | concurrency, determinism, performance |
| FR-015 | fan-out | observability, performance |
| FR-016 | explicit master arbitration | determinism |
| FR-017 | auto master arbitration (lex-lowest) | determinism |
| **FR-018** | **no eligible master skip** | **(none)** |
| FR-019 | arbitration before render | performance |
| FR-020 | winner identity capture | determinism |
| FR-021 | target_rule=explicit resolution | determinism |
| FR-022 | target_rule=source resolution | determinism, security |
| FR-023 | target_rule=role resolution | determinism |
| FR-024 | FEAT-009 permission gate | security |
| FR-025 | template grammar | determinism, security, performance |
| FR-026 | FEAT-007 redaction for excerpt | audit, determinism, security, performance |
| FR-027 | FEAT-009 body validation | security |
| FR-028 | missing-field render error | determinism, security |
| FR-029 | message_queue extension (origin/route_id/event_id) | cli, data-model |
| FR-030 | UNIQUE (route_id, event_id) | data-model, concurrency, performance |
| FR-031 | schema v8 migration | data-model |
| FR-032 | single insert path | security |
| FR-033 | queue --origin filter | cli, data-model, performance |
| **FR-034** | **queue operator actions on route rows** | **(none)** |
| FR-035 | six audit event types | audit, observability, security |
| FR-036 | route_matched/skipped field set | audit |
| FR-037 | skip reason closed set | audit, observability, security |
| FR-038 | status routing section | observability, performance |
| FR-039 | audit-append failure retry | audit, concurrency, security, performance |
| FR-039a | routing_worker_heartbeat | audit, observability, determinism, concurrency |
| FR-040 | cycle interval bounds | determinism, performance |
| FR-041 | per-route batch cap | determinism, security, performance |
| FR-042 | route processing order | determinism |
| FR-043 | clean shutdown | concurrency |
| FR-044 | cold-start recovery | concurrency |
| FR-045 | route add --json shape | cli |
| **FR-046** | **route list --json shape** | **(none)** |
| FR-047 | route show --json + runtime sub-object | cli, observability |
| **FR-048** | **route remove/enable/disable --json shape** | **(none)** |
| FR-049 | closed-set CLI error vocab | cli |
| FR-050 | string codes (not integer) | cli |
| FR-051 | routing_worker_degraded surface | observability, concurrency, performance |
| **FR-052** | **no non-event triggers (timers, polling, webhooks)** | **(none)** |
| FR-053 | no model-based decisions | determinism, security |
| **FR-054** | **no TUI/web/notification surface** | **(none)** |
| FR-055 | cannot broaden FEAT-009 permissions | security |
| SC-001 | end-to-end 5s latency | performance |
| **SC-002** | **100% lex-lowest master arbitration over N=100** | **(none)** |
| **SC-003** | **100% skip + cursor-advance with no masters over N=10** | **(none)** |
| **SC-004** | **no duplicate rows over N=10 fault-injected crashes** | **(none)** |
| **SC-005** | **100% blocked rows under kill switch off** | **(none)** |
| SC-006 | route list 500ms @ 1000 routes | cli, observability, security, performance |
| SC-007 | route add validation 100ms | performance |
| SC-008 | self-contained audit line | audit |
| SC-009 | backlog drain ceil(backlog/batch) cycles | performance |
| SC-010 | byte-for-byte determinism | determinism |

**Summary** (initial audit): 7 FRs uncovered, 4 SCs uncovered. Each appeared below as a `[Gap]` item with the recommended target checklist for the fix.

**Remediation status** (2026-05-16): All 11 gaps resolved. 12 new items added across 5 domain checklists (`cli.md` CHK031-CHK035, `audit.md` CHK031-CHK032, `determinism.md` CHK031-CHK032, `concurrency.md` CHK031, `security.md` CHK031-CHK032). The `[Gap]` markers in §1 and §2 below have been replaced with `[Resolved]` plus cross-references; the bolded entries in the Coverage Map table above remain bolded for historical traceability.

---

## §1. FR Coverage Audit

- [X] CHK001 Is FR-007 (closed-set `route_master_rule_invalid` error for `--master-rule` outside `{auto, explicit}`) addressed by at least one requirements-quality item across the existing checklists? [Resolved → cli.md CHK031, Spec §FR-007]
- [X] CHK002 Is FR-018 (closed-set `no_eligible_master` skip with cursor advance and no queue row) addressed by a coverage or measurability item? [Resolved → audit.md CHK031, Spec §FR-018]
- [X] CHK003 Is FR-034 (FEAT-009 queue operator actions — `queue approve/delay/cancel` — applying unchanged to route-generated rows) addressed by a consistency item between FEAT-009 and FEAT-010 contracts? [Resolved → cli.md CHK032, Spec §FR-034]
- [X] CHK004 Is FR-046 (`route list --json` array-of-objects shape ordered by `created_at` ASC) addressed by a JSON-stability item? [Resolved → cli.md CHK033, Spec §FR-046]
- [X] CHK005 Is FR-048 (`route remove`/`enable`/`disable` `--json` one-object shape with `operation` + timestamp) addressed by a JSON-stability item? [Resolved → cli.md CHK034, Spec §FR-048]
- [X] CHK006 Is FR-052 (no non-event triggers — timers, polling, file watchers, webhooks are out-of-scope) addressed as an explicit exclusion item in any checklist? [Resolved → security.md CHK031, Spec §FR-052]
- [X] CHK007 Is FR-054 (no TUI / web UI / notification surface — CLI + JSONL only) addressed as an explicit exclusion item? [Resolved → cli.md CHK035, Spec §FR-054]
- [X] CHK008 Are all 57 FRs (FR-001..FR-055 plus FR-009a, FR-039a) traceable to at least one domain checklist item per the Coverage Map above? [Traceability, Spec §FR-*]
- [X] CHK009 Is the FR coverage matrix maintained as the spec evolves (e.g., new FR added → updated in this checklist)? [Process Gap]

## §2. SC Coverage Audit

- [X] CHK010 Is SC-001 (event-to-tmux ≤ 5s) addressed by a quantification + measurability item? [Coverage, Spec §SC-001] — covered by `performance.md`
- [X] CHK011 Is SC-002 (100% lex-lowest master arbitration over N=100 fires) addressed by a determinism + measurability item? [Resolved → determinism.md CHK031-CHK032, Spec §SC-002]
- [X] CHK012 Is SC-003 (100% skip + cursor-advance with no eligible master over N=10) addressed by an arbitration-failure measurability item? [Resolved → audit.md CHK032, Spec §SC-003]
- [X] CHK013 Is SC-004 (no duplicate (route_id, event_id) rows over N=10 fault-injected crashes) addressed by a concurrency-safety measurability item? [Resolved → concurrency.md CHK031, Spec §SC-004]
- [X] CHK014 Is SC-005 (100% blocked + cursor-advance with kill switch off) addressed by a kill-switch consistency item? [Resolved → security.md CHK032, Spec §SC-005]
- [X] CHK015 Is SC-006 (route list 500ms @ 1000 routes) addressed across multiple checklists for cross-cutting impact? [Coverage, Spec §SC-006] — covered by `cli`, `observability`, `security`, `performance`
- [X] CHK016 Is SC-007 (route add validation 100ms) addressed by a CLI-latency measurability item? [Coverage, Spec §SC-007] — covered by `performance.md`
- [X] CHK017 Is SC-008 (one-JSONL-line skip analysis) addressed by an audit self-containment item? [Coverage, Spec §SC-008] — covered by `audit.md`
- [X] CHK018 Is SC-009 (backlog drain in ceil(backlog/batch) cycles) addressed by a backlog-catch-up measurability item? [Coverage, Spec §SC-009] — covered by `performance.md`
- [X] CHK019 Is SC-010 (byte-for-byte deterministic replay) addressed by determinism + boundary-of-contract items? [Coverage, Spec §SC-010] — covered by `determinism.md`
- [X] CHK020 Are all 10 SCs measurable from CLI tools or test-harness output without external profiling? [Measurability, Spec §SC-001..010]

## §3. Clarification Coverage Audit

- [X] CHK021 Is Clarifications Q1 (source-scope symmetry with target — `role:<role>[,capability:<cap>]`) reflected in at least one requirements-quality item across checklists? [Coverage, Clarifications Q1] — covered by `cli` (CHK006, CHK010), `data-model` (CHK003), `audit` (CHK007 indirectly)
- [X] CHK022 Is Clarifications Q2 (target_agent_id + target_label on every route_matched/skipped audit row) reflected? [Coverage, Clarifications Q2] — covered by `audit.md` (CHK006, CHK028) and `observability.md`
- [X] CHK023 Is Clarifications Q3 (no per-cycle audit; rate-limited `routing_worker_heartbeat`) reflected? [Coverage, Clarifications Q3] — covered by `audit.md` (CHK002, CHK015-CHK020) and `observability.md`
- [X] CHK024 Is Clarifications Q4 (single-threaded sequential worker, no cycle overlap, no per-route parallelism) reflected? [Coverage, Clarifications Q4] — covered by `concurrency.md` (CHK001-CHK004) and `determinism.md` (CHK017)
- [X] CHK025 Is Clarifications Q5 (routes structurally immutable — no in-place edit) reflected? [Coverage, Clarifications Q5] — covered by `cli.md` (CHK002, CHK028)

## §4. Edge-Case Coverage Audit

The spec enumerates ~16 edge cases in its Edge Cases section. This audit asks whether the categories of edge cases are represented by at least one checklist item.

- [X] CHK026 Are route-lifecycle edge cases (route created after events exist; route disabled mid-cycle; route enabled after backlog accumulation) addressed by lifecycle items in any checklist? [Coverage, Edge Cases]
- [X] CHK027 Are kill-switch interaction edge cases (kill-switch-off rows land in blocked, cursor still advances) addressed? [Coverage, Edge Cases]
- [X] CHK028 Are arbitration-failure edge cases (no master at all; explicit master not found/inactive) addressed? [Coverage, Edge Cases]
- [X] CHK029 Are race-window edge cases (master deregistered between arbitration and enqueue; target deregistered between resolve and enqueue; route removed while queue row mid-delivery) addressed by `concurrency.md`? [Coverage, Edge Cases]
- [X] CHK030 Are storage-integrity edge cases (UNIQUE constraint defense-in-depth; FEAT-008 event purge below cursor; orphan route_id in queue history) addressed? [Coverage, Edge Cases]
- [X] CHK031 Are operator-pattern edge cases (overlapping routes producing fan-out; identical-selector routes producing duplicate prompts) addressed? [Coverage, Edge Cases]
- [X] CHK032 Are audit-degradation edge cases (JSONL append fail; buffer overflow) addressed? [Coverage, Edge Cases]
- [X] CHK033 Are daemon-shutdown edge cases (worker exits at cycle boundary; in-flight txn commits or rolls back) addressed? [Coverage, Edge Cases, Spec §FR-043]

## §5. Plan + Research Decision Coverage Audit

- [X] CHK034 Is research §R1 (single-threaded sequential worker) traceable to a quality item in `concurrency.md` or `determinism.md`? [Traceability, Plan §R1]
- [X] CHK035 Is research §R2 (BEGIN IMMEDIATE cursor-advance-with-enqueue + partial UNIQUE defense) traceable to items in `concurrency.md` and `data-model.md`? [Traceability, Plan §R2]
- [X] CHK036 Is research §R3 (source-scope grammar symmetry) traceable to items in `cli.md` and `data-model.md`? [Traceability, Plan §R3]
- [X] CHK037 Is research §R4 (audit target identity as first-class fields) traceable to items in `audit.md`? [Traceability, Plan §R4]
- [X] CHK038 Is research §R5 (heartbeat thread, no per-cycle audit) traceable to items in `audit.md` and `observability.md`? [Traceability, Plan §R5]
- [X] CHK039 Is research §R6 (route immutability) traceable to items in `cli.md` and addressable in tests? [Traceability, Plan §R6]
- [X] CHK040 Is research §R7 (single insert path via `enqueue_route_message` + underscore kw args) traceable to items in `security.md`? [Traceability, Plan §R7]
- [X] CHK041 Is research §R8 (per-(route, event) active-master snapshot timing) traceable to items in `determinism.md`? [Traceability, Plan §R8]
- [X] CHK042 Is research §R10 (schema v8 migration idempotency + partial UNIQUE index) traceable to items in `data-model.md`? [Traceability, Plan §R10]
- [X] CHK043 Is research §R11 (FEAT-009 exception → FEAT-010 skip-reason mapping) traceable to items in `audit.md` or `security.md`? [Traceability, Plan §R11]
- [X] CHK044 Is research §R12 (heartbeat thread vs in-worker — separate thread for non-blocking) traceable to items in `concurrency.md`? [Traceability, Plan §R12]
- [X] CHK045 Is research §R13 (CLI exit-code surface reuse) traceable to items in `cli.md`? [Traceability, Plan §R13]
- [X] CHK046 Is research §R14 (10K-entry bounded audit buffer with FIFO eviction) traceable to items in `audit.md` (CHK026)? [Traceability, Plan §R14]
- [X] CHK047 Is research §R15 (validation order at route add) traceable to items in `cli.md`? [Traceability, Plan §R15]

## §6. Contract Artifact Coverage Audit

- [X] CHK048 Is `contracts/cli-routes.md` (6 route subcommands, flag sets, JSON shapes, error codes) audited by `cli.md` for completeness? [Coverage, Contract Artifact]
- [X] CHK049 Is `contracts/cli-queue-origin.md` (--origin filter, JSON-shape extension) audited by `cli.md` for backward compatibility? [Coverage, Contract Artifact]
- [X] CHK050 Is `contracts/cli-status-routing.md` (status routing JSON shape, FEAT-009 inheritance for kill-switch object merge) audited by `observability.md`? [Coverage, Contract Artifact]
- [X] CHK051 Is `contracts/socket-routes.md` (6 socket methods, request/response, error envelopes) audited by `cli.md` (since CLI ↔ socket are 1:1) AND `security.md` (authorization)? [Coverage, Contract Artifact]
- [X] CHK052 Is `contracts/routes-audit-schema.md` (6 JSONL event types with field schemas) audited by `audit.md` for completeness AND consistency? [Coverage, Contract Artifact]
- [X] CHK053 Is `contracts/error-codes.md` (CLI codes, skip reasons, sub-reasons, internal codes, FEAT-009 exception map) audited by `audit.md` and `cli.md` for vocabulary completeness? [Coverage, Contract Artifact]

## §7. Cross-Artifact Traceability

- [X] CHK054 Is every clarification (Q1-Q5) traceable from spec.md → plan.md (Implementation Notes) → research.md (R-section) → contracts (where applicable) → at least one checklist item? [Traceability, Cross-Artifact]
- [X] CHK055 Is every closed-set string in `contracts/error-codes.md` (8 CLI codes + 10 skip reasons + 5 sub-reasons + 4 internal codes) traceable back to a spec FR or research decision? [Traceability, Contract Artifact]
- [X] CHK056 Is every test file enumerated in plan.md (Technical Context §Testing) covered by at least one requirements-quality item somewhere? [Coverage, Plan §Technical Context]
- [X] CHK057 Is the Risk Register in plan.md (§1-§6) reflected in at least one quality item per risk? [Coverage, Plan §Risk Register]
- [X] CHK058 Are the explicit out-of-scope items (FR-052, FR-053, FR-054, plus deferred swarm-member parsing and arbitration prompts per Assumptions) tracked as scope-boundary items so they cannot accidentally creep into FEAT-010 tasks? [Boundary, Spec §FR-052, FR-053, FR-054, Assumptions]

## §8. Coverage Verdict

- [X] CHK059 With the 7 FR gaps (FR-007, FR-018, FR-034, FR-046, FR-048, FR-052, FR-054) addressed, do the 9 checklists (8 deep + this coverage audit) collectively cover 100% of FR-001..FR-055 + FR-009a + FR-039a? [Completeness, All FRs]
- [X] CHK060 With the 4 SC gaps (SC-002, SC-003, SC-004, SC-005) addressed, do the checklists collectively cover 100% of SC-001..SC-010 with measurable items? [Measurability, All SCs]
- [X] CHK061 Are all 5 clarifications fully reflected (no orphaned answers from `## Clarifications` that no checklist item references)? [Completeness, Clarifications]
- [X] CHK062 Is this `coverage.md` checklist the SOLE remaining quality gate to run before `/speckit.tasks`, or are there additional cross-artifact items that `/speckit.analyze` would catch? [Process, Pre-Tasks]
- [X] CHK063 Are there NEW domains (e.g., `migration.md`, `integration.md`, `scope-boundary.md`, `test-plan.md`) the 8 existing deep checklists do not contemplate, but the spec/plan/contracts surface? [Gap Identification, Meta]

## Recommended remediation order

Before running `/speckit.tasks`, address gaps in this order (highest impact first):

1. **CHK013 (SC-004 — duplicate-routing safety)** → add measurability item to `concurrency.md` referencing the Story 4 fault-injection test.
2. **CHK002 (FR-018) + CHK012 (SC-003)** → add the `no_eligible_master` skip+cursor-advance pair to `audit.md` and `determinism.md`.
3. **CHK001 (FR-007)** → add `route_master_rule_invalid` to `cli.md` validation-vocabulary section.
4. **CHK006 + CHK007 (FR-052 + FR-054)** → add scope-boundary items; consider creating `scope-boundary.md` as a 9th deep checklist.
5. **CHK003 (FR-034)** → add cross-feature consistency item to `cli.md` (queue-extension section).
6. **CHK004 + CHK005 (FR-046 + FR-048)** → add JSON-shape items to `cli.md`.
7. **CHK014 (SC-005)** → add kill-switch threshold item to `security.md`.

After remediation, re-run this `coverage.md` audit to confirm all items become checkable.

---

## Remediation log

**2026-05-16** — All 11 gaps addressed. Items added (12 total):

| Original gap | New item(s) | Target checklist |
|---|---|---|
| CHK001 (FR-007) | CHK031 | cli.md |
| CHK002 (FR-018) | CHK031 | audit.md |
| CHK003 (FR-034) | CHK032 | cli.md |
| CHK004 (FR-046) | CHK033 | cli.md |
| CHK005 (FR-048) | CHK034 | cli.md |
| CHK006 (FR-052) | CHK031 | security.md |
| CHK007 (FR-054) | CHK035 | cli.md |
| CHK011 (SC-002) | CHK031 + CHK032 | determinism.md |
| CHK012 (SC-003) | CHK032 | audit.md |
| CHK013 (SC-004) | CHK031 | concurrency.md |
| CHK014 (SC-005) | CHK032 | security.md |

Coverage map status: 57/57 FRs covered, 10/10 SCs covered, 5/5 clarifications covered.
The decision NOT to create a separate `scope-boundary.md` was made because FR-052 and FR-054 each fit cleanly into existing checklist scopes (security and cli respectively), and a 10th checklist for two items would add navigation overhead without analytical benefit.
