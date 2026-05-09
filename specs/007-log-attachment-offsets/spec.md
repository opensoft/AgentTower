# Feature Specification: Pane Log Attachment and Offset Tracking

**Feature Branch**: `007-log-attachment-offsets`
**Created**: 2026-05-08
**Status**: Draft
**Input**: User description: "FEAT-007 Pane Log Attachment and Offset Tracking: attach durable tmux pane logs to registered AgentTower agents and track read offsets so later features can ingest events incrementally and safely. Provides `agenttower attach-log`, optional `agenttower register-self --attach-log`, host-visible log path generation, `tmux pipe-pane -o` attachment via `docker exec`, durable log-attachment + offset state in SQLite, and a basic redaction utility for common secret patterns. Out of scope: event classification, `events --follow`, routing events, prompt delivery, log-based automation, in-container relay/sidecar, web UI / TUI, non-tmux logging, semantic secret detection."

## Clarifications

### Session 2026-05-08

- Q: How does a `log_attachments` row reach `status=detached`? → A: Add an explicit `agenttower detach-log` command. Detach is operator intent only — only valid transition is `active → detached`; offsets are retained byte-for-byte; re-attach from `detached` reuses the same row and retained offsets (mirrors the `stale → active` recovery path). The daemon MUST NOT implicitly detach on agent inactivation in FEAT-007.
- Q: What happens when `attach-log --log <new-path>` is invoked and the prior `log_attachments` row is `stale` or `detached` (not `active`)? → A: Path change ALWAYS supersedes the prior row, regardless of prior status. Prior status may be `active`, `stale`, or `detached`; the new path gets a fresh attachment row and fresh offsets at `(0, 0)`. Same-path recovery (FR-021 stale→active, FR-021d detached→active) remains the only special case that reuses the existing row and retained offsets.
- Q: How do `--status` and `--preview` behave when there is no `active` attachment? → A: `--status` ALWAYS succeeds and reports the most recent row (by `last_status_at`); when no row exists, it returns `attachment: null, offset: null`. `--preview` is allowed when the most recent row is `active`, `stale`, or `detached`; against a `superseded` row or no row at all it refuses with closed-set `attachment_not_found`; when the selected row exists but the resolved host file is gone, it refuses with closed-set `log_file_missing` (new CLI-facing rejection code, same identifier as the existing FR-046 lifecycle event).
- Q: When the host log file reappears after a `log_file_missing`-induced stale state, does the daemon auto-recover? → A: No. File reappearance does NOT change status by itself; the daemon emits a new `log_file_returned` lifecycle event for observability only. The row remains `stale` until an explicit `attach-log` is run by the operator. Stale recovery for the file-missing case treats the reappeared file as a FRESH STREAM — offsets reset to `(0, 0)` per the FR-024 / FR-025 file-consistency check applied at re-attach time. This does NOT change the pane-drift stale-recovery contract (FR-021's byte-for-byte retention still applies when the file at `log_path` is intact and `file_inode` / `file_size_seen` match the stored values).
- Q: How are FR-028 redaction patterns applied? → A: Redaction runs PER LINE. Anchored JWT and `.env`-shape patterns retain their `^...$` semantics and only match standalone lines. Unanchored token patterns (`sk-`, `gh[ps]_`, `AKIA`, `Bearer …`) match anywhere within a line with `\b` word-boundary protection on both sides where applicable. The redaction utility MUST NOT perform multi-line buffer matching in FEAT-007 — tokens that span newlines are not redacted in this feature.

## Threat Model & Trust Boundaries *(mandatory)*

This section is the authoritative threat model for FEAT-007. Every
hardening FR (§"Hardening (security-derived)" below, FR-047 through
FR-065) MUST cite at least one adversary class or trust boundary
defined here.

### Adversary classes

The daemon assumes the following adversary classes exist; each one
maps to a non-empty set of hardening FRs that mitigate or constrain
its leverage. Adversary classes outside this list are explicitly
out of scope (see §"Out of scope" below).

- **A1 — Operator with a typo or misconfiguration.** Not malicious;
  supplies a `--log <path>` that is unsafe by accident
  (relative path, traversal, shell metacharacters, points at a
  daemon-owned file, points at `/proc`). The daemon refuses with
  a closed-set code and zero side effects (FR-006, FR-051,
  FR-052, FR-053).
- **A2 — Malicious operator-controlled `--log <path>`.** Same
  surface as A1, but the operator deliberately supplies a payload
  intended to (a) break out of the `cat >> <log>` shell
  redirection (FR-047), (b) overwrite a daemon-owned path
  (FR-052), (c) traverse the canonical mount root via symlinks
  (FR-050), or (d) DoS the daemon via mount-list bombing (FR-063)
  or regex-pathological preview content (FR-064). The CLI is
  reachable only via the `0600` host-user-only socket, so this
  adversary already has host-user filesystem access.
- **A3 — Malicious in-container process emitting tmux pane
  content.** A compromised agent or co-tenant process inside a
  bench container that writes adversarially crafted bytes into
  the tmux pane: secrets in raw form, shell escape sequences in
  the pipe-pane command field, embedded NUL bytes, oversized
  lines. The daemon trusts pane content only insofar as the
  redaction utility processes it for operator-facing render
  surfaces (FR-027); the on-disk log file content is untrusted
  and never re-executed (FR-065).
- **A4 — Process inside the bench container that runs `tmux
  pipe-pane` directly to a non-AgentTower path or away from
  AgentTower.** The daemon detects this drift via FEAT-004
  reconciliation (`pane_pipe=0` → `status=stale`, FR-042) and via
  the orphan-detection startup pass (FR-043). The daemon NEVER
  auto-attaches an orphan (FR-043), so an in-container process
  that creates an orphan pipe cannot trick the daemon into
  binding it.
- **A5 — Process outside the bench container without `0600`
  socket access.** Cannot reach the daemon (FEAT-002 socket-file
  authorization). Out of scope for FEAT-007 mitigations beyond
  inheriting the FEAT-002 boundary unchanged.

### Trust boundaries

The daemon explicitly TRUSTS:
- **TB1**: FEAT-003's persisted `containers.mounts_json`. The
  daemon walks this JSON for FR-007 host-visibility proof without
  re-validating against `docker inspect`. Violation of TB1 (e.g.,
  the cached JSON is stale because a container was reconfigured
  but FEAT-003 hadn't rescanned yet) surfaces as
  `log_path_not_host_visible` or `pipe_pane_failed` rather than
  silent compromise. Inherited from FEAT-003 trust boundary.
- **TB2**: FEAT-006's `agents.container_id`, `agents.active`, and
  pane composite key columns. Used directly by FR-001 through
  FR-004 without re-validation.
- **TB3**: SO_PEERCRED-derived `socket_peer_uid` plumbed by the
  FEAT-002 socket server. Used in FR-044 audit rows. The daemon
  refuses unexpected uids per FR-058.
- **TB4**: The kernel's `os.stat` `st_dev` and `st_ino` for
  rotation/recreation detection (FR-024, FR-025). Inode reuse is
  a known kernel-level corner; the daemon also tracks
  `file_size_seen` so a reused inode at a smaller size still
  trips FR-024.
- **TB5**: Python's stdlib `re` engine compiled with `re.ASCII`
  (FR-049). Pre-compiled at module load; not re-compiled per call.

The daemon explicitly DOES NOT TRUST:
- **NT1**: Any field in the `attach_log` / `detach_log` /
  `attach_log_status` / `attach_log_preview` request envelope
  beyond the closed allowed-keys set (FR-039).
- **NT2**: The `source` field if supplied by a client (FR-039 wire
  rejection); only the daemon sets it.
- **NT3**: The bytes inside the host log file. Redaction is
  applied at every operator-facing render path; the file content
  is never executed, parsed as code, or used to make daemon
  decisions (FR-065).
- **NT4**: The `pane_pipe_command` string returned by `tmux
  list-panes` (FR-011) beyond a strict canonical-prefix match
  (FR-054). The string is sanitized before being stored as
  `prior_pipe_target` in audit rows (FR-044, FR-021).
- **NT5**: User-supplied `--log <path>` content beyond the FR-006
  shape rules and FR-051 / FR-052 / FR-053 / FR-050 hardening rules.

### Data flow path

```
[CLI in container]                     [host daemon]
   |                                       |
   |--- AF_UNIX socket (0600, host-uid) ---|
   |                                       |
   |       attach_log envelope             |
   |------------------------------------> [_check_schema_version]
   |                                       [_check_unknown_keys]
   |                                       [agent / pane / container resolution]
   |                                       [FR-007 host-visibility proof]
   |                                       |    \
   |                                       |     (reads cached containers.mounts_json — TB1)
   |                                       |
   |                                       [acquire agent_locks (FR-040)]
   |                                       [acquire log_path_locks if --log (FR-041)]
   |                                       [BEGIN IMMEDIATE]
   |                                       [docker exec → tmux list-panes (FR-011)]
   |                                       [docker exec → tmux pipe-pane -o (FR-010)]
   |                                       [INSERT/UPDATE log_attachments]
   |                                       [INSERT/UPDATE log_offsets]
   |                                       [append events.jsonl audit row]
   |                                       [COMMIT]
   |                                       |
   |                                       v
   |                                 [host log file at <canonical path>]
   |                                  mode 0600, dir mode 0700
   |                                  bytes written by container's tmux process
   |
   |       attach_log_preview envelope     |
   |------------------------------------> [reads host log file]
   |                                       [redaction.redact_lines per FR-027/FR-028/FR-029]
   |<----- redacted lines via response ----|
```

### Authentication & authorization

- **Authentication**: SO_PEERCRED on the AF_UNIX socket. The daemon
  records `socket_peer_uid` on every audit row (FR-044) and
  refuses calls from unexpected uids per FR-058. The daemon NEVER
  accepts identity claims from the request body.
- **Authorization**: Host user only via `0600` socket-file mode.
  Inherited verbatim from FEAT-002. Every FEAT-007 method runs
  inside this boundary; no method bypasses it.

### Data classification

- **C1 — Host log file content**: Potentially sensitive (operator,
  agent, or pane secrets including paste-buffer contents,
  inadvertently typed credentials, command-line API keys).
  Stored at mode `0600` under a `0700` parent directory (FR-008).
  The daemon ensures the modes; tmux running inside the container
  writes the bytes. Forensic operators with appropriate
  filesystem access may grep the raw file deliberately
  (Spec §Assumptions "Redaction is content-only").
- **C2 — `events.jsonl` audit log**: Potentially sensitive
  (`socket_peer_uid`, `prior_pipe_target` snippet, log paths).
  Inherits FEAT-001 file mode; FEAT-007 does not relax it.
- **C3 — `log_attachments.pipe_pane_command` column**: The
  literal `docker exec` shell that was issued, sanitized + bounded.
  Stored for forensic audit; never re-executed (FR-065).
- **C4 — Lifecycle event payloads**: Inode strings, sizes, log
  paths, pane composite keys. Same sensitivity tier as C2.
  Bounded by FR-062.

### Non-repudiation

- Every `log_attachments.status` transition appends exactly one
  JSONL audit row (FR-044), including system-driven transitions
  from FEAT-004 reconciliation (FR-042). Each row carries
  `socket_peer_uid` (TB3) and a daemon-clock UTC timestamp.
- No-op writes (idempotent re-attach per FR-018) and failed
  attaches (FR-045) DO NOT append. This means a sequence of
  rapid no-op re-attaches is invisible to the audit log; the
  daemon does NOT promise "every attach-log INVOCATION is
  audited" — only "every actual STATE TRANSITION is audited".
  This boundary is intentional and is documented here so
  downstream consumers can rely on it.
- Lifecycle events (FR-046) are observability signals, NOT
  audit rows. They are emitted to the daemon's lifecycle logger
  (the same surface FEAT-006 uses for `audit_append_failed`)
  and are subject to flapping suppression and rate limiting per
  FR-061. Operators MUST NOT rely on lifecycle events for
  forensic evidence; they are diagnostic output.

### Out-of-scope adversarial scenarios

The following are NOT in FEAT-007's threat model. Mitigations for
these are inherited from the kernel, Docker, or the host's
operating environment, OR are explicitly deferred:
- Kernel-level inode/device spoofing.
- Mount-namespace tricks that defeat `os.path.realpath`.
- Docker daemon compromise that returns falsified `inspect` data
  (FEAT-003's TB1 boundary).
- Host root compromise (host root can read every file in
  `~/.local/state/opensoft/agenttower/` regardless of mode).
- Side-channel timing attacks on the redaction utility (no
  constant-time comparison required because nothing in FEAT-007
  compares secrets — FR-027 is a one-way render transform).
- Cryptographic weakness of `secrets.token_hex(6)` for
  `lat_<12-hex>` collisions (48 bits is sufficient at MVP scale
  per Research R-001).
- An adversary with the ability to arbitrarily modify the host
  log file out-of-band. Redaction at preview time still applies
  (FR-027), but the daemon does not detect content tampering on
  its own (FR-065 makes this explicit).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Attach a tmux pipe-pane log to a registered agent (Priority: P1)

A developer working inside a tmux pane in a running bench container has already registered the pane as a FEAT-006 agent. They run `agenttower attach-log --target <agent-id>` (from inside the container, or from the host with an explicit `--target`). The host daemon resolves the bound pane via FEAT-006, generates the canonical host-visible log path `~/.local/state/opensoft/agenttower/logs/<container>/<agent-id>.log` (creating any missing parent directories at `0700`, the file at `0600` if absent), proves the path is host-visible by inspecting the container's mounts (FEAT-003), and runs `tmux pipe-pane -o -t <pane> 'cat >> <log_file>'` via `docker exec` against the bound container. The daemon persists one row in `log_attachments` and one row in `log_offsets` (initial `byte_offset=0, line_offset=0`), appends one JSONL audit record, and the same `agenttower attach-log --target <agent-id> --status` invocation surfaces the new attachment with `status=active`.

**Why this priority**: FEAT-007 has no value without P1 — it is the slice that proves the end-to-end host-daemon → docker-exec → tmux pipe-pane → host-visible log path → durable SQLite state path works. Every later feature (FEAT-008 event ingestion, FEAT-009 prompt delivery, FEAT-010 routing) needs durable, host-visible per-agent logs to function. P1 also exercises every dependency in the stack at once (FEAT-002 socket, FEAT-003 mount inspection, FEAT-004 pane registry, FEAT-005 thin-client identity, FEAT-006 agent registry).

**Independent Test**: Can be fully tested by spawning the host daemon under the existing test harness, seeding FEAT-003 / FEAT-004 / FEAT-006 tables with one active bench container, one active pane, and one registered agent bound to that pane; injecting a fake `docker exec` adapter that records the literal command issued and a fake `tmux` adapter that confirms the pipe-pane state; running `agenttower attach-log --target <agent-id>` from a subprocess whose environment simulates "inside that bench container, in that pane". The CLI MUST exit `0`, the fake `docker exec` MUST have received the documented `tmux pipe-pane -o -t <pane> 'cat >> <log_file>'` invocation against the resolved container, the `log_attachments` table MUST contain exactly one row in `status=active` bound to the agent's `agent_id` and pane composite key, the `log_offsets` table MUST contain one row at `(0, 0)`, and the JSONL events file MUST contain exactly one `log_attachment_change` audit row.

**Acceptance Scenarios**:

1. **Given** the daemon is running, the agent `agt_abc123def456` is registered and active in container `bench-acme` for pane `%17`, the host bind-mounts `~/.local/state/opensoft/agenttower/logs/<container>` to the same path inside the container, and the caller's environment resolves to that container/pane, **When** the user runs `agenttower attach-log --target agt_abc123def456`, **Then** the CLI exits `0`, prints `attached agent_id=agt_abc123def456 path=<host-path> source=explicit status=active`, the daemon issues `tmux pipe-pane -o -t %17 'cat >> /<host-path>'` via `docker exec -u <container_user> bench-acme sh -lc ...`, the `log_attachments` row is created with `status=active`, and the `log_offsets` row is created at `(byte_offset=0, line_offset=0)`.
2. **Given** an attachment already exists for `(agent_id=agt_abc123def456, log_path=<canonical>)` with `status=active` and `byte_offset=4096`, **When** the user re-runs `agenttower attach-log --target agt_abc123def456` from the same pane with no path override, **Then** the CLI exits `0` with the same attachment row (no duplicate), the `byte_offset=4096` is preserved (no reset), no new audit row is appended, and the daemon performs an idempotent `pipe-pane` re-issue (or no-op if the running pipe-pane already targets the canonical path).
3. **Given** a stored attachment for an agent whose pane was reactivated (FEAT-006 FR-008 re-activation: same composite pane key, `agents.active=1` after a transient inactive window), **When** the user re-runs `attach-log` from that pane, **Then** the existing attachment is reused, the offset is preserved, and the daemon re-engages `pipe-pane` against the now-live pane.
4. **Given** an existing attachment writes to path `/canonical/path/A.log` with `status=active`, **When** the user runs `attach-log --target <id> --log /canonical/path/B.log` (a different host-visible path for the same agent), **Then** the CLI exits `0`, the previous row transitions to `status=superseded` with `superseded_at` set and `superseded_by=<new attachment_id>`, a new attachment row is created in `status=active` for path B, a fresh `log_offsets` row is created at `(0, 0)` for path B, the running `pipe-pane` is toggled off (`tmux pipe-pane -t <pane>` with no command, the close variant) and re-engaged against B, and one `log_attachment_change` audit row is appended carrying both `prior_path` and `new_path`.

---

### User Story 2 - Log offsets persist across daemon restart (Priority: P1)

A future FEAT-008 event reader has consumed bytes `[0, 4096)` of an attached log and updated `log_offsets.byte_offset = 4096`, `line_offset = 137`. The host daemon is restarted (graceful or hard kill). On restart, the daemon reads the persisted offset directly from SQLite without re-scanning the log file from byte 0 — every attached agent's offset state is recovered byte-for-byte from the last committed transaction, and the next reader resumes at exactly the same position.

**Why this priority**: P1 alongside attachment because it is the second invariant FEAT-008 depends on. Without durable offsets, a daemon restart would force every reader to re-scan from byte 0 (causing duplicate event emission) or skip ahead (causing dropped events). FEAT-007 ships the offset table and persistence guarantee; FEAT-008 will ship the reader.

**Independent Test**: Can be fully tested by attaching one log, simulating a reader advancing the offset to `(byte_offset=4096, line_offset=137)` via a test seam that writes the row, killing the daemon process, restarting it, and re-reading the `log_offsets` row. The recovered values MUST equal the pre-restart values byte-for-byte. Optionally, repeat across `SIGTERM` (graceful) and `SIGKILL` (hard) restart paths to assert SQLite WAL durability.

**Acceptance Scenarios**:

1. **Given** an attached agent with `log_offsets = (byte_offset=4096, line_offset=137, last_event_offset=3200)`, **When** the daemon process is terminated and restarted, **Then** the same row reads back identically; subsequent reader calls observe `byte_offset=4096` without any reset.
2. **Given** an attached log whose underlying file has grown from 4096 bytes to 8192 bytes since the last offset advance, **When** the daemon restarts, **Then** the offset row is unchanged at `4096` (offsets advance only when a reader consumes bytes — FR-025), and `last_output_at` reflects the file's most recent observed mtime.

---

### User Story 3 - Operator-facing log preview applies basic secret redaction (Priority: P2)

An operator runs `agenttower attach-log --target <agent-id> --preview <N>` (or any future operator surface that exposes log excerpts). Lines containing common secret patterns — OpenAI-style API keys (`sk-…`), GitHub tokens (`gh[ps]_…`), AWS access keys (`AKIA…`), JWTs (three dotted base64 segments), bearer tokens, and `.env`-shape `KEY=value` where `KEY` matches the pattern `(API_?KEY|TOKEN|SECRET|PASSWORD|AUTH)` — are rendered with each secret replaced by a fixed `<redacted:<type>>` marker. The redaction utility is purely pattern-based, leaves byte offsets untouched, never inspects entropy, and never sends content to an external service.

**Why this priority**: P2 because it is required by FEAT-007 acceptance ("Event excerpts use redacted output") and gates safe operator inspection, but it is downstream of P1 (attachment) and P1's offset persistence in the dependency order. Redaction is independently testable against fixture inputs without any tmux/Docker plumbing.

**Independent Test**: Can be fully tested by feeding a fixture log buffer (containing each documented secret pattern at known byte offsets) to the redaction utility in isolation. Each pattern MUST be replaced by the documented marker; non-matching content MUST pass through byte-for-byte; the redacted output's byte length is allowed to differ from the input (markers are shorter than most matches), but the redaction utility MUST be a pure function (same input → same output). The same fixture suite is the contract that FEAT-008 will reuse for event excerpts.

**Acceptance Scenarios**:

1. **Given** a log line `User auth=sk-abc123XYZ then continued`, **When** the redaction utility processes it, **Then** the output is `User auth=<redacted:openai-key> then continued`.
2. **Given** a log line containing a JWT `eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c`, **When** the utility processes it, **Then** the entire JWT is replaced with `<redacted:jwt>`.
3. **Given** a `.env`-shape line `OPENAI_API_KEY=sk-test-1234`, **When** the utility processes it, **Then** the value (post-`=`) is replaced with `<redacted:env-secret>` while the key name is preserved verbatim.
4. **Given** a log line containing no documented pattern (`Built target ./bin/agenttower in 4.2s`), **When** the utility processes it, **Then** the output equals the input byte-for-byte.

---

### User Story 4 - `register-self --attach-log` is fail-the-call (Priority: P2)

An operator runs `agenttower register-self --role slave --capability codex --attach-log` (FEAT-006 invocation extended with the new flag). If the FEAT-007 attach succeeds, registration succeeds, the agent row is created, the attachment row is created, and both audit rows (FEAT-006 role-change and FEAT-007 attachment-change) are appended in the documented order. If the attach step fails for any closed-set reason (`log_path_not_host_visible`, `pipe_pane_failed`, `tmux_unavailable`, etc.), the entire `register-self` call fails atomically: the agent row is NOT created, no FEAT-006 audit row is appended, and the CLI surfaces the FEAT-007 failure code as the top-level error.

**Why this priority**: P2 — convenience flag, not the primary slice — but the semantics MUST be locked here so FEAT-006 callers and the FEAT-006 wire contract can rely on a deterministic atomic shape. Best-effort behavior is rejected for predictability: an operator who explicitly opts in to attach-log expects to be told if it didn't happen.

**Independent Test**: Can be fully tested by injecting a `tmux_unavailable` failure into the fake tmux adapter, running `register-self --attach-log`, and asserting (a) the CLI exits `3` with code `tmux_unavailable`, (b) zero rows in `agents`, (c) zero rows in `log_attachments`, (d) zero new JSONL audit rows. Repeat with `log_path_not_host_visible` injected via a fake `docker inspect` mount JSON that omits the canonical bind mount.

**Acceptance Scenarios**:

1. **Given** the canonical bind-mount is present and tmux is healthy, **When** `register-self --role slave --attach-log` runs, **Then** the agent is registered AND the log is attached AND both audit rows are appended in the order: FEAT-006 `agent_role_change` first, FEAT-007 `log_attachment_change` second.
2. **Given** the canonical bind-mount is missing (the daemon cannot prove host-visibility), **When** `register-self --role slave --attach-log` runs, **Then** the CLI exits `3` with closed-set code `log_path_not_host_visible`, no agent row is created, no log attachment row is created, no JSONL audit row is appended, and the daemon issues no `docker exec` invocation.

---

### User Story 5 - Stale-attachment detection and recovery (Priority: P3)

The daemon's persisted attachment state can drift from the actual `pipe-pane` state on the running tmux server (operator manually ran `tmux pipe-pane -t <pane>` to toggle off; the bench container restarted; tmux was killed and re-spawned). FEAT-007 detects this drift on every FEAT-004 pane reconciliation cycle: when a previously-attached pane is observed without `pipe_pane` active, the attachment row transitions to `status=stale` and a `log_attachment_change` audit row records the drift. A subsequent `attach-log` re-engages `pipe-pane` against the same path and transitions the row back to `status=active` (offsets retained).

**Why this priority**: P3 — recoverability matters but the daemon does not need to ship automatic re-attachment in MVP. Stale detection plus a clear operator-facing `attach-log --status` view is enough to keep the system honest; automatic re-attachment can ship later without redesign because the durable schema already carries `status` and the audit trail is already in place.

**Independent Test**: Can be fully tested by attaching a log, simulating a `pipe_pane=0` reading on the next FEAT-004 reconcile cycle (via the fake tmux adapter), and asserting the attachment row transitions to `status=stale`, the audit row is appended, the offset row is unchanged, and a follow-up `attach-log --target <id>` transitions back to `status=active` without resetting the offset.

**Acceptance Scenarios**:

1. **Given** an attached agent on pane `%17` with `byte_offset=4096`, **When** the next FEAT-004 reconcile cycle observes pane `%17` with `pipe_pane=0`, **Then** the attachment row transitions to `status=stale` (in the same `BEGIN IMMEDIATE` transaction as the FEAT-004 reconcile write — same cross-subsystem ordering pattern FEAT-006 uses for `last_seen_at`), one `log_attachment_change` audit row is appended with `prior_status=active`, `new_status=stale`, and the `log_offsets` row is unchanged.
2. **Given** a stale attachment with `byte_offset=4096`, **When** the operator runs `attach-log --target <id>`, **Then** the row transitions to `status=active`, `pipe-pane` is re-engaged, and `byte_offset=4096` is preserved.

---

### User Story 6 - File rotation / truncation resets the offset (Priority: P3)

The host log file at `~/.local/state/opensoft/agenttower/logs/<container>/<agent-id>.log` is rotated, truncated, or recreated outside AgentTower's control (operator ran `: > <log>`, `mv <log> <log>.bak`, `logrotate`, etc.). On the next reader cycle, the daemon detects the change via the file's inode (or `(device, inode)` pair on systems that distinguish), or via observing file size shrink relative to the last-seen size, and resets the offset to `(byte_offset=0, line_offset=0)`. The new file is treated as a fresh stream; downstream readers MUST NOT replay the prior file's content.

**Why this priority**: P3 — operationally important but rare, and recoverable. Detection must be present in the durable schema (`file_inode`, `file_size_seen`) so FEAT-008 readers can rely on a reset signal; the actual reader is FEAT-008 work.

**Independent Test**: Can be fully tested by attaching a log, advancing the offset to `(byte_offset=4096, line_offset=137)` via a test seam, recording the file's `(inode, size)`, then either (a) truncating the file to `0` bytes, or (b) deleting and recreating the file, and asserting the next call to the offset-recovery helper returns `(byte_offset=0, line_offset=0)` and emits one `log_rotation_detected` lifecycle event identifying the prior `(inode, size)` and the new `(inode, size)`.

**Acceptance Scenarios**:

1. **Given** an attached log with `(byte_offset=4096, file_inode=N1, file_size_seen=8192)`, **When** the file is truncated to `0` bytes (inode unchanged, size shrinks), **Then** the next offset-recovery cycle resets `(byte_offset=0, line_offset=0)` and emits one lifecycle event.
2. **Given** an attached log with `(byte_offset=4096, file_inode=N1)`, **When** the file is deleted and recreated (new inode `N2`), **Then** the next offset-recovery cycle resets the offset, updates `file_inode=N2`, and emits one lifecycle event.
3. **Given** an attached log at `(byte_offset=4096, file_inode=N1, file_size_seen=8192)`, **When** the host file is deleted and the next reader cycle observes its absence, **Then** the row transitions to `status=stale` and one `log_file_missing` lifecycle event is emitted; the offset row is unchanged.
4. **Given** the row is in `status=stale` with `(byte_offset=4096, file_inode=N1)` because the host file was deleted, **When** the file is recreated externally (new inode `N2`) and a reader cycle observes the reappearance, **Then** exactly one `log_file_returned` lifecycle event is emitted, the row REMAINS `status=stale`, the offset row is unchanged, and no `log_attachment_change` audit row is appended (the system signals the observability surface but takes no recovery action).
5. **Given** the row is in `status=stale` after a `log_file_returned` event with the file present at new inode `N2`, **When** the operator runs `attach-log --target <agent-id>`, **Then** the row transitions to `status=active`, offsets reset to `(byte_offset=0, line_offset=0, last_event_offset=0)`, `file_inode` is updated to `N2` and `file_size_seen` to the current size, one `log_rotation_detected` lifecycle event is emitted, and one `log_attachment_change` audit row is appended with `prior_status=stale, new_status=active`.

---

### User Story 7 - Operator-explicit detach (Priority: P3)

An operator runs `agenttower detach-log --target <agent-id>`. The daemon stops piping pane output to the host log by issuing `tmux pipe-pane -t <pane>` (no command) via `docker exec`, transitions the existing `log_attachments` row from `status=active` to `status=detached`, retains the `log_offsets` row byte-for-byte, and appends one `log_attachment_change` audit row. A subsequent `attach-log` against the same agent reuses the same `log_attachments` row, transitions it back to `status=active`, retains the offsets, and re-engages `pipe-pane` (mirrors the `stale → active` recovery path in FR-021). Detach is operator intent only — the daemon MUST NOT auto-detach in FEAT-007 (e.g., on agent deactivation, container restart, or pane drift; those paths use `stale`, not `detached`).

**Why this priority**: P3 — symmetry with attach for clean operator tear-down, but not required for the FEAT-008/009/010 critical path. Without it, the closed-set status value `detached` has no transition path. Including the explicit command (rather than overloading `stale` or `superseded`) preserves the semantic distinction: `stale` is reactive drift, `superseded` is path rotation, `detached` is intentional cessation.

**Independent Test**: Can be fully tested by attaching a log, advancing the offset to `(byte_offset=4096, line_offset=137)` via a test seam, running `detach-log --target <id>`, and asserting (a) the CLI exits `0`, (b) the fake `docker exec` received `tmux pipe-pane -t <pane>` (no command), (c) the `log_attachments` row is in `status=detached` with `last_status_at` advanced, (d) the `log_offsets` row is unchanged at `(4096, 137)`, (e) exactly one `log_attachment_change` audit row was appended with `prior_status=active, new_status=detached`. Then run `attach-log --target <id>` and assert the same row transitions back to `status=active`, the offset remains `(4096, 137)`, and a second `log_attachment_change` row is appended with `prior_status=detached, new_status=active`.

**Acceptance Scenarios**:

1. **Given** an attached agent on pane `%17` with `log_offsets=(byte_offset=4096, line_offset=137)`, **When** the operator runs `agenttower detach-log --target <agent-id>`, **Then** the CLI exits `0`, the daemon issues `tmux pipe-pane -t %17` (no command) via `docker exec`, the `log_attachments` row is updated to `status=detached`, the `log_offsets` row is unchanged, and one `log_attachment_change` audit row is appended with `prior_status=active, new_status=detached`.
2. **Given** an agent with a `log_attachments` row in `status=detached` and `log_offsets=(byte_offset=4096, line_offset=137)`, **When** the operator runs `agenttower attach-log --target <agent-id>`, **Then** the CLI exits `0`, the existing row transitions to `status=active` (no new row), the offsets remain `(4096, 137)`, `pipe-pane` is re-engaged at the same canonical path, and one `log_attachment_change` audit row is appended with `prior_status=detached, new_status=active`.
3. **Given** an agent with no `log_attachments` row OR whose attachment is in `status ∈ {stale, superseded, detached}`, **When** the operator runs `detach-log --target <agent-id>`, **Then** the CLI exits `3` with closed-set `attachment_not_found` (for missing rows or non-`active` rows), no daemon state mutates, and no `docker exec` is issued.
4. **Given** the daemon has marked an agent `active=0` (FEAT-006), **When** time passes without operator action, **Then** the agent's `log_attachments` row remains in its prior status (typically `active`); no implicit `detached` transition occurs.

---

### Edge Cases

- **Caller is on the host shell, not inside a bench container.** `attach-log` MUST refuse with closed-set `host_context_unsupported` (consistent with FEAT-006 register-self), unless `--target <agent-id>` was explicitly supplied — host-side targeting is supported because the operator is acting on a registered agent rather than themselves.
- **Caller's `$TMUX` / `$TMUX_PANE` is unset and `--target` was omitted.** Refuse with closed-set `not_in_tmux` and instruct the operator to either supply `--target` from the host or run from inside the agent's pane.
- **Target agent is unknown.** Refuse with `agent_not_found`. Same shape as FEAT-006.
- **Target agent is `active=0`.** Refuse with `agent_inactive`. The bound pane is not reachable through `docker exec` reliably and any pipe-pane attempt would either fail or attach to a stale tmux session.
- **Bound container is `active=0`** (FEAT-003 marked the container inactive between scans). Refuse with `agent_inactive` (the container is the operative ground truth — without it, every other check is moot).
- **Bound pane is unknown to FEAT-004.** Refuse with `pane_unknown_to_daemon`. Trigger one focused FEAT-004 rescan scoped to the agent's container (FEAT-006 FR-041) before declaring the pane unknown.
- **Operator supplies an explicit `--log <path>` that is not under any host bind-mounted path.** Refuse with `log_path_not_host_visible`. The daemon proves visibility by inspecting the container's `Mounts` JSON (FEAT-003 already persists this) and verifying the supplied path's prefix matches a documented bind mount whose host side resolves on the host's filesystem. No fallback to in-container relay (out of scope, FR-011).
- **Operator supplies an explicit `--log <path>` that is a directory, a symlink that escapes the canonical root, contains `..` segments, contains NUL bytes, or exceeds `4096` chars.** Refuse with `log_path_invalid` (matches FEAT-006 `project_path_invalid` shape).
- **Operator supplies an explicit `--log <path>` that another agent already owns.** Refuse with `log_path_in_use` and surface the conflicting `agent_id` in the error message (no silent overwrite).
- **`tmux pipe-pane` returns non-zero or its stderr contains the documented "no current target" / "session not found" / "pane not found" patterns.** Refuse with `pipe_pane_failed` and include a sanitized excerpt of stderr in the message (FEAT-006 sanitization applies). Roll back any attachment row that may have been partially written. The pane composite key in the error message MUST match the FEAT-004 short form.
- **`tmux` is not installed inside the bench container** (FEAT-003 may report this via container scan). Refuse with `tmux_unavailable`. No `docker exec` is issued.
- **`docker exec` itself fails** (container died between FEAT-003 scan and the attach call, daemon socket unreachable, etc.). Refuse with `internal_error` carrying a sanitized cause. The `log_attachments` row is NOT created.
- **Attachment row already exists with `status=active` to the same path** (idempotent re-attach). Daemon issues a fresh `pipe-pane` invocation defensively (in case tmux toggled it off externally) and returns success without creating a duplicate row, without resetting offsets, and without appending an audit row.
- **Attachment row already exists with `status=active` but to a different path** (path change). See User Story 1 acceptance scenario 4 — supersede the prior row.
- **Concurrent `attach-log` calls for the same agent.** Serialize through the FEAT-006 per-agent_id mutex (`agent_locks`); the second call observes the first call's writes inside `BEGIN IMMEDIATE`. No partial state.
- **Concurrent `attach-log` calls for different agents whose log paths happen to collide** (operator chose the same explicit `--log` for two agents). The first call wins; the second hits `log_path_in_use`. The mutex is per-`log_path` for this check (separate from the per-agent_id mutex).
- **`pipe-pane` is already running on the pane piping to a non-AgentTower path** (a user manually invoked it). Detect via the `tmux list-panes -F "#{pane_pipe}"` field. AgentTower toggles it off (`tmux pipe-pane -t <pane>` with no command) and re-engages with the AgentTower path. The prior pipe target is recorded in the audit row as `prior_pipe_target` for forensics.
- **Daemon crashes mid-attach** (between `tmux pipe-pane` returning success and the SQLite COMMIT). On restart, the daemon performs a reconciliation pass: each pane observed with `pipe_pane=1` whose target matches an AgentTower-canonical path but has no corresponding `log_attachments` row is logged as an orphan via lifecycle event `log_attachment_orphan_detected`, NOT auto-attached (operator action required to avoid silently re-binding under unknown conditions).
- **The host log directory `~/.local/state/opensoft/agenttower/logs/<container>/` does not exist.** The daemon creates it with `mode 0700` and verifies the resulting mode before proceeding. Same hardening as FEAT-001 events writer.
- **Forward-compat: a stale CLI calls `attach_log` against a newer daemon.** Mirror FEAT-006's behavior — the CLI sends `schema_version` in the request envelope; the daemon refuses with `schema_version_newer` if the daemon's schema is newer than what the CLI advertises.
- **Wire envelope contains an unknown key.** Refuse with `bad_request` listing the offending keys (matches FEAT-006 register_agent gate).
- **Operator runs `detach-log` against an agent with no attachment, or whose attachment is in `status ∈ {stale, superseded, detached}`.** Refuse with closed-set `attachment_not_found`. No state mutates; no `docker exec` is issued.
- **Operator runs `detach-log` against an agent that is `active=0`, whose pane is `active=0`, or whose container is `active=0`.** Refuse with the same closed-set codes attach-log uses (`agent_inactive`, `pane_unknown_to_daemon`, `agent_inactive` respectively) — detach requires the same liveness gates as attach so the `tmux pipe-pane` toggle-off can be issued reliably. The operator can re-attempt after the agent reactivates, or wait for FEAT-004 reconciliation to flip the row to `stale` (which is the system's reactive equivalent of detach for unreachable panes).
- **Daemon crashes mid-detach** (between `tmux pipe-pane` toggle-off returning success and the SQLite COMMIT). On restart, FEAT-004 reconciliation observes the pane with `pane_pipe=0` and flips the row to `status=stale` via FR-042 (the orphaned operator intent surfaces as drift, recoverable by re-running `attach-log` or `detach-log`).
- **`attach-log --status` against an agent with no `log_attachments` row.** Succeeds (exit `0`); response is `{attachment: null, offset: null}`. No closed-set rejection — `--status` is a universal read-only inspection.
- **`attach-log --preview <N>` against a `superseded` most-recent row, or against an agent with no row at all.** Refuse with closed-set `attachment_not_found`. The operator is expected to look at the agent's currently-active path (which may be a different row chain).
- **`attach-log --preview <N>` against a row in `active`/`stale`/`detached` whose host log file does not exist** (deleted, mount unmounted, file rotated by an external process between attach and preview). Refuse with closed-set `log_file_missing`. The attachment row is NOT mutated by the preview call (status changes for missing files happen via the FEAT-008 reader cycle per FR-026, not via `--preview`).
- **Operator supplies an explicit `--log <path>` containing a SYMLINK whose target escapes the canonical mount root** (FR-050). Refuse with `log_path_not_host_visible` after the realpath check; zero side effects.
- **Operator supplies an explicit `--log <path>` containing shell metacharacters** (`;`, `&&`, `$(...)`, backticks, embedded `\n`/`\r`/`\t`/0x7F) (FR-051). Refuse with `log_path_invalid` before any FR-007 host-visibility check; zero side effects.
- **Operator supplies an explicit `--log <path>` that points at a daemon-owned file** (`agenttower.sqlite3`, `events.jsonl`, `agenttowerd.sock`, `agenttowerd.lock`, `agenttowerd.pid`, or anywhere under `~/.config/opensoft/` / `~/.cache/opensoft/`) (FR-052). Refuse with `log_path_invalid` and an actionable message naming the matched daemon-owned root.
- **Operator supplies an explicit `--log <path>` that resolves under `/proc/`, `/sys/`, `/dev/`, or `/run/`** (FR-053). Refuse with `log_path_invalid` and an actionable message.
- **Pre-existing pane pipe target trickery**: an in-container process runs `tmux pipe-pane -o 'cat >> /tmp/innocent.log; cat >> ~/.local/state/opensoft/agenttower/logs/<container_id>/<agent_id>.log'` to embed the canonical path as a substring (FR-054). The daemon's strict-equality match treats this as a foreign target (NOT canonical), toggles it off (recording the full prior target in the audit row's `prior_pipe_target`, sanitized + bounded per FR-062), and re-engages with the daemon-canonical path.
- **`tmux list-panes` succeeds in FR-011 inspection but `tmux pipe-pane` fails moments later because the pane was killed** (FR-055). Refuse with `pipe_pane_failed`; no `log_attachments` row written; no toggle-off issued.
- **Chained or cyclic bind mounts in `containers.mounts_json`** (FR-056). Refuse with `log_path_not_host_visible` after the FR-056 max-depth check (≤ 8 hops); zero side effects.
- **`containers.mounts_json` contains > 256 mount entries** (FR-063). Refuse the attach with `log_path_not_host_visible`; emit one `mounts_json_oversized` lifecycle event carrying the observed count.
- **SO_PEERCRED returns a uid not equal to the daemon's effective uid** (FR-058). Daemon closes the connection immediately, emits one `socket_peer_uid_mismatch` lifecycle event, and processes no requests from that connection. Defense-in-depth against a hypothetical kernel boundary violation; the FEAT-002 `0600` socket-file mode is the primary control.
- **A line of pane output exceeds 64 KiB** (FR-064). On `--preview`, the daemon truncates at the byte boundary with a `…` marker before passing the line to redaction; the on-disk log file content is unchanged.
- **An external process modifies the host log file out-of-band** (NT3, FR-065). The daemon makes no attempt to detect or refuse content tampering — the FEAT-007 contract is observation, not integrity. Redaction at preview time still applies. Operators relying on log integrity must use the underlying filesystem's mechanisms (`chattr +a`, immutable parents, etc.).

## Requirements *(mandatory)*

### Functional Requirements

#### Identity and registration anchor

- **FR-001**: The `attach_log` daemon method MUST require an `agent_id` parameter that resolves to a row in the FEAT-006 `agents` table; anonymous panes MUST NOT be attachable. Closed-set rejection: `agent_not_found`.
- **FR-002**: The target agent MUST be `active=1`. Closed-set rejection: `agent_inactive`.
- **FR-003**: The bound pane (the FEAT-004 composite key denormalized into the agent row) MUST be present in the `panes` table with `active=1`. Closed-set rejection: `pane_unknown_to_daemon`. Before declaring `pane_unknown_to_daemon`, the daemon MUST trigger exactly one focused FEAT-004 rescan scoped to the agent's container (mirrors FEAT-006 FR-041).
- **FR-004**: The bound container (`agents.container_id`) MUST resolve to a `containers` row with `active=1`. Closed-set rejection: `agent_inactive` (the container is treated as the agent's life signal — same boundary as FEAT-006 master promotion).

#### Log path generation and host-visibility

- **FR-005**: When `--log <path>` is omitted, the daemon MUST generate the canonical host-visible path `~/.local/state/opensoft/agenttower/logs/<container_id>/<agent_id>.log`, where `<container_id>` is the FULL 64-char container id (not the short form, to avoid collisions across renames) and `<agent_id>` is the FEAT-006 `agt_<12-hex-lowercase>` form. The literal prefix `~/.local/state/opensoft/agenttower/logs/` (host-side, after `~` is expanded to the daemon user's home directory) is the SINGLE AUTHORITATIVE constant referenced by FR-011 (canonical-target match in pre-attach pipe-state inspection), FR-043 (orphan detection on startup), FR-052 (daemon-owned-path rejection), and FR-054 (strict canonical-target match). All four of those FRs MUST resolve the same constant from a single named source in code; ad-hoc duplication across modules is forbidden.
- **FR-006**: When `--log <path>` is supplied, the daemon MUST validate it against the same shape rules as FEAT-006 `project_path` (absolute, no `..` segment, no NUL byte, ≤ 4096 chars, no C0 control bytes after stripping). Closed-set rejection: `log_path_invalid`.
- **FR-007**: For every supplied or generated log path, the daemon MUST prove the path is HOST-VISIBLE before issuing any `docker exec`. Host-visibility means: there exists a bind mount in the bound container's `Mounts` JSON (FEAT-003 already persists this in `containers.mounts_json`) such that the supplied path lies under the mount's container-side prefix AND the corresponding host-side path resolves on the host filesystem. Closed-set rejection when proof fails: `log_path_not_host_visible`. The daemon MUST NOT fall back to an in-container relay; that path is explicitly out of scope (deferred to a later feature).
- **FR-008**: If the canonical host-side directory `~/.local/state/opensoft/agenttower/logs/<container_id>/` does not exist, the daemon MUST create it with `mode 0700` and verify the resulting mode before proceeding. The log file itself MUST be created with `mode 0600` if absent. The daemon MUST NOT broaden either mode if the directory or file already exists.
- **FR-009**: When the supplied log path is a host-side path that is already owned by a different `(agent_id)` in `log_attachments` with `status=active`, the daemon MUST refuse with closed-set `log_path_in_use` and surface the conflicting `agent_id` in the actionable message.

#### `pipe-pane` attachment mechanics

- **FR-010**: The daemon MUST attach the log via `docker exec -u <container_user> <container_id> sh -lc 'tmux pipe-pane -o -t <pane> "cat >> <log_file>"'`, where `<container_user>` is the FEAT-003 / FEAT-004 detected bench user, `<pane>` is the FEAT-004 short pane form `<session>:<window>.<pane>`, and `<log_file>` is the container-side path that maps to the proven host-visible path (per FR-007).
- **FR-011**: Before issuing the `tmux pipe-pane` command, the daemon MUST inspect the pane's existing pipe state via `tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}' -t <pane>`. If `pane_pipe=1` AND the pipe command already targets the AgentTower-canonical path, the attachment is treated as already-active (no new `pipe-pane` issued). If `pane_pipe=1` AND the pipe targets a non-AgentTower path, the daemon MUST first toggle the existing pipe off (`tmux pipe-pane -t <pane>` with no command) and record the prior target in the audit row's `prior_pipe_target` field.
- **FR-012**: A non-zero exit from `docker exec` or `tmux pipe-pane`, or any tmux stderr matching the documented patterns (`session not found`, `pane not found`, `no current target`), MUST surface as closed-set `pipe_pane_failed`. The message MUST include a sanitized excerpt of stderr (FEAT-006 sanitization rules: NUL strip, ≤ 2048 chars, no control bytes). No `log_attachments` row MUST be persisted on failure.
- **FR-013**: If `tmux` is not installed in the bound container (FEAT-003 surfaces this in the container scan; the daemon caches it on the `containers` row), the daemon MUST refuse with closed-set `tmux_unavailable` without issuing any `docker exec`.

#### Durable state — entities and persistence

- **FR-014**: The daemon MUST persist a `log_attachments` row per attachment with the fields documented in §Key Entities. The composite uniqueness key is `(agent_id, log_path)`; a second row may exist for the same agent on a different path only when the prior row has `status ∈ {superseded, stale, detached}`.
- **FR-015**: The daemon MUST persist a `log_offsets` row keyed by `(agent_id, log_path)` carrying `byte_offset`, `line_offset`, `last_event_offset`, `last_output_at`, `file_inode`, `file_size_seen`. Initial values on creation: `(byte_offset=0, line_offset=0, last_event_offset=0, last_output_at=NULL, file_inode=NULL, file_size_seen=0)`. The daemon MUST NOT pre-populate `file_inode` or `file_size_seen` at attach time — they are populated by the first FEAT-008 reader cycle.
- **FR-016**: Both `log_attachments` and `log_offsets` writes MUST be performed inside a single `BEGIN IMMEDIATE` SQLite transaction. The daemon MUST atomically write both rows (or neither) so a successful `tmux pipe-pane` is never observable without its corresponding offset row.
- **FR-017**: Offsets MUST persist across daemon restart. On graceful shutdown the daemon MUST issue a final `COMMIT` and ensure SQLite WAL is checkpointed; on crash, SQLite WAL recovery MUST yield the last committed `(byte_offset, line_offset)` for every `log_offsets` row.

#### Idempotency and re-attach semantics

- **FR-018**: Re-attach with the same `(agent_id, log_path)` and `status=active` MUST be a no-op success: no duplicate `log_attachments` row, no offset reset, no audit row, idempotent `pipe-pane` re-issue (defensively, in case tmux toggled it off externally between calls).
- **FR-019**: Re-attach for the same `agent_id` to a different `log_path` MUST mark the prior `log_attachments` row `status=superseded` with `superseded_at` and `superseded_by=<new attachment_id>`, REGARDLESS of the prior row's status — `active`, `stale`, and `detached` are all valid prior statuses for a path-change supersede. Same-path recovery (FR-021 / FR-021d) is the only path that reuses an existing row; any change to `log_path` always allocates a fresh row. The daemon MUST create a new `log_attachments` row at the new path with `status=active`, create a fresh `log_offsets` row at `(0, 0)` for the new path, and re-engage `pipe-pane` at the new path. The prior path's `pipe-pane` MUST be toggled off via `tmux pipe-pane -t <pane>` (no command) only when the prior row was `status=active` (when the prior row was `stale` or `detached`, no live pipe exists to toggle — skip the toggle-off and proceed directly to engaging at the new path). Exactly one `log_attachment_change` audit row MUST be appended carrying `prior_status ∈ {active, stale, detached}`, `new_status=active`, `prior_path`, and `new_path`.
- **FR-020**: Re-attach after pane reactivation (FEAT-006 FR-008: the bound pane composite key transitions from `agents.active=0` back to `agents.active=1` because FEAT-004 re-observed it active) MUST reuse the existing `log_attachments` row, retain the existing offset, and re-engage `pipe-pane` against the now-live pane. The attachment row's `status` transitions: `stale → active` (if it was previously stale) or remains `active` (if FEAT-004 only briefly inactivated the pane and the attachment had not yet been marked stale).
- **FR-021**: If at re-attach time a `log_attachments` row for the same `(agent_id, log_path)` exists with `status=stale`, the daemon MUST NOT create a new row; it MUST update the existing row to `status=active` and append a `log_attachment_change` audit row reflecting the recovery. Offset retention follows the file-consistency check from FR-024 / FR-025, applied at re-attach time: if the file at `log_path` exists AND `file_inode` matches the stored value AND `current_file_size ≥ file_size_seen`, the offset is RETAINED byte-for-byte (pane-drift recovery case — the file is intact and the reader can resume at `byte_offset`). Otherwise, offsets RESET to `(byte_offset=0, line_offset=0, last_event_offset=0)`, `file_inode` and `file_size_seen` are updated to the current observed values, and one `log_rotation_detected` lifecycle event is emitted (file-missing or file-rotated recovery case — the file is treated as a fresh stream). Both cases append the `log_attachment_change` audit row; the lifecycle event is in addition.

#### Detach mechanics

- **FR-021a**: `agenttower detach-log --target <agent-id> [--json]` MUST be operator intent only. The daemon MUST NOT initiate a `detached` transition for any reason in FEAT-007 (no auto-detach on agent deactivation, container restart, pane drift, or any other lifecycle event — those paths use `stale`, not `detached`).
- **FR-021b**: `detach-log` is valid only when the agent has a `log_attachments` row in `status=active`. Calling against an agent with no row, or whose row is in `status ∈ {superseded, stale, detached}`, MUST refuse with closed-set `attachment_not_found`. The daemon MUST NOT mutate state on this rejection and MUST NOT issue `docker exec`.
- **FR-021c**: On a valid `detach-log`, the daemon MUST issue `tmux pipe-pane -t <pane>` (no command) via `docker exec` to stop the running pipe, transition the existing `log_attachments` row from `status=active` to `status=detached` (advance `last_status_at`), retain the `log_offsets` row byte-for-byte (no reset of `byte_offset`, `line_offset`, `last_event_offset`, `file_inode`, or `file_size_seen`), and append exactly one `log_attachment_change` audit row carrying `prior_status=active, new_status=detached`. All SQLite writes MUST occur inside a single `BEGIN IMMEDIATE` transaction.
- **FR-021d**: If at `attach-log` time a `log_attachments` row for the same `(agent_id, log_path)` exists with `status=detached`, the daemon MUST NOT create a new row; it MUST update the existing row to `status=active`, retain the existing `log_offsets` row byte-for-byte, re-engage `pipe-pane`, and append exactly one `log_attachment_change` audit row reflecting the recovery (`prior_status=detached, new_status=active`). This mirrors FR-021's stale-recovery contract.
- **FR-021e**: `detach-log` MUST share the same liveness preconditions as `attach-log` (FR-001 through FR-004). Failures use the same closed-set codes (`agent_not_found`, `agent_inactive`, `pane_unknown_to_daemon`). Concurrent `detach-log` calls for the same `agent_id` MUST be serialized through the FEAT-006 `agent_locks` mutex (same registry as `attach-log` per FR-040).

#### Offset semantics

- **FR-022**: Offsets are BYTE-based against the host-side log file. `line_offset` is the count of `\n` bytes observed strictly before `byte_offset`; readers MUST NOT use `line_offset` as an authoritative position (it is a derived view kept consistent with `byte_offset`).
- **FR-023**: Offsets advance ONLY when a future FEAT-008 reader explicitly consumes bytes. `attach-log` itself MUST NOT advance offsets. FEAT-007 ships the schema and the persistence guarantee; the reader is FEAT-008.
- **FR-024**: The daemon MUST detect file truncation by observing `current_file_size < file_size_seen` and reset `(byte_offset=0, line_offset=0)` while preserving `file_inode`. One `log_rotation_detected` lifecycle event MUST be emitted carrying `prior_size`, `new_size`, `inode`.
- **FR-025**: The daemon MUST detect file recreation (rotation, `mv` + new file) by observing a changed `file_inode` (or `(device, inode)` pair on systems that distinguish) and reset `(byte_offset=0, line_offset=0)` while updating `file_inode` and `file_size_seen`. One `log_rotation_detected` lifecycle event MUST be emitted carrying `prior_inode`, `new_inode`.
- **FR-026**: When the host-side file does not exist on the next reader cycle (was deleted and not recreated), the daemon MUST mark the attachment `status=stale` and emit one `log_file_missing` lifecycle event. Offsets MUST NOT be reset until the file is recreated AND a successful re-attach has occurred. When the file LATER reappears at `log_path` (recreated by an external process, mount remounted, backup restored) WITHOUT an operator-initiated `attach-log`, the reader cycle that observes the reappearance MUST emit exactly one `log_file_returned` lifecycle event (carrying `agent_id`, `log_path`, `prior_inode` if previously recorded, `new_inode`, `new_size`). The daemon MUST NOT auto-flip `status=stale → active`, MUST NOT re-engage `pipe-pane`, and MUST NOT mutate offsets — recovery requires the operator to explicitly run `attach-log`, at which point FR-021 applies (the file-consistency check determines whether offsets are retained or reset; the file-missing-then-recreated path always lands in the reset branch because `file_inode` will differ from the stored value or `file_size_seen` will exceed the current size).

#### Redaction utility

- **FR-027**: The daemon MUST ship a redaction utility callable by any operator-facing log preview surface (`attach-log --preview <N>` for the N most recent lines, future FEAT-008 event-excerpt renders). Redaction MUST be a pure function: identical input produces identical output across calls.
- **FR-028**: The redaction utility MUST cover at minimum these closed-set patterns, each replaced by the documented marker. Patterns are applied PER LINE (input is split on `\n` and each line is redacted independently); FEAT-007 MUST NOT perform multi-line buffer matching. Patterns split into two semantic groups:

  *Unanchored token patterns* — match ANYWHERE within a line, with `\b` word-boundary protection on both sides where the boundary is meaningful (between `\w` and `\W` chars). Multiple matches in a single line MUST all be replaced.
  - `\bsk-[A-Za-z0-9]{20,}\b` → `<redacted:openai-key>`
  - `\bgh[ps]_[A-Za-z0-9]{20,}\b` → `<redacted:github-token>`
  - `\bAKIA[A-Z0-9]{16}\b` → `<redacted:aws-access-key>`
  - `\bBearer [A-Za-z0-9_\-\.=]{16,}` (literal `Bearer ` prefix preserved verbatim; only the credential portion is replaced) → `Bearer <redacted:bearer>`

  *Anchored line patterns* — match ONLY when the entire line conforms to the pattern (the `^...$` anchors are semantically meaningful: these patterns target standalone config-dump or `.env`-paste lines, not embedded credentials in mixed log lines).
  - JWT `^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$` (three dotted segments, each base64url-shape, total matched-string length ≥ 32 INCLUDING the two `.` separators) → `<redacted:jwt>`
  - `.env`-shape: `^([A-Z_][A-Z0-9_]*(API_?KEY|TOKEN|SECRET|PASSWORD|AUTH))=(.+)$` → keep the key, replace the value with `<redacted:env-secret>`

  Application order on a single line: unanchored patterns first (each replaced in left-to-right scan order), then anchored patterns evaluated against the post-unanchored line (anchored patterns will only fire if the line — after unanchored substitutions — still matches the entire-line pattern; in practice unanchored and anchored patterns are mutually exclusive on real inputs, so order is observably commutative for documented test fixtures).
- **FR-029**: The redaction utility MUST NOT perform entropy-based heuristics, semantic detection, LLM lookups, remote calls, or multi-line buffer matching. Application is strictly per-line (FR-028); tokens that span a `\n` are not redacted in FEAT-007. The pattern set is deliberately narrow; expansion is a future feature. False negatives are acceptable for MVP; matches on the documented patterns must round-trip identically across runs (no per-call randomness, no locale-dependent regex semantics — the daemon MUST compile patterns with explicit ASCII flag so `\b`, `\w`, `\W` are bytewise-defined).
- **FR-030**: Redaction MUST NOT alter byte offsets in `log_offsets`. The utility consumes raw bytes and produces redacted bytes; advancement of `byte_offset` is unaffected by whether content was redacted on render.

#### CLI surface

- **FR-031**: `agenttower attach-log --target <agent-id> [--log <path>] [--json]`. `--target` is required. `--log` is optional (default = canonical path per FR-005). `--json` emits the standard FEAT-006 envelope `{"ok": true, "result": {...}}`.
- **FR-032**: `agenttower attach-log --target <agent-id> --status [--json]` MUST be a universal read-only inspection: it ALWAYS exits `0` (success) when the agent itself is resolvable via FR-001, regardless of attachment status. The daemon MUST surface the MOST RECENT `log_attachments` row for the agent (highest `last_status_at`, irrespective of `status` value — `active`, `stale`, `detached`, or `superseded`) plus its associated `log_offsets` row. When the agent has NO `log_attachments` row at all, the response MUST be `{attachment: null, offset: null}` (text-mode prints `attachment=null offset=null`, JSON envelope nests the literal nulls). `--status` MUST NOT issue any `pipe-pane`, any `docker exec`, or any read of the host log file (it touches only SQLite and the FEAT-001 audit log is unchanged). Mirrors FEAT-006 `list-agents` read-only contract.
- **FR-033**: `agenttower attach-log --target <agent-id> --preview <N> [--json]` MUST emit the last `<N>` lines of the resolved host log file, redacted via FR-027 / FR-028. `<N>` MUST be ≥ 1 and ≤ 200 (a hard cap to prevent the daemon from streaming megabytes of log over the socket; preview is for inspection, not bulk read). `--preview` is allowed when the most recent `log_attachments` row for the agent is in `status ∈ {active, stale, detached}` (the host file at the row's `log_path` is still the agent's canonical historical record). For a most-recent row in `status=superseded`, OR when the agent has no `log_attachments` row at all, `--preview` MUST refuse with closed-set `attachment_not_found`. When the selected row exists in an allowed status but the resolved host file at `log_path` does NOT exist (deleted, mount unmounted, etc.), `--preview` MUST refuse with closed-set `log_file_missing`. `--preview` MUST NOT issue any `pipe-pane` or `docker exec`; it reads the host file directly. No state mutates and no audit row is appended on either success or rejection.
- **FR-034**: `agenttower register-self --attach-log` MUST be FAIL-THE-CALL semantics: if the FEAT-007 attach step fails for any reason, the entire `register-self` transaction rolls back atomically — no `agents` row created, no FEAT-006 audit row appended, no `log_attachments` row created, no `log_offsets` row created. The CLI surfaces the FEAT-007 failure code as the top-level error.
- **FR-035**: When `register-self --attach-log` succeeds, the daemon MUST commit the FEAT-006 agent row + FEAT-007 attachment + FEAT-007 offset row in a single `BEGIN IMMEDIATE` transaction; the FEAT-006 `agent_role_change` audit row MUST be appended FIRST, the FEAT-007 `log_attachment_change` audit row SECOND (deterministic ordering for downstream consumers).
- **FR-036**: `agenttower attach-log` MUST follow the FEAT-006 CLI exit-code surface: `0` on success, `1` on `host_context_unsupported`, `2` on `daemon_unavailable`, `3` on every other closed-set code, `4` reserved for internal CLI errors.
- **FR-037**: `agenttower attach-log` text-mode output is one `key=value` line per field on stdout; `--json` mode is one envelope object on stdout with stderr empty (FEAT-006 `--json` purity contract).
- **FR-037a**: `agenttower detach-log --target <agent-id> [--json]`. `--target` is required. No `--log` flag (the attached path is read from the existing `log_attachments` row; operator does not re-supply it). Exit-code surface, text-mode output shape, and `--json` envelope all follow the same contract as `attach-log` (FR-036, FR-037).

#### Failure surface

- **FR-038**: The closed-set error codes the daemon MAY raise from `attach_log`, `detach_log`, `attach_log_status`, `attach_log_preview` (and `register_agent` when `--attach-log` is in flight) are: `agent_not_found`, `agent_inactive`, `pane_unknown_to_daemon`, `log_path_invalid`, `log_path_not_host_visible`, `log_path_in_use`, `pipe_pane_failed`, `tmux_unavailable`, `attachment_not_found`, `log_file_missing`, `bad_request`, `value_out_of_set`, `internal_error`, `schema_version_newer`. The CLI-side may additionally classify `daemon_unavailable`, `not_in_tmux`, `host_context_unsupported`, `container_unresolved`, `tmux_pane_malformed` (inherited from FEAT-005 / FEAT-006 client resolution). Every code in this set MUST appear in the daemon-side `socket_api/errors.py:CLOSED_CODE_SET`. `attachment_not_found` is raised by `detach_log` (FR-021b) and `attach_log_preview` (FR-033). `log_file_missing` is raised by `attach_log_preview` (FR-033) when the resolved host file is absent; the same identifier is reused as a lifecycle event TYPE for the FEAT-008 reader's drift signal (FR-046) — the dual usage is intentional, the surfaces are distinct (synchronous CLI rejection vs. asynchronous observability event).
- **FR-039**: The wire envelope MUST reject unknown keys with `bad_request` (mirrors FEAT-006 `register_agent` gate). The closed allowed-keys set for `attach_log` is `{schema_version, agent_id, log_path, source}` where `source ∈ {explicit, register_self}` is daemon-internal-only and rejected at the wire (clients cannot supply it; the daemon sets it based on call site). The closed allowed-keys set for `detach_log` is `{schema_version, agent_id}` — no `log_path` (the daemon resolves it from the existing `active` row) and no `source` (only `explicit` is valid for detach in FEAT-007). The closed allowed-keys set for `attach_log_status` is `{schema_version, agent_id}`. The closed allowed-keys set for `attach_log_preview` is `{schema_version, agent_id, lines}` where `lines` is the integer 1 ≤ N ≤ 200 (FR-033).

#### Concurrency and cross-subsystem ordering

- **FR-040**: Concurrent `attach_log` calls for the same `agent_id` MUST be serialized through a per-`agent_id` mutex. Reuse the FEAT-006 `agent_locks` registry — adding a new mutex registry for FEAT-007 alone would force every set-* / attach-log path to acquire two locks, increasing deadlock surface. The same lock that serializes set-role / set-label / set-capability also serializes attach-log.
- **FR-041**: Concurrent `attach_log` calls for DIFFERENT agents whose explicit `--log` paths COLLIDE (operator chose the same path) MUST be serialized through a per-`log_path` mutex. The first call wins; the second observes the first call's `log_attachments` row inside `BEGIN IMMEDIATE` and refuses with `log_path_in_use`. This adds a new mutex registry `log_path_locks`.
- **FR-042**: Cross-subsystem ordering with FEAT-004 pane reconciliation MUST follow the FEAT-006 pattern — SQLite `BEGIN IMMEDIATE` provides the writer-serialization barrier; FEAT-004's `_commit_scan` does NOT acquire FEAT-007 mutexes. The stale-attachment detection (FR-021 transition `active → stale`) MUST happen INSIDE the FEAT-004 reconcile transaction so a concurrent `attach_log` can never commit a fresh `active` row that is immediately invalidated. When two concurrent SQLite writers both contend for the writer lock, the daemon MUST surface `SQLITE_BUSY` as closed-set `internal_error` (with a sanitized cause) and MUST NOT retry inside the FEAT-007 method; the operator-facing CLI MUST exit `3` and the caller may retry. Defense-in-depth boundary: the daemon never silently swallows a `SQLITE_BUSY` (it surfaces every contention failure).
- **FR-043**: The daemon MUST recover from crash mid-attach (between `tmux pipe-pane` returning success and the `COMMIT`). On startup, every pane observed with `pane_pipe=1` whose target matches an AgentTower-canonical path but has no corresponding `log_attachments` row MUST be recorded via lifecycle event `log_attachment_orphan_detected`. The daemon MUST NOT auto-attach orphans (operator action required to avoid silently re-binding under unknown conditions); the orphan event surfaces enough context (`container_id`, pane composite key, observed pipe target) for the operator to run `attach-log` deliberately.

#### Audit

- **FR-044**: Every `log_attachments` status transition MUST append exactly one JSONL audit row using the FEAT-001 `events.writer.append_event` helper, including `active → detached` (FR-021c) and `detached → active` (FR-021d). The on-disk shape mirrors FEAT-006: `{"ts": <utc-iso>, "type": "log_attachment_change", "payload": {...}}`. The payload carries `attachment_id`, `agent_id`, `prior_status`, `new_status`, `prior_path` (nullable), `new_path`, `prior_pipe_target` (nullable, for non-AgentTower toggle-off cases), `source ∈ {explicit, register_self}`, `socket_peer_uid` (FEAT-006 SO_PEERCRED).
- **FR-045**: No-op writes (idempotent re-attach per FR-018) MUST NOT append an audit row. Failed attaches MUST NOT append an audit row. The audit log captures actual state transitions only.
- **FR-046**: `log_rotation_detected`, `log_file_missing`, `log_file_returned`, `log_attachment_orphan_detected`, `mounts_json_oversized` (FR-063), `socket_peer_uid_mismatch` (FR-058) are LIFECYCLE events emitted via the daemon's lifecycle logger (same surface FEAT-006 uses for `audit_append_failed`), NOT JSONL audit rows. Rationale: they are observability signals about the daemon's view of external state, not state transitions on the agent record. `log_file_returned` is fired exactly once per stale-row reappearance event (when a reader cycle observes a file at `log_path` whose row is in `status=stale`); subsequent reader cycles MUST NOT re-fire the event for the same `(agent_id, log_path, file_inode)` triple — the daemon tracks "last reported reappearance inode" per row to suppress repeat firings. Suppression and rate-limit rules for the other lifecycle events are specified in FR-061; payload size bounds in FR-062.

#### Hardening (security-derived)

Every FR in this subsection is anchored in the §"Threat Model & Trust
Boundaries" section above. Each FR cites the adversary class (A1–A5)
and/or trust boundary (TB1–TB5, NT1–NT5) it addresses. These FRs are
binding requirements; an implementation that satisfies the rest of
the spec but drops a hardening FR has a security defect.

- **FR-047** (anchors A2; CHK061): The `tmux pipe-pane` shell command
  the daemon constructs in `docker exec` (FR-010, FR-019, FR-021c)
  MUST be built using `shlex.quote` (or an equivalent shell-quoting
  primitive that escapes every shell-meaningful byte) on every
  interpolated value: the host-visible log path, the container-side
  log path, the pane composite-key short form, and any other
  user-controllable string. The `subprocess` invocation MUST use the
  argv list form (no `shell=True` at the outer Python layer); the
  inner `sh -lc` shell is required for the `>>` redirection but
  receives only quoted values. The daemon MUST NOT interpolate raw
  user-supplied bytes into the inner shell command at any point,
  even when those bytes have already passed FR-006 shape validation.
  Defense-in-depth against A2 supplying a path that is shape-valid
  but shell-meaningful (spaces, `$`, backticks, `;`, `&&`).
- **FR-048** (anchors A1; CHK062): When the host log file does not
  yet exist at attach time, the daemon MUST create it via
  `os.open(path, O_CREAT | O_WRONLY | O_EXCL, mode=0o600)` (or an
  equivalent race-free primitive that fails if the path was created
  between the existence check and the open). The daemon MUST NOT
  use `pathlib.Path.touch` or any primitive lacking `O_EXCL`
  semantics. On `O_EXCL` failure (the file was created by a
  concurrent process), the daemon MUST refuse with `internal_error`
  carrying the cause, MUST NOT proceed with `tmux pipe-pane`, and
  MUST roll back the in-flight transaction. Defense against
  TOCTOU races between the FR-008 existence check and creation.
- **FR-049** (anchors A3; CHK063): Every redaction pattern from FR-028
  MUST be compiled with the `re.ASCII` flag set so that `\b`, `\w`,
  and `\W` are bytewise-defined; locale-dependent or Unicode-aware
  semantics are forbidden. Patterns MUST be pre-compiled at module
  load (not per call) and stored as module-level constants.
  Implementations that drop the `re.ASCII` flag fail SC-004's
  determinism requirement. Defense against A3 supplying lines whose
  Unicode-class-membership semantics differ from ASCII bytewise
  matching.
- **FR-050** (anchors A2, NT5; CHK037, CHK064): The host-visibility
  proof (FR-007) MUST resolve the candidate host-side path via
  `os.path.realpath` (or an equivalent symlink-collapsing primitive)
  AND verify that the realpath still lies under the resolved mount
  Source's realpath. A symlink whose target escapes the mount root
  MUST be rejected with `log_path_not_host_visible`. The daemon MUST
  NOT follow symlinks across the mount boundary even if the target
  itself is host-visible under a different mount. Defense against
  A2 supplying a `--log <path>` whose container-side leg is under a
  bind mount but whose host-side resolved path escapes the canonical
  log root.
- **FR-051** (anchors A2; CHK038): The supplied `--log <path>`
  validation (FR-006) MUST also reject any path containing shell-
  meaningful bytes that were not intended for shell construction:
  newline (`\n`), carriage return (`\r`), tab (`\t`) — these are
  separately controlled because they break log-line parsing for
  downstream FEAT-008 readers. NUL (already covered by FR-006), C0
  control bytes 0x01–0x1F (already covered), and DEL 0x7F MUST be
  rejected with `log_path_invalid`. The daemon MUST validate before
  any FR-007 host-visibility check; rejection produces zero side
  effects (zero docker exec, zero rows, zero JSONL).
- **FR-052** (anchors A2; CHK040): The `--log <path>` validation
  MUST reject any path that lies under or equals the daemon's own
  state namespace prefixes: `~/.local/state/opensoft/agenttower/`
  (parent of canonical log root, but other artifacts live there:
  `agenttower.sqlite3`, `events.jsonl`, `agenttowerd.sock`,
  `agenttowerd.lock`, `agenttowerd.pid`), `~/.config/opensoft/`,
  and `~/.cache/opensoft/`. EXCEPT the canonical log subdirectory
  `~/.local/state/opensoft/agenttower/logs/<container_id>/` is
  ALLOWED. Closed-set rejection: `log_path_invalid` with an
  actionable message naming the daemon-owned root that was matched.
  Defense against A2 attempting to overwrite the SQLite DB, the
  audit log, or the daemon socket via attach-log.
- **FR-053** (anchors A2; CHK041): The `--log <path>` validation
  MUST reject any path whose realpath (post-FR-050 resolution) lies
  under a virtual or special filesystem root: `/proc/`, `/sys/`,
  `/dev/`, `/run/`. Closed-set rejection: `log_path_invalid` with
  an actionable message. Defense against A2 attempting to attach a
  pipe to a kernel-virtual file (which would either fail in
  surprising ways or, worse, succeed with side effects on the host).
- **FR-054** (anchors A3, NT4; CHK042): The canonical-target match
  used by FR-011 (pre-attach pipe state inspection) and FR-043
  (orphan detection on startup) MUST be a STRICT EQUALITY check
  against the canonical container-side log path the daemon would
  itself generate, NOT a substring or prefix match. The daemon
  computes the expected canonical container-side path
  `<container_user_home>/.local/state/opensoft/agenttower/logs/<container_id>/<agent_id>.log`
  for the bound agent, and compares the parsed
  `pane_pipe_command` (which has the form `cat >> <path>` after
  shell tokenization) byte-for-byte against the expected
  `cat >> <quoted_canonical_path>`. Trickery via embedded shell
  separators (`;`, `&&`, redirection chains) MUST yield "foreign
  target" classification, not "AgentTower-canonical" classification.
  The parser MUST tokenize the shell command using the same `shlex`
  primitive used in FR-047.
- **FR-055** (anchors A4; CHK048): If `tmux list-panes` (FR-011)
  succeeds but the subsequent `tmux pipe-pane` (FR-010) fails with
  `pane not found`, `session not found`, `no current target`, or
  any non-zero exit, the daemon MUST refuse with `pipe_pane_failed`
  (FR-012), MUST NOT retry the attach within the same call, MUST NOT
  persist any `log_attachments` row, and MUST NOT toggle off any
  pre-existing pipe (the toggle-off in FR-019 / FR-021c only fires
  when supersede or detach has already completed FR-007 and FR-011
  successfully and is committed to the new path). Defense against
  the race window where the pane is observed live in FR-011 and
  killed before FR-010 issues.
- **FR-056** (anchors A2, TB1; CHK050): When the FR-007 host-visibility
  proof resolves a mount whose Source is itself a bind mount onto
  another path (chained mounts), the daemon MUST detect the
  chaining via repeated `os.path.realpath` resolution — if
  `realpath(source)` differs from `source`, the daemon MUST verify
  the entire resolution chain still terminates inside a path the
  daemon can stat with `os.path.isdir(parent)` and `os.access(parent,
  os.W_OK)`. Cyclic mount chains (`A → B → A`) MUST be detected
  via a max-depth bound (≤ 8 hops) and refused with
  `log_path_not_host_visible`. Defense against A2 / TB1 misconfig
  where the operator's compose file constructs a circular mount
  graph.
- **FR-057** (anchors A1; CHK046): The daemon's directory-mode
  verification (FR-008) MUST be performed UNDER the per-`agent_id`
  mutex (FR-040) to prevent a TOCTOU race between
  `verify_dir_mode(parent, 0o700)` and the subsequent file
  creation. Specifically, the sequence (verify dir mode →
  `os.open(file, O_CREAT|O_EXCL, 0o600)`) MUST occur inside a
  single critical section. If the directory's mode changes between
  verification and file creation (unlikely but possible if a
  privileged process intervenes), the FR-048 `O_EXCL` failure
  surfaces as `internal_error` and the transaction rolls back.
- **FR-058** (anchors A2, TB3; CHK044): The daemon MUST verify the
  SO_PEERCRED-derived `socket_peer_uid` matches the daemon's own
  effective uid (`os.geteuid()`) on every accepted connection. If
  the peer uid does not match, the daemon MUST close the connection
  immediately, log a lifecycle event `socket_peer_uid_mismatch`
  (carrying observed uid and expected uid), and MUST NOT process
  any request from that connection. Inherits FEAT-002's `0600`
  socket-file mode invariant; FR-058 is defense-in-depth against
  a kernel boundary violation. The check MUST run before any
  FEAT-007 method dispatch and before any FEAT-006/FEAT-005
  resolution.
- **FR-059** (anchors A2; CHK065): Concurrent `attach_log` /
  `detach_log` calls MUST acquire mutexes in the deterministic order
  AGENT FIRST, THEN LOG_PATH: per-`agent_id` lock from the FEAT-006
  `agent_locks` registry (FR-040), then per-`log_path` lock from
  the FEAT-007 `log_path_locks` registry (FR-041) only when an
  explicit `--log` path is supplied. Reverse-order acquisition is
  forbidden. The daemon MUST enforce the ordering via a single
  helper that takes both keys and acquires in the locked order;
  ad-hoc per-call ordering is not permitted. Defense against
  deadlock when two concurrent calls touch overlapping
  (`agent_id`, `log_path`) pairs.
- **FR-060** (anchors A2, TB5; CHK066): Test seams introduced by
  FEAT-007 (`AGENTTOWER_TEST_LOG_FS_FAKE`; see plan.md R-013) MUST
  be consulted ONLY by the dedicated adapter module
  (`logs/host_fs.py` per the project layout). Production code
  paths MUST NOT branch on the env var or import the seam in any
  other module. The seam MUST be a no-op when the env var is unset
  (production default). Tests asserting this invariant
  (`test_feat007_no_test_seam_in_production.py`) MUST be present.
  Inherits the FEAT-003 `_DOCKER_FAKE` / FEAT-004 `_TMUX_FAKE`
  pattern. Defense against accidental test-only code paths
  reaching production.
- **FR-061** (anchors A1; CHK053): Lifecycle events (FR-046) MUST
  be rate-limited per `(agent_id, log_path)` pair to prevent
  unbounded emission when an external condition flaps. Specifically:
  `log_file_missing` MUST be emitted at most once per
  `(agent_id, log_path)` per stale-state entry (the next emission
  requires the row to first transition out of `stale` and back);
  `log_file_returned` already has the FR-046 `(agent_id, log_path,
  file_inode)` triple suppression; `log_rotation_detected` MUST
  be emitted at most once per actual rotation (changed inode or
  shrunk size relative to last seen); `log_attachment_orphan_detected`
  is emitted at most once per `(container_id, pane_composite_key,
  observed_pipe_target)` triple per daemon lifetime. Defense
  against A1 / external flapping (mount remount loops, file
  rotation loops) generating unbounded daemon logs.
- **FR-062** (anchors A3; CHK052): Every audit-row payload field
  and every lifecycle-event payload field that carries
  externally-sourced bytes MUST be bounded: `prior_pipe_target`
  ≤ 2048 chars (already FR-012 / FR-044 inherited from FEAT-006);
  `pipe_pane_command` stored on `log_attachments` ≤ 4096 chars
  (data-model.md §1.1 already states this); `observed_pipe_target`
  on `log_attachment_orphan_detected` ≤ 2048 chars; lifecycle event
  payload total JSON-serialized size ≤ 4096 bytes. Oversized fields
  MUST be truncated with a `…` marker and a documented
  `truncated=true` sibling field. Defense against A3 emitting
  pathological pipe-command strings via in-container `tmux pipe-pane`
  invocations that the daemon then captures.
- **FR-063** (anchors TB1; CHK054): The FR-007 host-visibility proof
  MUST process at most 256 mount entries per `containers.mounts_json`.
  If the cached JSON exceeds this bound, the daemon MUST refuse the
  attach with `log_path_not_host_visible` (or `internal_error` if
  the FEAT-003 cache is structurally malformed) and emit a
  lifecycle event `mounts_json_oversized` carrying the observed
  count. The per-mount processing budget within the proof is also
  bounded: at most 8 `os.path.realpath` calls per mount, at most
  the FR-056 8-hop chain depth. Defense against TB1 violation
  (FEAT-003 cache containing an unreasonably large or
  intentionally-injected mount list).
- **FR-064** (anchors A3; CHK055): The `--preview <N>` host file
  read MUST bound the per-line byte budget at 64 KiB and the total
  read budget at 200 × 64 KiB = 12.8 MiB. Lines exceeding 64 KiB
  MUST be truncated at the byte boundary with a documented `…`
  marker before being passed to the redaction utility. The
  redaction utility itself MUST process each line in O(line_length
  × pattern_count) time with no backtracking-prone patterns;
  patterns containing nested quantifiers or alternation that could
  cause catastrophic backtracking are forbidden — the FR-028
  pattern set has been audited and contains no such constructs.
  Defense against A3 emitting a line with millions of partial
  matches that would DoS the redaction utility.
- **FR-065** (anchors A3, NT3; CHK043): The daemon MUST NOT execute,
  parse-as-code, or use as input to any decision the bytes inside
  the host log file. Specifically, the daemon MUST NOT: (a) source
  the file as a shell script, (b) eval the file as Python, (c) use
  any line of the file to construct a docker/tmux command, (d) use
  any line of the file as a parameter to a daemon method beyond
  the FR-027 redaction render. The file's bytes are operator-
  facing display content only. Defense against A3 writing escape
  sequences, command substitutions, or other adversarial content
  into the pane that would otherwise be captured and possibly
  re-executed by a misbehaving downstream consumer.

### Key Entities

- **`LogAttachment`** (table `log_attachments`): one row per attempt to bind a pane log to an agent.
  - `attachment_id` — synthetic stable id, shape `lat_<12-hex-lowercase>` (mirrors FEAT-006 `agt_<12-hex>` style; 48 bits of entropy, retried under per-`(agent_id, log_path)` mutex).
  - `agent_id` — FK to `agents.agent_id`.
  - Pane composite key, denormalized: `container_id`, `tmux_socket_path`, `tmux_session_name`, `tmux_window_index`, `tmux_pane_index`, `tmux_pane_id`. (Same denormalization rationale as FEAT-006 `agents`.)
  - `log_path` — the host-side path. Unique with `agent_id` when `status=active`.
  - `status` ∈ `{active, superseded, stale, detached}`.
  - `source` ∈ `{explicit, register_self}` — daemon-internal provenance, NOT operator-supplied.
  - `pipe_pane_command` — the literal shell that was issued to `docker exec`, sanitized + bounded; for forensic audit.
  - `attached_at` (ISO-8601 UTC, microsecond precision — matches FEAT-006 timestamp shape).
  - `last_status_at` (ISO-8601 UTC; the last time `status` transitioned).
  - `superseded_at` (nullable; set when `status=superseded`).
  - `superseded_by` (nullable; FK to a later `log_attachments.attachment_id` when `status=superseded`).
  - `created_at` (ISO-8601 UTC).

- **`LogOffset`** (table `log_offsets`): one row per attached `(agent_id, log_path)` describing the FEAT-008 reader's durable position.
  - `agent_id` — FK to `agents.agent_id`. Composite PK with `log_path`.
  - `log_path` — the host-side path.
  - `byte_offset` — number of bytes the reader has consumed from the start of the current file (or from the most recent rotation/truncation reset).
  - `line_offset` — number of `\n` bytes observed strictly before `byte_offset`. Derived; readers must not use as an authoritative position.
  - `last_event_offset` — byte offset of the most recently classified FEAT-008 event (used so FEAT-008 can resume per-event without rescanning).
  - `last_output_at` — ISO-8601 UTC; the most recent observed `mtime` of the file.
  - `file_inode` — `int64` (or `(device, inode)` pair on systems that distinguish); the inode of the file at the most recent reader cycle. NULL until first observation.
  - `file_size_seen` — `int64`; the file size observed at the most recent reader cycle. Used to detect truncation.
  - `created_at`, `updated_at` (ISO-8601 UTC).

- **Relationship to FEAT-006 `Agent`**: every `LogAttachment` row carries `agent_id` as an FK to `agents.agent_id`; deletion of an agent (not in scope for FEAT-006 / FEAT-007 MVP — agents are soft-marked `active=0`, never hard-deleted) is therefore not a concern. When an agent is reactivated (FEAT-006 FR-008), an existing `log_attachments` row in `status=stale` transitions back to `active` via FR-020 / FR-021; no new row is created.

- **Relationship to FEAT-004 `Pane`**: the pane composite key denormalized into `LogAttachment` allows FEAT-004 reconciliation to detect stale attachments without a JOIN (one read of `panes` per scan cycle). When FEAT-004 marks a pane `active=0`, the cross-subsystem ordering rule (FR-042) flips every `log_attachments` row with that pane key from `active` to `stale` in the same `BEGIN IMMEDIATE` transaction.

- **Relationship to FEAT-001 `events.jsonl`**: status transitions append a `log_attachment_change` row (FR-044). The on-disk JSONL envelope is the existing `{"ts", "type", "payload"}` shape — FEAT-007 reuses the FEAT-001 writer unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An end-to-end `agenttower attach-log --target <agent-id>` invocation against a registered agent succeeds in under **2 seconds** P95 (host daemon + `docker exec` + `tmux pipe-pane` + SQLite COMMIT + audit append) on a developer-class machine; this is the operator's interactive expectation budget.
- **SC-002**: Re-attaching the same `(agent_id, log_path)` an arbitrary number of times produces exactly **one** `log_attachments` row in `status=active` and exactly **one** `log_offsets` row across the entire run, regardless of invocation count. (Tested by running attach-log 100 times in a loop and asserting a single row in each table.)
- **SC-003**: Log offsets recovered from SQLite after a graceful daemon restart are **byte-for-byte identical** to the offsets at shutdown; the same invariant holds across a hard kill (`SIGKILL`) under SQLite's WAL durability.
- **SC-004**: For each of 10 standardized fixture inputs containing the FR-028 pattern set, the redaction utility produces the documented `<redacted:<type>>` marker **100% of the time** across 1,000 invocations (no per-call variance, no flake).
- **SC-005**: An `attach-log` invocation against a path that fails the FR-007 host-visibility proof leaves **zero side effects**: zero `log_attachments` rows, zero `log_offsets` rows, zero `docker exec` invocations issued, zero JSONL audit rows appended. Verified by a fixture that hands the daemon a `Mounts` JSON with no canonical bind-mount.
- **SC-006**: After FEAT-006 pane reactivation (a pane transitions `active=0 → active=1` via FEAT-004 reconciliation), a follow-up `attach-log` on the agent retains `byte_offset` byte-for-byte; tested by advancing offset to 4096 via a test seam, forcing reactivation, and re-attaching.
- **SC-007**: File rotation (rm + recreate, same path, new inode) is detected within **one** offset-recovery cycle (≤ 1 second after the first FEAT-008 reader call following the rotation), the offset is reset to `(0, 0)`, exactly one `log_rotation_detected` lifecycle event fires, and no FEAT-008 reader replays the prior file's content.
- **SC-008**: `register-self --attach-log` is atomic across success and failure paths: on success exactly one `agents` row + one `log_attachments` row + one `log_offsets` row + one `agent_role_change` JSONL row + one `log_attachment_change` JSONL row exist; on failure (any FR-038 closed-set code) zero rows in any of those tables and zero JSONL rows are appended. Verified across the EXPLICITLY ENUMERATED FR-038 codes that can fire from the FEAT-007 attach path inside register-self: `agent_not_found`, `agent_inactive`, `pane_unknown_to_daemon`, `log_path_invalid`, `log_path_not_host_visible`, `log_path_in_use`, `pipe_pane_failed`, `tmux_unavailable`, `bad_request`, `value_out_of_set`, `internal_error`, `schema_version_newer`. The codes `attachment_not_found` and `log_file_missing` are NOT exercised here because they cannot fire from the attach path (they originate from `detach_log` and `attach_log_preview` respectively, neither of which runs under register-self). The atomicity test plan MUST cover one fixture per code in this enumeration, asserting zero rows + zero JSONL audit rows for each.
- **SC-009**: The daemon's stale-attachment detection (FR-042) flips a `log_attachments` row from `active` to `stale` inside the same `BEGIN IMMEDIATE` transaction as the FEAT-004 reconcile that marks the bound pane inactive; observable as a single committed transaction in the SQLite WAL trail (no intermediate read sees `active` after the FEAT-004 inactivation has committed).
- **SC-010**: `attach-log --preview <N>` rendering a fixture log containing every FR-028 pattern produces zero raw secrets in the output across 1,000 runs. The rendered output MUST be grep-asserted against the FULL closed-set sentinel list — for unanchored token patterns: `sk-` (OpenAI key), `ghp_` and `ghs_` (GitHub token), `AKIA` (AWS access key); and for the JWT pattern, the literal three-base64-segment shape `^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$` MUST not appear in any rendered line; for the `.env`-shape pattern, no rendered line MUST match `^([A-Z_][A-Z0-9_]*(API_?KEY|TOKEN|SECRET|PASSWORD|AUTH))=(?!<redacted:env-secret>$)`. A SUCCESSFUL Bearer-token redaction MUST appear as the literal substring `Bearer <redacted:bearer>` (the prefix is preserved verbatim per FR-028); the original credential portion (`[A-Za-z0-9_\-\.=]{16,}` after `Bearer `) MUST NOT appear. Every one of these grep targets MUST be asserted across the 1,000 iterations; partial coverage of "some patterns checked" is insufficient.
- **SC-011**: A `detach-log` → `attach-log` round-trip on the same agent retains `(byte_offset, line_offset, last_event_offset, file_inode, file_size_seen)` byte-for-byte across both transitions, produces exactly **one** `log_attachments` row (no duplicate created on re-attach), and appends exactly **two** `log_attachment_change` audit rows in order: `active → detached`, then `detached → active`. The closed-set value `detached` is never reached by any non-operator code path in FEAT-007 — verified by exercising every other lifecycle event (pane drift, agent deactivation, container restart, file rotation, file truncation, file deletion) against an attached agent and asserting the row's status column is in `{active, stale, superseded}` but never `detached`.
- **SC-012**: Adversarial-input rejection (FR-051, FR-052, FR-053, FR-050) leaves zero side effects — verified by a fixture suite that supplies (a) `--log <path-with-shell-meta>` (every FR-051 metabyte plus `;`, `&&`, `$(...)`, backticks), (b) `--log` pointing at every daemon-owned root (FR-052 list), (c) `--log` resolving under each special-filesystem root (FR-053 list), (d) `--log` whose realpath escapes the canonical mount root via symlink (FR-050), and asserting for each case: zero `log_attachments` row, zero `log_offsets` row, zero `docker exec` invocations, zero JSONL audit rows, zero file-mode mutations on existing host paths.
- **SC-013**: Mutex acquisition order (FR-059) is enforced by code review and a runtime self-check — verified by `test_mutex_acquisition_order.py` that drives concurrent attach calls with overlapping `(agent_id, log_path)` pairs and asserts the daemon never holds `log_path_locks` while NOT holding the corresponding `agent_locks`. A reverse-order acquisition raises `internal_error` from the FR-059 helper.
- **SC-014**: Lifecycle event rate limiting (FR-061) is verified by a fixture that flaps the host file (delete/recreate 100 times in succession) and asserts at most one `log_file_missing` per stale-state entry, at most one `log_file_returned` per `(agent_id, log_path, file_inode)` triple, and at most one `log_rotation_detected` per actual rotation.

## Assumptions

- **Bind-mount provenance is the host-visibility proof.** The daemon proves a log path is host-visible by walking the bound container's `Mounts` JSON (FEAT-003 already persists this) and matching the supplied path against a mount whose host side resolves on the local filesystem. This assumes Docker's reported mounts are accurate; FEAT-003's existing trust boundary is inherited.
- **The canonical bind-mount is the operator's responsibility.** AgentTower does not configure bind mounts. The bench container template is expected to mount `~/.local/state/opensoft/agenttower/logs/<container>` from host to container (or an equivalent root the operator chooses). When the mount is missing, `attach-log` fails with `log_path_not_host_visible` and the operator must fix their compose/run config — there is no fallback.
- **`tmux pipe-pane -o` is the toggle variant.** Issuing it once with a command starts piping; issuing it once without a command stops piping. AgentTower issues the start variant for attach and the stop variant only when superseding to a different path or detected non-AgentTower target.
- **`pane_pipe_command` requires tmux ≥ 3.5 for full FR-011 / FR-054 / FR-043 fidelity.** tmux 3.4 and earlier do NOT expose the `pane_pipe_command` format variable, so the daemon receives `"<flag> "` with an empty command field on those versions. Behavior on tmux 3.4: (a) FR-054 strict-equality match never classifies the pipe as canonical, so the daemon defensively re-issues `pipe-pane -o` on every attach (idempotent — harmless); (b) FR-011 foreign-pipe toggle-off skips because the parser treats empty-command-with-flag-on as inactive; (c) FR-043 orphan recovery cannot extract the agent id from the pipe command and therefore cannot reclaim orphans on tmux 3.4 — operators on that version must clean orphan logs by hand. Production deployments wanting full orphan recovery should pin a tmux 3.5+ image; the FEAT-007 attach / detach / supersede happy paths work on 3.4 and 3.5 alike.
- **`docker exec` runs under `LANG=C.UTF-8` regardless of the container's default locale.** The daemon explicitly passes `-e LANG=C.UTF-8 -e LC_ALL=C.UTF-8` to every `docker exec` it issues for FEAT-004 pane discovery and FEAT-007 pipe-pane operations. Without this pin, tmux 3.4 in a POSIX/C-locale container silently substitutes tab and other "control" characters in `-F` format output with `_`, which surfaces as `output_malformed` from `parse_list_panes` and breaks the entire FEAT-004 / FEAT-007 pipeline. The pin is invisible to the bench user's interactive shell and only affects the daemon's structured calls.
- **`agt_<12-hex>` and `lat_<12-hex>` are independent identifier namespaces.** The `lat_` prefix matches the FEAT-006 spirit (`agt_`) and is used so an attachment id never visually collides with an agent id in operator output.
- **Per-`agent_id` mutex reuse.** FEAT-007 reuses FEAT-006's `agent_locks` mutex registry rather than introducing a new one. The trade-off: an in-flight `set-role` blocks an in-flight `attach-log` for the same agent. This is acceptable because both are operator-initiated mutations and parallel execution adds no value.
- **`register-self --attach-log` semantics are FAIL-THE-CALL, not best-effort.** When the operator opts in to attach-log, they want determinism: either the agent is registered AND the log is attached, or neither. Best-effort would silently land an agent without log capture, breaking the FEAT-008 / FEAT-009 / FEAT-010 contract that every registered agent has a durable observation surface.
- **Forward-compat / closed-set hygiene inherits from FEAT-006.** Every FEAT-007 daemon method runs `_check_schema_version` + `_check_unknown_keys` at the top; every wire shape error raises `bad_request`; every closed-set membership violation raises `value_out_of_set`. No new dispatch infrastructure.
- **Redaction is content-only.** It applies to operator-facing rendering (preview, future event excerpts) — never to the raw `log_path` file. The on-disk log file is the unmodified `pipe-pane` capture; redaction is a render-time transform. This is required so a future operator can grep the raw file for forensics if they have the access to do so.
- **`line_offset` is derived, not authoritative.** Readers MUST trust `byte_offset` for resumption. `line_offset` exists for human-friendly status output (`attach-log --status` rendering "consumed 137 lines / 4096 bytes") and for future tooling that may want to count lines without re-scanning the file.
- **"Byte-for-byte" definition.** Wherever the spec asserts a value is preserved or recovered "byte-for-byte" (FR-021 offset retention, FR-021c offset retention on detach, SC-003 durability, SC-006 reactivation, SC-011 detach round-trip), it means: the integer values stored in SQLite for `byte_offset`, `line_offset`, `last_event_offset`, and `file_size_seen` round-trip via SELECT identically (no truncation, no rounding, no integer-narrowing); the `file_inode` TEXT column round-trips identically (no encoding transformation, no whitespace mutation); and the `last_output_at` TEXT column round-trips identically (microsecond precision preserved, timezone offset preserved). The invariant is testable by a single `SELECT * FROM log_offsets WHERE …` round-trip.
- **Detach is explicit operator intent only.** The closed-set status `detached` is reachable only via `agenttower detach-log`; reactive lifecycle events (pane drift, container restart, file deletion, agent inactivation) use `stale` instead. The semantic distinction is preserved so downstream consumers (FEAT-008 reader, FEAT-009 prompt delivery, FEAT-010 routing) can read `status=detached` as "operator deliberately stopped capture; do not auto-resume" versus `status=stale` as "system detected drift; safe to recover on next attach". Auto-detach is rejected for the same reason `register-self --attach-log` is fail-the-call: when an operator opts in to a transition, they expect to be told whether it happened — and when they didn't opt in, the system MUST NOT silently transition the row.
