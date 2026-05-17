# CLI Contract Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for the FEAT-010 CLI surface — command coverage, flag specification, JSON shape stability, exit-code contract, and error-vocabulary completeness.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## Command Surface Completeness

- [X] CHK001 Are all `agenttower route` subcommands fully enumerated in the spec (add, list, show, remove, enable, disable)? [Completeness, Spec §FR-004]
- [X] CHK002 Is the absence of a `route update` command stated as intentional rather than left implicit? [Completeness, Spec §FR-009a, Clarifications]
- [X] CHK003 Is the `route reset-cursor` deferral explicitly out-of-scope with a successor reference? [Completeness, Spec §Edge Cases, Assumptions]
- [X] CHK004 Are the `agenttower routing enable/disable` commands (FEAT-009 inheritance) explicitly identified as the kill-switch, not new FEAT-010 surface? [Consistency, Spec §Story 5]

## Flag & Argument Specification

- [X] CHK005 Is the full flag set for `route add` enumerated (--event-type, --source-scope, --target, --target-rule, --master, --master-rule, --template, --json)? [Gap]
- [X] CHK006 Is the CLI flag pattern for `--source-scope` (or equivalent) defined symmetrically with `--target-rule`? [Spec §FR-006, Clarifications]
- [X] CHK007 Are required-vs-optional flag semantics specified per command? [Gap]
- [X] CHK008 Are flag short-form aliases (e.g., `-e` for `--event-type`) specified or explicitly out-of-scope? [Gap]
- [X] CHK009 Are mutually-exclusive flag combinations documented (e.g., `--target` vs `--target-rule=source`)? [Gap]
- [X] CHK010 Is the canonical encoding for `--source-scope` value (`role:slave,capability:codex`) specified with escape rules for commas/colons in values? [Clarity, Spec §FR-001, FR-006]

## JSON Output Stability

- [X] CHK011 Is the JSON output schema for each `--json` flag specified as a stable contract (field set, types, nullability)? [Clarity, Spec §FR-045..048]
- [X] CHK012 Is the JSON field ordering specified or declared insensitive? [Gap]
- [X] CHK013 Is the policy on additive JSON fields across schema versions documented? [Gap]
- [X] CHK014 Is the `runtime` sub-object in `route show --json` schema-versioned alongside the route object? [Spec §FR-047, Gap]
- [X] CHK015 Are the JSON field names for new FEAT-010 columns (`origin`, `route_id`, `event_id`) consistent between `route list`, `queue list`, and audit JSONL? [Consistency, Spec §FR-029, FR-033, FR-046]

## Exit Code & Error Vocabulary

- [X] CHK016 Is the integer-to-string exit-code mapping documented and stable across versions? [Spec §FR-050]
- [X] CHK017 Is the closed-set FEAT-010 CLI error vocabulary complete for every documented rejection path? [Completeness, Spec §FR-049]
- [X] CHK018 Is `route_source_scope_invalid` added to the error vocabulary after the source-scope symmetry clarification? [Spec §FR-049, Clarifications]
- [X] CHK019 Are exit codes for transient failures (SQLite locked, daemon unreachable) distinct from validation failures? [Gap]
- [X] CHK020 Is the precedence of CLI error checks specified when multiple validations fail simultaneously? [Ambiguity, Spec §FR-005..008]

## Output Channels & Formatting

- [X] CHK021 Are stdout-vs-stderr conventions specified for human, --json, and error outputs? [Gap]
- [X] CHK022 Is color/no-color output policy specified for human format? [Gap]
- [X] CHK023 Is pagination behavior for `route list` defined at scale (1000 routes per SC-006)? [Coverage, Spec §SC-006]
- [X] CHK024 Are output filters (e.g., `--enabled-only`, `--target <agent>`) for `route list` specified or explicitly out-of-scope? [Gap]
- [X] CHK025 Is the `--origin` filter for `agenttower queue` specified with explicit value enumeration (`direct`, `route`)? [Spec §FR-033]

## Lifecycle & Idempotency

- [X] CHK026 Is idempotency behavior consistent across `enable`/`disable`/`remove` (no-op succeeds vs error)? [Consistency, Spec §FR-009]
- [X] CHK027 Is `route remove <unknown-id>` exit behavior consistent with `route show <unknown-id>` and `route enable <unknown-id>`? [Consistency, Spec §FR-049]
- [X] CHK028 Is the immutability contract (no in-place edit) discoverable from CLI help, not just from the spec? [Spec §FR-009a, Gap]

## Documentation & Discoverability

- [X] CHK029 Are CLI help-text content requirements (per-command description, flag descriptions) specified? [Gap]
- [X] CHK030 Is the relationship between FEAT-010 CLI commands and FEAT-009 commands (queue, status, events) documented for operators? [Gap]

## Coverage-Gap Remediation (added 2026-05-16 per coverage.md audit)

- [X] CHK031 Is the closed-set `route_master_rule_invalid` error code present in the CLI error vocabulary for `--master-rule` values outside `{auto, explicit}`? [Completeness, Spec §FR-007, FR-049]
- [X] CHK032 Are FEAT-009 queue operator actions (`queue approve`/`delay`/`cancel`) explicitly documented as applying unchanged to route-generated rows — no additional permission, no new exit code, audit shape identical to direct-send rows? [Consistency, Spec §FR-034]
- [X] CHK033 Is the `route list --json` output schema specified as an array of route objects ordered by `created_at` ASC with `route_id` lex tiebreak? [Clarity, Spec §FR-046]
- [X] CHK034 Is the `route remove`/`enable`/`disable` `--json` output schema specified as exactly one object containing `route_id`, `operation`, and a timestamp? [Clarity, Spec §FR-048]
- [X] CHK035 Is the explicit exclusion of TUI, web UI, and desktop-notification surfaces (CLI + JSONL only) documented as a scope boundary so it cannot drift into the implementation? [Boundary, Spec §FR-054]
