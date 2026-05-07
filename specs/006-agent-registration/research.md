# Phase 0 Research: Agent Registration and Role Metadata

**Branch**: `006-agent-registration` | **Date**: 2026-05-07

This document records the research decisions that resolve every
NEEDS CLARIFICATION in `plan.md`'s Technical Context. Each entry
captures Decision, Rationale, and Alternatives Considered.

---

## R-001 — `agent_id` shape and entropy

**Decision**: `agent_id = "agt_" + secrets.token_hex(6)` →
`agt_<12-character-lowercase-hex>` (96 bits of entropy).

**Rationale**:
- FR-001 fixes the format; this is the implementation that
  satisfies it.
- `secrets.token_hex(6)` returns 12 lowercase hex chars on every
  Python 3.11+ build (stdlib, no third-party dependency).
- 96 bits of entropy makes accidental collisions vanishingly
  unlikely at MVP scale (< 10⁻¹⁵ probability for < 10⁹ ids by the
  birthday bound — well above the design ceiling).
- The literal `agt_` prefix is human-recognizable in CLI output
  and prevents collision with FEAT-003 container ids (no prefix)
  or FEAT-004 pane ids (`%N`).

**Collision handling**: A bounded retry loop (≤ 5 attempts) inside
the per-(container_id, pane_composite_key) registration mutex.
Each attempt generates a fresh id and tries the SQLite INSERT;
SQLite raises `IntegrityError` on the PK conflict. Exhausted
budget surfaces as `internal_error` (FR-035) and the daemon
stays alive. Five attempts is overwhelmingly conservative: the
expected number of retries at MVP scale is essentially zero.

**Alternatives considered**:
- ULID / UUIDv7 — adds a third-party dependency *or* a stdlib
  port; the visible benefit (sortable ids) does not apply here
  because list ordering is by `(active, container_id, parent,
  label, agent_id)` per FR-025, not creation time.
- `secrets.token_urlsafe(8)` — variable URL-safe alphabet, less
  readable, and the `_`/`-` chars complicate downstream grep
  patterns.
- Larger entropy (16 hex / 24 hex) — unnecessary at MVP scale;
  spec FR-001 locks 12 hex.

---

## R-002 — Mutable-field wire encoding (Clarifications Q1)

**Decision**: Argparse uses `argparse.SUPPRESS` as the default for
every mutable flag (`--role`, `--capability`, `--label`,
`--project`, `--parent`). When the user does not pass a flag, the
key is *absent* from the parsed `Namespace` and therefore absent
from the JSON request envelope. The daemon treats absent keys as
"leave unchanged" per FR-007. On *first* registration of a brand-
new pane, the CLI applies argparse-style defaults
(`role="unknown"`, `capability="unknown"`, `label=""`,
`project_path=""`) before sending; absent vs. default is decided
by checking whether the agent record already exists for the
caller's pane composite key (one `list_panes` lookup) — if it
exists, defaults are NOT applied.

**Wire shape (request envelope, FR-024)**:

```json
{
  "method": "register_agent",
  "params": {
    "container_id": "<full-id-from-FEAT-005>",
    "pane_composite_key": {
      "container_id": "<full-id>",
      "tmux_socket_path": "/tmp/tmux-1000/default",
      "tmux_session_name": "main",
      "tmux_window_index": 0,
      "tmux_pane_index": 0,
      "tmux_pane_id": "%17"
    },
    "role": "slave",                 // OPTIONAL — absent means "leave unchanged" on existing agent; on first registration, CLI applies default "unknown" if absent
    "capability": "codex",           // OPTIONAL — same semantics
    "label": "codex-01",             // OPTIONAL — same semantics
    "project_path": "/workspace/acme", // OPTIONAL — same semantics
    "parent_agent_id": "agt_aaaaaa"  // OPTIONAL — same semantics; on existing agent, MUST match stored value or rejection per FR-018a
  }
}
```

**Daemon-side**: the `register_agent` handler enumerates the
expected key set; unknown keys are rejected with `bad_request`.
For each known key, `key in params` distinguishes "supplied" from
"absent". On *creation* (no row exists for the composite key),
absent keys fall back to argparse-style defaults applied
*server-side* as well so the CLI/daemon agree on the contract;
on *update* (row exists), absent keys leave the stored value
intact.

