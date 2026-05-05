# Degraded State and Reconciliation Contracts Checklist: Bench Container Discovery

**Purpose**: Validate that FEAT-003's requirements around degraded-scan semantics, the reconciliation state machine, and the contracts that surface them (socket envelope, CLI exit codes, persisted rows, JSONL events, lifecycle log) are written well — complete, unambiguous, consistent, measurable, and free of contradictions — before `/speckit.tasks` consumes the spec.
**Created**: 2026-05-05
**Feature**: [spec.md](../spec.md) — see also [plan.md](../plan.md), [research.md](../research.md), [data-model.md](../data-model.md), [contracts/cli.md](../contracts/cli.md), [contracts/socket-api.md](../contracts/socket-api.md)

**Scope**: Tests requirements quality only; does NOT verify implementation. Sibling checklist [security.md](./security.md) covers the Docker subprocess and authorization surface; this file focuses on the semantics of *what is recorded and how it is reconciled* under healthy vs degraded outcomes.

## Degraded vs Healthy Status Definitions

- [x] CHK001 Are the precise conditions that produce `container_scans.status = 'ok'` enumerated (no Docker error AND every matching candidate inspected cleanly), with no remaining ambiguous "happy path" wording? [Clarity, Spec FR-018, Spec FR-019, Data-Model §2.2]
- [x] CHK002 Are the precise conditions that produce `container_scans.status = 'degraded'` enumerated (any docker_unavailable / permission_denied / timeout / non-zero exit / malformed inspect / config_invalid OR ≥1 inspect failure on a matching candidate)? [Completeness, Spec FR-018, Research R-014]
- [x] CHK003 Is the asymmetry between "envelope `ok: false`" (whole-scan failure, no result object but an audit row is still persisted) and "envelope `ok: true` with `result.status = "degraded"`" (partial result) unambiguous and consistent across spec, plan, contracts, and quickstart? [Consistency, Contracts socket-api.md §3, Quickstart §5.3]
- [x] CHK004 Is it explicit which whole-scan-failure cases STILL write a `container_scans` row (and a JSONL event) versus those that do NOT? [Clarity, Contracts socket-api.md §3.4, Spec FR-019]
- [x] CHK005 Are the requirements clear that a degraded scan never silently widens active scope to non-matching containers, even when Docker output is partially malformed? [Consistency, Spec FR-006, Spec FR-008, Spec FR-030]

## Reconciliation State Transitions

- [x] CHK006 Are the four reconciliation outcomes per matching candidate enumerated explicitly: insert-as-active, update-and-mark-active, touch-only-on-inspect-failure, mark-inactive? [Completeness, Data-Model §4.1, §5]
- [x] CHK007 Is the requirement explicit that ONLY a *successful* `docker ps` triggers active→inactive transitions for previously-active rows, and that a failed `docker ps` MUST NOT inactivate anything? [Consistency, Spec FR-012, Gap]
- [x] CHK008 Does the spec state precisely what "successful later running-container scan" in FR-012 means in the presence of partial inspect failures (i.e., is reconciliation still authoritative for the absent-from-`docker ps` cohort even when some inspects failed)? [Ambiguity, Spec FR-012]
- [x] CHK009 Is the FR-026 inspect-failure preservation rule defined for both branches (prior-record-exists vs no-prior-record) with no remaining ambiguity about *which* fields are preserved and which are updated? [Clarity, Spec FR-026, Data-Model §4.1]
- [x] CHK010 Does the spec define the outcome when a container that was previously inactive reappears in `docker ps` AND its inspect succeeds (re-activation: `active=1`, `last_scanned_at` updated, `first_seen_at` preserved)? [Coverage, Gap, Data-Model §2.1]
- [x] CHK011 Does the spec define the outcome when a container that was previously inactive reappears in `docker ps` but its inspect FAILS (FR-026 covers prior-record but the prior `active` flag is `0` — does the row stay inactive or transition to active using stale data)? [Edge Case, Ambiguity, Spec FR-026]
- [x] CHK012 Are the requirements explicit that `first_seen_at` is set on first INSERT and never updated thereafter, even on container-id reuse? [Consistency, Spec Assumptions, Data-Model §2.1]
- [x] CHK013 Does the spec define the active/inactive state for matching candidates that appeared in `docker ps` but failed inspect AND have no prior row — confirming no row is created at all (so `active` is N/A) and that this candidate is NOT counted in `matched_count`? [Clarity, Spec FR-026, Coverage]

