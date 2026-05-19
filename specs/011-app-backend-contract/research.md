# Phase 0 Research: Local App Backend Contract (FEAT-011)

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Date**: 2026-05-19

This phase resolves the open implementation questions surfaced by the technical context in `plan.md`. Every `NEEDS CLARIFICATION` from plan-time is closed below. No FR-level ambiguity remains (those were resolved across the two `/speckit.clarify` rounds — see `spec.md` §Clarifications, Session 2026-05-19).

---

## R-001: Host-vs-container peer detection mechanism

**Decision**: Reuse the existing FEAT-009 routing-toggle host-only detection. Wrap it in a single `app_contract/host_only.py` predicate `is_host_peer(connection) -> bool` so every `app.*` handler imports a single source of truth.

**Rationale**: FEAT-009 already needs this distinction for its routing-toggle host-only rule (per FEAT-009 spec and FR-042). The existing mechanism reads the peer's `pid` from `SO_PEERCRED` (Linux) or `LOCAL_PEERPID` (macOS), then inspects `/proc/<pid>/cgroup` (Linux) or `proc_pidinfo` (macOS) for a container cgroup marker. Reusing it avoids two divergent detection paths and ensures FR-042's "MUST reuse the same mechanism" constraint is trivially met.

**Alternatives considered**:
- *New independent detection in `app_contract/`*: rejected — divergence risk, violates FR-042 "MUST reuse".
- *Client-declared `peer_origin` field in `app.hello`*: rejected — trust boundary on a self-declared field is unacceptable for the host-only gate.

---

## R-002: macOS SO_PEERCRED variant choice

**Decision**: Use Python's `socket.getsockopt(socket.SOL_LOCAL, socket.LOCAL_PEERCRED)` (macOS) and `socket.SO_PEERCRED` (Linux). Wrap both behind `host_only.get_peer_pid_uid(conn)` returning `(pid, uid)`. The host-vs-container check runs against `pid`; the UID check (FR-041) runs against `uid`.

**Rationale**: This matches what FEAT-009's existing implementation uses (per code inspection of `src/agenttower/routing/permissions.py`). On macOS, `LOCAL_PEERCRED` returns `(uid, gid)` and `LOCAL_PEERPID` returns the pid; both are needed. On Linux, `SO_PEERCRED` returns `(pid, uid, gid)` in one call.

**Alternatives considered**:
- *`psutil` cross-platform abstraction*: rejected — adds a runtime dependency for a one-liner.
- *Windows-named-pipe variant*: out of scope — Windows daemon target uses Unix-domain sockets via WSL2 (per Assumptions) or AF_UNIX which Windows 10+ supports natively; `getsockopt(SO_PEERCRED)` is not available on Windows AF_UNIX, so the daemon falls back to checking the process owner via `GetNamedPipeServerProcessId` equivalent. This is out of scope for FEAT-011's contract — left to plan-level implementation in FEAT-012 / FEAT-013 host-runtime work if Windows desktop ships.

---

## R-003: Async vs threading model alignment with existing dispatcher

