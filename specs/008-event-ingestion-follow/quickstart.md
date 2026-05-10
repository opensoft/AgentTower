# Quickstart: Event Ingestion, Classification, and Follow CLI

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10
**Plan**: [plan.md](./plan.md)

End-to-end demo: register an agent in a bench container, attach its
pane log via FEAT-007, write some classifier-trigger lines, inspect
events with `agenttower events`, and follow live events.

Prerequisites:

- AgentTower built from the `008-event-ingestion-follow` branch and
  installed (the `agenttower` and `agenttowerd` console scripts on
  `$PATH`).
- A running bench container with `tmux` available (`docker exec
  <container> tmux ls` returns at least one pane).
- The host daemon is reachable (`agenttower status` exits 0).

Throughout this guide, `<agent-id>` is a placeholder for the value
returned by `register-self`; copy-paste it from your shell.

---

## Step 1 — Initialize daemon state (one-time)

```bash
agenttower config init
agenttower ensure-daemon
agenttower status
```

`agenttower status` should now include the new
`events_reader.running: true` field (data-model §7).

---

## Step 2 — Register an agent and attach its pane log

From inside the bench container's tmux pane:

```bash
agenttower register-self --label demo-agent --capability test
# -> agt_a1b2c3d4e5f6  (the FEAT-006 agent_id; copy this)

agenttower attach-log --target agt_a1b2c3d4e5f6
# -> log attached at /home/.../agt_a1b2c3d4e5f6.log
```

Confirm the attachment is `active`:

```bash
agenttower attach-log --status --target agt_a1b2c3d4e5f6
# -> { "status": "active", "log_path": "...", "byte_offset": 0, ... }
```

---

## Step 3 — Write some classifier-trigger lines

Inside the same pane, run a few commands to generate output that
exercises different classifier rules:

```bash
echo "running unit tests..."             # activity
python -c "raise ValueError('boom')"     # error (Traceback)
echo "FAILED tests/test_x.py::test_y"    # test_failed
echo "=== 12 passed in 0.34s ==="        # test_passed
echo "MANUAL_REVIEW: handle this case"   # manual_review_needed
```

These lines flow through `tmux pipe-pane` into the FEAT-007 host-
visible log file. The FEAT-008 reader picks them up within ≤ 1 s
of the byte being flushed (FR-001 / SC-002).

---

## Step 4 — List the events

Wait one reader cycle (≈ 1 s), then list events:

```bash
agenttower events --target agt_a1b2c3d4e5f6
```

Expected human output (newest order may vary by exact timing; the
default is oldest-first):

```text
2026-05-10 12:34:56  demo-agent (agt_a1b2c3d4e5f6)  activity              running unit tests...
2026-05-10 12:34:56  demo-agent (agt_a1b2c3d4e5f6)  error                 Traceback (most recent call last):
2026-05-10 12:34:57  demo-agent (agt_a1b2c3d4e5f6)  test_failed           FAILED tests/test_x.py::test_y
2026-05-10 12:34:57  demo-agent (agt_a1b2c3d4e5f6)  test_passed           === 12 passed in 0.34s ===
2026-05-10 12:34:57  demo-agent (agt_a1b2c3d4e5f6)  manual_review_needed  MANUAL_REVIEW: handle this case
```

Try a JSON pipe:

```bash
agenttower events --target agt_a1b2c3d4e5f6 --json | jq '.event_type'
# "activity"
# "error"
# "test_failed"
# "test_passed"
# "manual_review_needed"
```

Try a type filter:

```bash
agenttower events --target agt_a1b2c3d4e5f6 --type error --type test_failed --json
```

---

## Step 5 — Follow live events

In one terminal:

```bash
agenttower events --follow --target agt_a1b2c3d4e5f6
```

