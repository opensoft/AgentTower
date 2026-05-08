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

Expected:
```text
attached agent_id=agt_abc123def456 attachment_id=lat_a1b2c3d4e5f6
path=/home/user/.local/state/opensoft/agenttower/logs/<container_id>/agt_abc123def456.log
source=explicit status=active
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

Expected (note redaction):
```text
build started
auth=<redacted:openai-key> continuing
build complete in 4.2s
```

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
# → exit 0; attached agent_id=... status=active (existing row)
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

Expected:
```text
detached agent_id=agt_abc123def456 attachment_id=lat_a1b2c3d4e5f6
path=... status=detached
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

Simulate pane drift: kill tmux inside the container so FEAT-004
reconciliation marks the pane inactive.

```bash
# inside the container:
tmux kill-server
```

Within one FEAT-004 reconcile cycle (≤ 5 seconds):

```bash
agenttower attach-log --target agt_abc123def456 --status
# → status=stale ...
```

The `log_attachments` row was flipped `active → stale` in the
same SQLite transaction as the FEAT-004 reconcile that marked
the pane inactive (FR-042, SC-009). Offsets are UNCHANGED.

Recover by restarting tmux and re-running `attach-log`:

```bash
# inside the container:
tmux new-session -d -s main
# from any shell:
agenttower attach-log --target agt_abc123def456
```

Because the file at the prior `log_path` is intact, FR-021's
file-consistency check retains offsets byte-for-byte
(Clarifications Q4 specifies the file-missing case resets;
this is the file-intact case).

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

```bash
# Always succeeds, even with no attachment:
agenttower attach-log --target agt_abc123def456 --status

# Returns null fields when no attachment exists:
agenttower attach-log --target agt_no_log_yet --status
# → agent_id=agt_no_log_yet attachment=null offset=null

# Preview works on active/stale/detached:
agenttower attach-log --target agt_abc123def456 --preview 10

# Preview refuses on superseded or no-row with attachment_not_found:
agenttower attach-log --target agt_only_superseded --preview 10
# → exit 3; error: attachment_not_found

# Preview refuses with log_file_missing if host file absent:
rm /host/path/X.log
agenttower attach-log --target agt_with_active_row --preview 10
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

```bash
agenttower attach-log --target agt_unknown123def456
# stderr: error: agent_not_found: no such agent
# exit 3

agenttower attach-log --target agt_abc123def456 --log /not/host/visible/file.log
# stderr: error: log_path_not_host_visible: no canonical bind mount for /not/host/visible/file.log
# exit 3

agenttower attach-log --target agt_abc123def456 --preview 250
# stderr: error: value_out_of_set: lines must be between 1 and 200
# exit 3
```

`--json` mode for the same errors:

```json
{"ok":false,"error":{"code":"agent_not_found","message":"no such agent"}}
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
