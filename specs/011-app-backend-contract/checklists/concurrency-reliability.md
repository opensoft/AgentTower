# Concurrency & Reliability Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for multi-session concurrency, last-write-wins semantics, idempotency on `app.send_input`, scan timeout & client-disconnect resilience.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are concurrency requirements defined for every mutation method (which use last-write-wins, which use terminal-state guard, which use idempotency_key)? [Coverage, Spec §FR-030a, §FR-031a, Edge Cases §Adopt-mode race]
- [ ] CHK002 Is `idempotency_key`'s dedupe window TTL defined? [Gap, Spec §FR-031a]
- [ ] CHK003 Is the `(app_session_id, idempotency_key)` scope rule defined for the case of one client sending the same key from two connections (after a reconnect with new session)? [Gap, Spec §FR-031a]
- [ ] CHK004 Is "in-memory only" (FR-031a) reconciled with the daemon restart behavior — the key is forgotten, but is that acceptable from a UX perspective? [Coverage, Spec §FR-031a]
- [ ] CHK005 Is the rule defined for whether a mutation that *succeeded* but failed to send the response (broken socket) is covered by an idempotency mechanism for non-`send_input` mutations? [Coverage, Spec §FR-031a]
- [ ] CHK006 Is a cap defined on the number of pending idempotency keys per session? [Gap]

## Requirement Clarity

- [ ] CHK007 Is "last-write-wins" defined operationally for `app.agent.update` — is the final state determined by SQLite commit order, or by daemon-side serialization? [Clarity, Spec §FR-030a]
- [ ] CHK008 Is "no `expected_version` / `etag`" (FR-030a) sufficient to forbid implementing version stamps internally, or only forbid *exposing* them in v1.0? [Clarity, Spec §FR-030a]
- [ ] CHK009 Is "Client socket disconnect MUST NOT cancel the scan" (FR-030b) defined for both `wait=true` and `wait=false` modes? [Clarity, Spec §FR-030b]
- [ ] CHK010 Is the dedupe response's `deduplicated: true` marker required on every duplicate retry, or only the first retry? [Clarity, Spec §FR-031a]
- [ ] CHK011 Is "dedupe window" lifetime defined as "until session closes" or a separate TTL clock? [Ambiguity, Spec §FR-031a]

## Requirement Consistency

- [ ] CHK012 Are FR-030a (no `stale_object` on entity updates) and FR-034 (closed set still lists `stale_object`) reconciled — does the spec scope where `stale_object` may appear? [Consistency, Spec §FR-030a, §FR-034]
- [ ] CHK013 Is the FR-031a dedupe key scope `(app_session_id, idempotency_key)` consistent with Story 3's `app.send_input` requirements? [Consistency, Spec §FR-031a, §US3]
- [ ] CHK014 Is "no other `app.*` mutation MUST accept `idempotency_key`" (FR-031a) consistent with the absence of `idempotency_key` from FR-029's input shapes? [Consistency, Spec §FR-029, §FR-031a]
- [ ] CHK015 Are FR-030b's 30s timeout and SC-002's ≤500ms dashboard budget consistent under load (does an in-flight scan starve other requests)? [Consistency, Spec §FR-030b, §SC-002]

## Scenario Coverage

- [ ] CHK016 Are requirements defined for `app.scan.status` polling cadence and reconnect-after-disconnect resumability? [Gap, Spec §FR-030b]
- [ ] CHK017 Are requirements defined for two app sessions both calling `app.scan.panes` with `wait=true` simultaneously — coalesce, queue, or run independently? [Gap, Spec §FR-030, §FR-030b]
- [ ] CHK018 Are requirements defined for ordering guarantees between mutations from the same session and from different sessions? [Gap, Edge Cases §Concurrent app sessions]
- [ ] CHK019 Are requirements defined for the case where a mutation succeeds but the daemon dies before sending the response — is the next session start expected to reconcile? [Gap]
- [ ] CHK020 Is the behavior defined when two app sessions race `app.agent.update` on the same agent with contradictory values — both succeed, last commit wins, and both responses reflect the post-state at commit time? [Coverage, Spec §FR-030a]
- [ ] CHK021 Are requirements defined for race conditions between `app.scan.panes` completion and `app.agent.register_from_pane` (re-discovery of the same pane)? [Coverage, Edge Cases §Adopt-mode race]

## Measurability

- [ ] CHK022 Can FR-030b's 30s timeout be deterministically tested with a synthetic slow scan? [Measurability, Spec §FR-030b]
- [ ] CHK023 Can FR-031a's dedupe behavior be tested by sending the same `(app_session_id, idempotency_key)` twice and asserting `deduplicated: true`? [Measurability, Spec §FR-031a]
- [ ] CHK024 Can "scan completes server-side after client disconnect" (FR-030b) be verified by reconnecting and calling `app.scan.status`? [Measurability, Spec §FR-030b]
- [ ] CHK025 Can "no duplicate queue row and no duplicate audit row" (FR-031a) be verified by row-count assertions in SQLite/JSONL? [Measurability, Spec §FR-031a]

## Ambiguities, Conflicts, Gaps

- [ ] CHK026 Is there a defined cap on the number of in-flight scans across all sessions? [Gap, Spec §FR-030, §FR-030b]
- [ ] CHK027 Is the behavior defined for an `idempotency_key` longer than expected (e.g., 1MB string) — `validation_failed` with `details.field == "idempotency_key"`? [Gap, Spec §FR-031a]
- [ ] CHK028 Is the behavior defined for clock skew or clock-based ordering between sessions (the dashboard rows use timestamps from one clock; mutations may serialize on another)? [Gap]
- [ ] CHK029 Is the rule defined for what happens if a duplicate `idempotency_key` arrives *while* the original request is still in flight (not yet committed)? [Gap, Spec §FR-031a]
- [ ] CHK030 Is the FR-030a "no `stale_object` on entity updates" rule applied even when an update would conflict with a terminal state (e.g., updating an agent whose container just became inactive)? [Gap, Spec §FR-030a]