**Decision**: Reuse the existing dispatcher model (threaded — one OS thread per accepted connection, per FEAT-002). The `app_contract.dispatcher` registers method handlers with the same `Dispatcher` instance the legacy methods use, so `app.*` and legacy methods share the same per-connection thread. App-session state is keyed by `connection_id` (the dispatcher's existing handle) which gives us free cleanup on disconnect.

**Rationale**: The existing daemon is threaded, not asyncio-based. FEAT-008 event subscription (deferred) would re-evaluate this, but FEAT-011 is request/response only, so threads work fine. Sharing the dispatcher avoids a parallel I/O loop.

**Alternatives considered**:
- *Asyncio dispatcher for `app.*`*: rejected — would need a bridge to the threaded service layer; adds complexity for no measurable benefit at FEAT-011 scale.

---

## R-004: Envelope / details validation approach

**Decision**: Pure-Python validation via `envelope.py` and `errors.py` — no `pydantic`, no `jsonschema`. Success envelopes are built by `envelope.success(method, result)` and failure envelopes by `envelope.failure(method, code, details, message=None)`. Both helpers stamp `app_contract_version` automatically. The `errors.py` module exposes a registry `DETAILS_SCHEMA: dict[str, set[str]]` enumerating required keys per code; `envelope.failure()` asserts the supplied `details` dict contains every required key for the code, raising a daemon-side `ContractViolation` exception if a handler emits a malformed failure (caught and reported as `internal_error` to the client to avoid leaking the bug).

**Rationale**: The contract test suite is the system of record for envelope shape; adding `pydantic` / `jsonschema` to the runtime introduces a heavyweight dependency for a closed contract where every shape is known in advance. The closed-set codes and required-key registry are small (25 codes, ~10 entries with structured details) — a hand-written validator is more readable and faster than a schema engine. Contract tests still independently verify response shapes from the outside.

**Alternatives considered**:
- *pydantic models per envelope*: rejected — runtime dependency, slower cold start, encourages drift between Python model and FR-033/034/034a literal text.
- *jsonschema*: rejected — same reasons, plus higher per-call overhead which hurts SC-002's 500ms dashboard budget.

---

## R-005: Session token and `scan_id` generation strategy

**Decision**:
- `app_session_token`: `uuid.uuid4()` rendered as canonical lowercase hex with hyphens (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`). 36 characters. Stored as a Python `str`, never logged, never persisted.
- `app_session_id`: in-memory monotonic counter starting at `1` on daemon start. Reset on daemon restart per FR-006 "neither of which is persisted".
- `scan_id`: `uuid.uuid4()` hex string. Stored only in the in-memory scan-result table (FR-030c, cap 100).

**Rationale**: uuid v4 hex is 122 bits of entropy — sufficient for the connection-scoped, non-security-boundary role the token plays (per Assumptions and FR-006). Monotonic `app_session_id` aids audit attribution (operators can grep `app_session_id == 17` in JSONL). `scan_id` uses uuid to avoid sequential leakage between concurrent scans.

**Alternatives considered**:
- *cryptographically signed tokens*: rejected — token is not a security boundary (Assumptions); FR-043 forbids new auth primitives.
- *Integer-only `app_session_token`*: rejected — visually indistinguishable from `app_session_id` in logs would invite mix-ups; an explicit hex string makes redaction grep-friendly.

---

## R-006: Idempotency dedupe TTL and eviction policy

**Decision**: Per-session dict `{idempotency_key: (message_id, deduplicated_response)}` in `idempotency.py`. Lifetime = session lifetime (cleared when the connection closes; lost on daemon restart). Hard cap of **256 keys per session**; when full, the oldest entry is evicted (LRU). No wall-clock TTL.

**Rationale**: FR-031a says "in-memory only, lost on daemon restart or session close, which is acceptable because the same `app_session_id` cannot survive either." So session-lifetime is the natural envelope. The 256-key cap is generous (a session that sends 256+ `send_input` requests with distinct keys is pathological for a desktop control panel) and prevents memory bloat from a misbehaving client. LRU eviction means a client that re-uses keys for retries keeps the relevant ones hot. No TTL means we don't need a background sweeper thread.

**Alternatives considered**:
- *Wall-clock TTL (e.g., 5 min)*: rejected — needs a sweeper; introduces non-determinism into the dedupe test.
- *Unlimited keys per session*: rejected — DoS surface from a buggy client.
- *Daemon-wide dedupe store*: rejected — Clarify session locked `(app_session_id, idempotency_key)` as the scope.

---

## R-007: JSONL audit `origin` field threading

**Decision**: The existing FEAT-008 event-pipeline `JsonlAuditWriter` (per `src/agenttower/events/audit.py` and `src/agenttower/routing/audit_writer.py`) already accepts an `origin` keyword. Today the legacy CLI methods pass `origin="cli"` (when set at all). FEAT-011's `app_contract/audit.py` wraps the existing writer with a thin helper `emit_app_mutation(event_type, payload, session)` that injects `origin="app"` and `app_session_id=session.id` into the payload before forwarding to the existing writer. **No JSONL schema bump** — the file format already accommodates an `origin` string field.

**Rationale**: This keeps the JSONL contract additive at the value level (a new permissible value for an existing field), not at the schema level — consistent with FR-035 "additive within a major" and Edge Cases §Schema version vs contract version drift. The wrapper guarantees the `app_session_token` is never threaded through (FR-009, SC-008): only the int `app_session_id`.

**Alternatives considered**:
- *Separate JSONL file for app-driven mutations*: rejected — splits the audit trail, breaks operator-side `grep` workflows, and violates SC-010 byte-for-byte parity.
- *Schema version bump for the `origin = "app"` value*: rejected — additive value, not additive schema.

---

## R-008: View model assembly and "no global lock" enforcement

**Decision**: `view_models.py` exposes pure read functions that compose a view-model row from one or more service-layer DAOs (e.g., `pane_view(pane_row, agent_row | None) -> PaneViewModel`). The dashboard reads each surface independently (containers, panes, agents, etc.) through the same DAOs the CLI uses, with **no transaction wrapping the whole composition** — this satisfies FR-018 ("MUST NOT take any global lock, MUST tolerate slight inter-surface inconsistency"). Each individual DAO call runs in its own SQLite read transaction (the default for `sqlite3` connection with `isolation_level=None`).

**Rationale**: SC-002 (≤500ms dashboard) is achievable if each surface's count query is bounded (SQLite `COUNT(*)` on indexed columns is sub-ms at FEAT-011 scale). Composing without a global lock means concurrent CLI or app mutations can interleave between surface reads — explicitly documented as acceptable in FR-018.

**Alternatives considered**:
- *Snapshot the dashboard under a single `BEGIN`*: rejected — violates FR-018, hurts concurrent mutation latency.
- *Cache the dashboard for N ms*: rejected — invalidation complexity, masks bugs in fixture fixtures, breaks SC-002 "no-cache test".

---

## R-009: Scan worker integration

**Decision**: `app.scan.containers` and `app.scan.panes` call the existing FEAT-003 / FEAT-004 discovery scanners (already reusable as library functions per FEAT-003/004 specs). `scans.py` manages an in-memory `ScanRegistry` keyed by `scan_id`. For `wait=true`, the call blocks on a `threading.Event` armed by the scan worker; FR-030b's 30s cap is enforced by `Event.wait(timeout=30)`. For `wait=false`, the call returns immediately with the `scan_id`. The scan worker always completes server-side (FR-030b) and writes the result into the registry whether or not anyone is waiting.

The registry is an `collections.OrderedDict` (insertion-ordered) capped at 100 entries; when full, the oldest entry is evicted (FIFO). An evicted or unknown `scan_id` → `scan_not_found`.

**Rationale**: Reusing the existing scanners (FEAT-003/004) satisfies FR-004 ("dispatch into the same daemon-internal service layer"). `OrderedDict` is the simplest cap-with-eviction structure in the stdlib. FIFO over LRU because scan results have natural age-based usefulness (a 3-week-old scan result is no longer informative).

**Alternatives considered**:
- *Per-session scan registry*: rejected — Clarify session locked daemon-wide retention; per-session would break the reconnect-and-resume path implied by FR-030b.
- *Persist scan results to SQLite*: rejected — FR-030c explicitly requires in-memory only.

---

## R-010: Contract test client design

**Decision**: A bare-metal Python socket client in `tests/fixtures/app_synthetic_client.py` connects directly to the daemon Unix socket, frames NDJSON request lines, parses NDJSON response lines, and returns dicts. **Never** invokes the `agenttower` CLI subprocess — this is required by SC-001 ("zero lines parsing human CLI text"). The client exposes typed helpers per method (e.g., `client.app_hello() -> dict`, `client.app_dashboard(recent_limit=10) -> dict`) and a low-level `client.call(method, params) -> dict` escape hatch.

**Rationale**: Direct socket use mirrors what the future Flutter / Rust / Swift / Electron client will do (per Assumptions: "language-agnostic, could be consumed by..."). It also gives the test suite full control over framing edge cases (oversized line, malformed JSON, two JSONs on one line — see checklist `contract-surface.md` CHK019/CHK020).

**Alternatives considered**:
- *Reuse the FEAT-005 thin-client library*: rejected — the thin client is purpose-built for legacy methods and represents a different consumer profile; using it would couple FEAT-011 tests to FEAT-005 evolution.
- *grpc / http-style framework*: rejected — wrong transport.

---

## Summary

All ten research items closed; no remaining `NEEDS CLARIFICATION`. Ready to proceed to Phase 1 design artifacts.
