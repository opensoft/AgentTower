# FEAT-011 — Next Session Pickup

**Last updated**: 2026-05-19 (commit pending; round-4 + Story-1 socket integration test)
**Branch**: `011-app-backend-contract`
**Worktree**: `/workspace/projects/AgentTower-worktrees/011-app-backend-contract/`
**PR**: [#19](https://github.com/opensoft/AgentTower/pull/19) — OPEN, 7+ commits

## Latest progress (2026-05-19 round 4 + T023)

- **Round 4 clarifications encoded** (commit `5984d6b`): 70-question checklist
  walkthrough block in spec.md; 27-code closed set (added `malformed_request`);
  new FRs FR-003b (wire framing), FR-008a/b (hello idempotency + 8-session
  cap), FR-028a-d (adopt full-identity match + attach_log/inactive rules +
  parent_agent_id + label normalization), FR-030d/e (scan coalescing + 4-cap),
  FR-031 (routing_disabled vs permission_denied split), FR-044a-c (audit
  mutex + best-effort + ordering); new SCs SC-028..SC-038; all 668
  checklist items ticked across 23 files.
- **T023 done** — `tests/integration/test_story1_dashboard_bootstrap.py`
  walks Story 1 over a real Unix socket, **10 tests passing**. Includes
  SC-002 worst-of-5 ≤500ms and SC-008 token-redaction.
- **T030 folded into T023** — Round-4 Block H Q52 changed SC-002 from
  "p95 over 20 trials" to "worst across 5 trials"; that's what the test
  asserts.
- **errors.py bumped** to 27 codes (added `MALFORMED_REQUEST`); smoke
  suite now 57 passed.

### Drift discoveries (filed as T097, T098 in tasks.md)

T023 surfaced two real spec/implementation mismatches:

1. **T097**: FEAT-002 is one-request-per-connection, so FR-008 "invalidate
   on connection close" and FR-008a "idempotent on same connection" are
   unreachable as written. The implementation adapted (token-keyed
   registry across connections, token in `params`); the spec text needs
   updating to match. Recommended: spec fix, not code change.
2. **T098**: The legacy FEAT-002 `unknown_method` envelope is missing the
   FR-033-mandated `details: {}` field and `app_contract_version` stamp
   for `app.*` method names. Add a wrapping rewriter at the FEAT-011
   dispatcher.

These do NOT block US1 merge; they should be triaged at the start of
the next session.

---

This file exists so the next `/speckit.implement` session can pick up
without re-reading every commit message. The `tasks.md` checklist is the
authoritative scope list — this file just adds context the checklist
doesn't capture.

---

## 1. Sync first

```bash
cd /workspace/projects/AgentTower-worktrees/011-app-backend-contract
git status               # expect: clean tree on branch 011-app-backend-contract
git pull --ff-only       # safety: catch any remote-side updates
PYTHONPATH=src python -m pytest tests/unit/test_app_contract_smoke.py -q
# expect: 50 passed
```

If the smoke suite is green, you are safe to start adding code. If
anything fails, fix that first — do NOT layer new work on a broken base.

---

## 2. What's actually working today (don't redo)

The full **Story 1 bootstrap chain** is implemented and tested
in-process:

```
app.preflight  → diagnostic envelope (no session needed)
app.hello      → issues session token; returns daemon/contract versions
app.readiness  → 6 subsystem probes + state aggregation + hints[]
app.dashboard  → counts across 7 surfaces + recents + hints[]
```

- All 4 handlers registered in `socket_api/methods.py::DISPATCH` (39
  entries total — 35 legacy + 4 new `app.*`).
- Host-only gate (FR-042) on every method including preflight/hello.
- Session-required gate (FR-007) on readiness/dashboard, fires AFTER
  host-only so container peers never see session-state leakage.
- 27-entry closed code set (FR-034), 15-entry per-code `details`
  registry (FR-034a), envelope shape (FR-033), all enforced by
  `errors.validate_details()` → `ContractViolation` if a handler
  emits a malformed failure.
- Capability flags `{}` at v1.0 (FR-039), major-mismatch guard (FR-036).

**Ticked tasks in `tasks.md`**: 13 of 94 → T002, T004–T008, T010,
T024–T029. Plus partial: T015 (compact view models only).

---

## 3. Recommended pickup order

### Option A — Close out US1 properly (smallest scope, ~3–4 hours)

The fastest path to a "shippable" partial PR. Adds:

| Task | What | Why |
|---|---|---|
| T019..T022 | Move smoke tests into proper `tests/contract/test_app_*.py` files | Test layout matches `plan.md` §Project Structure; reviewers expect contract tests under `tests/contract/` |
| T023 | Integration test `tests/integration/test_story1_dashboard_bootstrap.py` over a real Unix socket | Closes the socket-level test gap noted in the PR review |
| T030 | SC-002 ≤500 ms benchmark fixture | Pins the latency contract |
| Polish: `T015` finish — full view models for all 7 entities | Needed by US2/US3 anyway | |

Outcome: a clean US1-complete PR ready to merge as `FEAT-011 (1/?)`.

### Option B — Move on to US2 Adopt (bigger scope, ~6–8 hours)

If you'd rather get more end-user value before merging. Adds:

| Task cluster | What |
|---|---|
| T011 | `IdempotencyStore` (in-memory, per-session, 256 cap, LRU). Needed by `app.send_input` (US3). |
| T012 | `ScanRegistry` (in-memory, 100 cap, FIFO). Needed by `app.scan.*`. |
| T013 | Audit helper `audit.emit_app_mutation()` — wraps existing FEAT-008 JSONL writer, injects `origin="app"` + `app_session_id`. |
| T015 finish | Full PaneViewModel + AgentViewModel for `app.pane.list/detail` + `app.agent.list/detail`. |
| T036..T041 | Scans (containers, panes, status) + adopt mutation (`app.agent.register_from_pane`). |
| T031..T035, T042 | Contract tests + integration test for Story 2. |

Outcome: the brief's "adopt-existing-panes" MVP target is hit. Bigger
PR but more value.

### Option C — One coherent monster PR (entire 81 remaining tasks)

Not recommended for this PR. Open as `FEAT-011 (2/?)` after merging
the current one.

**My recommendation**: Option A first (close US1 properly), then
merge, then Option B as a separate PR.

---

## 4. Known weaknesses / follow-ups already flagged

These were called out in the PR review (#19) and either fixed or
deferred:

| Issue | Severity | Status |
|---|---|---|
| FR-007 session gate not enforced | HIGH | **Fixed** in `3577f5c` |
| `probe_jsonl` writability check | MEDIUM | **Fixed** in `3577f5c` |
| `probe_docker` checks SQLite cache, not Docker itself | MEDIUM | Deferred — document in docstring during US2 polish |
| No socket-level integration test (only in-process smoke) | LOW | Deferred — see T023 in Option A |
| `set_registry()` is module-level mutation seam | LOW | Acceptable; revisit if dependency-injection becomes useful |
| Full DispatcherGateChain (T014) centralization | LOW | Acceptable as-is; each handler calls `gate_session_required()` at the top |

---

## 5. Pre-existing FEAT-001..010 test failures (NOT caused by FEAT-011)

Documented in commits `aa13224` and `8cb0c81`. Do NOT block on these:

1. `tests/integration/test_cli_status.py::test_status_default_output_six_lines`
   — FEAT-008/009/010 added status fields; test expects 6 lines, daemon
   now emits 14.
2. `tests/integration/test_feat009_backcompat.py::test_backcompat_status_json_keeps_feat002_through_008_keys`
   — asserts `schema_version == 7`; FEAT-010 bumped to 8.
3. `tests/integration/test_cli_scan_panes_inactive_cascade.py::test_inactive_container_with_only_inactive_prior_panes_still_touches_them`
   — pre-existing flaky millisecond-timestamp race.

These deserve a **separate cleanup PR**, not FEAT-011 scope.

---

## 6. Practical gotchas

### Circular imports

`socket_api/methods.py` does `from agenttower.app_contract.dispatcher
import APP_DISPATCH` at the END of the module (after all FEAT-002 names
are defined). The `app_contract.host_only` module imports
`_peer_is_host_process` from `socket_api/methods.py`. To prevent a
cycle when external code imports `app_contract.hello` (or any handler)
first, **handler modules MUST NOT import `host_only` at module load**
— they do `from .host_only import is_host_peer` inside the function
body. Same applies to `sessions.gate_session_required`.

When adding new handler modules, follow the same pattern:
- Use `TYPE_CHECKING` for `DaemonContext` import.
- Define `_NO_PEER_UID: int = -1` locally as a constant.
- Lazy-import anything that touches `socket_api/methods` (host_only,
  sessions, etc.) inside the function body.

### Test-time host-peer detection

The container probe (`_peer_is_host_process`) reads
`/proc/<pid>/cgroup` and `/.dockerenv` — both false-positive in WSL2,
Docker-in-Docker, and most CI sandboxes. Use the documented test seam:

```python
monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
```

…and also set the thread-local peer context:

```python
from agenttower.socket_api.methods import _set_request_peer_context
_set_request_peer_context(peer_pid=os.getpid())
```

The `host_peer` and `host_session` fixtures in
`tests/unit/test_app_contract_smoke.py` already do both — reuse them
or copy the pattern.

### Request-payload token location

Per the review fix in `3577f5c`, the `app_session_token` lives **inside
`params`**, not as a top-level request field:

```json
{"method": "app.readiness", "params": {"app_session_token": "f7a3..."}}
```

This avoids any change to `socket_api/methods.py` beyond the
9-line DISPATCH merge. The `quickstart.md` sample reflects this. If a
future change wants to move the token to the top level, it requires
modifying the FEAT-002 dispatcher — not a small change.

### FEAT-002's 64 KiB request cap is the effective payload limit

`server.py` enforces `MAX_REQUEST_BYTES = 65536` on the request line.
FR-003a specifies a 1 MiB cap, but the existing FEAT-002 cap binds
first. For US2/US3 work, this is unlikely to matter (no realistic
`app.send_input` payload approaches even 64 KiB). If a future
requirement needs >64 KiB, that's a separate spec/plan change against
`socket_api/server.py`.

---

## 7. File map (where things live)

```
src/agenttower/app_contract/
├── __init__.py             # APP_CONTRACT_VERSION, SUPPORTED_MINOR_RANGE
├── versioning.py           # constants + all closed-set enums
├── errors.py               # 27 error codes + DETAILS_REQUIRED_KEYS + validate_details
├── envelope.py             # success / failure / internal_error builders
├── sessions.py             # AppSession + SessionRegistry + gate_session_required
├── host_only.py            # is_host_peer wrapper (FR-042)
├── preflight.py            # app.preflight handler (FR-011)
├── hello.py                # app.hello handler (FR-010 + FR-036)
├── readiness.py            # 6 probes + emit_hints + app.readiness handler
├── dashboard.py            # counts + recents + app.dashboard handler
├── view_models.py          # compact builders for events/queue/routes (US1 only)
└── dispatcher.py           # APP_DISPATCH map → merged into FEAT-002 DISPATCH

tests/unit/
└── test_app_contract_smoke.py   # 50 tests covering all of the above

# Modules NOT yet created (next-session work):
src/agenttower/app_contract/{idempotency,scans,reads,mutations,audit}.py

tests/contract/                  # not yet populated; goal layout in plan.md
tests/integration/test_story*.py # not yet populated
tests/fixtures/app_*.py          # not yet populated (currently inline in smoke)
```

---

## 8. Commit before walking away

Whenever you stop mid-task:

1. Make sure the smoke suite passes: `PYTHONPATH=src pytest
   tests/unit/test_app_contract_smoke.py -q`.
2. Update `tasks.md` — tick the `[X]` for any task you fully
   completed.
3. Commit with a `FEAT-011: …` prefix and a Co-Authored-By footer.
4. Push: `git push` (already tracking origin/011-app-backend-contract).
5. Update this file's "Last updated" line with the new commit short
   hash if you significantly change the picture.

The PR (#19) auto-updates on push.

---

## 9. Quick mental model refresh

If you've been away from this codebase:

- **What this feature is**: a `app.*` socket method namespace that lets
  a packaged desktop app talk to `agenttowerd` without scraping CLI
  output. Host-only. Versioned. Closed-set everything.
- **Why it has so many specs**: 6 clarify rounds, multiple checklist
  passes, and analyze remediations produced a very tight contract.
  74 FRs, 38 SCs, 27 closed-set codes — all locked. The spec is the
  hardest-thinking part already done.
- **Where the implementation phase actually is**: 13/94 tasks done.
  The skeleton is solid; the bulk of US2/US3 mutation work + tests +
  polish remains.
