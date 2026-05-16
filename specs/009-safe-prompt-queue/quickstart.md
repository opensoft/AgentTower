# Quickstart: Safe Prompt Queue and Input Delivery

**Branch**: `009-safe-prompt-queue` | **Date**: 2026-05-11

This walk-through verifies FEAT-009 end-to-end on a developer
workstation with a single bench container running. It exercises
every user story (US1 – US6) and surfaces the key operator
commands. Total wall-clock time: ≤ 5 minutes after the
prerequisites are met.

## Prerequisites

- A host daemon running on the developer workstation
  (`agenttowerd`), already serving the FEAT-001..008 slice.
- One bench container running (image with `tmux` installed).
- The `agenttower` console script available on the host AND
  inside the bench container (FEAT-005 thin client).
- Two registered agents from FEAT-006:
  - A master, attached to a tmux pane inside the bench container.
    Call its `agent_id` `agt_aaaaaa111111` (12 hex chars), label
    `queen`.
  - A slave, attached to another tmux pane inside the same (or a
    second) bench container. Call its `agent_id`
    `agt_bbbbbb222222`, label `worker-1`.
- The state DB has been migrated to v7 (the daemon does this
  automatically on first boot of a FEAT-009-aware build).

Confirm the prerequisites:

```bash
# On the host
$ agenttower status
... daemon: running, schema_version=7, agents=2 (1 master, 1 slave), routing=enabled

$ agenttower agents list
agt_aaaaaa111111  queen      master   active
agt_bbbbbb222222  worker-1   slave    active
```

## 1. US1 — Master sends a prompt to a slave

From the master's tmux pane (inside the bench container):

```bash
$ agenttower send-input --target worker-1 --message "do the thing"
delivered: msg=12345678-1234-1234-1234-123456789012 target=worker-1(agt_bbbbbb222222)
$ echo $?
0
```

The slave's tmux pane now shows the envelope, terminated by an
Enter keystroke. The envelope body is byte-exact:

```text
Message-Id: 12345678-1234-1234-1234-123456789012
From: agt_aaaaaa111111 "queen" master
To: agt_bbbbbb222222 "worker-1" slave
Type: prompt
Priority: normal
Requires-Reply: yes

do the thing
```

Inspect the queue from the host (or any bench container):

```bash
$ agenttower queue
MESSAGE_ID                            STATE      SENDER          TARGET             ENQUEUED                  LAST_UPDATED              EXCERPT
12345678-1234-1234-1234-123456789012  delivered  queen(agt_aaaa) worker-1(agt_bbbb) 2026-05-11T15:32:04.123Z  2026-05-11T15:32:05.012Z  do the thing
```

Inspect the audit history:

```bash
$ agenttower events --target agt_bbbbbb222222 --type queue_message_delivered --since 2026-05-11T00:00:00Z
{ "schema_version": 1, "event_type": "queue_message_delivered", "message_id": "12345678-...", "from_state": "queued", "to_state": "delivered", ... }
```

## 2. US2 — Permission gate refuses disallowed sends

### 2a. Send to a non-slave/non-swarm target

```bash
$ agenttower send-input --target queen --message "infinite loop"
send-input failed: target_role_not_permitted — target role 'master' is not in the permitted set {slave, swarm}
$ echo $?
8
```

### 2b. Send to an unknown target

```bash
$ agenttower send-input --target ghost --message "hello"
send-input failed: agent_not_found — no agent with id or label 'ghost' is registered
$ echo $?
5
```

### 2c. Send to an inactive target

(Stop the slave's container, then attempt the send from the
master pane.)

```bash
$ agenttower send-input --target worker-1 --message "knock knock"
send-input failed: target_container_inactive — target's container is no longer in the daemon's active set
$ echo $?
9
```

In all three cases, `agenttower queue --state blocked` shows the
row (when one was created) with the corresponding `block_reason`,
and `agenttower events` shows the `queue_message_blocked` audit
row. In the unknown-target case (2b), no row is created at all
(FR-049 invariant on `agent_not_found`).

## 3. US3 — Operator inspects and overrides the queue

### 3a. Delay a queued send before delivery

Disable routing first to force a queued row that doesn't
immediately deliver:

```bash
# From the host
$ agenttower routing disable
routing disabled (was enabled)

# From the master pane
$ agenttower send-input --target worker-1 --message "wait for it" --no-wait
queued: msg=23456789-...
$ echo $?
0

# Re-enable routing — the row is still queued and now eligible
$ agenttower routing enable
routing enabled (was disabled)
```

(In practice the row landed in `blocked` with `kill_switch_off`
because routing was disabled at submit time. Use `approve` to
flip it back to `queued`.)

```bash
$ agenttower queue --state blocked
MESSAGE_ID                            STATE    SENDER          TARGET             ENQUEUED                  LAST_UPDATED              EXCERPT
23456789-...                          blocked  queen(agt_aaaa) worker-1(agt_bbbb) 2026-05-11T15:33:00.000Z  2026-05-11T15:33:00.020Z  wait for it

$ agenttower queue approve 23456789-...
approved: msg=23456789-... state=queued
```

The delivery worker picks it up within ≤ 1 s and delivers.

### 3b. Cancel a queued row

```bash
$ agenttower queue cancel 34567890-...
$ agenttower queue --state canceled --target worker-1
MESSAGE_ID                            STATE     ...   EXCERPT
34567890-...                          canceled  ...   nevermind
```