**Rationale**:
- Clarifications 2026-05-07 Q1 locks Option B: omitted flags
  leave stored values unchanged; preserves master/slave roles
  across routine re-`register-self`.
- `argparse.SUPPRESS` is the documented stdlib idiom for "do not
  insert a default into the namespace when the user does not
  pass this flag" — no custom sentinel needed.
- Distinguishing "user passed `--role unknown`" (overwrite) from
  "user did not pass `--role`" (leave unchanged) is a hard
  requirement of Q1 and falls out naturally from `SUPPRESS` +
  explicit dict membership check.

**Alternatives considered**:
- Custom sentinel (`_OMITTED = object()`) — works but adds
  bookkeeping; `SUPPRESS` already provides the same semantics.
- Always-transmit defaults (Option A from Q1) — explicitly
  rejected in clarification because of silent demotion risk.
- Daemon-side defaults only on creation, never on update —
  adopted as a refinement; the CLI also applies defaults on
  creation so the wire contract is symmetric and the daemon
  can validate the request without re-deriving "is this
  creation or update".

---

## R-003 — `last_seen_at` ownership and update path

**Decision**: `last_seen_at` is updated exclusively by the
FEAT-004 pane reconciliation transaction. Every reconciliation
that observes a pane composite key as `active=true` runs an
`UPDATE agents SET last_seen_at = :scan_time WHERE container_id = ? AND tmux_socket_path = ? AND ...`
in the same `BEGIN IMMEDIATE` transaction as the pane row
upsert. Reconciliations that fail to observe the pane (or
observe it as inactive) MUST NOT update `last_seen_at`. CLI
codepaths (`list_agents`, `register_agent` no-op,
`set_role`/`set_label`/`set_capability`) MUST NOT touch
`last_seen_at`.

**Rationale**:
- Clarifications 2026-05-07 Q2 locks Option A.
- Independent of `last_registered_at` — the former is
  passive observation (FEAT-004 scanner saw the pane), the
  latter is explicit registration intent.
- Single-writer semantics keep the field meaningful: there is
  exactly one codepath that writes it.
- The wiring is contained to `discovery/pane_reconcile.py` and
  is purely additive — the existing pane upsert already runs
  under a transaction, so the agent UPDATE rides along.

**Implementation**:
- `discovery/pane_reconcile.py` already groups pane upserts by
  `(container_id, tmux_socket_path)` for one transaction per
  socket. After the existing pane upsert, run one parameterised
  `UPDATE agents SET last_seen_at = :scan_time WHERE
  (container_id, tmux_socket_path, tmux_session_name,
  tmux_window_index, tmux_pane_index, tmux_pane_id) IN (...)`
  for the set of observed-active panes in that batch. The
  index `agents_pane_lookup` (data-model.md §2) covers this
  predicate.
- Active→inactive transitions cascade to `agents.active = 0`
  in the same transaction (FR-009).
- Inactive→active does NOT auto-flip `agents.active` —
  explicit `register-self` is required (FR-009).

**Alternatives considered**:
- CLI updates `last_seen_at` on every successful daemon call
  (Option B) — rejected because `list_agents` is read-only and
  `set_*` are operator events, not liveness signals.
- Defer to FEAT-007 / FEAT-008 (Option D) — rejected because
  `list-agents` benefits from a meaningful liveness column in
  MVP without waiting on later features.

---

## R-004 — Schema migration v3 → v4

**Decision**: Add exactly one migration function
`_apply_migration_v4(conn)` to `state/schema.py`, registered as
`_MIGRATIONS[4]`, and bump `CURRENT_SCHEMA_VERSION` from `3` to
`4`. The migration is idempotent (every `CREATE TABLE` and
`CREATE INDEX` uses `IF NOT EXISTS`), runs inside the existing
`_apply_pending_migrations` function under one
`BEGIN IMMEDIATE` transaction, rolls back the entire transaction
on failure, and refuses to serve the daemon on rollback. v3-only
DBs upgrade in one transaction; v4-already-current DBs re-open
as no-ops via the `IF NOT EXISTS` guards (the existing
`_ensure_current_schema` already calls every migration body
defensively for the current version, see `schema.py:236-237`).

