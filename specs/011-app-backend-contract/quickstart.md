# Quickstart: Local App Backend Contract (FEAT-011)

**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)

This quickstart walks a synthetic client through **Story 1** end-to-end (`app.preflight` → `app.hello` → `app.readiness` → `app.dashboard`) over the daemon's existing Unix socket. It is the minimum-viable proof that the contract is callable and renderable without scraping any human CLI text (SC-001).

Use this as both:
- A manual smoke check after building FEAT-011 locally.
- The literal script the integration test `tests/integration/test_story1_dashboard_bootstrap.py` will automate.

---

## Prerequisites

- FEAT-001..FEAT-010 already shipped and the daemon running on the host.
- At least one bench container running with at least one tmux pane.
- At least one registered agent (use the legacy `agenttower register-self` CLI to set one up for this smoke test).
- The daemon socket reachable at the configured path (typically `~/.local/state/opensoft/agenttower/agenttowerd.sock`).

---

## Step 0 — Locate the socket

```bash
test -S "$HOME/.local/state/opensoft/agenttower/agenttowerd.sock" && echo "socket present"
```

If the socket is missing or unreadable, the contract requires `app.preflight` to surface a structured code (`socket_missing` / `socket_permission_denied`) — not an unstructured connect error.

---

## Step 1 — `app.preflight` (no session required)

A client opens a Unix socket connection and writes one NDJSON line:

```json
{"method": "app.preflight", "params": {}}
```

**Expected response** on a healthy install:

```json
{"ok": true, "app_contract_version": "1.0", "result": {"socket_reachable": true, "daemon_reachable": true, "code": "ok"}}
```

**Failure paths** ([app-methods.md](./contracts/app-methods.md)):
- Daemon process down (but socket file present, stale-pid case): `code == "daemon_unavailable"`.
- Socket file missing: client gets a connection error from the OS; preflight cannot be reached. Client library is expected to translate this into `socket_missing`.
- Permission denied at open: client gets a connection error; client library translates to `socket_permission_denied`.
- Bench-container peer: `{ok: false, error: {code: "host_only", ...}}`.

---

## Step 2 — `app.hello` (issues session)

```json
{"method": "app.hello", "params": {"client_id": "smoke-test", "client_version": "0.0.0", "client_app_contract_major": 1}}
```

**Expected response**:

```json
{
  "ok": true,
  "app_contract_version": "1.0",
  "result": {
    "app_session_token": "f7a3...",
    "app_session_id": 1,
    "daemon_version": "0.10.0",
    "schema_version": 8,
    "app_contract_version": "1.0",
    "supported_minor_range": {"min": "1.0", "max": "1.0"},
    "host_user_id": "1000",
    "capability_flags": {},
    "state": "ok"
  }
}
```

