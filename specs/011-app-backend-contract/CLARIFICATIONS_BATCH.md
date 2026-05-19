# FEAT-011 Checklist Walkthrough — Batched Clarifying Questions

**Context:** After reading all 23 incomplete checklists (~640 items) plus spec/plan/data-model/contracts, most items audit consistency between already-decided artifacts and can be auto-ticked. The questions below are the **genuine open gaps** — spec is silent or ambiguous, and a default decision would materially affect the implementation.

**How to answer:** Reply with `Q1: <letter>` per row. Add `— <note>` if you want to override a recommendation. Multiple selections like `Q1: A` or "all recommended" both work. Items you skip get the recommended (`★`) default.

**Out of scope (will not ask):** pure-audit items in `clarify-propagation`, `cross-artifact-consistency`, `plan-quality`, `outcomes`, `requirements`, `quickstart-quality`, `research-rationale`, `data-model-quality`, `contract-files`, `read-surfaces` (already covered by FR-020a/020b/021/021a/021b/024a). Those will be ticked after this batch lands.

---

## Block A — Wire framing (contract-surface CHK002, CHK004, CHK012, CHK019)

**Applied answers:** Q1=A, Q2=A, Q3=B, Q4=no action.

**Q1. Line-ending byte.** FR-001 says "newline-delimited JSON" but doesn't pin the byte.
- A. `\n` only (strict). Daemon rejects any line containing `\r` with `validation_failed`. ★
- B. `\n` required, `\r` before `\n` tolerated (CRLF accepted on input; daemon emits `\n` only).
- C. Defer to implementation, document later.

**Q2. UTF-8 / embedded NUL handling.** Spec is silent.
- A. UTF-8 required; embedded NUL bytes rejected with `validation_failed`. ★
- B. Bytes are passed through; daemon doesn't validate.

**Q3. Two JSON objects on one request line.** Spec is silent.
- A. Parse the first object, reject the rest of the line with `malformed_request` (Q5). ★
- B. Reject the whole line.
- C. Try to parse both as separate requests.

**Q4. Max line length already answered (FR-003a 1 MiB / 8 MiB).** No action — tick CHK005/CHK006.

---

## Block B — Error code gaps (errors CHK015, CHK017, CHK019, CHK020; mutations CHK029, CHK030, CHK032; versioning CHK020)

**Applied answers:** Q5=B, Q6=A, Q7=B, Q8=A, Q9=A, Q10=A, Q11=A.

**Q5. Code for a malformed JSON request line (parse failure before dispatch).** FR-034 closed set has no entry.
- A. Reuse `validation_failed` with synthetic `details.field == "request_line"`, `reason == "malformed JSON"`. No closed-set bump. ★
- B. Add a 27th code `malformed_request` to FR-034 (details = `{reason: string}`). Most accurate.
- C. Close the connection (no envelope). Client sees EOF.

**Q6. Code for `app.send_input` when `target` is not a registered agent.**
- A. `agent_not_found` with `details.agent_id`. ★
- B. `routing_disabled` (reuse FEAT-009 kill-switch code).
- C. `validation_failed` with `details.field == "target"`.

**Q7. Code for the FEAT-009 permission gate refusing `app.send_input`** (distinct from kill-switch off).
- A. `routing_disabled` (current FR-031 wording — reuses one code for "queue refused us"). ★
- B. `permission_denied` (current code; reused from peer-UID rejection).
- C. Add a new closed-set code `routing_blocked` distinct from `routing_disabled`.

**Q8. Code for "session token format invalid"** (e.g., not 36-char hex UUID) — distinct from `app_session_expired`?
- A. Treat as `app_session_expired` (no new code; semantically "this token cannot be valid"). ★
- B. Treat as `app_session_required` (same as missing).
- C. Add a 27th code `app_session_token_malformed`.

