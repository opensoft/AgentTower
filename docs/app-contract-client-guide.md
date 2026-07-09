# App Backend Contract — Client Developer Guide (FEAT-011)

This guide is for anyone building a client against the AgentTower
`app.*` socket namespace — the first target is a Flutter desktop control
panel, but the contract is language-agnostic (Rust, Swift, Electron, or a
test harness work equally well).

The authoritative spec is `specs/011-app-backend-contract/`
(`spec.md`, `contracts/app-methods.md`, `contracts/closed-sets.md`,
`contracts/error-codes.md`). This guide is the practical orientation.

## 1. Transport

- **Unix domain socket.** The daemon listens on a single `AF_UNIX`
  stream socket (path from the FEAT-001 path contract, typically
  `~/.local/state/opensoft/agenttower/agenttowerd.sock`). There is no
  TCP / HTTP / WebSocket listener — local-only is an invariant.
- **NDJSON framing.** One request is one UTF-8 JSON object on one line
  terminated by a single `\n`. The response is one JSON object on one
  line. The line MUST be valid UTF-8, contain no `\r` or `\x00`, and
  hold exactly one JSON object — violations are rejected with
  `malformed_request` before dispatch.
- **One request per connection.** The daemon reads one line, dispatches,
  writes one line, and closes the socket. Open a fresh connection for
  every call. Sessions are NOT connection-bound (see §3).
- **Size cap.** A request line must not exceed the daemon's read cap
  (64 KiB effective; the contract documents 1 MiB). Oversized `app.*`
  lines get `payload_too_large`.

A request line:

```json
{"method": "app.readiness", "params": {"app_session_token": "f7a3…"}}
```

## 2. Envelopes

Every response is exactly one of:

```json
{"ok": true,  "app_contract_version": "1.0", "result": { … }}
{"ok": false, "app_contract_version": "1.0",
 "error": {"code": "<closed-set>", "message": "<prose>", "details": { … }}}
```

- `app_contract_version` is always present — check it to detect drift.
- `error.code` is always from the 27-entry closed set
  (`contracts/error-codes.md`). Never parse `error.message` — it is
  operator-facing prose. `error.details` is always an object (possibly
  `{}`); per-code required keys are in the FR-034a registry.
- Treat an unknown `error.code` (from a newer daemon) as an
  `internal_error`-class display state — do not crash.

## 3. Bootstrap sequence

1. **`app.preflight`** — no session needed. Returns
   `{socket_reachable, daemon_reachable, code}` where `code ∈ {ok,
   daemon_unavailable, socket_missing, socket_permission_denied}`. Use
   it to fail fast before `app.hello`.
2. **`app.hello`** — the handshake. Send optional `client_id`,
   `client_version`, `client_app_contract_major` (default `1`).
   Returns `app_session_token`, `app_session_id`, daemon/schema/contract
   versions, `supported_minor_range`, `host_user_id`, `capability_flags`,
   `state: "ok"`. On a major mismatch it returns
   `app_contract_major_unsupported` and issues **no** token — the client
   MUST stop.
3. **`app.readiness`** — `{state ∈ {ready, degraded, unavailable},
   subsystems[], hints[]}`. Render the control panel, a degraded
   banner, or a setup screen accordingly.
4. **`app.dashboard`** — one aggregate payload: counts + recent rows +
   `hints[]` for every surface.

**Session handling.** The token lives in a process-wide registry, NOT
bound to the connection that issued it. Re-present it in `params` on
every subsequent `app.*` call. It is invalidated only by daemon
restart or registry eviction — a call that fails to resolve the token
returns `app_session_expired`; call `app.hello` again. Every method
except `app.preflight` and `app.hello` returns `app_session_required`
when the token is missing.

## 4. Reads and pagination

`app.<entity>.list` / `app.<entity>.detail` exist for `container`,
`pane`, `agent`, `log_attachment`, `event`, `queue`, `route`.

- `limit`: default 50, hard cap 200.
- `cursor_next`: opaque base64 string (≤ 512 chars) — pass it back
  verbatim for the next page; never parse it. Reusing a cursor under a
  changed `order_by`/`filters` is rejected with `validation_failed`.
- `order_by`: `field`, `field:asc`, or `field:desc` from the per-surface
  closed set in `contracts/closed-sets.md`.
- Filters are exact-match only.

## 5. Mutations

All mutations are synchronous and return the post-mutation entity in
`result.row`. `app.scan.*` accept `wait` (default `true`, 30 s cap);
`wait:false` returns a `scan_id` to poll via `app.scan.status`.
`app.send_input` accepts an optional `idempotency_key` — a duplicate
retry returns the original `message_id` with `deduplicated: true`.

## 6. A minimal client loop (pseudocode)

```
sock = connect(socket_path); send(sock, {"method":"app.preflight"})
hello = one_shot({"method":"app.hello",
                  "params":{"client_id":"my-app","client_app_contract_major":1}})
if not hello.ok and hello.error.code == "app_contract_major_unsupported":
    abort("daemon speaks a newer major")
token = hello.result.app_session_token
dash  = one_shot({"method":"app.dashboard",
                  "params":{"app_session_token": token}})
render(dash.result)
```

Each `one_shot` opens a fresh socket, writes one NDJSON line, reads one
line, closes. See `tests/integration/test_story1_dashboard_bootstrap.py`
for a working reference client.

## 7. Forward compatibility

- Ignore unknown response fields (a newer daemon may add them).
- Check `capability_flags` before calling an optional method introduced
  in a later minor (none exist at v1.0 — `capability_flags == {}`).
- Surface unknown closed-set codes gracefully; never hard-fail on them.

## 8. FEAT-013 managed-session methods

FEAT-013 adds 8 new methods to the `app.*` namespace — `app.managed_*`
— for operator-driven creation of multi-agent tmux layouts inside bench
containers. They are **required** surfaces at `app_contract_version =
"1.0"` (not advertised in `capability_flags`; reached through the
additive-evolution rule).

See **[`docs/managed-sessions.md`](managed-sessions.md)** for the full
operator reference: templates, launch profiles, lifecycle states, the
M1–M8 method table, closed-set error codes, and the YAML override
directories.

Quick method list:

- `app.managed_layout_create` / `app.managed_layout_list` / `app.managed_layout_detail` — layout creation + read
- `app.managed_pane_list` / `app.managed_pane_detail` — pane read
- `app.managed_pane_remove` / `app.managed_pane_recreate` — destructive lifecycle
- `app.managed_pane_promote_from_adopted` — reserved stub (returns `not_implemented`)
