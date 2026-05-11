# Operator & Master UX Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the CLI-as-UX surface — operator command ergonomics, error-message clarity, listing format, multi-line body input, feedback latency, scriptability. Tests whether the operator-facing experience is specified (not just the contract), so a human can actually use FEAT-009 under pressure — NOT whether the CLI renders correctly.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## `send-input` Caller Experience

- [ ] CHK001 Is the default wait-or-timeout behavior of `send-input` documented in operator-facing help (not only in the spec's Assumptions)? [Gap, Spec §Assumptions]
- [ ] CHK002 Is the difference between exit-0 (`delivered`) and non-zero (`blocked`/`failed`/`canceled`/`timeout`) made unambiguous in human-readable output, not only by exit code? [Clarity, Spec §FR-010]
- [ ] CHK003 Are requirements defined for what `send-input` prints to stderr vs stdout under success and under each failure mode? [Gap, Clarity]
- [ ] CHK004 Is the operator informed (in human output) of the closed-set error code when a row is blocked or failed, so they can self-serve remediation via the queue commands? [Coverage, Spec §FR-049]
- [ ] CHK005 Is the operator-visible behavior when the daemon socket is missing or unreadable defined (clear error vs cryptic connection failure)? [Coverage, Spec §FR-049]

## Multi-Line & Special-Character Body Input

- [ ] CHK006 Is `--message-file` defined as the recommended path for shell-special-character or multi-line bodies, with `--message` discouraged for those cases in caller-facing docs? [Gap, Spec §FR-007]
- [ ] CHK007 Are the supported `--message-file` sources defined (filesystem path, `-` for stdin; no shell globbing, no URL fetch)? [Completeness, Spec §FR-007]
- [ ] CHK008 Are requirements specified for how multi-line bodies appear in the queue listing's excerpt (truncated at first newline, collapsed whitespace, or preserved up to cap)? [Gap, Clarity]
- [ ] CHK009 Is the behavior when `--message-file` points to a nonexistent or unreadable path defined (specific error vs generic I/O failure)? [Gap, Coverage]

## `queue` Listing Ergonomics

- [ ] CHK010 Are the listing's columns scannable by a human operator at typical terminal widths (≤120 columns), or is a `--wide` / `--json` escape hatch documented? [Gap, Measurability]
- [ ] CHK011 Is the listing's default time format (relative, absolute, or both) specified for the human-readable mode? [Gap, Clarity]
- [ ] CHK012 Is the listing's behavior under high row count defined (paging? truncation? default `--limit`)? [Coverage, Spec §FR-031]
- [ ] CHK013 Are filter-combination examples provided in caller-facing docs (e.g., "show all blocked rows targeted at agent X since yesterday")? [Gap, Coverage]
- [ ] CHK014 Is the operator told the total row count or "X of Y shown" when `--limit` truncates? [Gap, Coverage]

## Operator Override Commands

- [ ] CHK015 Is the operator informed which `block_reason` values are operator-resolvable vs intrinsic BEFORE they attempt `approve` (e.g., listed in the row display or `--help`)? [Coverage, Spec §FR-033]
- [ ] CHK016 Is the `delivery_in_progress` race specified as a transient error the operator should retry (with implicit guidance), vs a permanent rejection? [Clarity, Spec §FR-036]
- [ ] CHK017 Are requirements defined for confirming destructive operations (`cancel`, `routing disable`) in interactive sessions, or explicitly waived as out of scope for MVP? [Gap]
- [ ] CHK018 Is the operator told (in CLI output) what state the row transitioned to after a successful `approve`/`delay`/`cancel`, not just an exit-0 silence? [Coverage, Spec §FR-032, §US3 #7]
- [ ] CHK019 Is the operator told (in CLI output) the NEW `block_reason` on a `delay` action, distinct from any pre-existing block reason? [Coverage, Spec §FR-034]

## Feedback Latency

- [ ] CHK020 Is the operator-perceived latency between `send-input` completion and `queue` listing reflecting the new row quantified (or stated as immediate / single-transaction)? [Gap, Measurability]
- [ ] CHK021 Is the latency for `agenttower routing status` reflecting a recent toggle defined (immediate vs eventual)? [Gap, Measurability]
- [ ] CHK022 Is the typical "operator delays a queued row before it's picked up" timing window stated, so an operator knows whether their `delay` is likely to win the race? [Coverage, Spec §SC-008]

## JSON & Scripting

- [ ] CHK023 Is `--json` output specified as single-line (NDJSON-compatible) so it can be piped into `jq` or appended to a log file? [Gap, Clarity, §SC-007]
- [ ] CHK024 Are stable field names (snake_case) declared as a contract across all `--json` outputs? [Gap, Consistency]
- [ ] CHK025 Is the operator able to derive a single row's full history from `agenttower events --filter message_id=<id>` (or equivalent) alone? [Coverage, Spec §SC-006]
- [ ] CHK026 Are exit codes documented in operator-facing help (a single table of code-name → meaning), not just in the spec? [Gap, Coverage]

## Operator Mental Model

- [ ] CHK027 Is the operator told, in caller-facing docs, that `master` cannot `send-input` from the host CLI (so they're not confused by `sender_not_in_pane`)? [Coverage, Spec §FR-006, §Clarifications]
- [ ] CHK028 Is the operator told, in caller-facing docs, that toggling routing is host-only (so they're not confused by `routing_toggle_host_only` from inside a container)? [Coverage, Spec §FR-027, §Clarifications]
- [ ] CHK029 Is the operator told what "delivered" actually means (paste + Enter, not "agent acknowledged") so they don't infer reply semantics? [Coverage, Spec §FR-037, §FR-042]

## Notes

- These items test whether the operator-facing experience is specified, not whether it's pleasant.
- Resolution path: add Caller-facing docs to the spec, fill named Assumptions, or push UX details to `/speckit.plan` deliverables.
- Check items off as completed: `[x]`.