**Rationale**:
- FR-036 mandates idempotent, single-transaction migration that
  bumps `schema_version` only after the new table exists.
- FR-037 forbids modifying FEAT-001..004 schemas.
- The existing migration framework supports this pattern
  verbatim — see `_apply_migration_v2` (FEAT-003) and
  `_apply_migration_v3` (FEAT-004) in `state/schema.py:28-154`.

**Alternatives considered**:
- Multi-step migration (separate table + indexes) — rejected
  because the `IF NOT EXISTS` guards already handle re-open; a
  single migration function is consistent with v2 and v3.
- Skip indexes (add only the table) — rejected because
  `list_agents` deterministic ordering (FR-025) and the
  `last_seen_at` UPDATE in pane reconciliation (R-003) both
  benefit from indexes; see data-model.md §3 for the index
  list.

---

## R-005 — Mutex layout and lifetime

**Decision**: Two in-process `dict[key, threading.Lock]` maps
managed by `agents/service.py`, guarded by a `threading.Lock`
that protects the *map* (not the per-key locks). Acquire the
map-lock briefly to fetch-or-create the per-key lock; release
the map-lock; acquire the per-key lock; do the SQLite work;
release the per-key lock.

- `register_locks: dict[(container_id, tmux_socket_path,
  tmux_session_name, tmux_window_index, tmux_pane_index,
  tmux_pane_id), threading.Lock]` — for `register_agent`
  (FR-038).
- `agent_locks: dict[agent_id, threading.Lock]` — for
  `set_role`, `set_label`, `set_capability` (FR-039).

Per-key locks are never evicted during the daemon process
lifetime. Memory overhead is bounded by the number of distinct
panes ever registered (MVP scale: tens to low hundreds), so a
small constant per entry is acceptable.

**Rationale**:
- FR-038 / FR-039 require serialization per pane composite key
  and per agent_id respectively.
- SQLite's single-writer semantics serialize commits internally,
  but the read-modify-write of `effective_permissions` (compute
  from current role; UPDATE) needs an in-process advisory mutex
  to prevent a lost update.
- The dict-of-locks pattern is a stdlib idiom; no third-party
  dependency.

**Alternatives considered**:
- Single global mutex — rejected because FR-038 explicitly
  requires concurrent registrations from *different* panes to
  proceed in parallel.
- LRU eviction of per-key locks — rejected because eviction
  while a thread holds a lock is a footgun; MVP-scale memory
  use is negligible.
- SQLite `BEGIN EXCLUSIVE` only — rejected because while the
  SQL transaction is exclusive, the Python-side
  read-modify-write (compute new `effective_permissions` JSON
  from role) is not, and would require begin-retry on busy
  errors.

---

## R-006 — Audit record schema and append site

**Decision**: One JSONL row per successful role transition
appended to the existing FEAT-001 `events.jsonl` file via the
existing `events/writer.py` helper. The row shape:

```json
{
  "event_type": "agent_role_change",
  "ts_utc": "2026-05-07T14:30:00.000000+00:00",
  "agent_id": "agt_abc123def456",
  "prior_role": null,
  "new_role": "slave",
  "confirm_provided": false,
  "socket_peer_uid": 1000
}
```

`prior_role` is the JSON literal `null` on first registration
of an agent (Clarifications 2026-05-07 Q4); on subsequent
transitions it is the previous string value.
`confirm_provided` is `true` only on `set-role --role master
--confirm`; for every other path it is `false`.
`socket_peer_uid` comes from the FEAT-002 socket peer-cred
lookup (`SO_PEERCRED`) the daemon already performs.

**No-op rule**: A `set_*` call where the new value equals the
stored value is a successful no-op and MUST NOT append a new
row (FR-027). A `register_agent` call where the resolved
post-merge role equals the stored role MUST NOT append a new
row. Only writes that actually transition `agents.role` from
one value to another (including `null → X` on creation) are
logged.

**Rationale**:
- FR-014 + Clarifications Q4 lock the shape including
  `prior_role: null` on creation.
