# Implementation Plan: Pane Log Attachment and Offset Tracking

**Branch**: `007-log-attachment-offsets` | **Date**: 2026-05-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-log-attachment-offsets/spec.md`

## Summary

Implement AgentTower's pane log capture and read-offset tracking layer:
two new SQLite tables (`log_attachments`, `log_offsets`), four new
daemon socket methods (`attach_log`, `detach_log`,
`attach_log_status`, `attach_log_preview`), four new `agenttower` CLI
subcommand surfaces (`attach-log`, `attach-log --status`,
`attach-log --preview`, `detach-log`), one new `--attach-log` flag on
the existing FEAT-006 `register-self`, JSONL audit appendage on every
successful attachment status transition (event type
`log_attachment_change`), four new lifecycle event types
(`log_rotation_detected`, `log_file_missing`, `log_file_returned`,
`log_attachment_orphan_detected`), a stdlib-only redaction utility for
the FR-028 closed-set secret patterns, and one wiring change in the
FEAT-004 pane reconciliation path that flips `active → stale` for
attachments whose pane went inactive in the same SQLite transaction.
The feature turns a registered FEAT-006 agent into one whose pane
output is durably captured to a host-visible log file via
`tmux pipe-pane -o` issued through `docker exec`, and persists the
read-offset state every future FEAT-008 reader will resume from.

The single highest-stakes property FEAT-007 introduces — that a
log attachment MUST be host-visible before any `docker exec` is
issued (FR-007) — is enforced inside the daemon's attach pipeline:
the daemon walks the bound container's `Mounts` JSON (FEAT-003
already persists this in `containers.mounts_json`), proves the
supplied or generated path lies under a bind mount whose host side
resolves on the local filesystem, and refuses with closed-set
`log_path_not_host_visible` when proof fails — never falling back to
an in-container relay (out of scope, FR-007). The second highest-
stakes property is that `register-self --attach-log` is FAIL-THE-CALL
(FR-034): when the operator opts in to attach-log, either the agent
is registered AND the log is attached AND both audit rows are
appended in the documented order, or NEITHER row is created. Best-
effort behavior is rejected for predictability — an operator who
explicitly opts in expects determinism (Assumptions §
"register-self --attach-log semantics").

The state machine for `log_attachments.status` is closed-set
`{active, superseded, stale, detached}` and every transition is
explicit. Detach is operator-initiated only (Clarifications 2026-05-08
Q1; FR-021a–FR-021e): the daemon MUST NOT auto-detach for any reason
in FEAT-007. Path change always supersedes the prior row regardless of
prior status (Clarifications Q2; FR-019); same-path recovery is the
only path that reuses an existing row. Read-only inspection
(`--status`, `--preview`) is universally safe for `--status` and
selective for `--preview` (Clarifications Q3; FR-032, FR-033) —
`--preview` works against `active`, `stale`, and `detached` rows but
refuses against `superseded` rows or missing rows with
`attachment_not_found`, and refuses with `log_file_missing` when the
selected row's host file is gone. File reappearance after a
`log_file_missing`-induced stale state does NOT auto-recover
(Clarifications Q4; FR-026); the daemon emits one
`log_file_returned` lifecycle event for observability and waits for
operator-initiated `attach-log` to flip back to `active`. Stale
recovery via `attach-log` retains offsets only when the host file is
intact (matching `file_inode` and `file_size_seen ≤ current_size`);
otherwise the file is treated as a fresh stream and offsets reset to
`(0, 0)` per FR-024 / FR-025 (FR-021).

Redaction is per-line, stdlib `re` only (Clarifications Q5; FR-027,
FR-028, FR-029): unanchored token patterns (`\bsk-…\b`, `\bgh[ps]_…\b`,
`\bAKIA…\b`, `\bBearer …`) match anywhere in a line with `\b`
word-boundary protection; anchored patterns (JWT `^…$`, `.env`-shape
`^KEY=value$`) match only standalone lines. The daemon MUST compile
patterns with `re.ASCII` so `\b`/`\w`/`\W` are bytewise-defined and
cross-platform-stable. Multi-line buffer matching is explicitly out
of scope for FEAT-007 (FR-029).

The on-the-wire surface adds four new socket methods (FR-039) on top
of the existing FEAT-002 newline-delimited JSON envelope and inherits
FEAT-002's `0600`-host-user-only socket-file authorization verbatim
(no new authorization tier introduced). The SQLite migration adds
exactly two tables (`log_attachments`, `log_offsets`) plus their
indexes and bumps `CURRENT_SCHEMA_VERSION` from `4` (FEAT-006) to
`5`. FEAT-001 / FEAT-002 / FEAT-003 / FEAT-004 / FEAT-006 schemas
and persisted shapes are untouched (SC parallel to FEAT-006 SC-010).
The JSONL audit file is the existing FEAT-001 `events.jsonl` with
one new event-type `log_attachment_change` (FR-044); no new audit
log file is introduced. Lifecycle events go through the daemon's
existing lifecycle logger surface (same surface FEAT-006 uses for
`audit_append_failed`); they are observability signals about
external state and are NOT JSONL audit rows (FR-046).

Concurrency is bounded by two in-process advisory mutex maps:
per-`agent_id` is REUSED from FEAT-006's `agent_locks` registry
(FR-040; the same lock that serializes set-role / set-label /
set-capability also serializes attach-log / detach-log) and a new
per-`log_path` registry `log_path_locks` (FR-041; serializes
operator-supplied path collisions across different agents).
Cross-subsystem ordering with FEAT-004 pane reconciliation follows
the FEAT-006 pattern — SQLite `BEGIN IMMEDIATE` provides the
writer-serialization barrier; FEAT-004 does NOT acquire FEAT-007
mutexes; the stale-attachment transition (FR-042) happens inside
the FEAT-004 reconcile transaction so a concurrent `attach_log` can
never commit a fresh `active` row that is immediately invalidated.

The closed-set error code surface (FR-038) extends the FEAT-006
`socket_api/errors.py:CLOSED_CODE_SET` with: `log_path_invalid`,
`log_path_not_host_visible`, `log_path_in_use`, `pipe_pane_failed`,
`tmux_unavailable`, `attachment_not_found`, `log_file_missing`. Every
new code surfaces verbatim through both text-mode and `--json`
output. The CLI inherits FEAT-006's exit-code surface (FR-036): `0`
on success, `1` on `host_context_unsupported`, `2` on
`daemon_unavailable`, `3` on every other closed-set code, `4`
reserved for internal CLI errors.

The feature is testable end-to-end without a real Docker daemon,
real bench container, real tmux server, or real pipe-pane writes
(FR parallel to FEAT-006 FR-044), reusing the existing FEAT-003
`AGENTTOWER_TEST_DOCKER_FAKE`, FEAT-004 `AGENTTOWER_TEST_TMUX_FAKE`,
and FEAT-005 `AGENTTOWER_TEST_PROC_ROOT` test seams unchanged. One
new test seam `AGENTTOWER_TEST_LOG_FS_FAKE` is introduced to let
integration tests inject controlled `(inode, size)` observations of
host log files without needing a real filesystem inode race.

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001 /
FEAT-002 / FEAT-003 / FEAT-004 / FEAT-005 / FEAT-006; pyproject pins
`requires-python>=3.11`). Standard library only — no third-party
runtime dependency added.

**Primary Dependencies**: Standard library only — `sqlite3`,
`secrets` (for `attachment_id` 12-hex generation, mirroring
FEAT-006's `agt_<12-hex>`), `os` (`os.stat`, `os.makedirs(mode=…)`,
`os.path.realpath`, `os.path.commonpath`), `pathlib`, `socket`,
`argparse`, `json`, `dataclasses`, `typing`, `threading` (for the
new per-`log_path` mutex registry; reuses FEAT-006's per-`agent_id`
registry verbatim), `re` (compiled with `re.ASCII` for the FR-028
redaction patterns), `datetime` (for ISO-8601 microsecond UTC
timestamps consistent with FEAT-006's `attached_at`/`last_status_at`
shape), `subprocess` (only for the daemon-side `docker exec` that
issues the `tmux pipe-pane` command — same shape FEAT-004 already
uses for `tmux list-panes`; no new `subprocess` codepath is added in
the CLI). Reuses the FEAT-002 socket server (`socket_api/server.py`),
client (`socket_api/client.py`), and error envelope
(`socket_api/errors.py`) verbatim. Reuses FEAT-005 in-container
identity detection for the CLI side of `attach-log` (when called
without `--target` from inside a pane — though FR-031 makes
`--target` required, the FEAT-005 chain still resolves the caller's
container/pane for the host-context check). Reuses FEAT-006
`agents/service.py` resolution helpers for the `agent_id` →
`(container_id, pane_composite_key)` lookup that anchors every
attach call. Reuses FEAT-004 `tmux/` adapter for the
`tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}'` inspection
that drives FR-011 pre-attach pipe-state detection. Reuses FEAT-003
`containers.mounts_json` for FR-007 host-visibility proof. Reuses
FEAT-001 `events.writer.append_event` verbatim for the
`log_attachment_change` audit row.

