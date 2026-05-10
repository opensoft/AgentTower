# Phase 0 Research: Pane Log Attachment and Offset Tracking

**Branch**: `007-log-attachment-offsets` | **Date**: 2026-05-08

This document records the research decisions that resolve every
NEEDS CLARIFICATION in `plan.md`'s Technical Context. Each entry
captures Decision, Rationale, and Alternatives Considered.

---

## R-001 — `attachment_id` shape and entropy

**Decision**: `attachment_id = "lat_" + secrets.token_hex(6)` →
`lat_<12-character-lowercase-hex>` (48 bits of entropy).

**Rationale**:
- Spec § Key Entities fixes the format; this is the implementation
  that satisfies it.
- Mirrors FEAT-006 R-001 (`agt_<12-hex>`) byte-for-byte: same
  `secrets.token_hex(6)` call, same 48 bits, same lowercase-hex
  alphabet, same retry-on-collision discipline. Reusing the
  established pattern means tests, docs, and operator mental model
  are zero-cost extensions of FEAT-006.
- The `lat_` prefix is human-recognizable in CLI output and
  prevents visual collision with `agt_<12-hex>` agent ids in mixed
  operator output (Spec § Assumptions).
- 48 bits keeps accidental collisions vanishingly unlikely at MVP
  scale (birthday-bound collision expected at ~2^24 ≈ 16M unique
  attachments — far beyond plausible MVP fleets).

**Collision handling**: A bounded retry loop (≤ 5 attempts) inside
the daemon's attach pipeline, after the per-`(agent_id, log_path)`
mutex is acquired but before the SQLite INSERT. SQLite raises
`IntegrityError` on the PK conflict; each retry generates a fresh
`lat_<12-hex>` and tries again. Exhausted budget surfaces as
`internal_error` and the daemon stays alive (mirrors FEAT-006 FR-035).

**Alternatives considered**:
- ULID / UUIDv7 — adds a third-party dependency or a stdlib port;
  the visible benefit (sortable ids) does not apply: FEAT-007 lists
  attachments by status and `last_status_at`, not creation order.
- Reusing the agent's `agt_<12-hex>` as the attachment id — rejected
  because spec FR-019 / Clarifications Q2 require a fresh attachment
  row on every path change (one agent can have multiple attachments
  in `superseded` state plus one `active` row). A 1:1 mapping breaks
  the supersede ledger.

---

## R-002 — Optional-field wire encoding (mirrors FEAT-006 R-002)

**Decision**: Argparse uses `argparse.SUPPRESS` as the default for
every optional flag (`--log`, `--status`, `--preview`, `--json`,
`--attach-log` on register-self). When the user does not pass a
flag, the key is absent from the parsed `Namespace` and absent from
the JSON request envelope. The daemon treats absent keys as the
documented FR-005 / FR-031 / FR-039 defaults.

**Rationale**:
- The pattern is already proven in FEAT-006 (every mutable field
  uses `argparse.SUPPRESS` so omitted flags are absent on the wire).