- Reusing `events.jsonl` keeps the on-disk audit footprint to
  one file (Assumptions in spec.md).
- The `events/writer.py` lock + atomic-append helper is already
  thread-safe.

**Alternatives considered**:
- Separate `agents.jsonl` audit file — rejected by Assumptions
  ("FEAT-006 MUST NOT introduce a new audit log file").
- Log every write (incl. no-op) — rejected by FR-027.

---

## R-007 — Focused per-container rescan invocation (FR-041)

**Decision**: When `register_agent` resolves a pane composite
key that is not in the `panes` table (or is in the table with
`active=false`), the handler invokes the existing FEAT-004
`PaneDiscoveryService.scan(container=<resolved_container_id>)`
codepath — a single-element container set — exactly once.
The rescan inherits FEAT-004's 5-second per-call timeout
verbatim. After the rescan, the handler re-queries the
`panes` table; if the pane appears as `active=true`, the
registration proceeds; otherwise it refuses with
`pane_unknown_to_daemon` (FR-041).

**Rationale**:
- FR-041 mandates exactly one focused rescan, scoped to the
  caller's container, reusing the FEAT-004 codepath.
- FEAT-004's `PaneDiscoveryService.scan()` already accepts a
  container filter; FEAT-006 calls it with a single-element
  set rather than introducing a new "scan-one-container" API
  (per Assumptions in spec.md).
- The 5-second timeout is FEAT-004's existing per-call budget;
  no new constant is introduced.

**Implementation note**: The handler MUST NOT cascade to other
containers (FR-041) — the rescan call site explicitly passes
`{caller_container_id}` as the container set. If FEAT-004 ever
adds a request-scoped scan-one-container API, FEAT-006 SHOULD
adopt it (Assumptions).

**Alternatives considered**:
- Trigger a global `scan_panes` — rejected by FR-041.
- Refuse without rescan — rejected by FR-041 (the spec
  explicitly requires exactly one rescan attempt).

---

## R-008 — `effective_permissions` materialization

**Decision**: Materialized as a JSON column on every agent
row, recomputed on every write that mutates `role`. The pure
function `agents.permissions.effective_permissions(role: str)
-> dict` returns the closed-set object per FR-021 across all
six roles. The function is the single source of truth; both
the daemon-side write path and any read path that
constructs the JSON column use the same function.

| Role          | can_send | can_receive | can_send_to_roles |
| ------------- | -------- | ----------- | ----------------- |
| `master`      | true     | false       | `["slave", "swarm"]` |
| `slave`       | false    | true        | `[]` |
| `swarm`       | false    | true        | `[]` |
| `test-runner` | false    | false       | `[]` |
| `shell`       | false    | false       | `[]` |
| `unknown`     | false    | false       | `[]` |

**Rationale**:
- FR-021 fixes the derivation; this is a direct lookup.
- Materializing on the row (rather than computing at read time)
  keeps `list_agents` read-only and fast — the JSON column is
  ready for `--json` output verbatim (FR-022).
- FR-022 forbids FEAT-006 from consuming the value; the column
  exists for FEAT-009 / FEAT-010 to read.

**Alternatives considered**:
- Compute at read time — rejected because `list_agents` is
  read-only and a derived column avoids per-row Python
  computation.
- Store as separate boolean columns + JSON-array column —
  rejected because FR-021 specifies a single JSON object
  `effective_permissions`; downstream features parse one
  field, not three.

---

## R-009 — `list-agents` deterministic ordering (FR-025)

**Decision**: SQL `ORDER BY active DESC, container_id ASC, parent_agent_id ASC NULLS FIRST, label ASC, agent_id ASC`.
SQLite supports `NULLS FIRST` since 3.30 (default behavior on
ASC is NULLS FIRST without the explicit clause; the explicit
clause is included for portability and code clarity).

**Index**: `CREATE INDEX agents_active_order ON agents(active DESC, container_id ASC, parent_agent_id ASC, label ASC, agent_id ASC)` —
covers the ordering predicate without requiring a sort step.

**Rationale**:
- FR-025 fixes the order.
- An explicit covering index keeps `list_agents` constant-time
  per row at MVP scale.