**Storage**: One SQLite migration `v4 → v5` (FEAT-007), adding
exactly two new tables (`log_attachments`, `log_offsets`) and four
indexes (active-by-agent, active-by-pane composite, log_path
uniqueness for `status=active`, offset-by-agent); no other table is
touched. `CURRENT_SCHEMA_VERSION` advances from `4` (FEAT-006) to
`5`. Migration is idempotent on re-open via `IF NOT EXISTS`, runs
under a single `BEGIN IMMEDIATE` transaction inside
`schema._apply_pending_migrations`, and refuses to serve the daemon
on rollback. FEAT-001 / FEAT-002 / FEAT-003 / FEAT-004 / FEAT-006
schemas and persisted file modes (`0600`/`0700`) are unchanged. The
`events.jsonl` audit log is the existing FEAT-001 file; one new
event-type `log_attachment_change` is appended on every successful
attachment status transition (FR-044) — no new audit log path is
introduced. Host-side log files live at the FEAT-007-canonical path
`~/.local/state/opensoft/agenttower/logs/<container_id>/<agent_id>.log`
(full 64-char container id per FR-005), with directory mode `0700`
and file mode `0600` (FR-008). The pane-pipe payload writes are
appended by tmux running inside the container; the daemon never
writes to the log file directly, only ensures its existence and
mode at attach time.

**Testing**: pytest (≥ 7), reusing the FEAT-002 / FEAT-003 /
FEAT-004 / FEAT-005 / FEAT-006 daemon harness in
`tests/integration/_daemon_helpers.py` verbatim — every FEAT-007
integration test spins up a real host daemon under an isolated
`$HOME` and drives the `agenttower` console script as a subprocess.
The same three test seams (`AGENTTOWER_TEST_DOCKER_FAKE`,
`AGENTTOWER_TEST_TMUX_FAKE`, `AGENTTOWER_TEST_PROC_ROOT`) are reused
unchanged. One new test seam is introduced:
`AGENTTOWER_TEST_LOG_FS_FAKE` — a JSON-encoded mapping of
`{<host_path>: {"inode": <int>, "size": <int>, "exists": <bool>,
"contents": <str-or-null>}}` consumed by the `logs/host_fs.py`
adapter so integration tests can simulate truncation, recreation,
deletion, and reappearance without racing real filesystem syscalls.
Integration tests cover every US1 / US2 / US3 / US4 / US5 / US6 /
US7 acceptance scenario plus the spec's 21 edge cases. Unit tests
cover every concern enumerated in the spec's SCs:
`attachment_id` generation and uniqueness; FR-007 host-visibility
proof against fixture `Mounts` JSON (positive, negative, edge cases:
overlapping mounts, symlink mounts, read-only mounts, no canonical
mount); FR-011 pipe-state inspection (active-AgentTower-target /
active-foreign-target / inactive); FR-012 `pipe_pane_failed` stderr
sanitization; FR-014 / FR-015 atomic two-table commit; FR-016 WAL
durability across `SIGTERM` and `SIGKILL` restart paths; FR-018 /
FR-019 / FR-021 / FR-021d idempotent and recovery transitions;
FR-021a–FR-021e detach mechanics; FR-019 supersede-from-non-active
(active, stale, detached); FR-024 / FR-025 file truncation /
recreation detection; FR-026 file-missing → stale and
file-reappearance → `log_file_returned` (no auto-recovery); FR-027 /
FR-028 / FR-029 / FR-030 redaction across the closed-set fixture
suite (1000-iteration determinism per SC-004 / SC-010); FR-032 /
FR-033 read-only CLI behavior across every status value and the
no-row case; FR-034 / FR-035 fail-the-call atomicity for
`register-self --attach-log`; FR-040 / FR-041 mutex serialization;
FR-042 cross-subsystem ordering; FR-043 orphan detection on
daemon startup. A backwards-compatibility test
(`test_feat007_backcompat.py`) gates the SC parallel to FEAT-006
SC-010 by re-running every FEAT-001..006 CLI command and asserting
byte-identical stdout, stderr, exit codes, and `--json` shapes. A
migration test (`test_schema_migration_v5.py`) covers v4-only DB
upgrade, v5-already-current re-open, and forward-version refusal.

**Target Platform**: Linux/WSL developer workstations. The daemon
continues to run exclusively on the host (constitution principle I);
FEAT-007 introduces zero new in-container processes. The `attach-log`
CLI runs from inside a bench container as a short-lived thin client
(or from the host with `--target`), and the only daemon-side
`docker exec` codepaths FEAT-007 invokes are: (a) the
`tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}'`
inspection (FR-011, reuses FEAT-004 adapter), (b) the
`tmux pipe-pane -o … 'cat >> <log>'` attach (FR-010, new but
following the same `docker exec -u <container_user>` shape FEAT-004
already uses), (c) the `tmux pipe-pane -t <pane>` toggle-off for
supersede / detach paths (FR-019 / FR-021c), and (d) the FEAT-006
FR-041 focused rescan if the bound pane is unknown. No new tmux
subcommand shape, no new docker subcommand shape — every call goes
through the existing FEAT-003 / FEAT-004 adapter surfaces.

**Project Type**: Single-project Python CLI + daemon. Extends
`src/agenttower/`. Three existing modules (`cli.py`,
`state/schema.py`, `socket_api/methods.py`) gain additive surfaces;
one existing module (`socket_api/errors.py`) gains the new
closed-set error codes; one existing module
(`discovery/pane_reconcile.py`) gains a single side-effect that
flips `active → stale` for attachments whose pane went inactive in
the same transaction (FR-042); one existing module
(`agents/service.py`) gains the FEAT-007 wiring for
`register-self --attach-log` atomic two-table commit (FR-034 /
FR-035); one new package (`logs/`) is introduced for the attachment
domain logic, mirroring the package-per-domain split established by
FEAT-003's `discovery/`, FEAT-004's `tmux/`, FEAT-005's
`config_doctor/`, and FEAT-006's `agents/`.

**Performance Goals**:
- SC-001 — A single `agenttower attach-log --target <agent-id>`
  invocation against a healthy daemon, a healthy FEAT-004 pane
  lookup (no rescan), a healthy FEAT-006 agent resolution, a
  healthy FEAT-003 mount-prefix proof, a successful `tmux
  list-panes` inspection, a successful `tmux pipe-pane` attach,
  and a clean SQLite COMMIT + audit append completes within
  **2 seconds** wall-clock P95 end-to-end on a developer-class
  machine. The 2-second budget is the operator's interactive
  expectation; the daemon's portion is overwhelmingly bounded by
  the two `docker exec` round-trips.
- SC-003 — Offset durability across `SIGTERM` and `SIGKILL` restart
  paths is bounded by SQLite WAL durability; expected recovery time
  is sub-100 ms for a populated `log_offsets` table at MVP scale
  (tens of attachments).
- SC-004 / SC-010 — Redaction throughput is bounded by Python `re`
  performance on pre-compiled patterns; expected to be
  hundreds of megabytes per second on a developer-class machine,
  far above the 200-line preview cap (FR-033).
- `attach-log --status` is read-only, holds no FEAT-007 mutex, and
  returns the latest committed SQLite state. Expected steady-state
  usage at MVP scale is single-digit-millisecond per call.
- Stale-attachment detection in FEAT-004 reconciliation (FR-042)
  adds one indexed UPDATE per affected agent per scan cycle;
  expected overhead is sub-millisecond at MVP scale and is
  documented as such.

