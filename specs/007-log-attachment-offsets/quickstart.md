# Quickstart: Pane Log Attachment and Offset Tracking

**Branch**: `007-log-attachment-offsets` | **Date**: 2026-05-08

End-to-end CLI walkthrough that exercises every FEAT-007 surface
against a running host daemon and a registered FEAT-006 agent
inside a bench container.

---

## Prerequisites

- AgentTower daemon (`agenttowerd`) running on the host (via
  `agenttower ensure-daemon`).
- One bench container running with the canonical bind mount:
  ```
  -v ~/.local/state/opensoft/agenttower/logs:~/.local/state/opensoft/agenttower/logs
  ```
- The daemon force-pins `LANG=C.UTF-8` on every `docker exec` it
  issues (FEAT-004 pane discovery, FEAT-007 pipe-pane), so a bench
  container booted in the default Debian/Ubuntu POSIX/C locale is
  fine. (Bench-side interactive shells still use whatever locale you
  set — the pin only scopes the daemon's structured calls.)
- `tmux` available inside the bench (the daemon's pipe-pane attach
  requires it). tmux ≥ 3.5 is recommended for full FR-043 orphan
  recovery — older versions don't expose `pane_pipe_command`, which
  the daemon uses to extract the bound `agent_id` from a stray pipe.
  Attach / detach / supersede happy paths work on tmux 3.4 too.
- One tmux pane inside the container.
- One FEAT-006 agent registered to that pane:
  ```bash
  agenttower register-self --role slave --capability codex --label codex-01
  # → agent_id=agt_abc123def456
  ```

---

## 1. Attach a log (canonical path)

From inside the bench container, in the registered pane:

```bash
agenttower attach-log --target agt_abc123def456
```

Expected (one `key=value` per line; values shown are illustrative — agent
ids, attachment ids, container ids, and operator user names will differ in
your environment):
```text
attached agent_id=agt_abc123def456
attachment_id=lat_a1b2c3d4e5f6
path=/home/user/.local/state/opensoft/agenttower/logs/<container_id>/agt_abc123def456.log
source=explicit
status=active
```

What happened:
- Daemon proved host-visibility against the bind mount.
- Daemon ensured `~/.local/state/opensoft/agenttower/logs/<container_id>/`
  exists with mode `0700` and the file with mode `0600` (FR-008).
- Daemon issued `tmux pipe-pane -o -t <pane> 'cat >> <log>'`
  via `docker exec` (FR-010).
- Two SQLite rows committed atomically (FR-016): one in
  `log_attachments` (status=active), one in `log_offsets` at
  `(0, 0)`.
- One JSONL audit row appended:
  `{"type":"log_attachment_change","payload":{...prior_status:null,
  new_status:"active"...}}`.

Verify:
```bash
agenttower attach-log --target agt_abc123def456 --status
# → status=active byte_offset=0 line_offset=0 ...

ls -la ~/.local/state/opensoft/agenttower/logs/<container_id>/
# → drwx------  ...
# → -rw-------  ... agt_abc123def456.log
```

---

## 2. Generate some pane output and preview it (with redaction)

In the pane, paste a fixture that includes a fake secret:

```bash
echo "build started"
echo "auth=sk-AAAAAAAAAAAAAAAAAAAA continuing"
echo "build complete in 4.2s"
```

Inspect via preview:

```bash
agenttower attach-log --target agt_abc123def456 --preview 5
```

Expected (note redaction). On a real interactive bash + tmux pane, the
captured stream interleaves the typed commands, the prompt's ANSI
escape sequences, and the resulting output bytes. The redaction
transform applies to every line, so the secret is masked wherever it
appears (typed command echo and program output alike):
```text
build started
auth=<redacted:openai-key> continuing
build complete in 4.2s
```

In a real shell session you will additionally see the surrounding
prompt + bracketed-paste sequences (`[?2004h`, `[?2004l`, `[01;32m…[00m`)
inline. That is correct behavior — `pipe-pane` captures the raw byte
stream verbatim and FEAT-007's preview render performs redaction
without stripping ANSI. Future cleanup of escape codes would land in a
separate render layer; the current preview is faithful to the bytes
on disk.

The host log file itself is NOT redacted — redaction is render-time
only (FR-030, Assumptions §"Redaction is content-only"). To
confirm:

```bash
cat ~/.local/state/opensoft/agenttower/logs/<container_id>/agt_abc123def456.log
# → original bytes including the raw sk- token
```

---

## 3. Idempotent re-attach

Re-running `attach-log` against the same agent and same path is a
no-op success (FR-018):

```bash
agenttower attach-log --target agt_abc123def456
# → exit 0; first line reads
#   `already-attached agent_id=agt_abc123def456`
#   (the `already-attached` keyword instead of `attached` makes the
#   no-op semantics explicit; everything else matches the §1 form).
```

Verify exactly one row in each table:

```bash
sqlite3 ~/.local/state/opensoft/agenttower/agenttower.sqlite3 \
  "SELECT count(*) FROM log_attachments WHERE agent_id='agt_abc123def456';"
# → 1
```

Verify no new audit row appended:

```bash
grep '"type":"log_attachment_change"' ~/.local/state/opensoft/agenttower/events.jsonl | wc -l
# → 1 (only the original attach)
```

---

## 4. Detach explicitly

```bash
agenttower detach-log --target agt_abc123def456
```

Expected (one `key=value` per line; values shown are illustrative):
```text
detached agent_id=agt_abc123def456
attachment_id=lat_a1b2c3d4e5f6
path=...
status=detached
```

What happened:
- Daemon issued `tmux pipe-pane -t <pane>` (no command) to stop
  the pipe.
- `log_attachments.status` transitioned `active → detached`.
- `log_offsets` row UNCHANGED (offsets retained — FR-021c,
  Clarifications Q1).
- One audit row appended with `prior_status=active,
  new_status=detached`.

Verify offsets retained:

```bash
agenttower attach-log --target agt_abc123def456 --status
# → status=detached byte_offset=N line_offset=M ... (the values from before detach)
```

---

## 5. Re-attach after detach (offsets retained)

```bash
agenttower attach-log --target agt_abc123def456
```

Expected:
- Same `attachment_id` reused (FR-021d).
- `status` transitions `detached → active`.
- `byte_offset` and `line_offset` UNCHANGED from before detach.
- One audit row appended with `prior_status=detached,
  new_status=active`.

---

## 6. Path change supersedes the prior row

```bash
agenttower attach-log --target agt_abc123def456 --log /custom/path/X.log
```

Expected:
- Prior row → `status=superseded` (with `superseded_at` and
  `superseded_by=<new lat_id>`); FR-019, Clarifications Q2.
- New row created at `/custom/path/X.log` with `status=active`,
  fresh attachment_id, fresh offsets at `(0, 0)`.
- One audit row carrying `prior_path=...prior log path...,
  new_path=/custom/path/X.log, prior_status=active OR stale OR
  detached, new_status=active`.

Note: `--log` requires the supplied path to be host-visible per
FR-007. If `/custom/path/X.log` is not under any bind mount, the
call fails with `log_path_not_host_visible` and zero rows are
written (SC-005).

---

## 7. Atomic register-self with --attach-log

For a brand-new pane (no existing agent), one CLI call atomically
creates both rows:

```bash
agenttower register-self --role slave --capability codex \
                          --label codex-02 --attach-log
```

Expected text-mode output (in this order):
```text
registered agent_id=agt_xyz789abc012 ...
attached agent_id=agt_xyz789abc012 attachment_id=lat_b2c3d4e5f6a7 ...
```

Both audit rows appended in order: `agent_role_change` FIRST,
`log_attachment_change` SECOND (FR-035). On any FEAT-007 failure,
zero rows in any table and zero JSONL audit rows (FR-034 fail-the-
call).

---

## 8. Stale recovery from pane drift

Simulate pane drift: kill the tmux server *and* start a fresh session
so FEAT-004 sees the original pane composite key has disappeared and
reconciles it inactive. (Killing the server alone leaves the daemon in
the FR-010 `tmux_unavailable` state, which preserves prior pane rows
on the assumption that the server gap is transient — no stale flip.)

```bash
# inside the container:
tmux kill-server
tmux new-session -d -s scratch         # fresh server, fresh pane keys
```

Within one FEAT-004 reconcile cycle (≤ 5 seconds), the original pane
flips `active → inactive` and the bound attachment flips
`active → stale` in the same SQLite transaction (FR-042, SC-009):

```bash
agenttower attach-log --target agt_abc123def456 --status
# → status=stale ...
```

Offsets are UNCHANGED.

Recovery semantics differ from a soft restart: the new tmux session's
panes have new pane composite keys, so the original FEAT-006 agent
stays inactive (`agent_inactive` on attempted `attach-log`). Recover
by registering a fresh agent in the new pane:

```bash
# inside the new pane:
agenttower register-self --role slave --capability codex \
                          --label codex-recovered --attach-log
```

The new agent gets a new `agent_id` and a new `lat_<id>` attachment.
The previously-stale row remains in the registry with offsets retained
for forensic continuity; FEAT-008 readers ignore stale rows. (The
"file at the prior `log_path` is intact, retain offsets byte-for-byte"
recovery path applies on a `set-role`-style reactivation of the same
agent; that flow is documented in FEAT-006 and is exercised when the
pane restarts in-place rather than as a fresh server.)

---

## 9. Stale recovery from file deletion

Simulate file deletion:

```bash
rm ~/.local/state/opensoft/agenttower/logs/<container_id>/agt_abc123def456.log
```

The next FEAT-008 reader cycle (or next manually triggered
reader for tests) emits one `log_file_missing` lifecycle event
and flips the row to `status=stale` (FR-026). If the file later
reappears (recreated externally, mount remounted), one
`log_file_returned` lifecycle event is emitted and the row
remains `stale` (Clarifications Q4 — no auto-recovery).

Operator recovery:

```bash
agenttower attach-log --target agt_abc123def456
```

Because `file_inode` no longer matches the stored value (the
file is brand-new), the FR-021 file-consistency check resets
offsets to `(0, 0)` and emits one `log_rotation_detected`
lifecycle event in addition to the `log_attachment_change`
audit row.

---

## 10. Read-only inspection across all states

All `--target` arguments below must satisfy the closed-set
`agt_<12-hex-lowercase>` validator (FEAT-006); illustrative aliases
like `agt_no_log_yet` or `agt_only_superseded` would surface
`value_out_of_set` before reaching the daemon. Substitute valid-shape
ids from your environment.

```bash
# Always succeeds for a known agent, even with no attachment:
agenttower attach-log --target agt_abc123def456 --status

# Returns null fields when the agent has no attachment row at all:
agenttower attach-log --target agt_000000000000 --status
# → agent_id=agt_000000000000 attachment=null offset=null
# (NOTE: this is the "known agent, no attachment" case; an UNKNOWN
#  agent — one that has never been registered — surfaces
#  `agent_not_found, exit 3` instead. `--status` is read-only but
#  cannot synthesize state for agents the daemon has never seen.)

# Preview works on active/stale/detached:
agenttower attach-log --target agt_abc123def456 --preview 10

# Preview refuses on superseded or no-row with attachment_not_found:
agenttower attach-log --target agt_aaaaaaaaaaaa --preview 10
# → exit 3; error: attachment_not_found

# Preview refuses with log_file_missing if host file absent:
rm /host/path/X.log
agenttower attach-log --target agt_abc123def456 --preview 10
# → exit 3; error: log_file_missing
```

---

## 11. JSON output

Every CLI surface supports `--json`:

```bash
agenttower attach-log --target agt_abc123def456 --status --json
# → {"ok":true,"result":{"agent_id":"agt_abc123def456","attachment":{...},"offset":{...}}}

agenttower attach-log --target agt_abc123def456 --preview 3 --json
# → {"ok":true,"result":{"agent_id":"...","attachment_id":"lat_...","log_path":"...","lines":["..."]}}

agenttower detach-log --target agt_abc123def456 --json
# → {"ok":true,"result":{"agent_id":"...","attachment_id":"lat_...","log_path":"...","status":"detached",...}}
```

`--json` mode is byte-pure on stdout (one envelope object,
trailing newline); stderr empty (FEAT-006 `--json` purity contract).

---

## 12. Error envelope examples

The `--target` validator runs before the daemon round-trip, so an
ill-shaped id (e.g. `agt_unknown` or `agt_unknown123def456`) is
rejected as `value_out_of_set` rather than as `agent_not_found`. Use
a valid-shape (12-hex-lowercase) id when you want to exercise the
"agent doesn't exist" branch.

```bash
# Valid shape, but no such agent:
agenttower attach-log --target agt_111111111111
# stderr: error: agent 'agt_111111111111' not found
#         code: agent_not_found
# exit 3

# Valid agent, log path not under any bind mount → host-visibility refusal.
# The detail string lists the observed mount destinations so the
# operator can compare their bench template to the path the daemon
# expected:
agenttower attach-log --target agt_abc123def456 --log /not/host/visible/file.log
# stderr: error: no bind/volume mount covers container path
#         '/not/host/visible/file.log'; observed mount destinations
#         in this container: ...
#         code: log_path_not_host_visible
# exit 3

# Out-of-range preview line count:
agenttower attach-log --target agt_abc123def456 --preview 250
# stderr: error: --preview N must be between 1 and 200; got 250
#         code: value_out_of_set
# exit 3
```

`--json` mode for the same errors emits one byte-pure JSON envelope
per call (no `code:` line — the code lives in the envelope's
`error.code` field):

```json
{"ok":false,"error":{"code":"agent_not_found","message":"agent 'agt_111111111111' not found"}}
```

---

## 13. Verifying durability across daemon restart

```bash
# advance offset via test seam (or FEAT-008 reader)
# kill daemon hard:
pkill -9 -f agenttowerd
# restart:
agenttower ensure-daemon
# verify offset preserved byte-for-byte (SC-003):
agenttower attach-log --target agt_abc123def456 --status --json | jq .result.offset.byte_offset
# → same value as before kill
```