- The spec's allowed-keys closed sets (`{schema_version, agent_id,
  log_path, source}` for `attach_log`; `{schema_version, agent_id}`
  for `detach_log` / `attach_log_status`; `{schema_version,
  agent_id, lines}` for `attach_log_preview`) hinge on the client
  NOT transmitting unset keys. Mixed semantics where the CLI sends
  empty strings or `null`s would force the daemon to distinguish
  "client sent null" from "key absent" at every gate.
- The `source` field is daemon-internal-only (FR-039); the CLI
  MUST NOT advertise it. Wire-rejection of `source` from any client
  envelope is a one-line check at the `_check_unknown_keys` gate.

**Alternatives considered**:
- Allow clients to send `null` for unset fields — rejected because
  it conflicts with the closed allowed-keys set (a `null` value
  for a forbidden key would still need to be rejected, doubling the
  validation surface).
- Separate "set" and "clear" flags (e.g. `--clear-log`) — rejected
  because attach-log's only mutable field is the path itself, and
  re-attach to a different path is the supersede contract (FR-019),
  not a clear-then-set sequence.

---

## R-003 — `tmux pipe-pane -o` semantics

**Decision**: Use `tmux pipe-pane -o -t <pane> 'cat >> <log_file>'`
for the attach (open) variant and `tmux pipe-pane -t <pane>` (no
command, no `-o`) for the toggle-off variant.

**Rationale**:
- tmux man page 3.4 documents `-o` as: "Only open a new pipe if no
  previous pipe exists, allowing a pipe to be created if it does
  not already exist but ensuring that if one does, it is not closed."
  This is exactly the FR-018 idempotent-reissue semantic: re-running
  `attach-log` against an already-piped pane is a no-op success at
  the tmux layer because `-o` refuses to reopen a live pipe.
- The toggle-off variant (`tmux pipe-pane -t <pane>` with no inner
  command and no `-o`) closes the running pipe regardless of state.
  The daemon uses this only on supersede (FR-019, when prior status
  was `active`) and on detach (FR-021c).
- Defense-in-depth: even though `-o` is idempotent at the tmux
  layer, the daemon ALSO inspects state via FR-011 before issuing
  the command, so an existing AgentTower-canonical pipe is detected
  pre-issue and the second `pipe-pane` is skipped entirely.

**Alternatives considered**:
- `tmux pipe-pane` without `-o` (the unconditional open) — rejected
  because re-attach against a live pipe would close it (toggle
  behavior), defeating idempotency and creating a moment when no
  pipe is active. `-o` is the safer default.
- Using `tmux pipe-pane -O` (uppercase, "do nothing if no previous
  pipe is open") — rejected; this is the inverse semantic
  (re-engages only if already piping) and would prevent first-time
  attach.

---

## R-004 — Host-visibility proof algorithm (FR-007)

**Decision**: The daemon implements the proof in
`logs/host_visibility.py` as follows:

1. Load `containers.mounts_json` for the bound container (FEAT-003
   already persists this as a JSON array of objects with at minimum
   `Type`, `Source`, `Destination`, `Mode`, `RW`).
2. Filter to mounts where `Type ∈ {"bind", "volume"}`. Other types
   (`tmpfs`, `npipe`) are not host-visible by definition.
3. For each candidate mount, test whether the supplied or
   generated `log_path` (the CONTAINER-side path, i.e. the path the
   `cat >>` shell will write to) starts with the mount's
   `Destination` followed by `/` (or equals it exactly).
4. On match, compute the host-side path:
   `host_side = mount["Source"] + log_path[len(mount["Destination"]):]`.
5. Resolve `host_side` via `os.path.realpath` to defeat symlink
   escape (FR-006 already rejected `..` in the user-supplied form,
   but a mount Source itself could be a symlink). Verify the
   `realpath` still lies under the resolved mount Source to reject
   symlink escape.
6. Verify the resolved path's parent directory exists on the
   daemon's local filesystem via `os.path.isdir(parent)`. The
   daemon then ensures the directory has the correct mode 0700
   (creating it if absent) and the file has mode 0600 (creating
   it if absent), per FR-008.
7. Verify `os.access(realpath_source, os.W_OK)` for the attach
   path (the daemon must be able to ensure the file exists with
   correct mode). Read-only mounts cause `attach_log` to fail with
   `log_path_not_host_visible` because the file cannot be created
   under a read-only bind. (Read-only mounts ARE valid for
   `--preview` reading, but FEAT-007 doesn't surface a
   "read-only attach" flag — operators can mount the canonical log
   directory `RW`.)
8. When multiple candidate mounts match (overlapping mounts), the
   DEEPEST `Destination` prefix wins. This is the standard mount-
   priority rule: a more specific mount shadows a more general one.
9. The canonical generated path
   `~/.local/state/opensoft/agenttower/logs/<container_id>/<agent_id>.log`
   (FR-005) must be host-visible. The daemon emits a clear
   `log_path_not_host_visible` actionable message that names the
   missing canonical bind mount when the operator's compose / run
   config doesn't include it.

**Rationale**:
- The proof must be cheap (sub-millisecond) and deterministic; the
  daemon does NOT call `docker inspect` here (FEAT-003 already
  persisted the mounts; the daemon trusts the cached JSON within
  the FEAT-003 trust boundary documented in spec § Assumptions).
- Realpath-based escape check defends against operator misconfig
  (a Source that is itself a symlink to outside-the-host area).
- Deepest-prefix-wins matches the kernel's mount-resolution behavior
  and is what an operator would expect.

**Alternatives considered**:
- Calling `docker inspect <container>` per attach — rejected; adds
  a docker round-trip (~50 ms in dev environments) and requires the
  daemon to handle docker inspect failure modes. FEAT-003's
  cached `mounts_json` is the source of truth.
- Mounting-the-bind-mount-and-testing — i.e. actually trying to
  `os.open` the host path — rejected; spec FR-008 already does
  this for the canonical case. The proof is the gate BEFORE the
  attempt; the attempt is the safety net.

---

## R-005 — Pre-attach pipe-state inspection (FR-011)

**Decision**: The daemon issues `tmux list-panes -F '#{pane_pipe}
#{pane_pipe_command}' -t <pane>` via `docker exec` (reusing the
FEAT-004 tmux adapter). The output is one line per pane in the
short form `<0|1> <command>`; the daemon parses the first whitespace-
separated token as the pipe-active flag and the remainder as the
pipe command (verbatim, may contain spaces).