**Constraints**:
- No network listener anywhere in FEAT-007; the new socket methods
  reuse FEAT-002's `AF_UNIX` socket-file authorization (`0600`,
  host user only) verbatim (constitution principle I). No new
  `docker exec` codepath beyond the four documented shapes
  (`tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}'`,
  `tmux pipe-pane -o … 'cat >> <log>'`,
  `tmux pipe-pane -t <pane>` toggle-off, FEAT-006 FR-041 focused
  rescan reused unchanged).
- No third-party runtime dependency; all `attachment_id` generation,
  closed-set validation, mount-prefix proof, redaction regex
  compilation, mutex coordination, and CLI/JSON rendering use
  Python stdlib only.
- `attachment_id` is generated from `secrets.token_hex(6)` → 12 hex
  chars (48 bits of entropy) prefixed with `lat_` (mirrors FEAT-006
  `agt_<12-hex>` style; the `lat_` prefix prevents visual collision
  with `agt_` in operator output, per Assumptions §
  "agt_/lat_ namespaces"). Collisions are retried via a bounded
  loop (max 5 attempts) under the per-`(agent_id, log_path)`
  insert path; an exhausted retry budget surfaces as
  `internal_error` and the daemon stays alive.
- Host-visibility proof (FR-007): the daemon walks the bound
  container's `Mounts` JSON (already persisted by FEAT-003) and
  checks every mount whose `Type ∈ {bind, volume}`. For each mount,
  it tests whether the supplied or generated path lies under the
  mount's `Destination` (container-side prefix). On a match, it
  resolves the mount's `Source` (host-side prefix) on the daemon
  user's local filesystem via `os.path.realpath`; the proof
  succeeds when `realpath(<source>)` exists AND the daemon's
  `os.access(<source>, os.W_OK)` returns true OR the daemon's
  `os.access(<source>, os.R_OK)` returns true (read-only mounts
  are still host-visible for the purposes of this proof, but the
  ATTACH path additionally requires write-visibility). Symlinks
  inside the mount are rejected if their realpath escapes the
  mount root (FR-006 / edge case).
