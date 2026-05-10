# CLI Contract & JSON Schema Stability Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that CLI surface, error contract, pagination, and JSONL stable-schema requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Are all `agenttower events` flags enumerated with their pairwise interactions defined (e.g., `--cursor` × `--reverse`, `--since` × `--follow`)? [Completeness, Spec §FR-030, FR-033]
- [ ] CHK002 Is the JSONL stable schema in FR-027 complete enough that every field is present (or required-null) for all 10 event types? [Completeness, Spec §FR-027]
- [ ] CHK003 Are exit-code requirements defined for each error class (`agent_not_found`, daemon-unavailable, follow-stream-failure, invalid-args)? [Completeness, Spec §FR-034, FR-035a]
- [ ] CHK004 Are pagination cursor encoding requirements specified (encoding format, opacity, version compatibility, expiration semantics)? [Completeness, Spec §FR-030]
- [ ] CHK005 Are requirements defined for `--type <event_type>` invalid-value behavior (unknown type → error vs ignore)? [Gap, Spec §FR-030]
- [ ] CHK006 Are requirements defined for `--since` / `--until` invalid ISO-8601 input handling? [Gap, Spec §FR-030]
- [ ] CHK007 Are requirements defined for `--limit` upper bound, zero, and below-zero handling? [Gap, Spec §FR-030]
- [ ] CHK008 Is `--target` agent-id syntactic validation specified BEFORE registry lookup (so syntactic errors are distinguishable from `agent_not_found`)? [Completeness, Gap]
- [ ] CHK009 Are requirements defined for `--type` repeatability semantics (multi-value OR vs intersect)? [Completeness, Spec §FR-030]
- [ ] CHK010 Is the `schema_version` field's required initial value and bump semantics documented (FR-027 says non-breaking only — defined how)? [Completeness, Spec §FR-027]

## Requirement Clarity

- [ ] CHK011 Is "stable contract for scripting consumers" measurable across schema-version bumps (a non-breaking-change rule is documented)? [Clarity, Spec §FR-032]
- [ ] CHK012 Is "documented MVP page size (≤ 50)" specifying default vs maximum unambiguously? [Ambiguity, Spec §FR-030]
- [ ] CHK013 Is "one JSON object per event, one event per line" explicitly required to be NDJSON-compatible (no embedded newlines, terminating `\n`)? [Clarity, Spec §FR-032]
- [ ] CHK014 Is "closed-set `agent_not_found` error" defined as a specific machine-readable code (string identifier? integer? both)? [Clarity, Spec §FR-035a]
- [ ] CHK015 Is "non-zero status" specified as an exact exit code per error class, or any non-zero value? [Ambiguity, Spec §FR-034, FR-035a]
- [ ] CHK016 Is "human output not contractually stable" explicit about which fields/columns may change vs which must stay? [Clarity, Spec §FR-031]

## Requirement Consistency

- [ ] CHK017 Is the JSONL schema in FR-027 exactly the same as the `--json` CLI output schema in FR-032 (same field set, types, ordering)? [Consistency, Spec §FR-027, FR-032]
- [ ] CHK018 Is `--target` semantics consistent between `events` and `events --follow` for both the empty-result and `agent_not_found` cases? [Consistency, Spec §FR-035a]
- [ ] CHK019 Are error-message conventions consistent across `events`, `events --follow`, and the daemon-unreachable surface (same code names, same exit codes)? [Consistency, Spec §FR-034, FR-035a]
- [ ] CHK020 Is the ordering contract in FR-028 consistent with the cursor encoding in FR-030 (cursor encodes the same tuple used for sorting)? [Consistency, Spec §FR-028, FR-030]
- [ ] CHK021 Is `event_id`'s integer-backed but CLI-opaque treatment in FR-030 consistent with its JSON-number serialization in FR-027? [Consistency, Spec §FR-027, FR-030, Clarifications]

## Acceptance Criteria Quality

- [ ] CHK022 Is SC-011's "zero schema validation failures" tied to a concrete schema artifact (JSON Schema file path, version pin)? [Measurability, Spec §SC-011]
- [ ] CHK023 Is SC-012's "identical output (modulo pagination cursor)" defined byte-for-byte or field-for-field? [Measurability, Spec §SC-012]
- [ ] CHK024 Are acceptance criteria defined for human-output formatting stability vs explicit non-stability (which fields are columns, which are free-form)? [Acceptance Criteria, Spec §FR-031]
- [ ] CHK025 Are acceptance criteria specified for cursor round-trip integrity (cursor from page N+1 returns the next page after N, never overlap)? [Acceptance Criteria, Gap]

## Scenario Coverage

- [ ] CHK026 Are requirements specified for `--follow` against an agent that becomes unregistered mid-stream? [Coverage, Gap]
- [ ] CHK027 Are requirements specified for `--follow` when the daemon restarts mid-stream? [Coverage, Gap]
- [ ] CHK028 Are requirements defined for `events --json --follow --since` (interleaving rules between bounded backlog and live stream)? [Coverage, Spec §FR-033]
- [ ] CHK029 Are requirements defined for empty-result vs error in `events --type <unknown>` vs `events --type <known but no matches>`? [Coverage, Gap]
- [ ] CHK030 Are requirements specified for `--target` agent registered but with attachment in `stale` (not `active`) status? [Coverage, Spec §US1 AS4, US4]
- [ ] CHK031 Are requirements specified for the host-vs-container parity contract (FR-035) at the failure surface (same exit codes from both)? [Coverage, Spec §FR-035, SC-012]

## Edge Case Coverage

- [ ] CHK032 Is the case "agent registered, no attachment ever created" distinguished from "agent registered, attachment was deleted" in CLI behavior? [Edge Case, Gap]
- [ ] CHK033 Are requirements defined for excerpts containing characters that need JSON escaping (control chars, surrogates, invalid UTF-8 bytes)? [Edge Case, Gap]
- [ ] CHK034 Is the case "events from before a schema_version bump" required to remain readable by the new CLI? [Edge Case, Gap]
- [ ] CHK035 Are requirements defined for stdout vs stderr separation in `events` failure output (so machine-parsing of stdout is safe)? [Edge Case, Gap]
- [ ] CHK036 Are requirements specified for SIGPIPE behavior when piping `events --follow` into `head` or similar? [Edge Case, Gap]
- [ ] CHK037 Is the case "`--limit 0`" specified (empty result with success vs validation error)? [Edge Case, Gap]

## Non-Functional Requirements

- [ ] CHK038 Are `events` query latency requirements quantified for large event tables (millions of rows)? [NFR, Gap]
- [ ] CHK039 Is follow-stream backpressure behavior specified when the operator's terminal is slow (drop? buffer? error)? [NFR, Gap]

## Dependencies & Assumptions

- [ ] CHK040 Is the dependency on FEAT-005 thin-client routing version-pinned to a specific socket protocol surface? [Dependency, Spec §FR-035]