**Q9. Code for "daemon shutting down"** during graceful shutdown — distinct from `daemon_unavailable`?
- A. Return `internal_error` with `details.reason == "shutting_down"`. ★
- B. Add a 27th code `daemon_shutting_down`.
- C. Close the connection without envelope.

**Q10. Code for "scan in progress" when `wait=false` and a prior same-kind scan is still running.**
- A. Return success with the in-flight `scan_id` (no error; caller polls `app.scan.status`). ★
- B. Return `validation_failed.details.field == "scan_kind"`.
- C. Add a new closed-set code `scan_in_progress`.

**Q11. Code for a malformed `app_id` or detail-id parameter** (e.g., wrong type passed to `app.agent.detail`).
- A. `validation_failed` with `details.field == "<param_name>"`. ★
- B. `<entity>_not_found` (current behavior for unknown id).

---

## Block C — Mutation semantics (adopt CHK014/016/017/018/023/024/025; mutations CHK006/007/020/023/024/031; sessions CHK006)

**Applied answers:** Q12=B, Q13=B, Q14=B, Q15=A, Q16=A, Q17=A, Q18=A, Q19=A, Q20=A, Q21=A, Q22=A, Q23=A.

**Q12. Adopt with partial pane identity match.** `pane_id` matches but `session_name` or `window_index` differs from current discovery.
- A. Trust client-supplied identity; if `pane_id` resolves uniquely, accept. ★
- B. Require all 6 identity fields to match the current discovered row; mismatch → `pane_not_found`.

**Q13. Adopt with `attach_log: true` and the container is inactive at adopt time.**
- A. Adopt succeeds (agent row created), but log_attached is `false`; response includes `hints[]` entry suggesting "container_inactive, log not attached." ★
- B. Whole adopt fails with `container_inactive`.
- C. Adopt succeeds, response includes a structured `attach_log_warning: {...}` (not a hint).

**Q14. Adopt with `parent_agent_id` referring to a non-existent agent.**
- A. `validation_failed` with `details.field == "parent_agent_id"`. ★
- B. `agent_not_found` with `details.agent_id`.
- C. Silently accept (treat parent as informational, not enforced).

**Q15. Adopt with `container_id` from a scan that has since become inactive.** Pane was discovered but container now down.
- A. `container_inactive` with `details.container_id`. ★
- B. `pane_not_found` (since a pane in a dead container is effectively gone).

**Q16. `label` normalization on adopt and `app.agent.update`.**
- A. Trim leading/trailing whitespace; reject embedded newlines; otherwise free-form ≤ 256 chars. ★
- B. Free-form (any chars allowed) up to 256 chars; no trim.
- C. Lowercase, alphanumeric+hyphen only, ≤ 64 chars (slug-style).

**Q17. `capability` validation.**
- A. Free-form string within FEAT-006's existing length bound (whatever that is — reuse). ★
- B. Add a closed-set v1.0 vocabulary for capability.

**Q18. `app.agent.update` with multiple invalid fields in one call.**
- A. All-or-nothing: validate all inputs first; on any failure, return one `validation_failed` with `details.field` = first offending field; no SQLite mutation. ★
- B. Partial: apply valid fields, reject invalid ones in a structured response.

**Q19. `app.agent.update` setting `role=master` from the host-driven caller.** FR-026 says "no silent promotion to master." FEAT-006 has rules; does host-driven adopt/update get an exemption?
- A. Allowed if FEAT-006's existing rules already permit it for a host-driven caller; no FEAT-011-specific carve-out. ★
- B. Forbidden in FEAT-011: any `role=master` in `app.agent.update` → `validation_failed.details.field == "role"`. Caller must use the dedicated FEAT-006 master-promotion flow if any.

**Q20. `app.log.attach` input shape beyond `agent_id`.**
- A. `agent_id` only. ★
- B. `agent_id` + optional `mode: enum {"append", "replace"}` (matching FEAT-007 options).

