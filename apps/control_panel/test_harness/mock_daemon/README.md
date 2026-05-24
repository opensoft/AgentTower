# Mock FEAT-011 Daemon

Python harness used by FEAT-012 integration tests. Listens on a temp Unix socket and speaks the FEAT-011 `app.*` envelope contract per `contracts/app-methods-consumed.md`.

## Why Python

Per research R-17 (in `../../../../specs/012-flutter-control-panel/research.md`), keeping the harness in Python lets us reuse the FEAT-011 fixture files maintained alongside the real daemon implementation (`tests/contract/test_app_*` in the daemon repo) without re-implementing the envelope parser in Dart.

## Usage

```bash
# Start the harness in the background:
python3 server.py --socket /tmp/feat012-test.sock --fixture us1_happy_path.json &

# Point the Flutter app at it via env or Settings:
DAEMON_SOCKET_PATH=/tmp/feat012-test.sock flutter test integration_test/us1_adopt_and_operate.dart

# Stop with Ctrl+C or kill the background process.
```

The Dart-side helper (`../../test/helpers/mock_daemon_client.dart`, T052) spawns the harness automatically for each integration test and kills it on teardown — tests do NOT need to start the harness by hand.

## Fixture format

```json
{
  "app_contract_version": "1.0",
  "daemon_version": "0.11.0-mock",
  "app_session_token": "00000000-0000-4000-8000-000000000001",
  "app_session_id": 1,
  "host_user_id": "1000",
  "schema_version": 1,
  "responses": {
    "app.hello": {"ok": true, "result": {}},
    "app.preflight": {"ok": true, "result": {"checks": []}},
    "app.readiness": {"ok": true, "result": {"state": "ready", "subsystems": [], "hints": []}},
    "app.dashboard": {
      "ok": true,
      "result": {
        "counts": {
          "containers": {"active": 1, "inactive": 0, "degraded_scan": 0},
          "panes_by_state": {"discovered-and-unmanaged": 1},
          "registered_agents_by_state": {},
          "blocked_queue": 0,
          "recently_skipped_routes": 0
        },
        "recents": [],
        "recommended_next_action": null,
        "hints": []
      }
    },
    "app.pane.list": {
      "ok": true,
      "result": {
        "rows": [
          {
            "pane_id": "p1",
            "container_id": "bench-1",
            "tmux_socket": "/tmp/tmux-1000/default",
            "tmux_session_name": "main",
            "tmux_window_index": 0,
            "tmux_pane_index": 0,
            "state": "discovered-and-unmanaged"
          }
        ],
        "total": 1,
        "cursor_next": null,
        "ordering": "default"
      }
    }
  }
}
```

Notes:

- The `app.hello` `result` is filled in with the FEAT-011-required fields
  (`app_session_token`, `app_session_id`, `daemon_version`, `schema_version`,
  `app_contract_version`, `supported_minor_range`, `host_user_id`,
  `capability_flags`, `state`) — empty `{}` in the fixture is fine; the
  harness stamps the missing fields from the top-level fixture keys.
- If a request method is NOT in `responses`, the harness returns
  `unknown_method` (FR-034b) from FEAT-011's closed-set vocabulary with
  `details == {}`.
- **Envelope shapes** (per `specs/011-app-backend-contract/contracts/app-methods.md`):
  - `.list` returns `result: {rows: [], total: int|null, total_estimate: int|null, cursor_next: str|null, ordering: str}`
  - `.detail` returns `result: {row: <EntityViewModel>}`
  - Every mutation except `app.send_input` and `app.scan.*` also returns
    `result: {row: <post-mutation EntityViewModel>}`
  - `app.send_input` returns `result: {message_id, state, deduplicated}` (FLAT)
  - `app.scan.containers/.panes/.status` return `result: {scan_id, state, ...}` (FLAT)
- **Pane identity fields**: every `app.pane.*` row exposes all six identity
  fields (`pane_id`, `container_id`, `tmux_socket`, `tmux_session_name`,
  `tmux_window_index` as int, `tmux_pane_index` as int) so `app.agent.register_from_pane`
  can pass them back byte-for-byte (FR-028a).

## Error injection

To exercise the FEAT-011 error vocabulary, set `responses["<method>"]` to:

```json
{
  "ok": false,
  "error": {
    "code": "permission_denied",
    "message": "Master role required",
    "details": {"required_role": "master"}
  }
}
```

The 27-entry error code set lives in `apps/control_panel/lib/core/daemon/errors.dart` and is sourced from `specs/011-app-backend-contract/contracts/error-codes.md`.

To inject `app_contract_major_unsupported` and have the harness build the FR-036 `details = {daemon_app_contract_version, client_app_contract_major}` payload from the request, use:

```json
"app.hello": {
  "ok": false,
  "_use_helper": "app_contract_major_unsupported"
}
```

## Wire-framing strictness

The harness enforces FEAT-011 FR-003a (1 MiB request / 8 MiB response caps) and FR-003b (UTF-8 + `\n`-terminated + no `\r` / `\x00`). Tests that intentionally violate these expect to get `payload_too_large` or `malformed_request` responses.

## Per-test isolation

Each integration test should:
1. Spawn its own harness process with a unique socket path (e.g. `/tmp/feat012-<test-name>-<pid>.sock`)
2. Bind a fresh fixture
3. Tear down the process at the end of the test

The Dart helper at `../../test/helpers/mock_daemon_client.dart` automates this — see its `setUp` / `tearDown` patterns.