**Decision branches**:
- `pane_pipe=0` → no pipe active. Issue the attach `tmux pipe-pane
  -o … 'cat >> <log>'` directly. Idempotent FR-018 protection
  comes from the daemon-side row check + the `-o` flag.
- `pane_pipe=1` AND `pane_pipe_command` STARTS WITH the AgentTower
  canonical-log-prefix `~/.local/state/opensoft/agenttower/logs/`
  (after expanding `~` to the FEAT-003-detected container_user's
  home) → already attached to canonical path. No new `pipe-pane`
  issued. Return idempotent success.
- `pane_pipe=1` AND `pane_pipe_command` does NOT match the
  canonical prefix → foreign target. Record the prior target in
  the audit row's `prior_pipe_target` field (FR-044), issue
  `tmux pipe-pane -t <pane>` (no command) to toggle off, then
  issue the attach.

**Rationale**:
- The check is one extra `docker exec` round-trip per attach call.
  At the SC-001 budget of 2 seconds P95, this is well within
  acceptable cost.
- The canonical-prefix match is a string `startswith` check; no
  regex, no heuristics. The canonical prefix is a literal constant
  in `logs/host_visibility.py`.
- Sanitizing the captured `prior_pipe_target` for the audit row
  uses the same FEAT-006 sanitization rules (NUL strip, ≤ 2048
  chars, no control bytes).

**Alternatives considered**:
- Skip the pre-check; rely on `-o` for idempotency — rejected
  because the spec requires recording `prior_pipe_target` for
  forensics on foreign-target toggle-off (FR-011, FR-044). Without
  the pre-check, the daemon can't know whether a pipe was already
  running, let alone what it targeted.
- Use `tmux display-message -p '#{pane_pipe}'` instead of
  `list-panes` — `list-panes` is what FEAT-004 already uses for
  pane discovery; reusing it keeps the tmux adapter surface narrow.

---

## R-006 — `pipe-pane` shell construction (constitution principle III)

**Decision**: The daemon builds the `docker exec` command as a
list of arguments and the inner shell command as a separately
constructed string with every interpolated value passed through
`shlex.quote`:

```python
import shlex
inner = (
    f"tmux pipe-pane -o -t {shlex.quote(pane_short_form)} "
    f"{shlex.quote(f'cat >> {shlex.quote(container_side_log)}')}"
)
argv = ["docker", "exec", "-u", container_user, container_id,
        "sh", "-lc", inner]
```

The `subprocess` call uses the argv list form (no `shell=True`).

**Rationale**:
- Constitution principle III: "shell command construction must
  never interpolate raw prompt text". Although FEAT-007 isn't
  delivering prompts, the user-controllable `--log <path>` is
  interpolated into a `cat >>` shell construct. Without
  `shlex.quote`, a path containing spaces, `$`, backticks, or `;`
  would break the inner shell command.
