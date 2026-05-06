# Quickstart: Container-Local Thin Client Connectivity

**Branch**: `005-container-thin-client` | **Date**: 2026-05-06
**T057 walk**: 2026-05-06 — outputs in this document have been
verified against the live build; commands reproduce the documented
output and exit codes.

This walks through every FEAT-005 user-facing surface end-to-end
against a healthy host daemon and a simulated bench container. Each
step shows the exact command, the expected output, and the FR or
SC it exercises.

Pre-requisites:

- FEAT-001 / FEAT-002 / FEAT-003 / FEAT-004 already shipped.
- The host daemon is running (`agenttower ensure-daemon`).
- One bench container has been registered (`agenttower scan --containers`).
- One pane has been registered (`agenttower scan --panes`).

The illustrative outputs in §3, §4, §6, §9, and §10 use the
fake-adapter test seams (`AGENTTOWER_TEST_PROC_ROOT`,
`AGENTTOWER_TEST_DOCKER_FAKE`, `AGENTTOWER_TEST_TMUX_FAKE`) to
produce stable, reproducible output. Real-host invocations vary
slightly (e.g., `container_identity` resolves to `no_match` rather
than `host_context` when the host's `/etc/hostname` is non-empty).

---

## 1. Verify host-side behavior is unchanged (SC-006, SC-007, FR-005)

From a host shell, default text mode prints `KEY=value` lines:

```bash
$ agenttower status
alive=true
pid=12345
start_time=2026-05-06T10:30:00.123456+00:00
uptime_seconds=137
socket_path=/home/brett/.local/state/opensoft/agenttower/agenttowerd.sock
state_path=/home/brett/.local/state/opensoft/agenttower
```

JSON mode adds `schema_version` and `daemon_version` (and renames
`start_time` → `start_time_utc` per the FEAT-002 contract):

```bash
$ agenttower status --json
{"ok": true, "result": {"alive": true, "pid": 12345, "start_time_utc": "2026-05-06T10:30:00.123456+00:00", "uptime_seconds": 137, "socket_path": "/home/brett/.local/state/opensoft/agenttower/agenttowerd.sock", "state_path": "/home/brett/.local/state/opensoft/agenttower", "schema_version": 3, "daemon_version": "0.5.0"}}
```

Both forms are byte-identical to the FEAT-004 build. The new
`config doctor` subcommand and the new `SOCKET_SOURCE=` line on
`config paths` are the *only* additive surfaces; nothing else
changes.

---

## 2. Inspect resolved socket source on the host (FR-019, C-CLI-502)

```bash
$ agenttower config paths
CONFIG_FILE=/home/brett/.config/opensoft/agenttower/config.toml
STATE_DB=/home/brett/.local/state/opensoft/agenttower/agenttower.sqlite3
EVENTS_FILE=/home/brett/.local/state/opensoft/agenttower/events.jsonl
LOGS_DIR=/home/brett/.local/state/opensoft/agenttower/logs
SOCKET=/home/brett/.local/state/opensoft/agenttower/agenttowerd.sock
CACHE_DIR=/home/brett/.cache/opensoft/agenttower
SOCKET_SOURCE=host_default
```

The first six lines are byte-identical to the FEAT-001 build (in
declared `Paths` field order: `CONFIG_FILE`, `STATE_DB`,
`EVENTS_FILE`, `LOGS_DIR`, `SOCKET`, `CACHE_DIR`).
`SOCKET_SOURCE=` is the only added line and is always last.

---

## 3. Run the doctor on the host (US2 AS3, US3 AS4)

With the test seams pinning host context (no detection signals fire,
no $TMUX), the doctor produces the cleanest host output:

```bash
$ agenttower config doctor
socket_resolved	pass	/home/brett/.local/state/opensoft/agenttower/agenttowerd.sock (host_default)
socket_reachable	pass	daemon_version=0.5.0 schema_version=3
daemon_status	pass	schema_version=3 (cli supports 3); daemon_version=0.5.0
container_identity	info	host_context
tmux_present	info	not_in_tmux
tmux_pane_match	info	not_in_tmux
summary	0	3/6 checks passed
$ echo $?
0
```

Tokens are TAB-separated per FR-013. Exit `0` because every required
check (`socket_resolved`, `socket_reachable`, `daemon_status`) is
`pass` and the non-required `info` rows do not push the exit code
up.

On a typical real host (where `/etc/hostname` or `$HOSTNAME` is
non-empty), `container_identity` resolves to `fail` /
`no_match` rather than `info` / `host_context` because the
hostname signal produces a candidate that no FEAT-003 row matches;
the exit code is then `5` (degraded). `host_context` requires *every*
detection signal to return empty AND `AGENTTOWER_CONTAINER_ID` to be
unset (data-model §3.3).

---

## 4. Run the doctor in JSON mode (FR-014, SC-005, US2 AS5)

```bash
$ agenttower config doctor --json
{"summary": {"exit_code": 0, "total": 6, "passed": 3, "warned": 0, "failed": 0, "info": 3}, "checks": {"socket_resolved": {"status": "pass", "details": "/home/brett/.local/state/opensoft/agenttower/agenttowerd.sock (host_default)", "source": "host_default"}, "socket_reachable": {"status": "pass", "details": "daemon_version=0.5.0 schema_version=3", "source": "round_trip"}, "daemon_status": {"status": "pass", "details": "schema_version=3 (cli supports 3); daemon_version=0.5.0", "source": "schema_check"}, "container_identity": {"status": "info", "details": "host_context", "sub_code": "host_context"}, "tmux_present": {"status": "info", "details": "not_in_tmux", "sub_code": "not_in_tmux"}, "tmux_pane_match": {"status": "info", "details": "not_in_tmux", "sub_code": "not_in_tmux"}}}
```

One canonical JSON object on a single line per invocation
(`json.dumps` default — no pretty-print). Pipe through `jq` or
`python -m json.tool` for a multi-line view:

```bash
$ agenttower config doctor --json | python -m json.tool
{
    "summary": {
        "exit_code": 0,
        ...
    },
    ...
}
```

No incidental stderr lines. `summary.exit_code` matches the CLI
exit code. The keys are emitted in the per-row dict order produced
by the renderer (`status`, `details`, optional `source`, optional
`sub_code`, optional `actionable_message`).

---

## 5. Simulate an in-container shell (FR-025, SC-001)

This step is normally done by the test harness via
`AGENTTOWER_TEST_PROC_ROOT`, but the same effect can be reproduced
manually for a smoke test:

```bash
$ docker run --rm -it \
    -v "$HOME/.local/state/opensoft/agenttower/agenttowerd.sock:/run/agenttower/agenttowerd.sock" \
    -u "$(id -u)" \
    py-bench \
    agenttower status
alive=true
pid=12345
start_time=2026-05-06T10:30:00.123456+00:00
uptime_seconds=312
socket_path=/run/agenttower/agenttowerd.sock
state_path=/home/brett/.local/state/opensoft/agenttower
```

The six TSV keys match the host invocation byte-for-byte except for
`socket_path`, which now reflects the in-container mounted-default
path (`mounted_default` source). `--json` adds `schema_version` and
`daemon_version` as before.

---

## 6. Run the doctor inside the container (US2 AS1, US3 AS1)

```bash
$ agenttower config doctor
socket_resolved	pass	/run/agenttower/agenttowerd.sock (mounted_default)
socket_reachable	pass	daemon_version=0.5.0 schema_version=3
daemon_status	pass	schema_version=3 (cli supports 3); daemon_version=0.5.0
container_identity	pass	unique_match: 1234abcd5678... (py-bench)
tmux_present	pass	socket=/tmp/tmux-1000/default session=0 pane=%0
tmux_pane_match	pass	pane_match: %0 in py-bench:default:main:0.0
summary	0	6/6 checks passed
```

All six checks pass; the cgroup signal produced the candidate id
(`source=cgroup`); the daemon's `list_containers` matched it
uniquely; the daemon's `list_panes` matched the
`(tmux_socket_path, tmux_pane_id)` pair uniquely. The `tmux_present`
detail uses the `socket=... session=... pane=...` decomposed format
rather than the raw `$TMUX=...,...,$0` echo.

---

## 7. Override the socket via `AGENTTOWER_SOCKET` (US1 AS2)

```bash
$ AGENTTOWER_SOCKET=/tmp/custom-tower.sock agenttower config paths | tail -1
error: AGENTTOWER_SOCKET must be an absolute path to a Unix socket: value does not exist
$ echo $?
1
```

When the override points at a non-existent socket, the FR-002
pre-flight `S_ISSOCK` gate catches it BEFORE any connect attempt
and exits `1` with the literal `<reason>` token `value does not
exist`. The exit code is `1` (FR-002 pre-flight), NOT `2`
(FEAT-002 daemon-unavailable), because validation runs first.

When the override DOES point at a reachable socket, `env_override`
wins over both defaults:

```bash
$ ln -s "$HOME/.local/state/opensoft/agenttower/agenttowerd.sock" /tmp/custom-tower.sock
$ AGENTTOWER_SOCKET=/tmp/custom-tower.sock agenttower config paths | tail -1
SOCKET_SOURCE=env_override
```

---

## 8. Reject a malformed `AGENTTOWER_SOCKET` (FR-002, SC-002)

```bash
$ AGENTTOWER_SOCKET=relative/path agenttower status
error: AGENTTOWER_SOCKET must be an absolute path to a Unix socket: value is not absolute
$ echo $?
1

$ AGENTTOWER_SOCKET= agenttower status
error: AGENTTOWER_SOCKET must be an absolute path to a Unix socket: value is empty
$ echo $?
1

$ AGENTTOWER_SOCKET=$(printf '/run/with\x00nul') agenttower status
error: AGENTTOWER_SOCKET must be an absolute path to a Unix socket: value contains NUL byte
$ echo $?
1
```

Pre-flight rejection happens within 50 ms (SC-002); no daemon-side
state changes; no fall-back to the default. The closed-set
`<reason>` tokens (`value is empty`, `value is not absolute`,
`value contains NUL byte`, `value does not exist`,
`value is not a Unix socket`) are pinned by FR-002 + contracts/cli.md.

---

## 9. Daemon-down doctor (US1 AS4, US2 AS2, SC-004)

Stop the daemon (`agenttower stop-daemon` from the host) then:

```bash
$ agenttower config doctor
socket_resolved	pass	/run/agenttower/agenttowerd.sock (mounted_default)
socket_reachable	fail	socket_missing: /run/agenttower/agenttowerd.sock
    socket file does not exist at /run/agenttower/agenttowerd.sock; try `agenttower ensure-daemon` from the host
daemon_status	info	daemon_unavailable
    skipped because socket_reachable is fail
container_identity	info	daemon_unavailable
    skipped because socket_reachable is fail; run `agenttower scan --containers` from the host
tmux_present	pass	socket=/tmp/tmux-1000/default session=0 pane=%0
tmux_pane_match	info	daemon_unavailable
    skipped because socket_reachable is fail
summary	2	2/6 checks passed
$ echo $?
2
```

Exit `2` because `socket_reachable` is `fail` with sub-code
`socket_missing`. Every check still ran (FR-027); dependent checks
emit `info` / `daemon_unavailable` rather than being silently
omitted. No raw errno text leaks (FR-024) — only the closed-set
sub-code and the bounded actionable message.

---

## 10. Doctor under a `--network host` ambiguity (edge case 4)

When the container is run with `--network host` and `--hostname` is
unset, `/etc/hostname` is the host hostname, so the cgroup signal
fails (no Docker cgroup) and the hostname signal produces a
candidate that no FEAT-003 row matches:

```bash
$ agenttower config doctor
socket_resolved	pass	/run/agenttower/agenttowerd.sock (mounted_default)
socket_reachable	pass	daemon_version=0.5.0 schema_version=3
daemon_status	pass	schema_version=3 (cli supports 3); daemon_version=0.5.0
container_identity	fail	no_match: brett-laptop (hostname)
    run `agenttower scan --containers` from the host
tmux_present	pass	socket=/tmp/tmux-1000/default session=0 pane=%0
tmux_pane_match	fail	pane_unknown_to_daemon: /tmp/tmux-1000/default:%0
    no pane row matches; run `agenttower scan --panes` from the host
summary	5	4/6 checks passed
$ echo $?
5
```

Exit `5` (degraded) because the daemon round-trip succeeded but two
non-required checks (`container_identity`, `tmux_pane_match`)
failed. Every required check still passed.

---

## What FEAT-005 does NOT do

- Does not register agents, attach logs, or deliver input
  (FR-022).
- Does not call `scan_containers` or `scan_panes` from inside the
  container (FR-008, FR-022).
- Does not introduce a network listener, an in-container daemon,
  or an in-container relay (FR-022; constitution principle I).
- Does not modify any FEAT-001 / FEAT-002 / FEAT-003 / FEAT-004
  CLI surface beyond the two additive points above (FR-005,
  FR-026, SC-006, SC-007).
- Does not write anything to disk during `config doctor` (FR-029).

---

## T057 walk findings (drift captured into spec, not code)

The 2026-05-06 walk surfaced these discrepancies between the
pre-walk quickstart text and live-build behavior. All are
captured here (and into `spec.md` edge case 7 where a semantic
amendment was needed):

1. **§1**: default TSV is `KEY=value`, not whitespace-aligned, and
   contains 6 keys; the 8-key enumeration in spec US1 AS1 appears in
   `--json` only (and uses `start_time_utc` instead of `start_time`).
   Quickstart now shows both forms.
2. **§2**: `agenttower config paths` emits 6 `KEY=value` lines (in
   `Paths` field order: `CONFIG_FILE`, `STATE_DB`, `EVENTS_FILE`,
   `LOGS_DIR`, `SOCKET`, `CACHE_DIR`) plus the trailing
   `SOCKET_SOURCE=` line — not the 9 lines previously shown.
3. **§3 / §4**: `tmux_present` detail uses the decomposed
   `socket=... session=... pane=...` format; `daemon_status` detail
   appends `; daemon_version=...`. The `host_context` outcome on
   `container_identity` requires *every* detection signal empty,
   which is rare on real hosts.
4. **§4 (JSON)**: T057 walk noted `socket_reachable` was emitting
   `source: host_default` (mirroring the resolver source) rather than
   the `round_trip` value documented in R-007's worked example +
   data-model §3.5. Resolved by the O1 code fix in the same session
   — `socket_reachable.source` now emits `round_trip` per the
   documented contract.
5. **§7**: when `AGENTTOWER_SOCKET` points at a non-existent socket,
   the FR-002 pre-flight `S_ISSOCK` gate exits `1` with `value does
   not exist` BEFORE any connect attempt. The previous text claiming
   exit `2` (FEAT-002 daemon-unavailable) was incorrect — FR-002
   wins. Quickstart now reflects exit `1`.
6. **§10**: previously-shown `tmux_pane_match` `info` was wrong on
   a host shell; the implementation maps `pane_unknown_to_daemon` →
   `fail` regardless of context (closed-set sub-code per
   `contracts/cli.md` `tmux_pane_match` table). Spec edge case 7 was
   amended to align with this implementation choice — see
   `spec.md` Edge Cases.
