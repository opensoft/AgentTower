# Operator & Master UX Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the CLI-as-UX surface — operator command ergonomics, error-message clarity, listing format, multi-line body input, feedback latency, scriptability. Tests whether the operator-facing experience is specified (not just the contract), so a human can actually use FEAT-009 under pressure — NOT whether the CLI renders correctly.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md)

## `send-input` Caller Experience

- [ ] CHK001 **Open**: whether `agenttower send-input --help` documents the default-wait-or-timeout behavior is not specified. Behavior IS documented in contracts/cli-send-input.md and FR-009, but the on-CLI help text is not declared.
- [X] CHK002 Exit-0 (delivered) vs non-zero outcomes have distinct human-readable lines (contracts/cli-send-input.md "Stdout / stderr discipline").
- [X] CHK003 stdout/stderr discipline per outcome declared (contracts/cli-send-input.md).
- [X] CHK004 Operator sees the closed-set error code in stderr: `send-input failed: <code> — <human message>` (contracts/cli-send-input.md).
- [X] CHK005 Socket-missing / unreadable → `daemon_unavailable` (contracts/error-codes.md).

## Multi-Line & Special-Character Body Input

- [ ] CHK006 **Open**: spec/plan/contracts do not formally recommend `--message-file` over `--message` for shell-special-character bodies. Quickstart.md uses it for SC-003 demonstration; the recommendation is implicit.
- [X] CHK007 `--message-file` sources declared (filesystem path, `-` for stdin); no globbing, no URL fetch (contracts/cli-send-input.md).
- [X] CHK008 Multi-line body excerpt rendering = redact → collapse whitespace → truncate → `…` (FR-047b + Clarifications Q3 of 2026-05-11).
- [ ] CHK009 **Open**: behavior on nonexistent / unreadable `--message-file` path is not specified (no dedicated closed-set code for "file unreadable" — would fall through to argparse's generic I/O error).

## `queue` Listing Ergonomics

- [ ] CHK010 **Open**: whether the listing fits ≤120 columns at typical agent_id/label widths is not declared; no `--wide` flag exists; `--json` is the escape hatch for any layout concern.
- [ ] CHK011 **Open**: human-mode default time format choice (relative `3m ago` vs absolute ISO-8601) is not stated. Same as observability CHK017.
- [X] CHK012 High-row-count behavior: `--limit` default = 100, max = 1000 (contracts/cli-queue.md); no paging in MVP; operator can re-query with `--since` for sliding windows.
- [X] CHK013 Filter-combination examples present in quickstart.md (e.g., `queue --state blocked --target worker-1`).
- [ ] CHK014 **Open**: whether the listing prints "X of Y rows shown" when `--limit` truncates is not declared.

## Operator Override Commands

- [ ] CHK015 **Open**: data-model.md §3.3 has the operator-resolvable matrix, but whether `queue --json` includes a per-row `is_operator_resolvable` field (or `queue --help` lists which `block_reason`s are resolvable) is not declared. Operators must consult docs to know which rows are `approve`-eligible.
- [ ] CHK016 **Open**: `delivery_in_progress` retry guidance is not specified — should the operator retry immediately (race continues until the in-flight row reaches terminal, typically ≤ 5 s) or back off?
- [ ] CHK017 **Open**: confirmation prompts for destructive operations (`cancel`, `routing disable`) are not in scope per the existing CLI pattern, but this isn't explicitly waived in the spec. (In FEAT-001..008 no confirmation prompts exist, so the convention is "no prompts".)
- [X] CHK018 Operator sees the new state after `approve`/`delay`/`cancel`: `approved: msg=<id> state=queued` (contracts/cli-queue.md).
- [ ] CHK019 **Open**: whether `queue delay` explicitly tells the operator the new `block_reason=operator_delayed` in human output (vs implying it via the state change) is not specified.

## Feedback Latency

- [X] CHK020 `send-input` → `queue` listing latency is single-SQLite-transaction (immediate from any other thread reading the same DB) per plan §"Implementation Notes".
- [X] CHK021 `routing status` reflects toggles immediately (write-through cache per plan §"In-memory state").
- [ ] CHK022 **Open**: the typical race window between operator `delay` and worker pickup is bounded by `delivery_worker_idle_poll_seconds = 0.1` s, but this is not stated as an operator-facing latency guarantee.

## JSON & Scripting

- [X] CHK023 `--json` is single-line NDJSON-compatible (contracts/queue-row-schema.md "Notes").
- [X] CHK024 `snake_case` field naming uniform across all `--json` outputs (contracts/queue-row-schema.md).
- [X] CHK025 Single-row history reconstructible via `agenttower events --target <agent>` then `jq 'select(.message_id == "...")'` — works post FR-046 dual-write (no new `--filter` flag needed).
- [ ] CHK026 **Open**: same as api CHK033 — whether `--help` documents the FR-049 closed-set codes is not specified.

## Operator Mental Model

- [X] CHK027 Quickstart.md documents the host-side `send-input` refusal with example (line 102-104), so operators expecting `sender_not_in_pane` know to run from inside the master's pane.
- [X] CHK028 Quickstart.md documents the host-only routing-toggle constraint with example (line 122).
- [X] CHK029 "Delivered" = paste + Enter (FR-037 + FR-042 + quickstart troubleshooting).

## Plan-Grounded Additions (2026-05-12 pass)

- [X] CHK030 Human-readable success line shape (`delivered: msg=<id> target=<label>(<agent_id>)`) declared in contracts/cli-send-input.md.
- [X] CHK031 `<label>(<agent_id-prefix>)` rendering consistent between `queue` listing and `send-input` success output (contracts/cli-queue.md + cli-send-input.md).
- [ ] CHK032 **Open**: `--message-file -` EOF semantics not explicitly declared. Implicit: read until stdin EOF. Should clarify whether a body ending without a trailing newline is delivered byte-exact (it should be, per FR-005).
- [X] CHK033 `routing_disabled` (CLI exit 2 for `send-input`) vs `routing_toggle_host_only` (CLI exit 19 for `routing disable`) are distinct codes with distinct messages (contracts/error-codes.md "kill_switch_off vs routing_disabled" note).
- [X] CHK034 Human error message template `send-input failed: <code> — <human message>` declared in contracts/cli-send-input.md.
- [X] CHK035 Quickstart §"Troubleshooting" is operator-facing documentation accompanying the spec set (quickstart.md).
- [ ] CHK036 **Open**: when `agenttowerd` is not running at all, the CLI surfaces `daemon_unavailable` but a remediation hint (e.g., "start with `agenttowerd &`") is not specified.
- [ ] CHK037 **Open**: whether `queue --help` documents both `--since` forms (ms UTC + seconds UTC) is not declared.
- [X] CHK038 `--no-wait` with `--json` interaction implicit: with `--no-wait`, `--json` returns the row in its initial state (typically `queued`), with `--wait`, in its terminal state or last observed state (contracts/cli-send-input.md "Exit codes" "`delivery_wait_timeout`" path).
- [ ] CHK039 **Open**: behavior of `--target` against a label containing a hyphen, space, or Unicode glyph is not specified. FEAT-006 label charset is ASCII-printable per its FR-005, but the resolver's whitespace/unicode handling is undefined.
- [ ] CHK040 **Open**: long-label truncation in `queue` listing rows is not specified — labels longer than ~20 chars would break column alignment at 120-col terminals.

## Notes

- 23/40 items resolved by spec/plan/contracts through the 2026-05-12 remediation; **17 remain open**.
- UX has the most open items because operator-facing `--help` text, CLI rendering details, and operator-facing documentation are mostly polish work that lands during implementation rather than being pinned in the spec/plan/contracts surface.
- **Outstanding decisions for the user**: CHK001 (`--help` content), CHK006 (`--message-file` recommendation), CHK009 (nonexistent file error), CHK010 (terminal width), CHK011 (time format), CHK014 (truncation notice), CHK015 (operator-resolvable hint surface), CHK016 (`delivery_in_progress` retry), CHK017 (destructive-op confirmation), CHK019 (delay output detail), CHK022 (delay-race latency), CHK026 (`--help` error-code listing), CHK032 (stdin EOF semantics), CHK036 (daemon-not-running hint), CHK037 (`--since` form documentation), CHK039 (label edge characters), CHK040 (label truncation).