- FR-006 already rejects NUL bytes and C0 control bytes; `shlex.quote`
  is defense-in-depth for the remaining shell-meaningful chars.
- The pane composite key (FEAT-004 short form like `main:0.0`) is
  also `shlex.quote`d even though session/window/pane names go
  through FEAT-004's own validation; one defense layer is cheap.
- The `container_user` is the FEAT-003-detected bench user (already
  validated); not user-controllable input.

**Alternatives considered**:
- Use `shell=False` with a longer argv list — rejected; the inner
  `tmux pipe-pane … 'cat >> <log>'` requires shell because the
  `>>` redirection is a shell operator. The only alternative is to
  abandon `pipe-pane` and stream tmux's stdout to a host file via
  `docker exec` directly, which doesn't match the architecture's
  documented MVP approach.
- Use Python's `shlex.join` — rejected; `shlex.join` is fine for
  building a complete shell line, but the construction is more
  legible with explicit `shlex.quote` per interpolation.

---

## R-007 — Per-`log_path` mutex registry (FR-041)

**Decision**: A new `LogPathLockMap` class in `logs/mutex.py`
mirrors the FEAT-006 `_PerKeyLockMap` generic implementation but
keys on the canonical host-side log path (str). Production code
acquires this lock when an explicit `--log <path>` is supplied
(FR-041 collision check); when the daemon is using the FR-005
generated canonical path, no `log_path_locks` acquisition is
needed because the path is already keyed on `agent_id` and the
per-`agent_id` lock (reused from FEAT-006 `agent_locks`) already
serializes.

**Rationale**:
- FR-041 says "Concurrent attach_log calls for DIFFERENT agents
  whose explicit --log paths COLLIDE … MUST be serialized through
  a per-log_path mutex". Reusing FEAT-006's `_PerKeyLockMap` keeps
  the implementation cost ≈ 5 lines (subclass with a different key
  type).
- The lock is acquired AFTER the per-`agent_id` lock to maintain
  consistent lock ordering (agent → path) and avoid deadlock on
  same-agent same-path concurrent calls. (Same-agent same-path is
  already serialized by the per-`agent_id` lock; the per-`log_path`
  lock only matters for DIFFERENT agents.)
- The map grows with the number of distinct `log_path` values;
  entries are not evicted (memory overhead is bounded by MVP scale,
  same as FEAT-006).

**Alternatives considered**:
- Single global lock for all attach-log calls — rejected; would
  serialize unrelated agents and inflate SC-001's 2-second budget.
- Use SQLite `BEGIN IMMEDIATE` as the only collision detector
  (no per-`log_path` mutex) — rejected; spec FR-041 explicitly
  requires a per-`log_path` mutex AND SQLite serialization,
  because the "first wins" surface needs both an in-process race
  detector and a database-level race detector to avoid the second
  call wasting a `docker exec` before SQLite rejects it.

---

## R-008 — Cross-subsystem ordering with FEAT-004 (FR-042)

**Decision**: The FEAT-004 pane reconciliation transaction in
`discovery/pane_reconcile.py` is extended to also UPDATE
`log_attachments` rows bound to a pane that transitioned from
active to inactive. The UPDATE flips `status='active'` →
`status='stale'` and emits one `log_attachment_change` audit row
per affected attachment, all within the same `BEGIN IMMEDIATE`
transaction as the pane reconcile write. The FEAT-004 reconcile
does NOT acquire any FEAT-007 mutex (per the pattern established
in FEAT-006 / Clarifications session 2026-05-07-continued Q4 for
the agent table's `last_seen_at` updates).

**Rationale**:
- SQLite `BEGIN IMMEDIATE` provides writer-serialization at the
  database level; concurrent `attach_log` and `pane_reconcile`
  transactions cannot both touch the same `log_attachments` row;
  the last committed wins.
- The FR-042 invariant — "stale-attachment detection (FR-021
  transition active → stale) MUST happen INSIDE the FEAT-004
  reconcile transaction so a concurrent attach_log can never commit
  a fresh active row that is immediately invalidated" — is
  satisfied because the reconcile transaction commits the
  `pane.active=0` write and the `log_attachments.status='stale'`
  write atomically; an `attach_log` that won the per-`agent_id`
  lock and is BEHIND the reconcile in BEGIN IMMEDIATE ordering will
  observe the new `pane.active=0` state and refuse with
  `pane_unknown_to_daemon` (FR-003).