**Q21. `app.queue.approve` / `delay` / `cancel` input shape beyond `message_id`.**
- A. `message_id` only. ★
- B. `message_id` + optional `reason: string` recorded in audit row.

**Q22. `app.route.remove` of a route that does not exist.**
- A. `route_not_found` with `details.route_id`. ★
- B. Idempotent success (no error; response carries `removed: false`).

**Q23. `app.hello` called twice on the same connection.**
- A. Idempotent: return the same session token (no new session, no audit row). ★
- B. Accept and rotate: invalidate prior token, issue new one, audit `session_replaced`.
- C. Reject: `validation_failed.details.field == "<session>"` / reason "session already established."

---

## Block D — Concurrency & reliability (concurrency-reliability CHK016/017/018/019/026/028/029)

**Applied answers:** Q24=A, Q25=A, Q26=A, Q27=A, Q28=A, Q29=A.

**Q24. Two concurrent `app.scan.panes` calls (or same-kind scans) in flight.**
- A. Coalesce: second caller receives the in-flight `scan_id` and waits on the same scan. ★
- B. Queue: scans serialize; second caller blocks until first completes.
- C. Independent: both scans run in parallel; each gets its own `scan_id`.

**Q25. Cap on concurrent in-flight scans across all sessions.**
- A. Cap at 4 (2 containers + 2 panes); 5th scan → `validation_failed.details.reason == "too_many_scans_in_flight"`. ★
- B. Uncapped; trust workload.
- C. Cap at a single in-flight scan per kind globally (coalesce all by kind — implied by Q24-A).

**Q26. `app.scan.status` polling cadence — daemon-side SLA.**
- A. Daemon SHOULD answer within 100 ms (informational, not enforced). ★
- B. Add an explicit SC for `scan.status < 50 ms p95`.
- C. No SLA; document as "as fast as practical."

**Q27. Two `app.send_input` calls with the same `(app_session_id, idempotency_key)` where the first is still in flight (not yet committed).**
- A. Second request blocks until first commits; both return the same response (second with `deduplicated: true`). ★
- B. Second request returns immediately with a synthetic `deduplicated: true, pending: true` envelope.
- C. Second request errors with `validation_failed.details.field == "idempotency_key"` / reason "duplicate in flight."

**Q28. Mutation succeeded server-side but daemon died before response was sent.**
- A. No FEAT-011 mechanism. Client retries with `idempotency_key` (for send_input) or accepts the natural-idempotency cost (`update`, `route.add`, etc.). ★
- B. Add a "reconcile on next session" mechanism. (Major effort; defer to a future feature.)