In a second terminal (or back in the agent's pane):

```bash
echo "ERROR: something went wrong"
```

The follow terminal should print one new line within ≤ 1 s of the
write (SC-002):

```text
2026-05-10 12:35:12  demo-agent (agt_a1b2c3d4e5f6)  error  ERROR: something went wrong
```

Press Ctrl-C in the follow terminal — it should exit cleanly with
status 0 (`echo $?`).

---

## Step 6 — Verify durable persistence

Stop and restart the daemon:

```bash
agenttower stop
agenttower ensure-daemon
```

List events again:

```bash
agenttower events --target agt_a1b2c3d4e5f6 --limit 50
```

Same events, same order, same `event_id` values, no duplicates
(US3 / SC-003).

The JSONL history file is also intact:

```bash
wc -l ~/.local/state/opensoft/agenttower/events.jsonl
# (count includes both FEAT-008 events and FEAT-007 lifecycle/audit rows)
```

---

## Step 7 — Verify lifecycle separation (optional)

Trigger a log-file rotation and confirm the FEAT-007 lifecycle
event lands on the FEAT-007 surface, NOT in the FEAT-008 events
stream:

```bash
# Truncate the log in place
truncate -s 0 ~/.local/state/opensoft/agenttower/logs/<container_id>/agt_a1b2c3d4e5f6.log

sleep 2

# FEAT-007 lifecycle event in JSONL:
grep '"event_type":"log_rotation_detected"' ~/.local/state/opensoft/agenttower/events.jsonl

# FEAT-008 events stream does NOT include it:
agenttower events --target agt_a1b2c3d4e5f6 --type log_rotation_detected
# -> exit 7 (events_filter_invalid; closed-set type unknown to events.list)
```

This confirms FR-026 / SC-009.

---

## Step 8 — Inspect the classifier rule catalogue (debug)

Hidden flag, useful for verifying which rule fired:

```bash
agenttower events --classifier-rules
```

You should see all 11 matcher rules (priority-ordered) plus the two
synthetic rule ids (`pane_exited.synth.v1`, `long_running.synth.v1`).

---

## Step 9 — Argument-error sanity checks

```bash
agenttower events --target invalid-id
# stderr: target must match agt_<12 hex>
# exit 2

agenttower events --target agt_does_not_exist
# stderr: agent_not_found: no agent registered with id agt_does_not_exist
# exit 4

agenttower events --type made_up
# stderr: unknown event type 'made_up'
# exit 2

agenttower events --since 'not a date'
# stderr: --since must be ISO-8601 with offset
# exit 2

agenttower events --follow --limit 10
# stderr: --limit is not allowed with --follow
# exit 2
```

---

## Cleanup

Detach the log and stop the daemon:

```bash
agenttower detach-log --target agt_a1b2c3d4e5f6
agenttower stop
```

The events row count and JSONL file are NOT cleaned up — there is
no automatic retention in MVP (Clarifications Q4). Operators may
manually `rm` the `events.jsonl` file and `DELETE FROM events;` the
SQLite table if needed; this is out of band.

---

## Common patterns

### Pipe to a downstream tool

```bash
agenttower events --target <id> --follow --json | jq -c 'select(.event_type=="error")'
```

### Time-bound query

`--since` and `--until` accept ISO-8601 with an explicit offset
(`Z` or `±HH:MM`). On GNU date (Linux):

```bash
agenttower events --since "$(date -u -d '5 minutes ago' +%FT%TZ)"
```

On BSD date (macOS):

```bash
agenttower events --since "$(date -u -v-5M +%FT%TZ)"
```

Or supply an absolute timestamp directly:

```bash
agenttower events --since "2026-05-10T12:00:00Z"
```

### Reverse / paginate

```bash
agenttower events --reverse --limit 50
# print stderr `# next_cursor: <token>` if more events exist
agenttower events --reverse --limit 50 --cursor <token>
```

---

## What you've verified by completing this quickstart

| Step | Spec evidence |
|---|---|
| 4 | US1 (operator inspects events), FR-027 / FR-032 schema |
| 5 | US2 (follow), SC-002 latency |
| 6 | US3 (restart), SC-003 |
| 7 | FR-026 / SC-009 (lifecycle separation) |
| 8 | FR-008 / SC-007 visibility |
| 9 | FR-035a (`agent_not_found`), CLI argument-error contract |

The remaining acceptance scenarios (US4 file-change carry-over,
US5 `--json` schema strictness, US6 failure surface) are exercised
by the integration test suite, not by this manual quickstart.