## Counter Semantics

- [x] CHK014 Is `matched_count` defined precisely as matching parseable `docker ps` rows for this scan, including matching candidates whose inspect failed? [Clarity, Data-Model §2.2, §5]
- [x] CHK015 Is `inactive_reconciled_count` defined precisely (number of previously-active rows transitioned to active=0 in this scan, excluding rows that were already inactive)? [Clarity, Data-Model §2.2]
- [x] CHK016 Is `ignored_count` defined precisely (running containers in `docker ps` that did NOT match the rule), and is the boundary between "ignored" and "matched-but-failed-inspect-with-no-prior-record" unambiguous? [Clarity, Data-Model §2.2]
- [x] CHK017 Are the counter definitions consistent across spec.md FR-019/FR-025, data-model.md §2.2, contracts/socket-api.md §3.2, and contracts/cli.md C-CLI-201 stdout block? [Consistency]
- [x] CHK018 Is the requirement explicit about whether the counters refer to *this scan* only or cumulative-since-history (and therefore reset every scan)? [Ambiguity, Gap]
- [x] CHK019 Are the counters required to sum to the input population (`matched + ignored == |docker ps rows|` minus malformed-row count) so callers can detect parser drops? [Coverage, Gap]

## Atomicity and Commit Boundary

- [x] CHK020 Is the requirement explicit that the `container_scans` row insert and all `containers` upsert/touch/inactivate writes for a single scan commit in ONE SQLite transaction? [Completeness, Plan Constraints, Research R-005]
- [x] CHK021 Does the spec define the outcome if the SQLite transaction fails partway (rollback semantics, what the caller sees, whether a JSONL event is still emitted)? [Coverage, Gap]
- [x] CHK022 Are the requirements explicit about the order of side-effects: SQLite commit FIRST, JSONL append SECOND, lifecycle log SECOND-or-LAST, socket response LAST — so that a crash mid-flight cannot leave durable state inconsistent with what the caller observed? [Clarity, Gap]
- [x] CHK023 Does the spec address what happens to `events.jsonl` if a degraded scan's SQLite write succeeds but the JSONL append fails (or vice versa)? [Edge Case, Gap]
- [x] CHK024 Is the requirement explicit that the scan mutex is released ONLY after the SQLite commit (so a second scan never sees half-applied state)? [Completeness, Spec FR-023, Research R-005]

## Per-Container Error Attribution