- `NULLS FIRST` ensures non-swarm agents (NULL parent) come
  before swarm agents within the same container/parent
  grouping — useful for human readers scanning the TSV form.

**Alternatives considered**:
- Sort in Python — rejected because the SQL ORDER BY is
  trivial and deterministic across all SQLite versions
  AgentTower targets.

---

## R-010 — Closed-set error code addition

**Decision**: Add the FEAT-006 closed-set codes to
`socket_api/errors.py` as new `Final[str]` constants and
extend `CLOSED_CODE_SET` with the union. The new codes are:

```text
HOST_CONTEXT_UNSUPPORTED        = "host_context_unsupported"
CONTAINER_UNRESOLVED            = "container_unresolved"
NOT_IN_TMUX                     = "not_in_tmux"
TMUX_PANE_MALFORMED             = "tmux_pane_malformed"
PANE_UNKNOWN_TO_DAEMON          = "pane_unknown_to_daemon"
AGENT_NOT_FOUND                 = "agent_not_found"
AGENT_INACTIVE                  = "agent_inactive"
PARENT_NOT_FOUND                = "parent_not_found"
PARENT_INACTIVE                 = "parent_inactive"
PARENT_ROLE_INVALID             = "parent_role_invalid"
PARENT_ROLE_MISMATCH            = "parent_role_mismatch"
PARENT_IMMUTABLE                = "parent_immutable"
SWARM_PARENT_REQUIRED           = "swarm_parent_required"
SWARM_ROLE_VIA_SET_ROLE_REJECTED = "swarm_role_via_set_role_rejected"
MASTER_VIA_REGISTER_SELF_REJECTED = "master_via_register_self_rejected"
MASTER_CONFIRM_REQUIRED         = "master_confirm_required"
VALUE_OUT_OF_SET                = "value_out_of_set"
FIELD_TOO_LONG                  = "field_too_long"
PROJECT_PATH_INVALID            = "project_path_invalid"
UNKNOWN_FILTER                  = "unknown_filter"
SCHEMA_VERSION_NEWER            = "schema_version_newer"
```

`DAEMON_UNAVAILABLE` is *not* added to the daemon-side closed
set because it is a CLI-side classification — the daemon
never sees the call. CLI code maps connect-time failures to
`daemon_unavailable` per FR-032 (FEAT-002 inheritance).

**Rationale**:
- FR-040 lists the closed set; this is the implementation
  mapping.
- Existing FEAT-002/003/004 codes are unchanged byte-for-byte
  (SC-010).
- `CLOSED_CODE_SET` is the runtime guard that prevents typos
  from leaking unknown codes onto the wire (`make_error`
  raises `ValueError` on unknown code).

**Alternatives considered**:
- Reuse FEAT-002 `BAD_REQUEST` for input validation —
  rejected because the spec mandates closed-set codes that
  appear verbatim in `--json` output (FR-040), and
  downstream tooling needs to distinguish
  `value_out_of_set` from `field_too_long` from
  `project_path_invalid` etc.

---

## R-011 — CLI subcommand naming and dispatcher

**Decision**: Five new top-level subparsers under the existing
`agenttower` parser:

- `agenttower register-self`
- `agenttower list-agents`
- `agenttower set-role`
- `agenttower set-label`
- `agenttower set-capability`

Each subcommand routes through the existing FEAT-005
socket-resolution chain (`AGENTTOWER_SOCKET` → in-container
default → host default; `paths.resolve_socket_path`) and the
existing FEAT-002 client (`socket_api/client.py`).

**Rationale**:
- Spec FR-028..FR-031 fix the CLI names.
- Top-level subparsers (rather than `agenttower agents
  register`) match the existing FEAT-002 / FEAT-003 / FEAT-004
  pattern: `ensure-daemon`, `daemon`, `scan-containers`,
  `list-containers`, `scan-panes`, `list-panes`,
  `config doctor`, etc.

**Alternatives considered**:
- Group under `agenttower agents <verb>` — rejected for
  consistency with sibling top-level commands.
- Use hyphens vs underscores in subcommand names — hyphens
  match every existing FEAT-001..005 subcommand.

