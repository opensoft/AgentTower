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
  "session_token": "test-session-token",
  "responses": {
    "app.hello": {"ok": true, "result": {}},
    "app.preflight": {"ok": true, "result": {"checks": []}},
    "app.readiness": {"ok": true, "result": {"hints": []}},
    "app.dashboard": {
      "ok": true,
      "result": {
        "container_count": 1,
        "pane_count_by_state": {"discovered-and-unmanaged": 1},
        "registered_agent_count_by_state": {},
        "blocked_queue_count": 0,
        "recently_skipped_route_count": 0
      }
    },
    "app.pane.list": {
      "ok": true,
      "result": {
        "items": [
          {
            "pane_id": "p1",
            "container_id": "bench-1",
            "tmux_session_name": "main",
            "tmux_window_index": "0",
            "tmux_pane_index": "0",
            "state": "discovered-and-unmanaged"
          }
        ],
        "next_cursor": null
      }
    }
  }
}
```

If a request method is NOT in `responses`, the harness returns `method_not_found` from FEAT-011's closed-set vocabulary.

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

The 27-entry error code set lives in `apps/control_panel/lib/core/daemon/errors.dart`.

## Wire-framing strictness

The harness enforces FEAT-011 FR-003a (1 MiB request / 8 MiB response caps) and FR-003b (UTF-8 + `\n`-terminated + no `\r` / `\x00`). Tests that intentionally violate these expect to get `payload_too_large` or `malformed_request` responses.

## Per-test isolation

Each integration test should:
1. Spawn its own harness process with a unique socket path (e.g. `/tmp/feat012-<test-name>-<pid>.sock`)
2. Bind a fresh fixture
3. Tear down the process at the end of the test

The Dart helper at `../../test/helpers/mock_daemon_client.dart` automates this — see its `setUp` / `tearDown` patterns.