- [x] CHK025 Does the spec define the exact shape of `error_details_json` entries (`{container_id, error_code, error_message}`) and require that this shape is identical at the SQLite boundary, the socket boundary, and the JSONL boundary? [Consistency, Data-Model §2.2, Contracts socket-api.md §3.3]
- [x] CHK026 Is the requirement clear that per-container errors only appear in `error_details_json` for matching candidates (non-matching candidates that fail to parse are NEVER attributed there)? [Clarity, Gap]
- [x] CHK027 Is the closed set of `error_code` tokens that may appear inside `error_details_json` enumerated, and is it a strict subset of the top-level closed-error set? [Completeness, Research R-014]
- [x] CHK028 Are the requirements explicit about whether a single matching candidate may produce MULTIPLE entries in `error_details_json` (e.g., timeout AND malformed) or AT MOST ONE? [Ambiguity, Gap]
- [x] CHK029 Is the requirement clear that the top-level `error_code` for a partial-failure scan is the *representative* code (not "mixed"), and is the rule for choosing the representative documented? [Clarity, Research R-014]
- [x] CHK030 Does the spec define the bounded length and sanitization rules for `error_details_json[*].error_message` (matching FR-032's 2048-char + NUL/control-byte rule for top-level `error_message`)? [Consistency, Spec FR-032, Spec FR-033]

## Idempotency and Replay

- [x] CHK031 Are the requirements explicit that two healthy scans run back-to-back against an unchanged Docker state produce two distinct `container_scans` rows with distinct `scan_id` values, but converge `containers` rows to the same content (idempotent reconciliation)? [Completeness, Gap]
- [x] CHK032 Is `scan_id` uniqueness guaranteed (UUID4 collision risk acknowledged or formally rejected) and is the requirement clear that an existing `scan_id` is NEVER reused? [Clarity, Spec Assumptions]
- [x] CHK033 Does the spec define the outcome of replaying the same `scan_containers` socket request twice in quick succession with respect to the mutex (each blocks separately, both produce distinct rows)? [Coverage, Spec FR-023]
- [x] CHK034 Is the requirement explicit that JSONL events for the same `scan_id` are NEVER appended more than once (one-event-per-degraded-scan invariant)? [Completeness, Spec FR-019, Research R-015]

## Healthy-Scan No-Side-Effect Invariants

- [x] CHK035 Is the requirement explicit that healthy scans append NOTHING to `events.jsonl` — and is "healthy" defined identically here as in the degraded definitions above? [Consistency, Spec FR-019, Quickstart §5.4]
- [x] CHK036 Is the requirement explicit that healthy scans STILL emit `scan_started` and `scan_completed` rows to the lifecycle log (i.e., lifecycle log is independent of the `events.jsonl` quietness rule)? [Clarity, Research R-015]
- [x] CHK037 Does the spec define what an empty-result healthy scan (zero matching containers, zero ignored, zero reconciled) writes — confirming a `container_scans` row is still inserted with all counters zero? [Coverage, Gap]

## CLI Exit Code and Output Contracts

- [x] CHK038 Is the mapping from `result.status` to CLI exit code (0 for ok, 5 for degraded) consistent across spec, plan, and contracts/cli.md? [Consistency, Contracts cli.md C-CLI-201]
- [x] CHK039 Is the CLI behavior on the partial-degrade path (envelope `ok: true`, `result.status = "degraded"`) clearly distinguished from the whole-scan-failure path (envelope `ok: false`) in stderr format AND exit code? [Clarity, Contracts cli.md §C-CLI-201]
- [x] CHK040 Are the stdout `key=value` lines for `agenttower scan --containers` consistent with the JSON shape they summarize (every key on stdout has a corresponding field in `result`)? [Consistency, Contracts cli.md C-CLI-201]
- [x] CHK041 Is `duration_ms` defined unambiguously (computed client-side from response `completed_at - started_at`) so two callers measuring the same scan see the same value? [Clarity, Contracts cli.md C-CLI-201]
- [x] CHK042 Is the requirement explicit that `agenttower list-containers` exit codes do NOT include `5` (degraded) because `list-containers` cannot trigger a degraded outcome? [Consistency, Contracts cli.md C-CLI-202]

## Schema Migration v1 → v2

- [x] CHK043 Is the requirement explicit that the v1 → v2 migration runs under a single transaction and is idempotent on re-open? [Completeness, Research R-012]
- [x] CHK044 Does the spec define what happens if migration v2 fails partway (rollback to v1 vs. partial commit, daemon refusal to serve, error code surfaced)? [Coverage, Gap]
- [x] CHK045 Is the FEAT-003 daemon's behavior when opened against a v3 (future) database explicit (refuse to start vs. forward-compat tolerance)? [Edge Case, Gap, Data-Model §7]
- [x] CHK046 Is the FEAT-002 daemon's behavior when opened against a v2 (future) database documented as "refuse to start; downgrade is not supported"? [Consistency, Data-Model §7, Spec Assumptions]
- [x] CHK047 Does the spec define the migration's effect on a v1 database that contains zero rows in any table (confirm no-op aside from inserting the new tables and bumping `schema_version`)? [Coverage, Gap]

## Reordering, Tiebreakers, and Determinism

- [x] CHK048 Is the `list_containers` ordering rule (`active DESC, last_scanned_at DESC, container_id ASC`) defined consistently and identified as a stable, deterministic ordering? [Clarity, Spec FR-016, Research R-011]
- [x] CHK049 Is the requirement explicit that the same `last_scanned_at` for two rows with the same `active` value is broken by `container_id ASC` (not by SQLite default row order)? [Edge Case, Research R-011]
- [x] CHK050 Are the requirements clear about whether the `containers` rows returned by `list_containers` reflect the latest *committed* scan (not in-flight state) — i.e., the read query MUST run after any in-flight scan's commit OR with a snapshot that excludes in-flight changes? [Coverage, Gap]
- [x] CHK051 Does the spec define whether `list-containers` results are deterministic between two consecutive calls with no intervening scan (no spurious row reorder)? [Measurability, Gap]

## Lifecycle Log and Audit Trail Coherence

- [x] CHK052 Is the requirement explicit that every `container_scans` row has a corresponding `scan_started` AND `scan_completed` lifecycle log line referencing the same `scan_id`? [Completeness, Research R-015]
- [x] CHK053 Is the requirement explicit that a degraded scan's JSONL event references the same `scan_id` that appears in the `container_scans` row (audit trail correlation)? [Consistency, Research R-006]
- [x] CHK054 Does the spec define the behavior when the lifecycle log emit fails (e.g., disk full): does the scan still commit to SQLite, still emit the JSONL event, still respond to the caller? [Coverage, Gap]
- [x] CHK055 Is the order of writes (lifecycle log `scan_started` BEFORE Docker calls; lifecycle log `scan_completed` AFTER SQLite commit) documented as a requirement, not just a research hint? [Clarity, Research R-015]

## Configuration-Driven Reconciliation

- [x] CHK056 Does the spec define what happens to existing container rows when `name_contains` is changed between scans (e.g., a previously-matching name no longer matches)? Is the now-non-matching container marked inactive, left alone, or treated as ignored? [Edge Case, Gap]
- [x] CHK057 Is the requirement explicit that the matching rule is applied to `docker ps`-reported names (post slash-strip) AND consistently to all subsequent reconciliation steps within the same scan (no rule drift mid-scan)? [Consistency, Research R-002, R-003]
- [x] CHK058 Does the spec define whether matching is applied case-insensitively at both rule-substring AND container-name comparison sides (consistent case folding)? [Clarity, Spec FR-004]
- [x] CHK059 Is the requirement clear that `config_invalid` short-circuits the scan BEFORE any Docker call, so a misconfigured config never spawns subprocesses? [Coverage, Spec FR-006, Spec FR-030]

## Cross-Boundary Shape Consistency (Contract Drift)

- [x] CHK060 Is the JSON shape returned by `scan_containers` socket method, surfaced by `agenttower scan --containers --json`, and persisted into `container_scans` (decoded) demonstrably equivalent (one canonical shape, not three near-duplicates that can drift)? [Consistency, Data-Model §6, Contracts cli.md, Contracts socket-api.md]
- [x] CHK061 Is the JSON shape returned by `list_containers`, surfaced by `agenttower list-containers --json`, and stored as decoded `containers` rows demonstrably equivalent? [Consistency, Data-Model §6, Contracts cli.md, Contracts socket-api.md]
- [x] CHK062 Are the field NAMES in the wire JSON aligned across socket-api and cli (e.g., `matched_count` vs `matched`) — confirming the documented mapping (CLI uses `matched`, JSON uses `matched_count`) is intentional and explicitly noted as such? [Clarity, Contracts cli.md, Contracts socket-api.md, Ambiguity]

## Notes

- Check items off as completed: `[x]`
- Each item asks "Is the *requirement* clear/complete/consistent/measurable?" — not "Does the code do X?".
- `[Gap]` items are likely actionable: either add the missing requirement to spec.md / plan.md / research.md / data-model.md, or explicitly defer with rationale.
- `[Ambiguity]` and `[Conflict]` items should be resolved by another `/speckit.clarify` round before `/speckit.tasks`.
- This checklist is the second-pass quality gate after `security.md`; together they cover the bulk of the FEAT-003 risk surface. If both pass, the spec is ready for `/speckit.tasks`.

## Closure Notes

- Closed after adding FR-037 through FR-050 and updating plan/research/data-model/contracts to cover whole-scan audit rows, exact status definitions, reconciliation after partial inspect failures, counter semantics, SQLite transaction rollback, side-effect ordering, per-container error shape, scan id idempotency, migration failure behavior, deterministic list reads, config-driven inactivation, and config-invalid short-circuiting.