---

## R-012 — Daemon-side request validation order

**Decision**: For every method, validate in this order before
acquiring any mutex:

1. Schema-version forward-compat check (refuse with
   `schema_version_newer` if daemon is older than the request
   shape — defensive; in practice the CLI will refuse first).
2. Closed-set field shape (role, capability in closed sets;
   `agent_id` matches `agt_<12-hex>`; `parent_agent_id` matches
   shape; filter keys belong to known set).
3. Free-text bounds and sanitization (FR-033 / FR-034) on
   `label`, `project_path`.
4. Master-safety static rejection (`register_agent` rejects
   `--role master`; `set_role` requires `--confirm` for master,
   rejects swarm).
5. Acquire the appropriate per-key advisory mutex.
6. Read current state inside the mutex.
7. Validate dynamic invariants (parent exists, parent is
   active, parent role is `slave`; agent exists; agent active;
   container active for master promotion;
   `parent_agent_id` immutability).
8. Compute the effective post-write state.
9. Single SQLite transaction: write agent row, write
   `effective_permissions`, append JSONL audit row (if a real
   transition).
10. Release the mutex.

**Rationale**:
- Validating before mutex acquisition keeps mutex hold times
  short.
- Closed-set validation is cheap; running it first surfaces
  obvious errors fast.
- Master-safety static rejection (4) is intentionally before
  mutex acquisition — these calls never need to inspect
  database state.
- Steps 5–10 are the read-modify-write window that needs the
  per-key mutex (R-005).

**Alternatives considered**:
- Validate inside the mutex — rejected because static
  validation does not need any locked state and would
  needlessly extend mutex hold times.

---

## R-013 — Test seam reuse

**Decision**: Reuse the existing FEAT-003 / FEAT-004 / FEAT-005
test seams verbatim:

- `AGENTTOWER_TEST_DOCKER_FAKE` — FEAT-003 fake `docker`
  invocation outputs.
- `AGENTTOWER_TEST_TMUX_FAKE` — FEAT-004 fake `tmux` invocation
  outputs.
- `AGENTTOWER_TEST_PROC_ROOT` — FEAT-005 fake `/proc` + `/etc`
  fixture root.

No new test seam is introduced. FEAT-006 integration tests
seed:

1. The `containers` table via FEAT-003 fakes (one or more
   active bench containers).
2. The `panes` table via FEAT-004 fakes (one or more active
   panes per container).
3. The CLI process environment via `AGENTTOWER_TEST_PROC_ROOT`
   to simulate "running inside that container, in that pane"
   for FEAT-005 identity detection.
4. The `agents` table is left empty at test start (or seeded
   with one slave for the swarm-child story).

**Rationale**:
- FR-044 / SC-012 mandate that FEAT-006 be testable end-to-end
  without a real Docker daemon, real container, or real tmux
  server.
- The three existing seams already cover every external
  surface FEAT-006 touches.
- Adding a new seam would add maintenance burden without a
  concrete need.

**Alternatives considered**:
- Add a `AGENTTOWER_TEST_AGENTS_FAKE` env var that pre-seeds
  the `agents` table — rejected because the SQLite layer is
  the canonical seed point in tests; pre-seeding via direct
  SQL in `_daemon_helpers.py` is clearer than a new env var.

---

## R-014 — `--target` resolution

**Decision**: `agenttower set-role`, `set-label`, and
`set-capability` accept `--target <agent-id>` as required input.
The CLI passes the value verbatim over the wire; the daemon
validates the shape (`agt_<12-hex>` regex), then looks up the
row by `agent_id` PK.

The CLI does NOT auto-resolve the caller's pane to its agent
because (a) the operator is often setting fields on a *different*
agent than the one they are running from (e.g., the master
promotes a slave); (b) auto-resolution would compose poorly
with `--target` (two ways to identify the agent); (c) the
spec explicitly exposes `--target` (FR-030, FR-031).

**Rationale**:
- FR-030 / FR-031 require `--target`.
- Explicit identification is safer for the master-safety
  boundary — there is no path where `set-role --role master`
  applies to "whatever agent is in this pane" implicitly.

