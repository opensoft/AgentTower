# Security Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the security-relevant requirements (permission model, kill switch, shell-injection safety, redaction, authorization boundary, body validation, threat model). Tests whether the requirements themselves are complete, clear, consistent, and measurable — NOT whether the implementation is secure.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md)

## Permission Model Requirements

- [X] CHK001 Permitted sender roles enumerated as a closed set; every other role refused (FR-021).
- [X] CHK002 Permitted target roles enumerated as a closed set; every other role refused (FR-022).
- [X] CHK003 Precedence order is deterministic — six explicitly numbered steps (FR-019 + FR-020 after Clarifications session 2 Q3 + data-model.md §3.4).
- [X] CHK004 Sender (locked at enqueue) vs target (re-checked at delivery) asymmetry rationale declared (Assumptions "Sender liveness at delivery time is NOT re-checked"; FR-025).
- [X] CHK005 Sender role demoted between enqueue and delivery handled (Edge Cases "Sender role demoted between enqueue and delivery": delivery proceeds, authorization locked at enqueue).
- [X] CHK006 Target role demoted between enqueue and delivery handled with `target_role_not_permitted` re-check (Edge Cases + FR-025).
- [X] CHK007 Send to self → `target_role_not_permitted` (Edge Cases "Send to self").
- [X] CHK008 `master → swarm` permission stated with same explicitness as `master → slave` (FR-022 + US1 #5).

## Kill Switch Requirements

- [X] CHK009 Kill switch is a single global boolean (FR-026 + Assumptions "Routing flag scope").
- [X] CHK010 Toggle vs status auth rules distinct: toggle is host-only, status is any-origin (FR-027 + Clarifications session 2 Q2).
- [X] CHK011 Host-only constraint enforced via `(caller_pane is None AND peer_uid == os.getuid())` discriminator (FR-027 + research §R-005).
- [X] CHK012 `routing_toggle_host_only` is a distinct closed-set code (FR-049 + contracts/error-codes.md).
- [X] CHK013 `approve` behavior for `kill_switch_off` rows depends on current switch state (FR-030 + FR-033 + Edge Cases "Operator approves while kill switch is off").
- [X] CHK014 Race between disable and in-flight delivery resolved: in-flight rows finish; new pickups blocked (Session 2 Q1 + FR-028).

## Shell-Injection & tmux Delivery Safety

- [X] CHK015 Prohibition on shell-string interpolation is a hard MUST NOT (FR-038).
- [X] CHK016 Body transport closed to stdin + tmux no-shell argument passing (FR-038).
- [X] CHK017 Paste-buffer lifecycle: per-message scope, cleared after delivery (FR-039 + plan §"Delivery worker loop").
- [X] CHK018 SC-003 expressed in externally observable terms (process-tree snapshot before/after + pane content byte-equal assertion).
- [X] CHK019 Submit keystroke fixed to Enter (Assumptions "Submit keystroke is Enter" + plan §"Defaults locked").
- [X] CHK020 Resolved by Group-A Q1: on `paste_buffer` / `send_keys` failure after a successful `load_buffer`, the worker invokes `delete_buffer` best-effort in a `finally` block; cleanup errors are logged but never raised; the row still transitions to `failed` with the original `failure_reason`. Encoded in spec Clarifications, plan §"Delivery worker loop", T042, T046.

## Body Validation & Resource Limits

- [X] CHK021 Prohibited byte categories enumerated exhaustively (FR-003: empty, non-UTF-8, NUL, ASCII controls except `\n`/`\t`).
- [X] CHK022 Size cap applies to serialized envelope (FR-004).
- [X] CHK023 Configurable with 64 KiB default (FR-004 + Assumptions "Body size cap" + plan §"Defaults locked").
- [X] CHK024 Closed-set rejection codes distinct (FR-049: `body_empty`, `body_invalid_encoding`, `body_invalid_chars`, `body_too_large`).
- [X] CHK025 SC-009 ≤ 100 ms rejection with zero bytes persisted (SC-009 + T081).

## Redaction Surfaces

- [X] CHK026 Redaction-required surfaces enumerated (FR-047a: queue listings, audit excerpts, JSONL, `--json`).
- [X] CHK027 Non-redaction surfaces enumerated (FR-047a: persisted `envelope_body`, paste buffer, target-pane bytes).
- [X] CHK028 Excerpt cap = 240 chars + `…` truncation marker (FR-011 + FR-047b + Assumptions + queue-row-schema.md `maxLength: 241`).
- [X] CHK029 Resolved by Group-A Q3: FR-047b extended to require the excerpt pipeline to catch any exception from the redactor and substitute the fixed literal `"[excerpt unavailable: redactor failed]"`; raw body MUST NEVER fall back. T020/T021 implement and test.
- [X] CHK030 `envelope_body_sha256` covers the raw body (Clarifications session 2 Q1 + data-model.md §2).

## Authorization Boundary & Threat Model

- [X] CHK031 Unix socket is the sole authentication gate; higher-level RBAC out of scope (Assumptions "Authorization at the socket boundary is host-user only").
- [ ] CHK032 **Open**: behavior when the socket file's permissions are weakened externally (out-of-band threat — e.g., `chmod 666 /run/agenttower.sock`) is not specified. FEAT-001 sets the mode but doesn't re-check.
- [X] CHK033 Audit non-repudiation properties declared (FR-046 + FR-047: append-only, raw body excluded, operator identity captured for operator-driven transitions).
- [X] CHK034 Operator-identity capture on routing-toggle actions: `host-operator` sentinel for host toggles, audited via `routing_toggled` event (Clarifications session 2 Q4 + contracts/socket-routing.md).
- [X] CHK035 `daemon_shutting_down` closed-set error during shutdown (FR-049 + Edge Cases "Daemon receives send-input while shutting down").
- [X] CHK036 Compromised master mitigations: operator runs `queue cancel <id>` (Edge Cases) and `routing disable` (FR-027); the safety surface is operator-driven by design.

## Plan-Grounded Additions (2026-05-12 pass)

- [X] CHK037 Host-origin discriminator `(caller_pane is None AND peer_uid == os.getuid())` reproducible from research §R-005 alone; spec FR-027 + plan §"Implementation Notes" cross-reference.
- [X] CHK038 `HOST_OPERATOR_SENTINEL` reservation is two-layered (literal-rejection + regex-rejection); research §R-004 + T015 + T016.
- [X] CHK039 AST gate enumerates f-strings, `.format`, `.join`, `%`-formatting, `shell=True`, `os.system`, `os.popen` (research §R-007).
- [X] CHK040 AST gate scope (`subprocess_adapter.py` only) justified in research §R-007 with rationale ("fakes and abstract adapter Protocol are not exercised because they don't run real processes").
- [X] CHK041 Reason-state coherence CHECKs declared at the schema layer (data-model.md §2).
- [X] CHK042 Resolved by Group-A Q5/Q7: uniform bounded-retry policy (3 attempts at 10/50/250 ms) on every in-transition SQLite read/write including the pre-paste re-check; persistent failure → `failure_reason='sqlite_lock_conflict'`. Spec Assumptions "SQLite lock-conflict retry policy"; T028 DAO retry helper; T042 worker integration.
- [ ] CHK043 **Open**: tmux buffer name `agenttower-<message_id>` could in principle collide with an operator-set buffer named the same. The likelihood is vanishingly small (UUIDv4 message_id), but no requirement explicitly bars operator-side buffer naming with the `agenttower-` prefix.
- [X] CHK044 Plan §"Delivery worker loop" shows `delete_buffer` is called BEFORE the `transition_queued_to_delivered` SQLite commit, so a failed delete leaves the row in `failed` (not `delivered` with a leaked buffer).
- [X] CHK045 `submit_keystroke` restricted to a closed set (plan §"Defaults locked" enumerates `"Enter"` as the only value; tmux-delivery CHK003 cross-reference).
- [X] CHK046 Body `bytes` typing in tmux adapter Protocol method signatures (plan §"Implementation Notes" + T036).
- [X] CHK047 `routing_toggled` covered by the R-008 disjointness test (T086 + T091).
- [ ] CHK048 **Open**: threat-model expectation when an attacker has direct filesystem access to write `daemon_state` via the `sqlite3` CLI (out-of-band) is not specified. Implicit: file mode `0o600` is the host-side defense.
- [X] CHK049 Resolved by Group-A Q8: bench-container callers to `queue.approve`/`delay`/`cancel` are required to resolve to an active registered agent; otherwise return closed-set `operator_pane_inactive`. Host-origin callers (no pane) continue to write the `host-operator` sentinel. Encoded in FR-049 (new code added), contracts/socket-queue.md, contracts/cli-queue.md (exit 21), T049 dispatcher, T069 service.
- [X] CHK050 SQLite file mode `0o600` is enforced at FEAT-001 init; FEAT-009 does not re-check but inherits via the same daemon process owning the file (plan §"Constraints" "FEAT-009 introduces zero new file modes").

## Notes

- 47/50 items resolved (4 new Group-A walk resolutions appended to the 2026-05-12 remediation); 3 remain open.
- **Outstanding decisions for the user**: CHK032 (socket-permissions out-of-band threat), CHK043 (tmux buffer name collision protection), CHK048 (out-of-band SQLite tampering threat model). All three are threat-model items the user previously categorized as Group B (lower priority).