**Key invariants to assert** (Story 1 acceptance #1):
- `app_session_token` is a non-empty string.
- `app_contract_version` matches `MAJOR.MINOR` regex.
- `daemon_version` matches the running daemon.
- `capability_flags == {}` at v1.0.
- `state == "ok"`.

**Failure paths**:
- Client declares `client_app_contract_major: 2` (or any value the daemon doesn't speak): `{ok: false, error: {code: "app_contract_major_unsupported", details: {daemon_app_contract_version: "1.0", client_app_contract_major: 2}}}`. **No session is issued**, no subsequent `app.*` call is accepted.

Save `app_session_token` for every subsequent call.

---

## Step 3 — `app.readiness` (with session)

```json
{"method": "app.readiness", "params": {"app_session_token": "f7a3..."}}
```

**Expected response on a healthy install**:

```json
{
  "ok": true,
  "app_contract_version": "1.0",
  "result": {
    "state": "ready",
    "subsystems": [
      {"name": "docker",                  "status": "ok", "reason": "", "hint": null},
      {"name": "tmux_discovery",          "status": "ok", "reason": "", "hint": null},
      {"name": "sqlite",                  "status": "ok", "reason": "", "hint": null},
      {"name": "jsonl",                   "status": "ok", "reason": "", "hint": null},
      {"name": "routing_worker",          "status": "ok", "reason": "", "hint": null},
      {"name": "log_attachment_workers",  "status": "ok", "reason": "", "hint": null}
    ],
    "hints": []
  }
}
```

**Key invariants** (Story 1 acceptance #2):
- `state == "ready"` when every subsystem is `ok`.
- Each subsystem row has `status ∈ {ok, degraded, unavailable}` and `reason == ""` when `status == "ok"`.
- `hints` is always present, may be empty.

**Sample degraded response** (Docker stopped):

```json
{
  "result": {
    "state": "degraded",
    "subsystems": [
      {"name": "docker", "status": "unavailable", "reason": "Cannot connect to docker daemon", "hint": "start the docker service"},
      ...
    ],
    "hints": [{"code": "docker_unavailable_hint", "severity": "action_required", "message": "Docker is not reachable from the daemon."}]
  }
}
```

---

## Step 4 — `app.dashboard`

```json
{"method": "app.dashboard", "params": {"recent_limit": 5, "app_session_token": "f7a3..."}}
```

**Expected shape on a healthy install with ≥1 container and ≥1 agent**:

```json
{
  "ok": true,
  "app_contract_version": "1.0",
  "result": {
    "counts": {
      "containers":      {"active": 1, "inactive": 0, "degraded_scan": 0},
      "panes":           {"total": 3, "registered": 1, "unregistered": 2},
      "agents":          {"total": 1, "by_role": {"master": 1, "slave": 0, "swarm": 0, "test-runner": 0, "shell": 0, "unknown": 0}},
      "log_attachments": {"active": 1, "degraded": 0, "none": 0},
      "events":          {"total": 47},
      "queue":           {"queued": 0, "blocked": 0, "delivered": 47, "canceled": 0, "failed": 0},
      "routes":          {"enabled": 0, "disabled": 0}
    },
    "recent": {
      "events": [ ... up to 5 ... ],
      "queue":  [ ... up to 5 ... ],
      "routes": [ ... up to 5 ... ]
    },
    "hints": [
      {"code": "enable_first_route", "severity": "info", "message": "No routes configured yet."}
    ]
  }
}
```

**Key invariants** (Story 1 acceptance #3):
- Every count is a non-negative integer (never `null`, never `-1`).
- Every "recent" array length is `≤ recent_limit`.
- `hints` is always present.
- The whole payload renders without consulting any subprocess output.

**SC-002 budget**: This entire flow (Steps 2–4) must complete in **≤ 500 ms** wall-clock on a workstation with no warmed caches.

---

## Step 5 — Verification

After the four calls above, confirm:

1. **No subprocess invocation** — the script never ran `agenttower` as a child process. The only I/O was over the Unix socket.
2. **No CLI parsing** — no `grep`, `awk`, or text scraping of any kind.
3. **All envelopes are structurally valid** — every response has `ok`, `app_contract_version`, and exactly one of `result` / `error`.
4. **Token redaction** — the JSONL audit at `~/.local/state/opensoft/agenttower/audit.jsonl` does **not** contain `app_session_token` anywhere; it does contain `app_session_id: 1` if any mutation was issued during the session.

---

## Beyond Story 1

The full integration test set exercises:

- **Story 2** ([test_story2_adopt_roundtrip.py](./)) — `scan.panes` → `pane.list` (unregistered row) → `agent.register_from_pane` → `agent.detail` (confirm linkage), within the SC-004 2 s budget.
- **Story 3** ([test_story3_operator_actions.py](./)) — `route.add` / `route.update`, `send_input` (with idempotency_key), `queue.approve/delay/cancel`, `log.attach/detach`, `agent.update`.
- **Story 4** ([test_story4_degraded_states.py](./)) — every readiness failure mode from Story 4 acceptance produces a structured, renderable state.
- **Story 5** ([test_story5_version_drift.py](./)) — major-mismatch refusal, and a within-major minor-N-vs-minor-(N+1) compatibility check (synthetic clients).

Each story acceptance scenario maps 1:1 to a contract or integration test under `tests/contract/` or `tests/integration/`. The exhaustive test inventory ships with `/speckit.tasks`.