**Alternatives considered**:
- Auto-resolve `--target` from the caller's pane — rejected per
  above.
- Allow `--target current` as an alias — out of scope for
  FEAT-006; can be added later without breaking the contract.

---

## R-015 — Default `list-agents` form rendering (Clarifications Q5)

**Decision**: Render as TSV with a required header row, locked
nine-column schema, in this exact order:

```text
AGENT_ID\tLABEL\tROLE\tCAPABILITY\tCONTAINER\tPANE\tPROJECT\tPARENT\tACTIVE
```

Each row:

- `AGENT_ID` — full `agt_<12-hex>`.
- `LABEL` — verbatim, sanitized of NUL / C0 control bytes (per
  FR-033); empty string renders as empty between the tabs.
- `ROLE` — closed-set string.
- `CAPABILITY` — closed-set string.
- `CONTAINER` — `<full_container_id>[:12]` (12-char short id).
- `PANE` — `<session>:<window>.<pane>` from the FEAT-004 short
  pane form (e.g., `main:0.1`).
- `PROJECT` — verbatim, sanitized as above.
- `PARENT` — `<parent_agent_id>[:16]` (literal 16 chars
  including the `agt_` prefix and 12 hex chars) or the literal
  `-` (single ASCII hyphen) when null. **Note**: per
  Clarifications Q5 the user said "12-char short" — this
  refers to the 12-hex portion of the agent_id; the full
  rendered form is `agt_<12-hex>` which is 16 chars. The CLI
  emits the full `agt_<12-hex>` form (consistent with
  `AGENT_ID` column).
- `ACTIVE` — literal `true` or `false`.

**Snapshot test** (`test_list_agents_tsv_render.py`) locks the
output byte-for-byte across a fixed seeded state.

**Rationale**:
- Clarifications Q5 locks the columns and rendering rules.
- Tab separation matches FEAT-002 / FEAT-005 conventions for
  scriptable output.
- Future fields go to `--json` or a separately-introduced
  `--wide` flag — never the default form.

**Alternatives considered**:
- Fixed-width aligned table (Q5 Option C) — rejected by user
  choice; TSV is more script-friendly.
- One-line summary (Q5 Option D) — rejected; lossy.

---

## R-016 — Edge case: caller pane composite key changed

**Decision**: Per FR-006, an agent's binding to a pane composite
key is immutable. A `register-self` from a *different*
composite key (different container, socket, session, window,
pane index, or pane id) is treated as a brand-new agent
registration — a new agent row is created with a new
`agent_id`. The previous agent row stays in history with
whatever `active` flag the FEAT-004 reconciliation last
assigned. FEAT-006 provides no CLI surface to re-bind an
existing agent to a new pane (deferred per Assumptions).

**Rationale**:
- FR-006 explicitly mandates this.
- Spec edge case lines 70-71 describe the same behavior
  ("AgentTower MUST treat this as a *new* agent (bound to the
  new pane key); the old agent record MUST stay in history").

**Implementation**: The `register_agent` handler keys lookup by
the full pane composite key (six-tuple PK in `panes` mirrored
on `agents`). A different tuple → different lookup result →
INSERT path → new `agent_id`.

---

## R-017 — Concurrency property: convergence on same `agent_id`

**Decision**: Two concurrent `register-self` invocations from
the same pane (same composite key) MUST converge on the same
`agent_id`. The per-(container_id, pane_composite_key)
registration mutex (R-005) serializes them. The first holder
runs the INSERT (new agent_id); the second holder runs the
UPDATE (same agent_id). Both invocations observe the
post-commit row state and return identical `agent_id`
values.

**Rationale**:
- Spec edge case line 72 mandates the property.
- The mutex guarantees serialization; the SQLite PK on the
  composite-key tuple makes the second insert a no-op /
  fall-through to UPDATE.

**Test**: `test_cli_register_concurrent.py` spawns two
`register-self` subprocesses bound to the same simulated pane
and asserts both exit `0` with identical `agent_id` and
exactly one row in `agents`.

---

## R-018 — Forward-compat: daemon newer than CLI

