# API & CLI Contract Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the CLI surface, JSON contract, exit-code vocabulary, and argument conventions. Tests whether the contract is fully specified, internally consistent, and machine-consumable — NOT whether the CLI actually runs.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## `send-input` Contract

- [ ] CHK001 Are `--message` and `--message-file` declared as mutually exclusive with a single-source-of-truth rule (exactly one required)? [Clarity, Spec §FR-007]
- [ ] CHK002 Is the behavior of `--message-file -` (stdin) defined, including the edge case of empty stdin? [Coverage, Spec §FR-007, §FR-003]
- [ ] CHK003 Is the default `send-input` wait behavior quantified with a configurable timeout default, and the configuration surface (e.g., `config.toml`) named? [Clarity, Spec §FR-009, §Assumptions]
- [ ] CHK004 Are `--no-wait` semantics specified for both the exit code and the `--json` output when the row is still in a non-terminal state at return time? [Completeness, Spec §FR-009, §FR-010]
- [ ] CHK005 Is the distinction between submit-time validation rejection (no row created) and post-enqueue rejection (row exists with `block_reason`) made unambiguous in CLI feedback? [Clarity, Spec §FR-010]
- [ ] CHK006 Is `send-input` declared as the sole row-creation entry point, with event-driven, scheduled, and implicit triggers explicitly excluded? [Completeness, Spec §FR-008, §FR-051]
- [ ] CHK007 Is the host-vs-bench-container origin rule documented in the `send-input` contract (not only in the permission section)? [Consistency, Spec §FR-006, §Clarifications]
- [ ] CHK008 Is the behavior on `--target` resolution failure (unknown agent_id) distinguished from "target inactive" with distinct closed-set error codes? [Clarity, Spec §FR-049, §US2 #4, §US2 #5]

## `queue` Subcommand Contract

- [ ] CHK009 Are the canonical filters (`--state`, `--target`, `--sender`, `--since`, `--limit`, `--json`) enumerated as the complete supported set? [Completeness, Spec §FR-031]
- [ ] CHK010 Is the AND-combination rule for multiple filters explicitly stated? [Clarity, Spec §FR-031, §US3 #2]
- [ ] CHK011 Is the ordering rule for `queue` listings stated deterministically (oldest `enqueued_at` first, `message_id` tie-breaker)? [Clarity, Spec §FR-031]
- [ ] CHK012 Are the preconditions for `approve`, `delay`, and `cancel` defined as a state × `block_reason` decision matrix that a script can implement without ambiguity? [Completeness, Spec §FR-033, §FR-034, §FR-035]
- [ ] CHK013 Is the `--limit` default documented (or stated as "no default cap")? [Gap, Coverage]
- [ ] CHK014 Are timestamp filters (`--since`) defined with an explicit format (ISO 8601 only? UNIX epoch acceptable?)? [Clarity, Gap]

## `routing` Subcommand Contract

- [ ] CHK015 Are the three routing subcommands (`enable`, `disable`, `status`) each given an explicit exit-code policy under success, no-change (already-in-state), and failure? [Completeness, Spec §FR-027]
- [ ] CHK016 Is the host-only origin constraint surfaced as a specific closed-set error code (`routing_toggle_host_only`) rather than a generic permission failure? [Clarity, Spec §FR-027, §FR-049, §Clarifications]
- [ ] CHK017 Is `routing status` required to expose the same fields under `--json` as in human-readable mode (last toggle timestamp, toggling identity, current state)? [Consistency, Spec §FR-027, §US4 #1]

## JSON Output Schema

- [ ] CHK018 Is the `--json` schema for `send-input` enumerated field-by-field with nullable markers? [Completeness, Spec §FR-011]
- [ ] CHK019 Is the same JSON shape required for all queue subcommands (`approve`/`delay`/`cancel`) to enable downstream tooling reuse? [Consistency, Spec §FR-011, §FR-032, §US3 #7]
- [ ] CHK020 Are JSON field types (timestamp encoding, redacted-string convention, role enum literal set) specified rather than left to implementer interpretation? [Clarity, Gap]
- [ ] CHK021 Is the "exactly one JSON object on stdout" guarantee applied uniformly across every `--json` callsite (`send-input`, `queue`, `queue approve/delay/cancel`, `routing status`)? [Consistency, Spec §FR-011, §SC-007]
- [ ] CHK022 Is the JSON output line format declared (single-line NDJSON-compatible vs pretty-printed)? [Gap, Clarity]
- [ ] CHK023 Is the field naming convention (snake_case vs camelCase) declared as a stability contract? [Gap, Consistency]

## Exit Code & Error Vocabulary

- [ ] CHK024 Is the closed-set error vocabulary listed exhaustively in one canonical place (FR-049) with every code consumed by a specific spec'd code path? [Completeness, Spec §FR-049]
- [ ] CHK025 Are integer exit codes declared as variable across revisions while the string code is the stable contract? [Clarity, Spec §FR-050]
- [ ] CHK026 Are exit-code requirements distinguished between terminal-success, terminal-failure, wait-timeout, and submit-validation-rejection? [Completeness, Spec §FR-010]
- [ ] CHK027 Is `daemon_unavailable` defined as a separate code from `daemon_shutting_down` (different semantics, different remediation)? [Clarity, Spec §FR-049]
- [ ] CHK028 Are `delivery_in_progress`, `approval_not_applicable`, `delay_not_applicable`, and `terminal_state_cannot_change` each tied to the precise state condition that triggers them? [Clarity, Spec §FR-033 – §FR-036]
- [ ] CHK029 Is `sender_not_in_pane` mapped specifically to the host-origin / unregistered-pane case and not overloaded with `sender_role_not_permitted`? [Clarity, Spec §FR-006, §Clarifications, §FR-049]
- [ ] CHK030 Are the closed-set error codes mutually exclusive on a single CLI invocation (no possibility of two simultaneous codes)? [Consistency, Gap]

## Argument Conventions

- [ ] CHK031 Is the acceptable form of `--target` defined unambiguously (agent_id only? label allowed? both with precedence rule?)? [Clarity, Gap]
- [ ] CHK032 Is the behavior of unknown CLI flags specified (reject with closed-set error vs ignore)? [Gap]
- [ ] CHK033 Is the CLI's help/usage output required to enumerate the same error codes documented in FR-049, so operators can self-serve remediation? [Coverage, Gap]
- [ ] CHK034 Is the thin-client-vs-daemon split surfaced in CLI behavior (e.g., is there a distinct error when the daemon is unreachable vs misbehaving)? [Coverage, Spec §FR-049]

## Notes

- Each item asks "is X specified", not "does X work" — these validate the contract before implementation.
- Gaps flagged here should be resolved during `/speckit.plan` (where implementation choices may reveal further contract ambiguity) or via `/speckit.clarify` if blocking.
- Check items off as completed: `[x]`. Reference the FR or spec section you updated to resolve each item.