### 3c. Attempt to mutate a terminal row

```bash
$ agenttower queue cancel 12345678-1234-1234-1234-123456789012
queue cancel failed: terminal_state_cannot_change — row is in terminal state 'delivered'
$ echo $?
15
```

## 4. US4 — Global routing kill switch

```bash
# From the host (host-only constraint)
$ agenttower routing disable
routing disabled (was enabled)

# Master attempts a send — row lands in blocked
$ agenttower send-input --target worker-1 --message "during incident"
send-input failed: routing_disabled — kill switch is off; row created in blocked state
$ echo $?
2

# Operator can still inspect / cancel
$ agenttower queue --state blocked --since 2026-05-11T00:00:00Z
...one row, state=blocked, block_reason=kill_switch_off

# Routing toggle from a bench container is refused
$ agenttower routing disable   # inside the bench container
routing disable failed: routing_toggle_host_only — routing toggle requires host CLI
$ echo $?
19
```

Re-enable routing:

```bash
$ agenttower routing enable
routing enabled (was disabled)

# Existing kill_switch_off rows stay blocked until explicitly approved
$ agenttower queue --state blocked --since 2026-05-11T00:00:00Z   # still shows the row
$ agenttower queue approve <message_id>                  # operator unblocks
```

## 5. US5 — Shell metacharacters in the body

```bash
$ agenttower send-input --target worker-1 --message-file ./payload.txt
# payload.txt contains:
#   '$(touch /tmp/should-not-exist); echo "${X}"; rm -rf /; `uname`
delivered: msg=45678901-...
```

Verify safety: no new process was spawned on the host or in the
container, and `/tmp/should-not-exist` was not created.

```bash
$ ls /tmp/should-not-exist 2>&1
ls: cannot access '/tmp/should-not-exist': No such file or directory

$ docker exec <bench-container> ls /tmp/should-not-exist 2>&1
ls: cannot access '/tmp/should-not-exist': No such file or directory
```

The slave's tmux pane received the exact characters as input —
none of them executed as shell.

## 6. US6 — Daemon restart during in-flight delivery

(Requires the fault-injection test seam
`AGENTTOWER_TEST_TMUX_FAKE` to delay the paste so the daemon can
be stopped mid-attempt; see the integration test
`test_queue_us6_restart_recovery.py` for the deterministic
setup.)

```bash
# Submit a row that will be in-flight when the daemon is killed
$ agenttower send-input --target worker-1 --message "interrupted" --no-wait
queued: msg=56789012-...

# (In another shell) kill the daemon between
# delivery_attempt_started_at and delivered_at
$ kill -KILL <agenttowerd-pid>

# Restart the daemon
$ agenttowerd &

# The row was transitioned to failed during boot
$ agenttower queue --state failed --target worker-1
MESSAGE_ID  STATE   SENDER          TARGET             ENQUEUED  LAST_UPDATED  EXCERPT
56789012-.. failed  queen(agt_aaaa) worker-1(agt_bbbb) ...       ...           interrupted

$ agenttower queue --target worker-1 --since 2026-05-11T00:00:00Z --json | jq '.[] | select(.message_id == "56789012-...") | .failure_reason'
"attempt_interrupted"
```

The slave's tmux pane did NOT receive a second paste. The audit
log contains exactly one `queue_message_failed` entry for the
recovery transition.

## 7. JSON contract validation

Every `--json` output validates against the
`queue-row-schema.md` JSON Schema:

```bash
$ agenttower queue --json --limit 10 | jq -c '.[]' | while read row; do
    echo "$row" | jsonschema -i /dev/stdin specs/009-safe-prompt-queue/contracts/queue-row-schema.md
  done
# (no errors)
```

The audit JSONL validates against `queue-audit-schema.md`:

```bash
$ tail -100 ~/.local/state/opensoft/agenttower/events.jsonl \
    | jq -c 'select(.event_type | startswith("queue_message_"))' \
    | while read entry; do
        echo "$entry" | jsonschema -i /dev/stdin specs/009-safe-prompt-queue/contracts/queue-audit-schema.md
      done
# (no errors)
```

## 8. What to do next

- Continue to `/speckit.tasks` to generate the implementation
  task list.
- Optionally run `/speckit.analyze` for a final cross-artifact
  consistency check before implementation.
- Optionally run another `/speckit.checklist` against any
  remaining risk area (e.g., `performance.md`) before tasks.

## Troubleshooting

| Symptom | Likely cause | Remedy |
|---|---|---|
| `send-input` returns `sender_not_in_pane` | Running from host or from an unregistered pane | Run inside the master's registered tmux pane |
| `send-input` returns `target_label_ambiguous` | Two active agents share the label | Use the `agent_id` instead, or deregister one |
| `send-input` returns `body_too_large` | Body + envelope headers > 64 KiB | Trim the body or raise `envelope_body_max_bytes` in `[routing]` config |
| `queue approve` returns `approval_not_applicable` | `block_reason` is intrinsic (role-based) | Use `queue cancel` instead |
| `routing disable` returns `routing_toggle_host_only` | Caller is a bench-container thin client | Run from host CLI |
| Worker appears stalled (rows stuck `queued`) | Daemon is in degraded-JSONL state OR delivery thread crashed | Check `agenttower status` for `degraded_queue_audit_persistence`; check daemon logs |