**Decision**: All five new CLIs inherit the FEAT-005
forward-compat policy verbatim. When the CLI's local
`CURRENT_SCHEMA_VERSION` is *less than* the
`schema_version` returned by the daemon's `status`
round-trip, the CLI MUST surface `schema_version_newer` and
refuse the call without making any state-changing socket
call. The check happens in the CLI's pre-flight phase before
any `register_agent` / `set_*` call. `list-agents` is
treated identically — it MUST refuse rather than risk
returning a partial row shape.

**Rationale**:
- Spec edge case line 79 mandates the inheritance.
- FEAT-005's `config doctor` already implements this for
  `daemon_status` — the same pattern applies to every new
  CLI.

**Implementation**: A small helper in `agents/client_resolve.py`
calls `status` once and short-circuits if the daemon is
newer.

---

## R-019 — Migration test coverage

**Decision**: `tests/integration/test_schema_migration_v4.py`
exercises:

1. Fresh DB → `CURRENT_SCHEMA_VERSION = 4` after first
   `open_registry`; `schema_version` row reads `4`; `agents`
   table exists with the expected columns and indexes.
2. v3-only DB (FEAT-005-only build seed) → `open_registry`
   upgrades to v4 in one transaction; `schema_version` reads
   `4`; FEAT-001..004 tables and rows are unchanged
   byte-for-byte (compared via `sqlite3` schema dump).
3. v4-already-current DB → `open_registry` is a no-op; no
   migration runs; `schema_version` stays `4`.
4. v5-on-disk DB (synthetic; insert `schema_version = 5` into
   a freshly-opened DB) → `open_registry` raises
   `sqlite3.DatabaseError` and the daemon refuses to serve.

**Rationale**:
- FR-036 mandates idempotent, single-transaction migration with
  forward-version refusal.
- Mirrors the FEAT-003 / FEAT-004 migration test patterns
  exactly.

---

## R-020 — `--target` and `--parent` shape validation

**Decision**: Both `--target <agent-id>` and `--parent
<agent-id>` are validated against the regex
`^agt_[0-9a-f]{12}$` *before* any socket call. Mismatches are
rejected client-side with `value_out_of_set` and an actionable
message ("expected agt_<12-character-lowercase-hex>"). The
daemon re-validates the same regex defensively so a malformed
value cannot reach the SQLite query.

**Rationale**:
- FR-001 fixes the shape.
- Client-side validation gives a fast, actionable error before
  the round-trip; daemon-side validation is the security
  boundary.
- Closed-set code is `value_out_of_set` per FR-040 (no
  separate code for "agent_id shape").

---

## R-021 — In-process advisory mutex implementation note

**Decision**: Use `threading.Lock`, not `threading.RLock` — the
critical section is a single read-modify-write that does not
recurse. The fetch-or-create of the per-key lock uses
`dict.setdefault` under a guard lock (R-005) — `setdefault` is
atomic in CPython for built-in dicts but the surrounding logic
(if-not-exists-create-then-acquire) is not, so the explicit
guard is required.

**Rationale**:
- `Lock` is the simplest stdlib primitive that satisfies the
  requirement.
- `RLock` would mask bugs where the same thread enters the
  critical section twice; we want that to fail loudly.

---

## R-022 — Sanitization helper reuse

**Decision**: Reuse the existing
`agenttower.tmux.parsers.sanitize_text(text, max_len)` helper
introduced by FEAT-004 for free-text bounding (NUL strip, C0
control strip, multi-byte-safe `…` truncation). FEAT-006
applies it to `label` (max 64) and `project_path` (max 4096).
Over-bound values are *not* truncated — they are rejected with
`field_too_long` per FR-033.

**Rationale**:
- Single source of truth for sanitization rules across all
  free-text fields.
- FEAT-004 already locks the multi-byte-safe truncation
  semantics; FEAT-006 inherits them.

**Alternatives considered**:
- New FEAT-006-specific sanitizer — rejected; the existing
  helper is general-purpose.

---

## Summary

Every NEEDS CLARIFICATION in plan.md's Technical Context is
resolved above. The decisions are consistent with the spec's
clarifications (2026-05-07 Q1–Q5), the architecture, the
FEAT-001..005 conventions, and the constitution.