- `pipe-pane` shell construction (FR-010): the daemon constructs
  the `docker exec` command as a list of arguments
  (`["docker", "exec", "-u", <container_user>, <container_id>,
  "sh", "-lc", <inner_cmd>]`) and the inner shell command as a
  separate string. The log path is shell-quoted via
  `shlex.quote(<container_side_log_path>)` before being
  interpolated into `cat >> <log>`; the pane name (FEAT-004 short
  form) is also `shlex.quote`d. No raw user-supplied text reaches
  the shell construction site (FR-006 already enforces shape, but
  defense-in-depth via shlex is added per constitution principle
  III "shell command construction must never interpolate raw
  prompt text"). Inputs that fail FR-006 shape validation never
  reach this construction site.
- `tmux pipe-pane -o` semantics (Research R-008): the `-o` flag is
  "open only if no previous pipe exists"; this is the correct flag
  for the IDEMPOTENT attach path (FR-018). Toggle-off uses
  `tmux pipe-pane -t <pane>` (no command, no `-o`). The daemon
  pre-checks pipe state via FR-011 inspection before deciding
  which form to issue.
- File-mode invariants: directory `~/.local/state/opensoft/
  agenttower/logs/<container_id>/` is created with `mode 0700` and
  the resulting mode is verified after creation; the log file
  itself is created with `mode 0600` if absent and the daemon
  MUST NOT broaden either mode if the path already exists
  (FR-008). Mode verification reuses the existing FEAT-001
  `_verify_file_mode`/`_DIR_MODE` helpers.
- Single-transaction writes: every successful attach / detach /
  supersede commits the `log_attachments` write, the `log_offsets`
  write (or initial creation), and any cascaded prior-row update
  in one SQLite `BEGIN IMMEDIATE` transaction (FR-016); rollback on
  failure leaves no audit row and no row mutation. Failed attaches
  also leave no audit row (FR-045).
- Audit-shape consistency with FEAT-006: the `log_attachment_change`
  payload mirrors FEAT-006's `agent_role_change` shape — every
  payload carries `socket_peer_uid` (SO_PEERCRED, plumbed from the
  accepted AF_UNIX socket; cannot be spoofed via the request body),
  `source ∈ {explicit, register_self}` (daemon-internal-only;
  rejected at the wire if a client supplies it), and the daemon
  clock's ISO-8601 microsecond UTC timestamp. The exact field set
  is documented in `data-model.md` §`log_attachment_change` and
  enforced by `test_log_attachment_audit_record_shape.py`.
- `register-self --attach-log` atomicity (FR-034 / FR-035): when
  the FEAT-007 attach is in flight as part of a FEAT-006
  `register_agent` call, BOTH the `agents` row write AND the
  `log_attachments` + `log_offsets` writes commit in ONE
  `BEGIN IMMEDIATE` transaction; the JSONL audit appends are
  ordered: FEAT-006 `agent_role_change` FIRST, FEAT-007
  `log_attachment_change` SECOND. On any FEAT-007 failure the
  entire transaction rolls back; no partial agent row, no partial
  attachment row, no JSONL audit rows appended. The CLI surfaces
  the FEAT-007 failure code as the top-level error.
- Stale-attachment detection (FR-042): every FEAT-004 pane
  reconciliation transaction that observes a previously-active
  pane composite key transitioning to `active=0` MUST also flip
  every `log_attachments` row bound to that pane composite key
  from `status=active` to `status=stale` in the same SQLite
  transaction. The `log_offsets` row is NOT touched
  (offsets are retained for recovery per FR-021). One
  `log_attachment_change` audit row is appended per affected row
  with `prior_status=active, new_status=stale, source=explicit`
  (the source is "explicit" because the pane reconciliation's
  intent is observable; the audit log treats reconcile-driven
  transitions as system intent, not operator intent, but they
  use the same surface — see Research R-009 for the rationale).
- Cross-subsystem concurrency (FR-042): the FEAT-007 per-`log_path`
  mutex covers `attach_log` against other `attach_log` calls only;
  FEAT-004 pane reconciliation MUST NOT acquire it. The FEAT-007
  per-`agent_id` mutex (reused from FEAT-006 `agent_locks`)
  serializes attach / detach / set-* calls for the same agent
  but does NOT block FEAT-004 reconciliation. Cross-subsystem
  ordering between an `attach_log` transaction and a FEAT-004
  reconciliation transaction touching the same `log_attachments`
  row is provided **exclusively** by SQLite's `BEGIN IMMEDIATE`
  semantics — the last committed transaction wins for overlapping
  mutable columns; `SQLITE_BUSY` surfaces as `internal_error`
  without daemon-side retry.
- Schema version forward-compat: every new CLI surfaces
  `schema_version_newer` and refuses the call without corrupting
  state, inheriting the FEAT-006 forward-compat policy verbatim
  (FR-038). The wire envelope's `schema_version` field is the
  CLI's advertised version; the daemon refuses with
  `schema_version_newer` when its own schema has advanced past
  what the CLI knows.
- Closed-set hygiene: every FEAT-007 daemon method runs
  `_check_schema_version` + `_check_unknown_keys` at the top
  (mirrors FEAT-006); every wire shape error raises
  `bad_request`; every closed-set membership violation raises
  `value_out_of_set`. No new dispatch infrastructure.
- The CLIs MUST NOT send any input into any tmux pane, MUST NOT
  call `docker exec` for any purpose other than the four shapes
  enumerated in **Target Platform**, MUST NOT modify any
  pane log byte-for-byte (the daemon ensures the file exists and
  has correct mode, but the file's CONTENTS are written by the
  container's tmux process), and MUST NOT install any tmux hook.
  FEAT-007 is observation-only.
- Redaction is content-only: it applies to operator-facing
  rendering surfaces (`--preview` output, future FEAT-008 event
  excerpts) — never to the raw `log_path` file. The on-disk log
  file is the unmodified `pipe-pane` capture; redaction is a
  render-time transform. This is required so a forensic operator
  with appropriate filesystem access can grep the raw file
  (Assumptions § "Redaction is content-only").
- `line_offset` is derived (FR-022): readers MUST trust
  `byte_offset` for resumption. `line_offset` exists for human-
  friendly status output and tooling; FEAT-007 ships the schema
  and the persistence guarantee, the reader is FEAT-008.
- Fresh test seam `AGENTTOWER_TEST_LOG_FS_FAKE`: a JSON-encoded
  mapping consumed only by `logs/host_fs.py`. Production code uses
  the real `os.stat` / `os.path.exists` / `os.access`. The seam is
  the FEAT-007 equivalent of FEAT-003's `_DOCKER_FAKE` and FEAT-004's
  `_TMUX_FAKE` — it lives behind the same `_load_fake_or_none()`
  helper pattern and is documented in `data-model.md` §
  "test seams".

**Scale/Scope**: One host user, one daemon, two new SQLite tables
(`log_attachments`, `log_offsets`), four new SQLite indexes, one
new JSONL event-type (`log_attachment_change`), four new lifecycle
event types (`log_rotation_detected`, `log_file_missing`,
`log_file_returned`, `log_attachment_orphan_detected`), four new
socket methods (`attach_log`, `detach_log`, `attach_log_status`,
`attach_log_preview`), four new CLI subcommand surfaces
(`attach-log`, `attach-log --status`, `attach-log --preview`,
`detach-log`), one new `--attach-log` flag on the existing
`register-self`, seven new closed-set error codes
(`log_path_invalid`, `log_path_not_host_visible`, `log_path_in_use`,
`pipe_pane_failed`, `tmux_unavailable`, `attachment_not_found`,
`log_file_missing`), one new domain package (`logs/`), one new test
seam (`AGENTTOWER_TEST_LOG_FS_FAKE`). Expected steady-state usage:
tens of attached agents per host at MVP scale, sub-millisecond
SQLite reads on indexed lookups, single-digit-KB JSON payloads on
`attach-log --status`, ≤ 200 lines × ≤ ~1 KB per line ≈ 200 KB
maximum on `attach-log --preview` (FR-033 hard cap). The advisory
mutex maps grow with the number of distinct `agent_id` /
`log_path` values observed per daemon lifetime; entries are not
evicted (memory overhead is bounded by MVP agent count).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                     | Status | Evidence |
| ----------------------------- | ------ | -------- |
| I. Local-First Host Control   | PASS   | The log attachment registry is owned exclusively by the host daemon; the four new socket methods reuse FEAT-002's `AF_UNIX` socket-file authorization (`0600`, host user only) verbatim. No new network listener, no new in-container daemon, no new relay. Host-side log files live under the host's `~/.local/state/opensoft/agenttower/logs/<container_id>/` namespace per architecture §4 "Deployment Model". The bench-container CLI is a thin client that sends one socket request per call; durable state is owned 100 % by the host daemon (FR-014..FR-017). The constitution's "MVP Tower runs as a host daemon" property is preserved (no in-container relay, FR-007 explicitly rejects the in-container relay fallback as out of scope). |
| II. Container-First MVP       | PASS   | This is the durable observation slice that turns a registered FEAT-006 agent into one whose pane output is captured to a host-visible log via `tmux pipe-pane -o` issued through `docker exec` (FR-010). The host context is explicitly supported with `--target` (architecture §8 "Agents register from inside their tmux pane" pattern is preserved; FR-031 makes `--target` required so host operators can act on a registered agent). All new daemon-side `docker exec` codepaths are per-running-bench-container and reuse the FEAT-003 / FEAT-004 adapter shapes — no new container-discovery rule, no new tmux-server discovery, no new container-shell shape. |
| III. Safe Terminal Input      | PASS   | FEAT-007 is observation-only. The daemon does not deliver any input via FEAT-007 (input delivery is FEAT-009's concern). The `tmux pipe-pane` command issues `cat >> <log>` — a pure stdout redirection — never `send-keys` or `set-buffer`. Shell command construction uses `shlex.quote` for every interpolated value (log path, pane composite key); no raw user-supplied text reaches the shell construction site (Constraints § "pipe-pane shell construction"). All untrusted free-text inputs (`--log <path>`) are validated against the FEAT-006 path-shape rules (FR-006: absolute, no `..` segment, no NUL byte, ≤ 4096 chars, no C0 control bytes) before any `docker exec` is issued; failures surface as `log_path_invalid` and the daemon issues no `docker exec`. The `tmux pipe-pane` toggle-off and re-engage paths (FR-019, FR-021c) use the same shlex-quoted construction. Redaction is per-line, stdlib `re` only, with patterns compiled `re.ASCII` for cross-platform stability (Constraints § "Redaction"); the redaction utility is a pure function with no I/O side effect (FR-027). The host-visibility proof (FR-007) is the safety gate that prevents the daemon from creating a log path that would silently fall back to in-container-only storage and hide pane output from the operator's forensic view. |
| IV. Observable and Scriptable | PASS   | Every new CLI ships dual output: a human-readable form (one `key=value` line per field per FR-037) and a `--json` form with stable closed-set error codes (FR-038). Every successful attachment status transition appends exactly one JSONL audit row with `attachment_id`, `agent_id`, `prior_status`, `new_status`, `prior_path`, `new_path`, `prior_pipe_target`, `source`, `socket_peer_uid`, and timestamp (FR-044); the audit log is the existing FEAT-001 `events.jsonl`, no new file. `attach-log --status --json` exposes every attachment field and every offset field verbatim (FR-032). Lifecycle events (`log_rotation_detected`, `log_file_missing`, `log_file_returned`, `log_attachment_orphan_detected`) are emitted via the daemon's existing lifecycle logger (same surface FEAT-006 uses for `audit_append_failed`) so the operator can observe daemon-detected drift without mining the JSONL audit log (FR-046). Failure modes are a single closed-set error code set; every failure path exits non-zero with a code that appears verbatim in `--json` output. |
| V. Conservative Automation    | PASS   | FEAT-007 is registry-and-observation-only; it does NOT classify events (deferred to FEAT-008), does NOT route prompts (deferred to FEAT-009 / FEAT-010), and does NOT auto-attach orphans (FR-043: orphans are surfaced via `log_attachment_orphan_detected` lifecycle event but never auto-bound — operator action required). Detach is operator intent only (FR-021a, Clarifications Q1); no auto-detach occurs in FEAT-007 for any reason. File reappearance does not auto-recover (FR-026, Clarifications Q4); the system signals via `log_file_returned` and waits for operator-initiated `attach-log`. `register-self --attach-log` is FAIL-THE-CALL (FR-034); best-effort behavior is rejected so an operator who opts in is told whether the attachment landed. Redaction is a deliberately narrow closed-set pattern list (FR-028); expansion is a future feature. The daemon does NOT consume `last_event_offset` for any decision in FEAT-007 (FR-023); FEAT-008 reads it. |

| Technical Constraint                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Primary language Python                                                       | PASS   | Python 3.11+, stdlib only. No new runtime dependency. |
| Console entrypoints `agenttower` & `agenttowerd`                              | PASS   | Extends `agenttower` with `attach-log` (with `--status`, `--preview`, `--log` modes) and `detach-log`. Adds `--attach-log` flag on the existing FEAT-006 `register-self`. `agenttowerd run` is unchanged. |
| Files under `~/.config` / `~/.local/state` / `~/.cache` `opensoft/agenttower` | PASS   | The two new SQLite tables live in the existing `state.db`. JSONL audit rows are appended to the existing FEAT-001 `events.jsonl`. Host-side log files live at the canonical path `~/.local/state/opensoft/agenttower/logs/<container_id>/<agent_id>.log` (architecture §4). No new path is introduced. |
| Docker default `name_contains = ["bench"]`, host `docker exec -u "$USER"`     | PASS   | FEAT-007 calls `docker exec -u <container_user>` for the four documented shapes only. The container user is the FEAT-003-detected bench user (already persisted on the `containers` row). No new bench-name rule, no new container discovery shape. |
| CLI: human-readable defaults + structured output where it helps               | PASS   | Every new CLI ships a stable, scriptable default (one `key=value` line per field on stdout per FR-037) and a `--json` form (FR-031, FR-032, FR-033, FR-037a). |

| Development Workflow                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Build in `docs/mvp-feature-sequence.md` order                                 | PASS   | This is FEAT-007, immediately after FEAT-006 (`006-agent-registration`). Spec §"Out of scope" lists every later feature (FEAT-008 event classification, FEAT-009 prompt delivery, FEAT-010 routing) explicitly to keep this slice narrow. |
| Each feature CLI-testable                                                     | PASS   | Every US1..US7 acceptance scenario maps to at least one named integration test invoking the real `agenttower` console script under the FEAT-002 daemon harness; see the integration-test inventory in **Project Structure** below. |
| Tests proportional to risk; broader for daemon state, sockets, Docker/tmux adapters, permissions, and input delivery | PASS   | Host-visibility proof has dedicated unit + integration coverage (positive, negative, overlapping mounts, symlink escape, no-canonical-mount). Atomic two-table commit + WAL durability has dedicated coverage (`test_log_attach_transaction.py`, `test_log_offsets_durability_signals.py`). `register-self --attach-log` fail-the-call atomicity has integration coverage across every FR-038 closed-set code. Concurrency is covered by `test_attach_log_mutex.py` (per-agent_id reuse from FEAT-006) and `test_attach_log_path_collision.py` (per-`log_path` new registry). Cross-subsystem ordering is covered by `test_pane_reconcile_stale_attachment.py`. Redaction has 1000-iteration determinism coverage per SC-004 / SC-010. Schema migration has dedicated `test_schema_migration_v5.py` coverage. |
| Preserve existing docs and NotebookLM sync mappings                           | PASS   | This feature does not edit existing Markdown under `docs/`. New artifacts live entirely under `specs/007-log-attachment-offsets/`. |
| No TUI, web UI, or relay before the core slices work                          | PASS   | None introduced here. FEAT-007 is the durable-observation slice on top of the six core slices (FEAT-002..006). The in-container relay is explicitly out of scope (FR-007); host-only logging is explicitly out of scope (FEAT-007 spec input). |
| Decide explicitly whether `/speckit.checklist <topic>` is needed before tasks | DECISION | A `security` checklist was recommended and run (`checklists/security.md`). A `concurrency` checklist was ALSO recommended but was DEFERRED — the FR-040..FR-042 + FR-059 concurrency invariants are covered by dedicated tasks (T028 `test_log_path_locks_mutex.py`, T048 `test_attach_log_mutex.py`, T049 `test_attach_log_path_collision.py`, T060/T061 concurrency integration tests, T153 `test_pane_reconcile_stale_attachment.py`, T215 `test_mutex_acquisition_order.py` for SC-013) plus the FR-059 deterministic-acquisition-order helper enforced at runtime. The deferral is recorded here so the `/speckit.tasks` artifact remains coherent with the plan; if the team wants the additional gate before implementation, run `/speckit.checklist concurrency` and the resulting items will land in `checklists/concurrency.md`. |

**Result**: Gates pass. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/007-log-attachment-offsets/
├── plan.md                        # This file (/speckit.plan output)
├── research.md                    # Phase 0 output: resolved decisions
├── data-model.md                  # Phase 1 output: log_attachments + log_offsets + JSONL schema + lifecycle event schemas + test seam JSON shape
├── quickstart.md                  # Phase 1 output: end-to-end CLI walkthrough
├── contracts/
│   ├── cli.md                     # User-facing CLI contracts (C-CLI-701 attach-log; C-CLI-702 attach-log --status; C-CLI-703 attach-log --preview; C-CLI-704 detach-log; C-CLI-705 register-self --attach-log)
│   └── socket-api.md              # Socket-level contracts for the four new methods (attach_log, detach_log, attach_log_status, attach_log_preview) plus the FEAT-006 register_agent extension when --attach-log is in flight
├── checklists/                    # /speckit.checklist outputs (security + concurrency recommended)
└── tasks.md                       # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

Only files actually touched by FEAT-007 are listed. FEAT-001 /
FEAT-002 / FEAT-003 / FEAT-004 / FEAT-005 / FEAT-006 files remain
unchanged unless an explicit "EXTENDS" note appears.

```text
src/agenttower/
├── cli.py                                # EXTENDS: add subparsers `attach-log` (with --status / --preview / --log modes) and `detach-log`; add `--attach-log` flag to existing `register-self`; reuse FEAT-005 socket-resolution chain; argparse uses `argparse.SUPPRESS` for optional flags so omitted flags are absent in the dict and not transmitted (mirrors FEAT-006 Q1 wire encoding); `--json` flag on every new subcommand
├── state/
│   ├── schema.py                         # EXTENDS: bump CURRENT_SCHEMA_VERSION 4 → 5; add `_apply_migration_v5`; register migration in `_MIGRATIONS`; v4-only DBs upgrade in one BEGIN IMMEDIATE transaction
│   ├── log_attachments.py                # NEW: SQLite reads/writes for the `log_attachments` table; pure data-access layer mirroring `state/agents.py`; closed-set INSERT/UPDATE/SELECT helpers; deterministic ordering helper for status-and-recent listings
│   └── log_offsets.py                    # NEW: SQLite reads/writes for the `log_offsets` table; pure data-access layer; helpers for atomic offset advance (FEAT-008's contract anchor), file-consistency check (FR-024 / FR-025), and reset
├── logs/                                 # NEW package: log attachment domain logic
│   ├── __init__.py                       # NEW: package marker; re-exports LogAttachmentRecord, LogOffsetRecord, AttachLogRequest, LogService, LogRedactor
│   ├── identifiers.py                    # NEW: attachment_id generation `lat_<12-hex>`; bounded retry-on-collision under per-(agent_id, log_path) insert path (mirrors FEAT-006 R-001 retry logic; max 5 attempts)
│   ├── host_visibility.py                # NEW: FR-007 host-visibility proof — walks the bound container's `Mounts` JSON, matches container-side path against each mount's Destination prefix, resolves Source on the host filesystem via realpath; closed-set rejection codes
│   ├── pipe_pane.py                      # NEW: tmux pipe-pane command construction (FR-010, FR-011) with shlex-quoting; pre-attach state inspection via `tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}'` (reuses FEAT-004 tmux adapter); toggle-off variant for supersede / detach paths
│   ├── redaction.py                      # NEW: FR-027–FR-030 redaction utility; pre-compiled regex patterns with re.ASCII flag; per-line application; unanchored tokens with \b protection; anchored standalone-line patterns (JWT, .env-shape); pure function, no I/O
│   ├── preview.py                        # NEW: FR-033 last-N-lines reader; reverse-read of the host log file with hard cap at 200 lines × bounded byte budget; consumes redaction utility before returning
│   ├── host_fs.py                        # NEW: thin adapter for `os.stat` / `os.path.exists` / `os.makedirs(mode=0o700)` / `os.access`; honors AGENTTOWER_TEST_LOG_FS_FAKE for integration tests; production code uses real syscalls verbatim
│   ├── service.py                        # NEW: top-level orchestrator for attach_log / detach_log / attach_log_status / attach_log_preview daemon-side; consumes the per-`agent_id` (FEAT-006 agent_locks) and per-`log_path` (FEAT-007 log_path_locks) mutex registries (FR-040, FR-041); single-transaction commit; rollback on failure; supersede-from-any-status logic (FR-019); same-path recovery from stale or detached (FR-021, FR-021d)
│   ├── mutex.py                          # NEW: per-`log_path` advisory mutex registry `LogPathLockMap` (keyed by canonical host-side log path, FR-041); thread-safe fetch-or-create under guard lock (research mirrors FEAT-006 R-005 pattern); FEAT-004 reconciliation does NOT acquire this map (cross-subsystem ordering via SQLite BEGIN IMMEDIATE)
│   ├── audit.py                          # NEW: JSONL audit-row writer for `event_type=log_attachment_change` appended to events.jsonl; reuses FEAT-001 `events.writer.append_event`; skip on no-op (FR-045) and on failed attaches (FR-045); lifecycle event helpers for `log_rotation_detected`, `log_file_missing`, `log_file_returned`, `log_attachment_orphan_detected` via the daemon's lifecycle logger (FR-046)
│   ├── orphan_recovery.py                # NEW: FR-043 startup pass; for every running bench container's panes (reuses FEAT-004 list-panes), checks panes with `pane_pipe=1` whose target matches the AgentTower-canonical path prefix and that have no corresponding `log_attachments` row; emits one `log_attachment_orphan_detected` lifecycle event per orphan; never auto-attaches (operator action required)
│   └── client_resolve.py                 # NEW: client-side resolver for `attach-log` / `detach-log`; reuses FEAT-005 identity + tmux-self-identity for the host-context check; resolves the agent_id → (container_id, pane composite key) lookup via the FEAT-006 `list_agents` socket method when `--target` is supplied; maps every failure to a closed-set error code
├── agents/
│   └── service.py                        # EXTENDS: `register_agent` gains a `--attach-log` codepath that runs the FEAT-007 attach inside the same `BEGIN IMMEDIATE` transaction as the agent row write (FR-034, FR-035); audit-row ordering enforced (agent_role_change FIRST, log_attachment_change SECOND); rollback on any FEAT-007 failure leaves zero rows in agents/log_attachments/log_offsets and zero JSONL rows
├── socket_api/
│   ├── methods.py                        # EXTENDS: add four new dispatch entries (`attach_log`, `detach_log`, `attach_log_status`, `attach_log_preview`); each handler routes to `logs/service.py`; existing entries unchanged byte-for-byte
│   ├── errors.py                         # EXTENDS: add new closed-set codes (`LOG_PATH_INVALID`, `LOG_PATH_NOT_HOST_VISIBLE`, `LOG_PATH_IN_USE`, `PIPE_PANE_FAILED`, `TMUX_UNAVAILABLE`, `ATTACHMENT_NOT_FOUND`, `LOG_FILE_MISSING`); extend `CLOSED_CODE_SET` accordingly; existing codes unchanged
│   └── client.py                         # EXTENDS (additive only): add typed wrappers `attach_log()`, `detach_log()`, `attach_log_status()`, `attach_log_preview()`; reuse existing connect / framing logic
└── discovery/
    └── pane_reconcile.py                 # EXTENDS: every pane reconciliation transaction that observes a previously-active pane composite key transitioning to active=0 MUST also flip every `log_attachments` row bound to that pane composite key from `status=active` to `status=stale` in the SAME SQLite transaction (FR-042); per-affected-row audit append for `log_attachment_change` with prior_status=active, new_status=stale; the offset row is unchanged (offsets retained for recovery per FR-021)

tests/
├── unit/
│   ├── test_attachment_id_generation.py             # NEW: `lat_<12-hex>` shape; collision retry under insert path; entropy bound; non-collision with `agt_<12-hex>` namespace
│   ├── test_host_visibility_proof.py                # NEW: FR-007 — positive (canonical bind mount present); negative (no canonical bind mount); overlapping mounts (deepest match wins); symlink escape (rejected); read-only mount (rejected for attach, allowed for read inspection); empty Mounts JSON; malformed Mounts JSON
│   ├── test_pipe_pane_command_construction.py       # NEW: FR-010 — shlex-quoted log path; shlex-quoted pane composite key; container_user verbatim; rejects un-validated input; rejects raw NUL byte; constructs the exact `docker exec -u <user> <container> sh -lc 'tmux pipe-pane -o -t <pane> "cat >> <log>"'` shape
│   ├── test_pipe_pane_state_inspection.py           # NEW: FR-011 — parses `pane_pipe=0` / `pane_pipe=1` correctly; identifies AgentTower-canonical target vs. foreign target via prefix match against the canonical log root; surfaces foreign target via `prior_pipe_target` audit field
│   ├── test_pipe_pane_failed_sanitization.py        # NEW: FR-012 — non-zero docker exec exit; non-zero tmux pipe-pane exit; tmux stderr matching `session not found` / `pane not found` / `no current target`; sanitized stderr excerpt (NUL-strip, ≤ 2048 chars, no control bytes)
│   ├── test_log_path_validation.py                  # NEW: FR-006 — absolute path; no `..` segment; no NUL byte; ≤ 4096 chars; no C0 control bytes; matches FEAT-006 `project_path` validation byte-for-byte
│   ├── test_log_path_in_use.py                      # NEW: FR-009 — same path owned by different agent_id rejected with conflicting agent_id surfaced in actionable message
│   ├── test_log_attachments_table.py                # NEW: FR-014 — composite uniqueness (agent_id, log_path); status closed-set check constraint; `lat_<12-hex>` PK shape; FK to agents.agent_id; field types and nullability per data-model.md
│   ├── test_log_offsets_table.py                    # NEW: FR-015 — composite PK (agent_id, log_path); initial values on creation; field types; FK to log_attachments composite key
│   ├── test_log_attach_transaction.py               # NEW: FR-016 — single BEGIN IMMEDIATE for log_attachments + log_offsets writes; rollback on either failure; pipe-pane success without offset row never observable
│   ├── test_log_offsets_durability_signals.py       # NEW: FR-017 — durability invariant signals (every successful write commits; SQLite WAL mode is on; no daemon-side caching ahead of COMMIT)
│   ├── test_attach_idempotency.py                   # NEW: FR-018 — same (agent_id, log_path) and status=active is no-op success; no duplicate row; no offset reset; no audit row; pipe-pane re-issued defensively (idempotent)
│   ├── test_supersede_from_active.py                # NEW: FR-019 — path change from active prior status; superseded_at + superseded_by set; new row at new path; fresh offsets; toggle-off issued; one audit row with prior_path/new_path
│   ├── test_supersede_from_stale.py                 # NEW: FR-019 / Clarifications Q2 — path change from stale prior status; toggle-off NOT issued (no live pipe); same supersede contract; audit row carries prior_status=stale
│   ├── test_supersede_from_detached.py              # NEW: FR-019 / Clarifications Q2 — path change from detached prior status; toggle-off NOT issued; audit row carries prior_status=detached
│   ├── test_recovery_from_stale_pane_drift.py       # NEW: FR-021 — file intact; offsets retained byte-for-byte; status active; audit row prior_status=stale
│   ├── test_recovery_from_stale_file_changed.py     # NEW: FR-021 / Clarifications Q4 — file_inode differs OR file_size_seen > current_size; offsets reset; log_rotation_detected lifecycle event in addition to the audit row
│   ├── test_recovery_from_detached.py               # NEW: FR-021d — same-path attach from detached reuses row; offsets retained; pipe-pane re-engaged; audit row prior_status=detached
│   ├── test_detach_mechanics.py                     # NEW: FR-021a–FR-021c — explicit detach only; toggle-off issued; status active → detached; offsets retained; audit row appended; rejected on non-active row with attachment_not_found; same liveness gates as attach
│   ├── test_no_implicit_detach.py                   # NEW: FR-021a / Clarifications Q1 — agent.active=0 / container.active=0 / pane.active=0 / file_missing all leave status untouched (no implicit detached transition); pane-drift uses stale; file-missing uses stale
│   ├── test_offset_advance_invariant.py             # NEW: FR-022 / FR-023 — attach-log MUST NOT advance byte_offset; line_offset is derived from byte_offset and \n count; FEAT-007 ships the schema invariant only
│   ├── test_file_truncation_detection.py            # NEW: FR-024 — current_file_size < file_size_seen; reset (byte_offset=0, line_offset=0); preserve file_inode; one log_rotation_detected lifecycle event with prior_size/new_size/inode
│   ├── test_file_recreation_detection.py            # NEW: FR-025 — file_inode differs from stored; reset (byte_offset, line_offset); update file_inode and file_size_seen; one log_rotation_detected lifecycle event with prior_inode/new_inode
│   ├── test_file_missing_then_returned.py           # NEW: FR-026 / Clarifications Q4 — file disappears on next reader cycle: status active → stale, log_file_missing fired, offsets unchanged; file later reappears: log_file_returned fired exactly once per (agent_id, log_path, file_inode), status remains stale (no auto-recovery), offsets unchanged
│   ├── test_redaction_unanchored.py                 # NEW: FR-027 / FR-028 / Clarifications Q5 — sk-, gh[ps]_, AKIA, Bearer match anywhere in line with \b protection; multiple matches in single line all replaced; word-boundary respected on both sides where applicable; matches on every fixture input deterministic across 1000 invocations (SC-004)
│   ├── test_redaction_anchored.py                   # NEW: FR-028 / Clarifications Q5 — JWT only matches standalone lines; .env-shape only matches standalone KEY=VALUE lines; mixed log lines pass through; anchors retained
│   ├── test_redaction_per_line.py                   # NEW: FR-029 / Clarifications Q5 — input split on \n; each line processed independently; tokens spanning newlines NOT redacted; multi-line buffer matching not performed
│   ├── test_redaction_purity.py                     # NEW: FR-027 / FR-029 — pure function (same input → same output across 1000 calls); no per-call randomness; locale-independent (re.ASCII flag verified)
│   ├── test_redaction_no_offset_alteration.py       # NEW: FR-030 — redaction utility consumes raw bytes and produces redacted bytes; advancement of byte_offset is unaffected by redaction
│   ├── test_status_universal_read.py                # NEW: FR-032 / Clarifications Q3 — `--status` always succeeds when agent resolvable; returns most recent row regardless of status; agent with no attachment returns attachment=null offset=null; --status does NOT issue docker exec / pipe-pane / file read
│   ├── test_preview_allowed_statuses.py             # NEW: FR-033 / Clarifications Q3 — preview works against active/stale/detached; rejects superseded with attachment_not_found; rejects no-row with attachment_not_found
│   ├── test_preview_file_missing.py                 # NEW: FR-033 / Clarifications Q3 — selected row in allowed status but host file missing → log_file_missing closed-set rejection
│   ├── test_preview_redaction_integration.py        # NEW: FR-033 — preview output passes through FR-027/FR-028 redaction; raw secrets MUST NOT appear in output across 1000 runs (SC-010)
│   ├── test_preview_line_cap.py                     # NEW: FR-033 — N=1, N=200, N=0 (rejected value_out_of_set), N=201 (rejected value_out_of_set), N=−1 (rejected); empty file (returns empty); file with fewer than N lines (returns all)
│   ├── test_register_self_attach_log_atomic_success.py  # NEW: FR-034 / FR-035 — register_agent + attach_log commit in one transaction; agent_role_change audit row FIRST, log_attachment_change SECOND
│   ├── test_register_self_attach_log_fail_the_call.py   # NEW: FR-034 — every FEAT-007 closed-set failure code (log_path_not_host_visible, pipe_pane_failed, tmux_unavailable, log_path_in_use, log_path_invalid, log_path_in_use, ...) leaves zero agents row, zero log_attachments row, zero log_offsets row, zero JSONL audit rows
│   ├── test_attach_log_mutex.py                     # NEW: FR-040 — concurrent attach_log calls for same agent_id serialized through the FEAT-006 agent_locks registry; concurrent calls for different agents proceed in parallel
│   ├── test_attach_log_path_collision.py            # NEW: FR-041 — concurrent attach_log calls from different agents whose explicit --log paths collide serialized through the new log_path_locks registry; first wins, second observes log_path_in_use; per-`log_path` mutex map fetch-or-create thread-safe
│   ├── test_pane_reconcile_stale_attachment.py      # NEW: FR-042 — FEAT-004 reconcile transaction that flips pane.active=1 → 0 also flips every bound log_attachments row from active to stale in the same transaction; offsets unchanged; one audit row per affected row
│   ├── test_orphan_detection_on_startup.py          # NEW: FR-043 — daemon startup pass identifies pane_pipe=1 with AgentTower-canonical target but no log_attachments row; emits one log_attachment_orphan_detected lifecycle event per orphan; does NOT auto-attach
│   ├── test_audit_row_shape.py                      # NEW: FR-044 — log_attachment_change payload has every documented field (attachment_id, agent_id, prior_status, new_status, prior_path, new_path, prior_pipe_target, source, socket_peer_uid, ts); types per data-model.md; nullable fields nullable
│   ├── test_audit_no_op_skip.py                     # NEW: FR-045 — idempotent re-attach (FR-018) appends no audit row; failed attach appends no audit row; only actual state transitions appear
│   ├── test_lifecycle_event_surface.py              # NEW: FR-046 — log_rotation_detected, log_file_missing, log_file_returned, log_attachment_orphan_detected go through the daemon's lifecycle logger (NOT events.jsonl); log_file_returned suppressed for repeat firings on same (agent_id, log_path, file_inode) triple
│   ├── test_socket_api_attach_log_envelope.py       # NEW: FR-039 — wire envelope shape; allowed-keys set; unknown key rejected with bad_request listing offending keys; source field rejected at wire (clients cannot supply it)
│   ├── test_socket_api_register_agent_attach_log.py # NEW: FR-035 — register_agent envelope gains optional --attach-log signal; daemon-internal source=register_self set on the FEAT-007 audit row only; not exposed to clients
│   ├── test_schema_v5_migration_unit.py             # NEW: v4 → v5 idempotent; log_attachments + log_offsets tables + indexes created on otherwise-unchanged FEAT-006 DB; FEAT-001..006 tables untouched
│   └── test_log_value_out_of_set.py                 # NEW: out-of-set status / source values rejected via closed-set validators with value_out_of_set; actionable message lists valid values
└── integration/
    ├── test_cli_attach_log.py                              # NEW: US1 AS1 / SC-001 — attach-log returns 0; persists exactly one log_attachments row in active; one log_offsets row at (0,0); fake docker exec received documented pipe-pane invocation; one log_attachment_change JSONL row appended
    ├── test_cli_attach_log_idempotent.py                   # NEW: US1 AS2 / SC-002 — re-running attach-log 100 times produces exactly one row in each table; no offset reset; no duplicate audit row
    ├── test_cli_attach_log_supersede_path_change.py        # NEW: US1 AS4 / FR-019 / Clarifications Q2 — path change supersedes prior row across active/stale/detached starts
    ├── test_cli_attach_log_pane_reactivation.py            # NEW: US1 AS3 / FR-020 — pane reactivation reuses attachment; offsets retained; pipe-pane re-engaged
    ├── test_cli_attach_log_offsets_persist_restart.py      # NEW: US2 / SC-003 — offsets advanced via test seam to (4096, 137); SIGTERM + SIGKILL daemon restarts; offsets recovered byte-for-byte
    ├── test_cli_attach_log_redaction_preview.py            # NEW: US3 / SC-010 — preview rendering of fixture log with every FR-028 pattern produces zero raw secrets across 1000 runs
    ├── test_cli_register_self_attach_log_success.py        # NEW: US4 AS1 / SC-008 — register-self --attach-log atomic success; both audit rows appended in order agent_role_change FIRST, log_attachment_change SECOND
    ├── test_cli_register_self_attach_log_failure.py        # NEW: US4 AS2 / SC-008 — register-self --attach-log fail-the-call across every FR-038 closed-set code; zero rows in any table; zero JSONL rows
    ├── test_cli_attach_log_stale_recovery.py               # NEW: US5 AS1 / AS2 / FR-042 — FEAT-004 reconcile flips bound row to stale; follow-up attach-log recovers to active retaining offset
    ├── test_cli_attach_log_file_missing.py                 # NEW: US6 AS3..AS5 / FR-026 / Clarifications Q4 — file deleted → stale + log_file_missing event; file recreated → log_file_returned event, status still stale; operator runs attach-log → status active, offsets reset, log_rotation_detected event
    ├── test_cli_attach_log_file_truncated.py               # NEW: US6 AS1 / FR-024 — file truncated to 0; offsets reset; one log_rotation_detected event
    ├── test_cli_attach_log_file_recreated.py               # NEW: US6 AS2 / FR-025 — file deleted and recreated (new inode); offsets reset; one log_rotation_detected event
    ├── test_cli_detach_log.py                              # NEW: US7 AS1 / SC-011 — detach-log: status active → detached; offsets retained; audit row appended; toggle-off issued
    ├── test_cli_detach_log_re_attach.py                    # NEW: US7 AS2 / SC-011 — re-attach from detached: same row reused; offsets retained byte-for-byte; status active
    ├── test_cli_detach_log_invalid_state.py                # NEW: US7 AS3 / FR-021b — detach-log on agent with no row, or on stale/superseded/detached row, refused with attachment_not_found
    ├── test_cli_no_implicit_detach.py                      # NEW: US7 AS4 / FR-021a — exercising every other lifecycle path (pane drift, agent inactivation, container restart, file rotation/truncation/deletion) leaves status in {active, stale, superseded} but never detached
    ├── test_cli_attach_log_status.py                       # NEW: FR-032 / Clarifications Q3 — --status against agent with active row; with stale/detached/superseded row; with no row at all; never issues docker exec
    ├── test_cli_attach_log_preview.py                      # NEW: FR-033 / Clarifications Q3 — --preview against active/stale/detached succeeds; against superseded/no-row refused attachment_not_found; against allowed-status with missing host file refused log_file_missing
    ├── test_cli_attach_log_host_visibility.py              # NEW: SC-005 / FR-007 — explicit --log not under any bind mount refused log_path_not_host_visible; zero side effects (no rows, no docker exec, no JSONL); positive case proves through fixture Mounts JSON
    ├── test_cli_attach_log_path_in_use.py                  # NEW: FR-009 — different agent owns same path → log_path_in_use; conflicting agent_id surfaced in error message
    ├── test_cli_attach_log_path_invalid.py                 # NEW: FR-006 — relative / `..` / NUL byte / over-cap rejected log_path_invalid; matches FEAT-006 project_path validator byte-for-byte
    ├── test_cli_attach_log_pipe_pane_failed.py             # NEW: FR-012 — non-zero pipe-pane exit / matching stderr → pipe_pane_failed; sanitized stderr excerpt; no log_attachments row persisted
    ├── test_cli_attach_log_tmux_unavailable.py             # NEW: FR-013 — tmux not installed in container → tmux_unavailable; no docker exec issued
    ├── test_cli_attach_log_concurrent_same_agent.py        # NEW: FR-040 — two concurrent attach-log calls for same agent_id serialize via FEAT-006 agent_locks; second observes first's writes inside BEGIN IMMEDIATE
    ├── test_cli_attach_log_concurrent_path_collision.py    # NEW: FR-041 — two concurrent attach-log calls from different agents whose --log paths collide; first wins, second hits log_path_in_use
    ├── test_cli_attach_log_orphan_recovery.py              # NEW: FR-043 — startup pass identifies orphans (pane_pipe=1 with canonical-prefix target, no log_attachments row); emits log_attachment_orphan_detected per orphan; never auto-attaches
    ├── test_cli_attach_log_inactive_agent.py               # NEW: edge cases — agent.active=0 / container.active=0 → agent_inactive
    ├── test_cli_attach_log_pane_unknown.py                 # NEW: edge cases — bound pane absent after FEAT-006 FR-041 focused rescan refused pane_unknown_to_daemon
    ├── test_cli_attach_log_host_context.py                 # NEW: edge cases — host shell without --target → host_context_unsupported; with --target → succeeds (host-side targeting)
    ├── test_cli_attach_log_no_daemon.py                    # NEW: SC parallel to FEAT-006 SC-009 — daemon down → exit code 2 with FEAT-002 daemon-unavailable message
    ├── test_cli_attach_log_schema_newer.py                 # NEW: FR-038 — daemon schema_version > CLI build → schema_version_newer; refuses without state mutation
    ├── test_cli_attach_log_unknown_keys.py                 # NEW: FR-039 — wire envelope unknown keys → bad_request listing offending keys
    ├── test_schema_migration_v5.py                         # NEW: SC parallel to FEAT-006 SC-010 — v4-only DB upgrades to v5 cleanly; v5-already-current re-open is a no-op; forward-version refusal preserved; FEAT-001..006 tables untouched
    ├── test_feat007_backcompat.py                          # NEW: SC parallel to FEAT-006 SC-010 — every FEAT-001..006 CLI command produces byte-identical output; no existing socket method gains a code or shape; existing tests still pass
    └── test_feat007_no_real_docker_or_tmux.py              # NEW: parallel to test_feat006_no_real_docker_or_tmux.py; asserts no real docker / tmux / network call during the FEAT-007 test session beyond what the existing FEAT-003/FEAT-004 fakes simulate
```

**Structure Decision**: Keep the FEAT-001..006 single-project layout.
The new `logs/` package mirrors the package-per-domain split
established by FEAT-003's `discovery/` and `docker/`, FEAT-004's
`tmux/` and `discovery/pane_reconcile.py`, FEAT-005's
`config_doctor/`, and FEAT-006's `agents/`: `service.py`
orchestrates, `identifiers.py`, `host_visibility.py`,
`pipe_pane.py`, `redaction.py`, `preview.py`, `host_fs.py`,
`audit.py`, `orphan_recovery.py`, `mutex.py`, and
`client_resolve.py` keep each FR's logic in one testable unit. The
SQLite layer mirrors FEAT-003 / FEAT-004 / FEAT-006's split between
`state/schema.py` (migrations) and `state/<table>.py` (typed
read/write helpers) by adding `state/log_attachments.py` and
`state/log_offsets.py`. The dispatch table in
`socket_api/methods.py` gains exactly four new entries
(`attach_log`, `detach_log`, `attach_log_status`,
`attach_log_preview`); existing entries are unchanged byte-for-byte.
`socket_api/errors.py` adds the FEAT-007 closed-set codes; existing
codes are unchanged. `socket_api/client.py` gets four new typed
wrappers; the framing / connect path is unchanged.
`discovery/pane_reconcile.py` gains the single side-effect of
flipping bound `log_attachments` rows to `stale` in the same
transaction (FR-042). `agents/service.py` gains the FEAT-007
wiring for `register-self --attach-log` atomic two-table commit
(FR-034 / FR-035) — the agent row, the attachment row, the offset
row, and both JSONL audit rows are committed atomically; on any
failure the entire transaction rolls back. `cli.py` gets two new
subparsers (`attach-log` with mode flags, `detach-log`) plus the
`--attach-log` flag on the existing `register-self`; argparse uses
`argparse.SUPPRESS` defaults for optional flags so omitted flags
are absent from the parsed dict and not transmitted (mirrors
FEAT-006 Q1 wire encoding). `state/schema.py` gains exactly one
new migration function `_apply_migration_v5`, registered in
`_MIGRATIONS[5]`, and `CURRENT_SCHEMA_VERSION` moves from `4` to
`5`. The constitution's no-new-listener / no-new-relay clause is
enforced by the absence of any edit to `socket_api/server.py`,
`socket_api/lifecycle.py`, or `daemon.py` beyond optional plumbing
of the new method handlers into the dispatch context and the
startup-pass invocation of `logs/orphan_recovery.py`.

## Complexity Tracking

> No constitutional violations to justify. This section is intentionally empty.

## Implementation Deviations

The following items were resolved during implementation in ways that
deviate slightly from the literal spec/plan reading. Each is recorded
here for forward-compat and PR-review traceability.

### tmux_present field on `containers` row (FR-013)

The plan describes FR-013 as "If tmux is not installed in the bound
container (FEAT-003 surfaces this in the container scan; the daemon
caches it on the `containers` row), the daemon MUST refuse with
closed-set `tmux_unavailable` without issuing any `docker exec`."

The current FEAT-003 schema does NOT persist a ``tmux_present`` column
on ``containers``. Adding the column is a v6 schema bump touching
FEAT-003, beyond the FEAT-007 scope.

**Resolution adopted at MVP**: ``LogService._resolve_active_container``
treats every active container as tmux-available. The actual tmux
availability is detected at FR-011 inspection time when ``tmux
list-panes`` returns a non-zero exit or one of the FR-012 stderr
patterns — the daemon then surfaces ``pipe_pane_failed`` rather than
``tmux_unavailable``. From the operator's perspective, both codes
are exit 3 with an actionable message; the closed-set distinction is
preserved at the wire surface but the FR-013 path is functionally
subsumed by FR-012 at MVP.

**Follow-up**: persisting ``tmux_present`` on the FEAT-003 container
scan is tracked as a post-MVP cleanup. Once it lands, ``LogService``
will short-circuit on the cached value and emit ``tmux_unavailable``
before any ``docker exec``, matching the literal FR-013 contract.

### `register-self --attach-log` (FR-034 / FR-035)

US4's atomic two-table register+attach surface is implemented in this
PR (see ``agents/service.py`` extension and the new ``attach_log``
nested wire key). Tests cover success and fail-the-call atomicity
across the FR-038 closed-set codes that can fire from the FEAT-007
attach path.

### Orphan recovery on daemon startup (FR-043)

Implemented in this PR via ``logs/orphan_recovery.py`` and a daemon
startup hook. The pass runs after schema migration, before the socket
listener accepts requests; it emits one
``log_attachment_orphan_detected`` lifecycle event per orphan and
never auto-attaches.
