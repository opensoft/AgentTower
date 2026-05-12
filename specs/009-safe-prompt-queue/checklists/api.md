# API & CLI Contract Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the CLI surface, JSON contract, exit-code vocabulary, and argument conventions. Tests whether the contract is fully specified, internally consistent, and machine-consumable — NOT whether the CLI actually runs.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md)

## `send-input` Contract

- [X] CHK001 `--message` / `--message-file` mutually exclusive, exactly one required (FR-007).
- [X] CHK002 `--message-file -` (stdin) defined; empty-stdin path → `body_empty` per FR-003 (contracts/cli-send-input.md).
- [X] CHK003 Default wait = 10 s, configurable via `[routing].send_input_default_wait_seconds` in config.toml (FR-009 + Assumptions + plan §"Defaults locked").
- [X] CHK004 `--no-wait` semantics for exit code + `--json` (FR-009 + FR-010 + contracts/cli-send-input.md).
- [X] CHK005 Submit-time validation (no row) vs post-enqueue rejection (row with `block_reason`) distinguished in CLI feedback (FR-010 + contracts/cli-send-input.md "Exit codes").
- [X] CHK006 `send-input` is sole row-creator (FR-008 + FR-051 + T094a negative-requirement test).
- [X] CHK007 Host-vs-container origin documented in contracts/cli-send-input.md "Caller context" + spec FR-006 (post-Clarifications session 2 Q3).
- [X] CHK008 `agent_not_found` (resolution miss) vs `target_not_active` (registered but inactive) are distinct codes in FR-049 + contracts/error-codes.md.

## `queue` Subcommand Contract

