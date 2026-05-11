# Security Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the security-relevant requirements (permission model, kill switch, shell-injection safety, redaction, authorization boundary, body validation, threat model). Tests whether the requirements themselves are complete, clear, consistent, and measurable — NOT whether the implementation is secure.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## Permission Model Requirements

- [ ] CHK001 Are the permitted sender roles enumerated as a closed, exhaustive set with every other FEAT-006 role explicitly refused? [Completeness, Spec §FR-021]
- [ ] CHK002 Are the permitted target roles enumerated as a closed, exhaustive set with every other FEAT-006 role explicitly refused? [Completeness, Spec §FR-022]
- [ ] CHK003 Is the precedence order of enqueue-time permission/availability checks explicitly specified so that `block_reason` is deterministic when multiple checks would fail? [Clarity, Spec §FR-019, §FR-020]
- [ ] CHK004 Is the asymmetry between sender authorization (locked at enqueue) and target authorization (re-checked at delivery) documented with a rationale, not merely asserted? [Clarity, Spec §FR-025, §Assumptions]
- [ ] CHK005 Are requirements specified for the "sender role demoted between enqueue and delivery" scenario? [Coverage, Spec §Edge Cases]
- [ ] CHK006 Are requirements specified for the "target role demoted between enqueue and delivery" scenario, including which closed-set block_reason applies? [Coverage, Spec §Edge Cases, §FR-025]
- [ ] CHK007 Is the "send to self" case classified to a specific `block_reason` rather than left as undefined behavior? [Coverage, Spec §Edge Cases]
- [ ] CHK008 Is the `master → swarm` permission rule stated with the same explicitness as the `master → slave` rule? [Consistency, Spec §US1 #5, §FR-022]

## Kill Switch Requirements

- [ ] CHK009 Is the kill switch scope defined as a single global boolean, with per-target / per-role / per-sender variants explicitly excluded from MVP? [Clarity, Spec §FR-026, §Assumptions]
- [ ] CHK010 Are the authorization rules for toggling routing distinct from the rules for reading routing status? [Consistency, Spec §FR-027, §Clarifications]
- [ ] CHK011 Is the host-only constraint on `routing enable` / `routing disable` phrased as an enforceable origin check (not just a documented policy)? [Measurability, Spec §FR-027]
- [ ] CHK012 Is the closed-set error `routing_toggle_host_only` distinct from generic permission failures so callers can branch on it? [Clarity, Spec §FR-049]
- [ ] CHK013 Is the behavior of `approve` for `kill_switch_off` rows distinguished between "switch currently enabled" and "switch currently disabled"? [Clarity, Spec §FR-030, §FR-033, §Edge Cases]
- [ ] CHK014 Are requirements defined for the race between a kill-switch toggle and an in-flight delivery attempt (does disable preempt mid-paste, or wait for the row to reach terminal)? [Gap, Coverage]

## Shell-Injection & tmux Delivery Safety

- [ ] CHK015 Is the prohibition on shell-string interpolation of the body or envelope phrased as an enforceable MUST NOT, not a recommendation? [Clarity, Spec §FR-038]
- [ ] CHK016 Are the only allowed body-transport mechanisms enumerated as a closed set (stdin, tmux no-shell argument passing)? [Completeness, Spec §FR-038]
- [ ] CHK017 Are paste-buffer lifecycle requirements (creation, scoping per-message, clearing after delivery) defined to prevent cross-message replay? [Completeness, Spec §FR-039]
- [ ] CHK018 Is the shell-injection safety success criterion expressed in externally observable terms (process-tree snapshot before/after), not just "no exploit possible"? [Measurability, Spec §SC-003]
- [ ] CHK019 Is the submit keystroke fixed (Enter) rather than left to implementer choice? [Clarity, Spec §Assumptions]
- [ ] CHK020 Are requirements defined for the case where `tmux load-buffer` succeeds but `paste-buffer` fails (must still clear/scope the buffer)? [Gap, Coverage]

## Body Validation & Resource Limits

- [ ] CHK021 Are the prohibited byte categories in submitted bodies enumerated exhaustively (empty, invalid UTF-8, NUL, ASCII controls except \n and \t)? [Completeness, Spec §FR-003]
- [ ] CHK022 Is the body-size cap applied to the serialized envelope (not just the raw body) to prevent header-stuffing bypass? [Clarity, Spec §FR-004]
- [ ] CHK023 Is the size cap stated to be configurable but bounded by a documented MVP default (64 KiB)? [Completeness, Spec §FR-004, §Assumptions]
- [ ] CHK024 Are the closed-set error codes for body-validation rejections distinct enough to drive different operator remediation paths (encoding vs chars vs empty vs too-large)? [Clarity, Spec §FR-049, §US5 #4]
- [ ] CHK025 Is the rejection latency requirement quantified for oversize bodies, with a guarantee that zero bytes are persisted on rejection? [Measurability, Spec §SC-009]

## Redaction Surfaces

- [ ] CHK026 Is the set of surfaces requiring body redaction enumerated exhaustively (queue listings, audit excerpts, JSONL, `--json`)? [Completeness, Spec §FR-047a]
- [ ] CHK027 Is the set of surfaces that MUST NOT be redacted enumerated explicitly (persisted `envelope_body`, paste buffer, target-pane bytes)? [Completeness, Spec §FR-047a, §Clarifications]
- [ ] CHK028 Is the excerpt cap quantified with a numeric limit AND a truncation marker convention? [Measurability, Spec §FR-011, §Assumptions]
- [ ] CHK029 Are requirements specified for the FEAT-007 redaction utility's failure modes (what happens if redaction itself throws)? [Coverage, Gap]
- [ ] CHK030 Is `envelope_body_sha256` defined as covering the raw (un-redacted) body so that integrity checks survive display-time redaction? [Consistency, Spec §FR-012, §FR-012a]

## Authorization Boundary & Threat Model

- [ ] CHK031 Is the Unix socket boundary documented as the sole authentication gate, with all higher-level RBAC explicitly out of scope for MVP? [Clarity, Spec §Assumptions]
- [ ] CHK032 Are requirements defined for what happens if the socket file's permissions are weakened externally (out-of-band threat)? [Gap, Threat Model]
- [ ] CHK033 Is the audit log's non-repudiation property explicitly stated (append-only, raw body excluded, operator identity captured for operator-driven transitions)? [Completeness, Spec §FR-046, §FR-047]
- [ ] CHK034 Are requirements defined for operator-identity capture on routing-toggle actions, comparable to those for `approve`/`delay`/`cancel`? [Coverage, Spec §Key Entities (Routing flag)]
- [ ] CHK035 Is the daemon's behavior during shutdown defined to prevent unsigned-in operations (`daemon_shutting_down` error closed-set)? [Coverage, Spec §Edge Cases, §FR-049]
- [ ] CHK036 Is the threat of a registered master being compromised explicitly considered, with the operator-side mitigations (`queue cancel`, `routing disable`) named? [Gap, Threat Model]

## Notes

- Items are written as "unit tests for the spec text" — they check whether requirements are well-written, not whether the implementation is secure.
- A failing item indicates a spec gap to fix before `/speckit.plan` (or in a follow-up `/speckit.clarify`), not an implementation defect.
- Check items off as completed: `[x]`. Add inline notes for findings. Cross-reference fixes to the FR they touched.
