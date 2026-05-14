# FEAT-001..008 Integration Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the integration surfaces FEAT-009 consumes from prior features — FEAT-001 JSONL writer, FEAT-002 socket envelope/error vocab, FEAT-004 tmux adapter, FEAT-005 caller pane identity, FEAT-006 agent registry, FEAT-007 redaction utility, FEAT-008 events.jsonl stream. Tests whether each reused surface is named precisely, used additively, and shielded against breaking by a backcompat invariant — NOT whether the integrations work at runtime.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-12
**Walked**: 2026-05-12
**Feature**: [plan.md](../plan.md) | [research.md](../research.md)

## FEAT-001 JSONL Writer (events.writer)

- [X] CHK001 `agenttower.events.writer.append_event` reused verbatim (plan.md §"Primary Dependencies").
- [X] CHK002 `events.jsonl` is the same file FEAT-008 uses (spec.md §Clarifications Q4 + data-model.md §7.2).
- [X] CHK003 No new file modes; inherits FEAT-001's `0o600`/`0o700` (plan.md §"Constraints").

## FEAT-002 Socket Envelope & Errors

- [X] CHK004 `socket_api/server.py`, `client.py`, `errors.py` reused verbatim (plan.md §"Primary Dependencies").
- [X] CHK005 `{ok: true, result: ...}` / `{ok: false, error: ...}` envelope shape preserved (contracts/socket-queue.md "Envelope serialization", contracts/socket-routing.md).
- [X] CHK006 FEAT-009 codes added to `CLOSED_CODE_SET`; existing codes preserved (data-model.md §8, T014).
- [X] CHK007 `{code, message}` error envelope shape preserved (contracts/socket-queue.md "Envelope serialization").

## FEAT-004 tmux Adapter

- [X] CHK008 TmuxAdapter extension is purely additive — four new methods, zero changes to existing methods (plan.md §"Project Structure").
- [X] CHK009 SubprocessTmuxAdapter preserves the `docker exec -u <bench-user> <container-id> tmux -S <socket-path> ...` pattern (plan.md §"Implementation Notes").
- [X] CHK010 FakeTmuxAdapter extension is additive; T038 explicitly preserves existing FEAT-004 fake behavior.
- [X] CHK011 `TmuxError.failure_reason` field added for FR-018 mapping without losing existing FEAT-004 error codes (plan.md §"Implementation Notes" "tmux adapter Protocol extension").
- [X] CHK012 `socket_path` resolution reuses the FEAT-004 pane-discovery helpers; the SubprocessTmuxAdapter extensions consume the same `(container_id, bench_user, socket_path)` triple FEAT-004 already produces.

## FEAT-005 Caller Pane Identity

- [X] CHK013 `CallerContext.caller_pane` is the FEAT-005 surface read for both `sender_not_in_pane` and `routing_toggle_host_only` checks (research §R-005).
- [X] CHK014 "No pane = host origin" is the FEAT-005-derived discriminator (research §R-005).
- [X] CHK015 `peer_uid == os.getuid()` is defense-in-depth; pane-absence is the actual discriminator (research §R-005 "necessary but not sufficient").

## FEAT-006 Agent Registry

- [X] CHK016 Read-only registry use: FEAT-009 calls `list_agents` and lookup helpers; the only "write" is the additive `HOST_OPERATOR_SENTINEL` reservation in `identifiers.py` (T015), which mutates code, not the agents table.
- [X] CHK017 `AGENT_ID_RE` (`^agt_[0-9a-f]{12}$`) is the shape predicate for `--target` resolution (research §R-001).
- [X] CHK018 `HOST_OPERATOR_SENTINEL` lives in `agents/identifiers.py` (research §R-004, T015).
- [X] CHK019 `validate_agent_id_shape` reservation is backwards-compatible — only the literal `"host-operator"` is rejected; all valid `agt_<12-hex>` callers continue to work (research §R-004, T016).
- [ ] CHK020 **Open**: "active agents have unique labels" is not declared as a FEAT-006 invariant. The `target_label_ambiguous` failure mode handles the case where two active agents share a label, but FEAT-006 itself doesn't prevent this from happening — operators can register two slaves with the same label. This is defensible (the failure mode is the safeguard) but could be tightened either at the FEAT-006 registry level or as a documented FEAT-006 assumption.

## FEAT-007 Redaction Utility

- [X] CHK021 `logs/redaction.redact_one_line` reused verbatim (plan.md §"Primary Dependencies").
- [X] CHK022 Redactor `str` input is compatible with FEAT-009's excerpt pipeline (which decodes `bytes → str` before redaction; plan.md §"Excerpt pipeline").

## FEAT-008 Events Stream

- [X] CHK023 Seven `queue_message_*` + one `routing_toggled` types added; no FEAT-008 type renamed or removed (plan.md §"Backwards compatibility"; data-model.md §2 events_new rebuild).
- [X] CHK024 R-008 disjointness test imports closed sets from FEAT-007 lifecycle, FEAT-008 classifier_rules, and FEAT-009 routing module (T086, T091).
- [X] CHK025 `agenttower events` reader works unchanged after FR-046 dual-write — the events table now stores queue audit rows alongside classifier rows, surfaced through the existing `events.list` query path (data-model.md §7.1 column mapping).
- [X] CHK026 `degraded_events_persistence` (FEAT-008) and `degraded_queue_audit_persistence` (FEAT-009) are both surfaced through `agenttower status` and declared distinct (T054, plan.md §"JSONL audit append + degraded path").

## CLI Surface Inheritance

- [X] CHK027 FEAT-005 thin-client routing reused verbatim for `send-input`'s in-container path (plan.md §"Primary Dependencies").
- [X] CHK028 argparse subparser pattern reused; no new dependency (plan.md §"Primary Dependencies").

## Backcompat Test Scope

- [X] CHK029 `test_feat009_backcompat.py` re-runs every FEAT-001..008 CLI command with byte-identical assertions (T087).
- [X] CHK030 Backcompat test is a hard gate before merge (tasks.md "Risk mitigation": "schedule it as the gate before any merge to main").

## Notes

- 29/30 items resolved by spec/plan/research/tasks through the 2026-05-12 remediation; 1 remains open.
- **Outstanding decision for the user**: CHK020 (whether FEAT-006 should enforce label uniqueness as a schema invariant, or whether the MVP-level `target_label_ambiguous` failure mode is sufficient).