- [X] CHK009 Canonical filter set declared (`--state`, `--target`, `--sender`, `--since`, `--limit`, `--json`) in FR-031 + contracts/cli-queue.md.
- [X] CHK010 AND-combination of filters stated (FR-031 + US3 #2).
- [X] CHK011 Ordering rule: `enqueued_at` ASC, `message_id` tie-breaker (FR-031 + contracts/cli-queue.md).
- [X] CHK012 `approve`/`delay`/`cancel` preconditions formalized as a state × `block_reason` matrix (FR-033/034/035/036 + data-model.md §3.3 "Operator-resolvable block reasons" table).
- [X] CHK013 `--limit` default = 100 (contracts/cli-queue.md), max = 1000.
- [X] CHK014 `--since` accepts canonical ms UTC form and seconds UTC form (FR-012b + Clarifications Q5 of 2026-05-11 + contracts/cli-queue.md).

## `routing` Subcommand Contract

- [X] CHK015 Exit-code policy declared for each of `enable`/`disable`/`status` under success / no-change / failure (contracts/cli-routing.md).
- [X] CHK016 `routing_toggle_host_only` is a specific closed-set code (FR-027 + Clarifications session 2 Q2 + FR-049).
- [X] CHK017 `routing status --json` exposes the same field set as human-readable mode (contracts/socket-routing.md "Success response" + US4 #1).

## JSON Output Schema

- [X] CHK018 `send-input` `--json` schema enumerated with nullable markers (FR-011 + contracts/queue-row-schema.md).
- [X] CHK019 Same JSON shape across `send-input`, `approve`, `delay`, `cancel` (FR-011 + FR-032 + US3 #7 + contracts/queue-row-schema.md).
- [X] CHK020 JSON field types specified — timestamp pattern, identity regex, role enum (contracts/queue-row-schema.md JSON Schema patterns).
- [X] CHK021 "Exactly one JSON object on stdout" applied to every `--json` callsite (FR-011 + SC-007 + contracts/queue-row-schema.md "Notes").
- [X] CHK022 Single-line NDJSON-compatible declared in contracts/queue-row-schema.md "Notes".
- [X] CHK023 `snake_case` field naming used uniformly across all `--json` outputs (contracts/queue-row-schema.md JSON Schema + contracts/queue-audit-schema.md); enforced by JSON Schema `additionalProperties: false` and explicit field names.

## Exit Code & Error Vocabulary

- [X] CHK024 FR-049 enumerates the full closed-set vocabulary (24 codes after the 2026-05-12 remediation, incl. `agent_not_found`, `message_id_not_found`, `since_invalid_format`).
- [X] CHK025 Integer exit codes are variable, string codes are stable (FR-050 + contracts/error-codes.md).
- [X] CHK026 Exit-code categories distinguished: terminal-success / terminal-failure / wait-timeout / submit-validation-rejection (FR-010 + contracts/error-codes.md integer map).
- [X] CHK027 `daemon_unavailable` (socket unreachable) and `daemon_shutting_down` (shutting down) are distinct codes (FR-049 + contracts/error-codes.md).
- [X] CHK028 Precondition codes tied to state conditions (FR-033 – FR-036 + data-model.md §3.3).
- [X] CHK029 `sender_not_in_pane` specifically for host-origin / unregistered-pane case; distinct from `sender_role_not_permitted` (FR-006 + Clarifications session 2 Q3 + FR-049).
- [X] CHK030 Closed-set codes are mutually exclusive on a single CLI invocation by construction — each CLI handler returns one error envelope; the dispatch layer returns the first failing check (FR-019/020 precedence + FR-033 – FR-036).

## Argument Conventions

- [X] CHK031 `--target` accepts agent_id or label with shape-discriminated resolution (Clarifications session 2 Q2 + research §R-001 + contracts).
- [ ] CHK032 **Open**: behavior on unknown CLI flags is implicit (argparse rejects with usage error mapped to `bad_request` per contracts/error-codes.md integer 64). Could be explicit in the CLI contract.
- [ ] CHK033 **Open**: whether `agenttower send-input --help` (and the other subcommands' `--help`) lists the FR-049 closed-set error codes is not specified. The contracts/error-codes.md table is the canonical reference, but the CLI's `--help` may or may not surface it.
- [X] CHK034 `daemon_unavailable` covers socket-unreachable; `daemon_shutting_down` covers in-shutdown — distinct cases visible via the closed set (FR-049 + contracts/error-codes.md).

## Plan-Grounded Additions (2026-05-12 pass)

- [X] CHK035 `body_bytes` base64 declared as transport-only; SQLite `envelope_body` stores raw bytes (contracts/socket-queue.md + research §R-002).
- [X] CHK036 `wait_timeout_seconds` bounded [0.0, 300.0] across socket and CLI (contracts/socket-queue.md + contracts/cli-send-input.md).
- [X] CHK037 JSON Schema `allOf`/`if/then` enforces `state=blocked ⇒ block_reason ≠ null` etc. (contracts/queue-row-schema.md).
- [X] CHK038 Integer-exit-code map declared as MVP-only; string codes are the stability surface (contracts/error-codes.md + FR-050).
- [X] CHK039 Idempotent `routing.enable`/`disable` (`changed=false`) MUST NOT emit an audit row (contracts/socket-routing.md "Success response" notes).
- [X] CHK040 Empty-state `queue --json` returns `[]` with exit `0` (contracts/cli-queue.md).
- [X] CHK041 Dual-usage `target_not_found` resolved by the 2026-05-12 rename: agent lookup → `agent_not_found`, row-id lookup → `message_id_not_found` (Clarifications session 2 Q5).
- [X] CHK042 `since_invalid_format` is in FR-049 (added by Clarifications session 2 Q4).
- [X] CHK043 Body-validation rejections produce no row and no `excerpt`; the CLI error envelope carries the closed-set code instead (contracts/cli-send-input.md + FR-003).
- [X] CHK044 `--json` outputs guaranteed single-line NDJSON-compatible across all commands (contracts/queue-row-schema.md "Notes" — no contradiction with FR-011).
- [X] CHK045 `cursor` on `queue.list` declared reserved-for-future-use, not populated in MVP responses (contracts/socket-queue.md).
- [X] CHK046 Human-listing column names declared as part of the contract (contracts/cli-queue.md "Default columns").
- [X] CHK047 `agent_id` prefix rendering rule: first 8 hex chars of `agt_<12-hex>` → `agt_aaaa` (8-char prefix, contracts/cli-queue.md). Collision is theoretically possible (1 in 16^4 ≈ 1 in 65 K) but the `--json` output always carries the full id for disambiguation.
- [X] CHK048 `routing.status` response fields are always present whether the flag was toggled or remains at seed default (contracts/socket-routing.md "Success response" + data-model.md §2 seed row guarantees non-null `last_updated_at` / `last_updated_by`).

## Notes

- 46/48 items resolved by spec/plan/contracts through the 2026-05-12 remediation; 2 remain open.
- **Outstanding decisions for the user**: CHK032 (unknown-CLI-flag behavior — implicit vs explicit), CHK033 (whether `--help` enumerates the FR-049 closed-set codes).
