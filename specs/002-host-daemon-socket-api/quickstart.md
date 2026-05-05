# Quickstart: Host Daemon Lifecycle and Unix Socket API (FEAT-002)

**Branch**: `002-host-daemon-socket-api` | **Date**: 2026-05-05

This quickstart walks through every CLI behavior FEAT-002 ships, in the
order an end user (or test harness) would exercise them. It assumes
FEAT-001 has been installed on the same Python environment.

---

## 0. Prerequisites

```bash
# FEAT-001 must already be initialized.
agenttower config init

# Sanity-check the path contract; the SOCKET path is what FEAT-002 binds.
agenttower config paths
# Expected (paths vary by host):
#   CONFIG_FILE=/home/user/.config/opensoft/agenttower/config.toml
#   STATE_DB=/home/user/.local/state/opensoft/agenttower/agenttower.sqlite3
#   EVENTS_FILE=/home/user/.local/state/opensoft/agenttower/events.jsonl
#   LOGS_DIR=/home/user/.local/state/opensoft/agenttower/logs
#   SOCKET=/home/user/.local/state/opensoft/agenttower/agenttowerd.sock
#   CACHE_DIR=/home/user/.cache/opensoft/agenttower
```

If `STATE_DB` or any FEAT-001 artifact is missing, every FEAT-002
command exits non-zero with an actionable error and does **not** start
the daemon (FR-003).

---

## 1. Start the daemon (US1)

```bash
agenttower ensure-daemon
# Expected stdout (one line):
#   agenttowerd ready: pid=12345 socket=/home/user/.local/state/opensoft/agenttower/agenttowerd.sock state=/home/user/.local/state/opensoft/agenttower/
echo $?  # 0
```

The command:

- Verifies FEAT-001 initialization.
- Spawns `agenttowerd run` as a detached subprocess
  (`start_new_session=True`, stdout/stderr → `<LOGS_DIR>/agenttowerd.log`).
- Polls the socket until a `ping` succeeds (≤ 2 s, SC-001).

```bash
# JSON form:
agenttower ensure-daemon --json
# {"ok":true,"started":false,"pid":12345,"socket_path":"...","state_path":"..."}
# `started` is true on first run, false on subsequent runs.
```

### Idempotence (US1 acceptance #2)

```bash
for i in $(seq 1 20); do agenttower ensure-daemon >/dev/null; done
pgrep -af agenttowerd
# Exactly one matching process (SC-002).
```

### Concurrent ensure-daemon (SC-009)

```bash
for i in 1 2 3 4 5; do agenttower ensure-daemon & done
wait
pgrep -af agenttowerd
# Exactly one live daemon, all five invocations exited 0.
```

---

## 2. Query daemon status (US2)

```bash
agenttower status
# alive=true
# pid=12345
# start_time=2026-05-05T12:34:56.789012+00:00
# uptime_seconds=42
# socket_path=/home/user/.local/state/opensoft/agenttower/agenttowerd.sock
# state_path=/home/user/.local/state/opensoft/agenttower/
echo $?  # 0
```

```bash
agenttower status --json
# {"ok":true,"result":{"alive":true,"pid":12345,"start_time_utc":"...","uptime_seconds":42,"socket_path":"...","state_path":"...","schema_version":1,"daemon_version":"0.2.0"}}
```

### Status when no daemon is running (US2 acceptance #2)

```bash
agenttower stop-daemon >/dev/null
agenttower status
# stderr: error: daemon is not running or socket is unreachable: try `agenttower ensure-daemon`
echo $?  # 2
```

### Raw `ping` over the socket

The CLI does not expose a `ping` subcommand in FEAT-002, but the
protocol is reachable directly:

```bash
SOCKET=$(agenttower config paths | awk -F= '/^SOCKET=/{print $2}')
printf '{"method":"ping"}\n' | nc -U "$SOCKET"
# {"ok":true,"result":{}}
```

`ping` mutates no durable state (FR-015) and emits no lifecycle log
event.

---

## 3. Recover from stale state (US3)

```bash
# Make sure the daemon is running, then kill it abruptly.
agenttower ensure-daemon >/dev/null
PID=$(agenttower status --json | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["result"]["pid"])')
kill -9 "$PID"

# Stale pid + lock + socket left behind. Recovery is automatic.
agenttower ensure-daemon
# agenttowerd ready: pid=<new pid> socket=... state=...
echo $?  # 0
```

The recovery path:

- `flock(LOCK_EX | LOCK_NB)` succeeds (kernel released the dead
  daemon's lock).
- The pre-existing socket inode is classified as stale and unlinked
  (R-004).
- The new daemon binds, writes its pid file, and emits
  `daemon_recovering` and `daemon_ready` to `<LOGS_DIR>/agenttowerd.log`.
- The whole sequence completes within 3 s (SC-004).

### Refusal: socket path is a non-socket file

```bash
SOCKET=$(agenttower config paths | awk -F= '/^SOCKET=/{print $2}')
rm -f "$SOCKET"
echo "junk" > "$SOCKET"
agenttower ensure-daemon
# error: socket path is not a unix socket: /home/.../agenttowerd.sock: refusing to remove
echo $?  # 1
```

The daemon refuses rather than removing a path it cannot prove it owns
(FR-009).

---

## 4. Shut the daemon down (US4)

```bash
agenttower ensure-daemon >/dev/null
agenttower stop-daemon
# agenttowerd stopped: socket=... state=...
echo $?  # 0
```

```bash
agenttower stop-daemon --json
# {"ok":true,"stopped":true,"socket_path":"...","state_path":"..."}
```

### Stopping when nothing is running (US4 acceptance #3)

```bash
agenttower stop-daemon
# stderr: error: no reachable daemon to stop
echo $?  # 2
```

### SIGTERM / Ctrl-C cleanup

```bash
agenttower ensure-daemon >/dev/null
PID=$(agenttower status --json | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["result"]["pid"])')
kill -TERM "$PID"
# Daemon performs the same shutdown sequence as the API method (R-007):
# - stop accepting new connections,
# - join in-flight handlers,
# - unlink socket / pid / lock content,
# - exit 0.

agenttower ensure-daemon
# Starts a fresh daemon without manual cleanup (FR-022, SC-006).
```

---

## 5. Inspect the lifecycle log

```bash
LOGS_DIR=$(agenttower config paths | awk -F= '/^LOGS_DIR=/{print $2}')
tail -f "$LOGS_DIR/agenttowerd.log"
```

Sample lines:

```text
2026-05-05T12:34:56.789012+00:00	level=info	event=daemon_starting	pid=12345	state_dir=/home/user/.local/state/opensoft/agenttower
2026-05-05T12:34:56.812445+00:00	level=info	event=daemon_recovering	unlinked=.../agenttowerd.sock	reason=stale_socket
2026-05-05T12:34:56.834102+00:00	level=info	event=daemon_ready	socket=.../agenttowerd.sock	pid=12345
2026-05-05T12:35:42.501007+00:00	level=info	event=daemon_shutdown	trigger=api
2026-05-05T12:35:42.612331+00:00	level=info	event=daemon_exited	exit_code=0
```

Only the six lifecycle tokens listed in `data-model.md` §1.4 appear in
this file in FEAT-002 (FR-027). Per-request, per-agent, per-pane, and
event-classification entries are owned by FEAT-005, FEAT-007, and
FEAT-008.

---

## 6. Pre-flight failure modes

| Scenario                                              | Command            | Exit | Stderr substring                              |
| ----------------------------------------------------- | ------------------ | ---- | --------------------------------------------- |
| FEAT-001 not initialized                              | `ensure-daemon`    | `1`  | `agenttower is not initialized`               |
| `STATE_DIR` mode is `0755` (wider than `0700`)        | `ensure-daemon`    | `1`  | `unsafe permissions on /...`                  |
| Socket path is a regular file                         | `ensure-daemon`    | `1`  | `socket path is not a unix socket`            |
| Daemon already running for this state directory       | `ensure-daemon`    | `0`  | (no error; FR-007 path)                       |
| Daemon not running                                    | `status`           | `2`  | `daemon is not running or socket is unreachable` |
| Daemon not running                                    | `stop-daemon`      | `2`  | `no reachable daemon to stop`                 |
| Daemon answered but returned a structured error       | `status`           | `3`  | the daemon's `error.message`                  |
| Daemon spawned but did not become ready in 2 s        | `ensure-daemon`    | `2`  | `daemon failed to become ready within ...`    |

---

## 7. Cleanup for tests / dev iteration

```bash
agenttower stop-daemon || true
rm -f "$(agenttower config paths | awk -F= '/^LOGS_DIR=/{print $2}')/agenttowerd.log"
```

A clean shutdown leaves only the lifecycle log behind (and even that is
operator-managed, R-012). The next `ensure-daemon` starts from scratch.
