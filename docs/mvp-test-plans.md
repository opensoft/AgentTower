# AgentTower MVP Test Plans

Status: Draft v0.1  
Date: 2026-05-11  
Scope: MVP through `FEAT-010`

These three plans should be run in order after `FEAT-010` lands. Together they
verify the MVP from deterministic contracts through real bench-container use and
finally through safety/resilience failure modes.

## Plan 1: Deterministic MVP Contract Suite

Goal: prove every MVP feature contract without requiring real Docker containers,
real tmux sessions, or real agent CLIs.

This is the first gate because failures here should be cheap, reproducible, and
specific. It should run in CI and in a local clean checkout.

### Coverage

- Package entrypoints: `agenttower`, `agenttowerd`
- Config/state path resolution and initialization
- SQLite schema migrations through the MVP schema version
- JSONL audit/event writer contracts
- Daemon lifecycle: start, status, stop, stale recovery, lock behavior
- Unix socket protocol: framing, errors, one-request-per-connection behavior
- Docker adapter parsing and degraded Docker states
- Container discovery reconciliation
- tmux adapter parsing, pane scan reconciliation, inactive cascade behavior
- Container-local socket override and runtime identity detection
- `config doctor` output and exit-code behavior
- Agent registration, idempotency, role/capability validation, master promotion
  safety, swarm parent validation
- Log attachment contracts, path validation, redaction, offset persistence,
  log rotation/truncation/missing-file handling
- Event reader loop, classifier rules, debounce, restart recovery, JSON schema
- `FEAT-009` prompt queue schema, permission checks, kill switch, cancellation,
  delay/approval states, safe paste-buffer command construction
- `FEAT-010` route subscription schema, event notification envelopes,
  per-target FIFO ordering, arbitration records, swarm report parser

### Environment