**Q29. Max concurrent app sessions per daemon.**
- A. Cap at 8 (matches plan.md "≤3 concurrent" upper bound with headroom). 9th `app.hello` → `validation_failed.details.reason == "too_many_sessions"`. ★
- B. Uncapped.
- C. Cap at 3 (matches plan.md's stated upper bound exactly).

---

## Block E — Sessions & versioning edge cases (sessions CHK006/014/017/022/023; versioning CHK015/016/020)

**Applied answers:** Q30=A, Q31=A, Q32=A, Q33=A, Q34=B, Q35=A, Q36=A.

**Q30. Daemon restart mid-session — distinct code from `app_session_expired`?**
- A. Use `app_session_expired` (current closed set is enough; client reconnects and calls hello). ★
- B. Add a 27th code `daemon_restarted` so the client can distinguish "I disconnected" from "daemon went away."

**Q31. `app.hello` with empty or absent `client_id`/`client_version`.**
- A. Accept; store as `""`. Informational only — no validation. ★
- B. Require both as non-empty if present; reject empty strings.

**Q32. Peer UID re-checked after `app.hello` succeeded.**
- A. Check only at accept (current FR-041 implication). ★
- B. Re-check on every request (defends against fd inheritance attacks; minor perf cost).

**Q33. Connection drops between mutation commit and audit row write.**
- A. Audit row is written before envelope sent; on connection drop the row is still durable. Client retry with idempotency_key handles duplicate-prevention. ★
- B. Audit row carries the now-invalid `app_session_id`. Document that future audit consumers must accept "session that no longer exists" rows.

**Q34. Daemon's `supported_minor_range.max` advertises a minor it doesn't actually implement (erroneously high).**
- A. Document as "daemon-side invariant; clients SHOULD trust the advertised range." No defensive code in app contract. ★
- B. Add a contract test that asserts every method in `supported_minor_range.max` is implemented.

**Q35. Malformed `client_app_contract_major` (string, negative, missing).**
- A. Missing → default to `1` (per closed-sets.md). String/negative → `validation_failed.details.field == "client_app_contract_major"`. ★
- B. Any malformed value → treat as major 1 (most permissive).
- C. Reject hello entirely with `app_contract_major_unsupported`.

**Q36. Should `app.preflight` expose the daemon's contract major (so a client can detect major mismatch without calling `app.hello`)?**
- A. No — preflight stays minimal; client must call `app.hello` to check major. ★
- B. Yes — add `app_contract_version` to the `app.preflight` response so clients can fast-fail before hello.

---

## Block F — Readiness & dashboard gaps (readiness CHK008/016/017/023/024/026; dashboard CHK005/025)

**Applied answers:** Q37=A, Q38=A, Q39=A, Q40=A, Q41=A, Q42=A, Q43=A.

**Q37. Which readiness subsystems are mandatory for top-level `state == "ready"`?**
- A. All 6 must be `ok`. Any subsystem `degraded` or `unavailable` lowers top-level to `degraded`. (Already in closed-sets.md aggregation table.) ★
- B. `docker`, `sqlite`, `jsonl`, `routing_worker` mandatory; `tmux_discovery`, `log_attachment_workers` optional (degraded on those keeps state `ready`).

**Q38. Subsystem status flapping (e.g., docker briefly unreachable).**
- A. Reflect instantaneous state on every call; no debouncing. ★
- B. Debounce: status changes < 1s old are masked.

**Q39. `subsystem.reason` length cap.**
- A. ≤ 512 chars, no embedded newlines. ★
- B. ≤ 256 chars.
- C. No cap (free-form).

**Q40. Upper bound on `app.readiness` wall-clock.**
- A. SHOULD complete within 100 ms (plan.md target, not normative). ★
- B. Add a new SC `app.readiness < 100 ms p95` as normative.

**Q41. Platform-specific subsystems on Windows.** Docker subsystem on Windows hosts where Docker Desktop may not be installed — does `docker.status == "unavailable"` make sense, or should the row be absent?
- A. Row always present; `status == "unavailable"`, `reason == "docker not detected on platform"`. ★
- B. Row absent on platforms without docker; clients tolerate the missing row (FR-037).

**Q42. `events` count buckets on `app.dashboard`.** FR-016 doesn't enumerate buckets for `events`.
- A. Single `events.total_recent` count (count of events in the last 24h or last 1000 rows). ★
- B. Enumerate by event_type (open set — would force a closed set we don't have).
- C. Omit events from `counts`; only show in `recents`.

**Q43. `recent_limit = 0`.** FR-017 says `[1, 50]`; 0 is technically out of bounds.
- A. `validation_failed.details.field == "recent_limit"`, reason "out of bounds." ★ (Already implied by FR-017.)
- B. Accept 0 as "no recents; counts only."

---

## Block G — Observability & audit (observability CHK002/003/006/014/015/016/017/018/022/023/024/025)

**Applied answers:** Q44=A, Q45=A, Q46=B, Q47=A, Q48=B, Q49=A, Q50=A, Q51=A.

**Q44. Per-method audit event types — which audit event name does each mutation emit?**
- A. Reuse upstream FEAT audit event names byte-for-byte (e.g., `app.queue.approve` emits `queue_approved`, `app.route.add` emits `route_created`, `app.agent.register_from_pane` emits `agent_registered`). Just add `origin == "app"`. ★
- B. Add `app.*`-namespaced audit event names (e.g., `app.queue_approved`). Operators can grep by surface.

**Q45. Failed mutations emit audit rows?**
- A. No — only successful commits emit audit rows. Failures live in daemon stderr/logs only. ★
- B. Yes — failed mutations emit a row with `result: "failure", error_code: "..."` for forensic trail.

**Q46. JSONL audit unwritable mid-mutation** (disk full, permission lost).
- A. Mutation rolls back (transactional with the SQLite commit). Returns `internal_error`. ★
- B. Mutation proceeds; audit row is dropped; daemon logs a warning. (Audit is best-effort.)

**Q47. Audit-row ordering vs SQLite commit.**
- A. Audit row written AFTER SQLite commit, BEFORE response envelope sent. Sync flush. ★
- B. Audit row written async; eventually-consistent.

**Q48. Concurrent app sessions emit audit rows simultaneously — serialization.**
- A. Per-line append is atomic at the OS level (POSIX `O_APPEND` on small writes); no daemon-side mutex needed. ★
- B. Daemon-side mutex around the audit writer for safety.

**Q49. `app.preflight` and `app.hello` audit logging.**
- A. Not audited (they're not mutations). Connection accept/close already logged by FEAT-002. ★
- B. Emit a `session_established` audit row on every successful `app.hello`.

**Q50. `client_id` and `client_version` in audit rows.**
- A. Not included (audit row size is precious; `app_session_id` is enough for attribution). ★
- B. Include both as optional fields in the audit row.

**Q51. JSONL schema version bump for adding `origin == "app"`?** Research R-007 claims the writer already accepts string variants. Verify, then:
- A. No bump; `origin` is already an open string field that accepts new values additively. ★
- B. Bump JSONL schema_version (would conflict with FEAT-008 conventions; major work).

---

## Block H — Performance bounds (performance CHK003/004/010/011/015/017/018/019/020/024/025/026)

**Applied answers:** Q52=A, Q53=A, Q54=A, Q55=A, Q56=A, Q57=A, Q58=A.

**Q52. SC-002 / SC-004 latency budget percentile.** Spec says "≤ 500 ms" without specifying p50/p95/p99/max.
- A. Worst-case across 5 trials (deterministic, easy to test on CI). ★
- B. p95 across 100 trials (statistical; more realistic).
- C. p99 across 100 trials (strict).

**Q53. SC-004 (2s adopt round-trip) — sum across 4 calls or each call individually.**
- A. Sum of all 4 wall-clocks (`scan.panes` + `pane.list` + `register_from_pane` + `agent.detail`). ★
- B. Each call individually ≤ 2 s (loose).

**Q54. Scale assumption for SC tests.** Plan.md says ≤10 containers, ≤200 agents, ≤1k events/day, ≤100 routes. Use as test fixtures?
- A. Yes — SC tests use exactly these fixture sizes. ★
- B. Use 10x scale (100 containers, 2000 agents) as a separate "scale" test suite.

**Q55. Latency budget exceeded behavior.** If a method's wall-clock blows past the target (e.g., `app.dashboard` taking > 500 ms), what does the daemon do?
- A. Nothing — always wait for completion. Budget is for testing, not runtime enforcement. ★
- B. Return `internal_error` with `details.reason == "timeout"` after 2× target.

**Q56. `scan.status` polling SLA.**
- A. SHOULD return within 100 ms (informational). ★
- B. Add explicit SC.

**Q57. `app.events.list` with deep history.** No `since`/`until` constraint, JSONL has millions of rows.
- A. Default ordering `event_id DESC` + pagination cap 200 keeps any single response bounded. Deep history requires pagination via cursor_next. Document as "use cursor_next to iterate." ★
- B. Hard cap on total iterated rows per session (e.g., 10,000); reject further pagination.

**Q58. Dashboard perf in degraded states.** Does SC-002 (≤500ms) hold when Docker is unavailable?
- A. Yes — readiness probes are cached; degraded state doesn't add I/O. ★
- B. Document: SC-002 holds only in non-degraded states; degraded adds up to 2 s.

---

## Block I — Security boundary (security CHK002/006/013/014/015/017/018/022/023/024/026)

**Applied answers:** Q59=A, Q60=A, Q61=A, Q62=A, Q63=A, Q64=A, Q65=A, Q66=A, Q67=A.

**Q59. macOS `SO_PEERCRED` variant.** Linux has `SO_PEERCRED`; macOS uses `LOCAL_PEERPID` + `getpeereid`. Spec doesn't pin.
- A. Reuse FEAT-002's existing peer-cred implementation byte-for-byte. ★
- B. Add an OS-specific note in research.md (clarify but don't change).

**Q60. Privilege drop on daemon startup.** Spec is silent.
- A. Out of scope; daemon assumed to run as the user. Documented in Assumptions. ★
- B. Add a requirement that daemon refuses to start as root.

**Q61. Socket file permissions changed mid-session.** (External `chmod`.)
- A. Daemon does not monitor; session continues unaffected. Documented as "operator responsibility." ★
- B. Daemon periodically validates socket perms and invalidates sessions on drift.

**Q62. Symlink attacks on the socket path.**
- A. Out of scope; documented as "FEAT-002 socket-path policy unchanged." ★
- B. Add a startup check that the socket path is not a symlink.

**Q63. Connection exhaustion (DoS).** Many `app.hello` calls from the same UID flooding sessions.
- A. Already mitigated by max-concurrent-sessions cap (Q29). ★
- B. Add rate-limit on `app.hello` per UID per minute.

**Q64. Secret redaction in `error.message` / `error.details`.** A payload field accidentally containing a secret leaks into validation_failed.
- A. `error.message` is operator-facing prose; daemon truncates `payload` references to first 64 chars before quoting. ★
- B. No redaction; document that callers must not put secrets in request payloads.

**Q65. Peer-cred check timing.**
- A. Accept-time only (FR-041 implication). ★
- B. Per-request re-check.

**Q66. Root daemon + non-root client.** Daemon starts as root for some reason; client is a normal user.
- A. Reject with `permission_denied` (daemon's effective UID must match peer UID). ★
- B. Allow (root daemon accepts any UID with matching socket permissions).

**Q67. Static-analysis test ensuring no `AF_INET` import in FEAT-011 code.**
- A. Yes — add a contract test that grep-scans `src/agenttower/app_contract/**` for `socket.AF_INET` and fails if found. ★
- B. Skip; SC-006 packet capture already covers this at runtime.

---

## Block J — Closed-set bookkeeping (errors CHK013; scope CHK027; cross-artifact CHK041)

**Applied answers:** Q70=A.

**Q68. error-codes.md says "26 entries"; closed-sets.md also says 26; FR-034 lists the 26.** Verified. No action.

**Q69. FR-040 + Assumptions tension** ("host OR mounted into a bench container" allowed for legacy; bench-container clients rejected from `app.*`). Already resolved by FR-042. ★ Auto-tick.

**Q70. `capability_flags` size cap.** No cap defined.
- A. ≤ 64 keys at `app.hello` response. ★
- B. No cap; document as "as needed."

---

## Default selection summary

Items marked ★ are my recommendation. If you reply "**all defaults**" or "**all recommended**", I'll apply every ★ as the answer, tick the corresponding checklist items, encode the new decisions into `spec.md` as a "Session 2026-05-19 (round 4)" Clarifications block, and resume `/speckit.implement`. If you want to override some, reply with `Q5: B, Q12: A, Q24: B, ...` and apply defaults to the rest.