- The audit-row append for the system-driven transition is OK
  because FR-044 makes the audit log capture every status
  transition, and the audit row's `source` field carries `explicit`
  (per the closed set `{explicit, register_self}`); the source set
  intentionally does NOT distinguish "operator" from "system" — it
  distinguishes the call-path (standalone CLI vs. inside register-
  self). System-driven transitions reuse `explicit`.

**Alternatives considered**:
- Add a `system` source value — rejected; the closed set is
  small and fixed by FR-039. Adding a third value would require
  bumping `schema_version` for the audit-row schema. The
  transition's PROVENANCE is already captured by the audit row's
  context (a stale transition emitted from the reconcile path is
  correlated with a `pane_state_change` lifecycle event from
  FEAT-004 in the same wall-clock instant).
- Have FEAT-004 reconcile acquire a FEAT-007 mutex — rejected;
  this is exactly the cross-subsystem coupling the FEAT-006
  design avoided by relying on SQLite's BEGIN IMMEDIATE.

---

## R-009 — `socket_peer_uid` plumbing (reused from FEAT-006)

**Decision**: Reuse FEAT-006's SO_PEERCRED plumbing verbatim. The
FEAT-002 socket server already exposes the connecting client's
uid via `socket.getsockopt(SO_PEERCRED)`; FEAT-006 plumbs it into
the audit-row payload. FEAT-007 plugs into the same mechanism in
`logs/audit.py`.

**Rationale**: zero new infrastructure; one line in the audit-row
serializer.

**Alternatives considered**: none — the alternative is to omit
`socket_peer_uid` from the FEAT-007 audit row, which would break
the FEAT-006 spec parallelism (every audit row carries this
field for forensic attribution).

---

## R-010 — File inode and size tracking

**Decision**: The daemon's `logs/host_fs.py` module exposes:

```python
def stat_log_file(host_path: str) -> Optional[FileStat]: ...
class FileStat:
    inode: int
    size: int
    mtime_iso: str  # microsecond-precision UTC
```

Implementation calls `os.stat(host_path, follow_symlinks=False)`
on Linux/WSL; `st_ino` becomes `inode`, `st_size` becomes `size`,
`st_mtime` is converted to an ISO-8601 microsecond UTC string via
`datetime.datetime.fromtimestamp(stat.st_mtime,
tz=datetime.timezone.utc).isoformat(timespec='microseconds')`. On
file-missing, returns `None`. Honors
`AGENTTOWER_TEST_LOG_FS_FAKE` for integration tests.