- Fresh checkout
- Isolated `HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, and `XDG_CACHE_HOME`
- Fake Docker/tmux adapters or fake binaries ahead of the real tools in `PATH`
- No dependency on a real running Docker daemon
- No dependency on a real tmux server

### Procedure

1. Install the package in editable mode with test extras.
2. Run the full unit suite.
3. Run integration tests that use fake Docker/tmux fixtures.
4. Assert no test opens a TCP/UDP listener.
5. Assert no test sends terminal input except through the `FEAT-009` mocked safe
   delivery seam.
6. Validate event JSON against the event schema.
7. Validate CLI output contracts for human, TSV, and JSON modes where present.
8. Verify all generated state files use required host-user-only permissions.

### Required Checks

```bash
python -m pip install -e '.[test]'
pytest -q tests/unit tests/integration
```

Additional checks should be added when `FEAT-009` and `FEAT-010` specs land:

```bash
pytest -q tests/unit -k 'queue or route or arbitration or prompt'
pytest -q tests/integration -k 'queue or route or arbitration or prompt'
```

### Pass Criteria

- All unit and fake-adapter integration tests pass.
- Re-running daemon startup tests leaves exactly one daemon per isolated state
  directory.
- Schema migrations are idempotent from a clean database and from every prior
  MVP schema version.
- Every CLI command has deterministic stdout/stderr and documented exit codes.
- Queue, route, and arbitration state transitions are covered by tests.
- Unsafe input targets are rejected before any tmux delivery command is built.

### Failure Triage

- Contract, parser, schema, and permission failures block all later plans.
- Fake-adapter behavior drift means either the adapter contract or the test
  fixture is wrong; fix before running real Docker/tmux tests.
- Timing failures in daemon tests should be investigated before moving on,
  because they usually turn into flakiness in Plan 2.

## Plan 2: Real Bench Container Smoke Test

Goal: prove the MVP works against real Docker, real tmux, real mounted socket
access, real log files, and real pane output.

This plan verifies that the deterministic contracts from Plan 1 survive the
actual deployment shape: host daemon, bench container, thin client, and tmux
panes.

### Coverage

- Host daemon running as MVP source of truth
- Running bench container discovery
- Container-local `agenttower` reaching the host socket
- tmux pane discovery inside the bench container
- Self-registration from inside tmux panes
- Role/capability metadata visible from host and container
- Log attachment through `tmux pipe-pane`
- Log offset advancement from real appended output
- Event classification from real terminal output
- Prompt queue delivery into an eligible pane
- Route notification from a slave event to a master
- Swarm child registration and display

### Environment

- One disposable bench container whose name matches the configured bench rule
- `tmux` installed inside the bench container
- The host `agenttowerd` socket mounted into the bench container
- Host-visible log directory mounted or otherwise writable as specified by the
  MVP mount contract
- Disposable AgentTower state via isolated XDG paths

The helper script `scripts/smoke/pybench-mvp-bench.sh` prepares this shape from
the local `py-bench:brett` image. Use `reset` before `up` when the test must
start from a fresh AgentTower database rather than retaining inactive historical
container/pane rows from a prior smoke run.

### Procedure

1. Initialize isolated host state.
2. Start `agenttowerd` on the host.
3. Start a disposable bench container.
4. Inside the bench container, start one tmux session with at least four panes:
   `master-a`, `master-b`, `slave-1`, and `swarm-1`.
5. From the host, scan containers and panes.
6. From inside each pane, run `agenttower register-self` with the appropriate
   role and capability.
7. Attach a log to `slave-1` and `swarm-1`.
8. Route selected slave events to both masters.
9. Cause `slave-1` to print:
   - an `AGENTTOWER_DONE` completion marker
   - a waiting-for-input marker or known prompt pattern
   - a test pass pattern
   - a test failure pattern
10. Follow events from the host and verify event rows appear with the expected
    agent and pane identity.
11. Send a queued prompt from `master-a` to `slave-1`.
12. Attempt a second prompt from `master-b` to `slave-1` and verify `FEAT-010`
    arbitration state appears.
13. Register or report `swarm-1` as a child of `slave-1` and verify the
    relationship appears in `list-agents`.
14. Stop the daemon, restart it, and verify log offsets and registry state
    resume without duplicate events.

### Representative Commands

Exact commands may change as `FEAT-009` and `FEAT-010` specs finalize, but the
smoke test should exercise this shape:

```bash
agenttower config init
agenttower ensure-daemon
agenttower scan --containers --panes
agenttower list-containers
agenttower list-panes
agenttower list-agents
agenttower attach-log --target <slave-id>
agenttower route --from <slave-id> --to <master-a-id>
agenttower route --from <slave-id> --to <master-b-id>
agenttower events --follow
agenttower send-input --target <slave-id> --message "echo agenttower-smoke"
agenttower queue
```

### Pass Criteria

- The bench container is discovered and marked active.
- tmux panes are discovered with stable container, socket, session, window,
  pane, pid, tty, command, cwd, and title identity.
- Container-local `agenttower status` reaches the host daemon.
- All registered agents appear in `list-agents` with correct role and
  capability metadata.
- Log files are created at host-visible paths and offsets advance as output is
  appended.
- Event classification emits `completed`, `waiting_for_input`, `test_passed`,
  and `test_failed` from real pane output.
- Routed slave events notify both masters.
- Prompt delivery reaches only eligible slave/swarm targets.
- Multi-master arbitration prevents silent prompt collisions.
- Restarting the daemon does not duplicate historical events.

### Failure Triage

- If the socket is unreachable inside the container, diagnose mount path,
  permissions, and `AGENTTOWER_SOCKET`.
- If panes are missing, inspect `docker exec`, bench user selection, tmux socket
  discovery, and UID assumptions.
- If events are missing, inspect `pipe-pane`, host-visible log paths, offset
  rows, and classifier input.
- If arbitration fails, inspect queue ownership, target locks, and route state
  before testing with real agent CLIs.

## Plan 3: MVP Operational Resilience and Safety Drill

Goal: prove the MVP remains safe and diagnosable under failures, adversarial
input, daemon restarts, stale state, multiple masters, and long-running agent
sessions.

This is the final gate because it intentionally stresses edge cases after the
core real-world flow is known to work.

### Coverage

- Daemon crash and stale pid/socket/lock recovery
- Bench container restart and inactive-container reconciliation
- tmux pane exit, pane replacement, and inactive-pane history
- Missing, truncated, rotated, and permission-denied log files
- Agent re-registration and idempotency after pane/container changes
- Unknown, inactive, or unauthorized target rejection
- Global prompt-routing kill switch
- Prompt queue cancellation, delay, approval, failure, and delivery audit rows
- Multi-master prompt collision handling
- Route subscription filtering by event type
- Swarm report parsing with malformed or stale parent references
- Redaction of secrets in log excerpts and events
- Large output bursts and partial-line handling
- No shell interpolation of prompt text or log text
- CLI behavior when daemon is unavailable
- JSONL/SQLite durability after restart

### Environment

- Same real bench setup from Plan 2
- Two master panes and at least two slave panes
- One swarm child pane
- A disposable project directory with commands that can intentionally pass,
  fail, hang, print secrets, and exit

### Procedure

1. Start from a passing Plan 2 environment.
2. Kill `agenttowerd` abruptly and verify `ensure-daemon` recovers.
3. Restart the bench container and verify old containers/panes become inactive
   instead of being deleted.
4. Recreate tmux panes and verify new identities are distinct from historical
   pane records.
5. Rotate and truncate attached log files; verify offsets recover safely.
6. Remove read permission from one log file; verify only that agent degrades and
   others continue ingesting.
7. Print secret-like values in a pane; verify redaction in event excerpts.
8. Send prompt text containing shell metacharacters, newlines, quotes, command
   substitutions, and ANSI/control characters; verify delivery uses safe tmux
   paste-buffer behavior and does not execute locally.
9. Try to send input to `unknown`, inactive, unregistered, and unauthorized
   panes; verify rejection before delivery.
10. Enable the global routing/input kill switch and verify queued prompts do not
    deliver.
11. Have both masters target the same slave and verify arbitration prompts,
    queue state, and audit records.
12. Exercise arbitration decisions: `queue-next`, `delay`, and `cancel`.
13. Emit events of multiple types from a slave and verify routes notify only for
    subscribed event types.
14. Emit valid and malformed `AGENTTOWER_SWARM_MEMBER` lines and verify correct
    child display or conservative rejection.
15. Restart the daemon and verify registry, queue, routes, events, offsets, and
    arbitration records are durable.

### Pass Criteria

- Failures are isolated: one bad log, pane, route, or container does not stop the
  daemon or unrelated agents.
- Recovery is explicit and visible through CLI output, event rows, or lifecycle
  logs.
- No unknown or unauthorized pane receives input.
- Prompt text and log text never become shell commands.
- Multi-master collisions are serialized and auditable.
- Route filters behave exactly as configured.
- Restarting the daemon preserves state and does not replay old prompt delivery
  or duplicate historical events.
- All safety-relevant actions are represented in SQLite and/or JSONL audit
  history.

### Failure Triage

- Any unexpected input delivery is a release blocker.
- Any unredacted secret-like excerpt should block the MVP unless explicitly
  accepted as outside the redaction contract.
- Any route or arbitration behavior that is not visible to the user should block
  `FEAT-010` completion.
- Any daemon crash from malformed log output, malformed swarm reports, or prompt
  text is a release blocker.

## Overall MVP Exit Criteria

The MVP is verified only when all three plans pass in order:

1. Plan 1 proves contracts and deterministic behavior.
2. Plan 2 proves the real host-daemon/container/tmux/log/event path.
3. Plan 3 proves operational safety and recovery.

At that point AgentTower can claim the MVP provides a usable local control plane
for bench-container tmux agents: discovery, registration, logging, eventing,
safe prompt delivery, event routing, swarm display, and multi-master
arbitration.