**Rationale**:
- Linux/WSL inode identity is sufficient for FR-024 / FR-025
  rotation detection; the spec mentions `(device, inode)` pair
  "on systems that distinguish" — Linux's single inode is fine.
  Storing `device` as well costs one extra column and makes
  FEAT-007 portable to BSD/MacOS later if needed; we elect to
  store `(device, inode)` as a `device_inode_str` column shaped
  `f"{st_dev}:{st_ino}"` to keep one INTEGER comparison fast and
  avoid future schema bumps. Production code initializes
  `device_inode_str = "<dev>:<ino>"` and reads it back via string
  equality (FR-025's "changed inode" check is `before != after`).
- `follow_symlinks=False`: defends against operator-supplied paths
  that resolve to a symlink the daemon doesn't expect; the FR-007
  proof already forbids symlink escape, but stat'ing the target
  vs. the link is a minor footgun avoided.

**Alternatives considered**:
- Store inode and device as separate INTEGER columns — rejected;
  more verbose and the spec field naming is `file_inode` (single
  identifier) per the schema. Storing as `device:inode` string
  satisfies the spec while preserving cross-platform fidelity.

---

## R-011 — File-mode invariants (FR-008)

**Decision**: At attach time, the daemon ensures the canonical
host directory exists with mode 0700:

```python
parent = os.path.dirname(host_log_path)
if not os.path.exists(parent):
    os.makedirs(parent, mode=0o700, exist_ok=True)
verify_dir_mode(parent, 0o700)  # reuses FEAT-001 helper
```

If the directory already exists, the daemon reads its mode and
REFUSES to broaden it (per FR-008 "MUST NOT broaden either mode if
the directory or file already exists"). A directory with mode
broader than 0700 surfaces as `internal_error` with a clear
actionable message naming the path; the daemon does NOT auto-fix.

For the file:

```python
if not os.path.exists(host_log_path):
    fd = os.open(host_log_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL,
                 mode=0o600)
    os.close(fd)
verify_file_mode(host_log_path, 0o600)
```

Race-free creation via `O_EXCL`; `verify_file_mode` reuses the
FEAT-001 helper.

**Rationale**:
- Reuses FEAT-001's existing `_verify_file_mode` / `_verify_dir_mode`
  helpers; no new mode-handling code.
- `O_EXCL` prevents a TOCTOU race between `os.path.exists` and
  `os.open`.
- Refusing to widen broader-than-expected modes preserves the
  FEAT-001 invariant that the daemon never silently mutates user-
  set permissions.

**Alternatives considered**:
- Use `pathlib.Path.touch(mode=0o600, exist_ok=False)` — rejected;
  `Path.touch` doesn't support `O_EXCL` semantics across all
  Python versions consistently. Direct `os.open` is the proven
  primitive (FEAT-001 already uses it).

---

## R-012 — Redaction pattern compilation (FR-027–FR-030)

**Decision**: `logs/redaction.py` exposes one public function
`redact_lines(text: str) -> str` that:

1. Splits `text` on `\n` (no `splitlines` — `splitlines` interprets
   `\r` as a line separator, breaking the byte-fidelity contract
   for tmux pipe-pane output, which uses `\n`).
2. For each line, applies `_UNANCHORED_PATTERNS` first (each is a
   compiled `re.Pattern` with `re.ASCII` flag, applied via
   `pattern.sub(replacement, line)`), then applies
   `_ANCHORED_PATTERNS` second (each is a compiled `re.Pattern`
   with `re.ASCII | re.DOTALL` and a `^…$` regex; applied via
   `pattern.fullmatch(line)` and replacement only on full match).
3. Joins the redacted lines with `\n` and returns.

The pattern table is module-level constants:

```python
_UNANCHORED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b", re.ASCII), "<redacted:openai-key>"),
    (re.compile(r"\bgh[ps]_[A-Za-z0-9]{20,}\b", re.ASCII), "<redacted:github-token>"),
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b", re.ASCII), "<redacted:aws-access-key>"),
    (re.compile(r"\bBearer ([A-Za-z0-9_\-\.=]{16,})", re.ASCII), "Bearer <redacted:bearer>"),
)
_ANCHORED_PATTERNS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", re.ASCII),
     lambda m: "<redacted:jwt>" if len(m.group(0)) >= 32 else m.group(0)),
    (re.compile(r"^([A-Z_][A-Z0-9_]*(API_?KEY|TOKEN|SECRET|PASSWORD|AUTH))=(.+)$", re.ASCII),
     lambda m: f"{m.group(1)}=<redacted:env-secret>"),
)
```

**Rationale**:
- `re.ASCII` ensures `\b`/`\w`/`\W` are bytewise-defined; without
  it Python 3 defaults to Unicode-aware regex semantics, which
  could surprise on operator locales. Spec FR-029 mandates this.
- Module-level pre-compilation amortizes regex compilation across
  all preview / future event-excerpt calls — important for the
  SC-004 / SC-010 1000-iteration determinism budget.
- The JWT 32-char minimum is enforced by the lambda (regex-only
  enforcement would require a back-reference to count total
  length; the lambda is clearer and equivalent).
- Splitting on `\n` (not `splitlines`) preserves the FR-029
  invariant that the redaction utility never crosses a `\n`.

**Alternatives considered**:
- Single mega-regex with alternation — rejected; harder to test,
  and the per-pattern `re.sub` calls are already negligible
  overhead at the 200-line preview cap.
- Apply anchored patterns FIRST then unanchored — rejected;
  the spec § FR-028 documents "unanchored first, then anchored"
  ordering, and on real inputs they are mutually exclusive (an
  anchored line is never partially matched by an unanchored
  pattern that requires `\b` boundaries inside what the anchored
  pattern claims as the entire line).

---

## R-013 — Test seam `AGENTTOWER_TEST_LOG_FS_FAKE`

**Decision**: A new env var `AGENTTOWER_TEST_LOG_FS_FAKE` is read
by `logs/host_fs.py` at module load time. When set to a path, the
file at that path is read once and parsed as JSON of shape:

```json
{
  "<host_path>": {
    "exists": true,
    "inode": 12345,
    "size": 4096,
    "contents": "..."
  },
  "<another_path>": { "exists": false }
}
```

Production code paths (`stat_log_file`, `read_tail_lines`,
`ensure_directory_mode`, etc.) consult this map BEFORE calling
real OS syscalls. When the env var is absent, the module uses
real `os.stat` / `os.path.exists` / `os.access` / `open`.

**Rationale**:
- Mirrors the existing FEAT-003 `AGENTTOWER_TEST_DOCKER_FAKE` and
  FEAT-004 `AGENTTOWER_TEST_TMUX_FAKE` patterns: a single env-var
  switch, JSON-shaped fixture, no monkeypatching, no plumbing
  through fixture parameters.
- Allows integration tests to simulate file truncation, recreation,
  deletion, and reappearance deterministically — without real
  filesystem inode races that flake on slow CI runners.
- The seam is constrained: only `logs/host_fs.py` reads it. No
  other module touches the env var; no production code path
  changes behavior based on its presence beyond the host_fs
  adapter.

**Alternatives considered**:
- Pytest monkeypatch of `os.stat` / `os.path.exists` — rejected;
  monkeypatching globals is invasive and breaks parallelism.
- Use a real `tmpfs`-backed fixture filesystem — rejected; cannot
  control inode values directly, complicating FR-025 inode-
  change tests.

---

## R-014 — Orphan recovery on daemon startup (FR-043)

**Decision**: At daemon startup (after schema migration completes,
before the socket listener begins accepting requests), the daemon
runs `logs/orphan_recovery.detect_orphans()`:

1. For each `containers` row with `active=1`, issue
   `tmux list-panes -F '#{session_name}:#{window_index}.#{pane_index} #{pane_pipe} #{pane_pipe_command}' -a` via the FEAT-004 tmux adapter.
2. For each pane with `pane_pipe=1`, parse `pane_pipe_command`. If
   it `startswith` the AgentTower canonical-log-prefix, look up
   the corresponding `log_attachments` row by container_id +
   pane composite key.
3. If no matching row exists, emit one
   `log_attachment_orphan_detected` lifecycle event with
   `container_id`, pane composite key, and observed pipe target.
4. NEVER auto-attach. The startup pass is observation-only.

The pass blocks daemon startup at most for one per-container
`tmux list-panes` round-trip (~50 ms per container in dev). It
is bounded by the number of running bench containers (MVP scale:
one or two).

**Rationale**:
- FR-043 is explicit: "MUST NOT auto-attach orphans (operator
  action required to avoid silently re-binding under unknown
  conditions)". The startup pass is the surface that lets the
  operator know an orphan exists; their `attach-log` call binds
  it deliberately.
- Running the pass at startup (post-migration, pre-listener)
  rather than on every `attach-log` keeps the startup cost
  bounded and the steady-state cost zero.

**Alternatives considered**:
- Run the pass on every `tmux list-panes` socket call — rejected;
  high steady-state cost, and operators don't `list-panes` often
  enough to drive observability.
- Run the pass periodically in a background timer — rejected;
  introduces a new timer surface; FEAT-007's spec doesn't require
  it. FEAT-008 will likely have its own reader timer; orphan
  detection can ride on that later if needed.
