# Phase 0 Research: Safe Prompt Queue and Input Delivery

**Branch**: `009-safe-prompt-queue`
**Date**: 2026-05-11
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Purpose

Phase 0 resolves every `NEEDS CLARIFICATION` from Technical Context and
documents the small set of additional design decisions FEAT-009 needs
beyond what `## Clarifications` already locked. Each entry follows the
Decision / Rationale / Alternatives format.

The two `/speckit.clarify` sessions (5 + 5 = 10 questions) already
pinned the headline product decisions. Phase 0 focuses on the
*implementation-shaped* questions the spec deliberately left to
planning: SQL affinity, sentinel reservation mechanics, host-origin
detection mechanics, JSONL event-type disjointness verification, shell-
injection AST gate scope, and pre-paste re-check ordering.

## R-001 — Target shape detection: `AGENT_ID_RE` vs literal UUIDv4

**Decision**: Use `AGENT_ID_RE` (`^agt_[0-9a-f]{12}$`) from
`src/agenttower/agents/identifiers.py` for `--target` shape detection.
The Clarifications Q2 wording "UUIDv4 textual form" is reinterpreted
as "the registered agent_id shape" — the spec's *intent* is "treat
the input as an agent_id iff it matches the registered form,
otherwise treat it as a label," not literal UUIDv4 detection.

**Rationale**: FEAT-006 chose `agt_<12-hex>` over UUIDv4 explicitly
(see `identifiers.py` docstring) for shorter operator-visible
identifiers (16 chars vs 36). Using literal UUIDv4 detection would
make every `--target` accept a label (because no agent_id matches
UUIDv4 in this codebase), defeating the resolver's purpose. The
spec's `message_id` field is a separate identifier with no FEAT-006
contract and remains UUIDv4 (FR-001).

**Alternatives considered**:

- *Re-clarify the spec to spell out `agt_<12-hex>`.* Rejected because
  the spec's intent is already unambiguous and the wording change
  would be cosmetic; documenting the reconciliation in `plan.md` is
  sufficient.
- *Use UUIDv4 for both `message_id` and `agent_id` going forward.*
  Out of scope (would break FEAT-006 wire format).
- *Use a single shape regex covering both UUIDv4 and `agt_<12-hex>`.*
  Adds complexity for no operator benefit — agent_ids in this
  codebase only ever come in one form.

## R-002 — `envelope_body` SQL affinity: `BLOB` vs `TEXT`

**Decision**: `envelope_body BLOB NOT NULL`. Read and write the body
as `bytes`, never as `str`, throughout the routing package.

**Rationale**: FR-003 forbids NUL bytes and ASCII controls except
`\n` / `\t`, so a validated body is always valid UTF-8 and could in
principle round-trip through `TEXT`. But Q1 locked
"byte-exact persistence and delivery"; SQLite's `TEXT` affinity
applies implicit encoding conversions controlled by
`connection.text_factory`. The default `str` factory would decode
`bytes` to UTF-8 and re-encode on read, which is byte-exact *only*
if the input was valid UTF-8 and no normalization is applied. Using
`BLOB` removes the entire class of encoding-round-trip ambiguity,
matches the "raw body bytes" wording of FR-012a literally, and lets
the FR-012a test ("submit body containing every character class →
read back and assert byte-equal") use a single `memoryview`
comparison.

**Rationale, second axis**: SQLite's `BLOB` and `TEXT` affinities
have identical on-disk encoding for ASCII-clean content; the storage
cost is the same. The only operational difference is the Python-side
type returned by the cursor (`bytes` for `BLOB`, `str` for `TEXT`).
`bytes` is correct here — the body is a payload, not a string.

**Alternatives considered**:

- *`TEXT` with `text_factory = bytes`.* Works, but two readers
  (queue listing redacted excerpt, audit excerpt) want `str` and one
  reader (the delivery worker) wants `bytes`. Mixing requires
  per-call casts. `BLOB` is clearer.
- *Base64-encode the body in a `TEXT` column.* Wastes 33% of the
  size cap, complicates the FR-004 size check, makes the body
  unreadable in `sqlite3` CLI output. Rejected.

## R-003 — `daemon_state` table shape: key/value vs flat columns

**Decision**: `daemon_state` is a key/value table with a CHECK
constraint pinning `key` to the closed set
`{'routing_enabled'}` in MVP.

```sql
CREATE TABLE daemon_state (
    key             TEXT PRIMARY KEY CHECK (key IN ('routing_enabled')),
    value           TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    last_updated_by TEXT NOT NULL
);
```

`value` is the ASCII string `"enabled"` or `"disabled"` (not a
SQLite integer) so the column accepts a string lossily through any
client. Future flags extend the CHECK enum without a schema bump.

**Rationale**: One-row-per-flag matches the FR-026 wording "single
boolean routing flag in `daemon_state`" and the FR-027 audit
requirement (`last_toggled_at`, `last_toggled_by_agent_id`). It
also leaves room for FEAT-010 to add a maintenance-mode flag
without a new table. The CHECK enum forces every future flag to
be a spec amendment, preserving the closed-set discipline.

**Alternatives considered**:

- *Single-row table with one column per flag.* Cleaner per-flag
  read but requires schema migration for every new flag (FEAT-010
  has at least one candidate flag — see `docs/architecture.md`
  §23).
- *Store flag in a JSON column on an existing table.* Mixes
  concerns — no existing table has the right cardinality. Rejected.
- *Boolean as `INTEGER` (`0` / `1`).* SQLite has no bool type;
  ASCII string is more legible in `sqlite3` CLI inspection and
  matches the wire-format JSON shape (`"enabled"` / `"disabled"`)
  used in `routing status --json`.

## R-004 — `host-operator` sentinel reservation mechanics

**Decision**: Add `HOST_OPERATOR_SENTINEL = "host-operator"` as a
module-level constant in `src/agenttower/agents/identifiers.py`.
Extend `validate_agent_id_shape` to refuse this exact literal even
though it fails the `AGENT_ID_RE` regex anyway — the explicit
reservation guards against future shape regex changes weakening the
guarantee. Also expose the constant from `agents/__init__.py` so
FEAT-009 imports it without touching the private module.

```python
HOST_OPERATOR_SENTINEL: Final[str] = "host-operator"

def validate_agent_id_shape(value: str) -> str:
    if value == HOST_OPERATOR_SENTINEL:
        raise RegistrationError(
            "value_out_of_set",
            f"agent_id may not be the reserved sentinel {HOST_OPERATOR_SENTINEL!r}",
        )
    if not isinstance(value, str) or not AGENT_ID_RE.match(value):
        raise RegistrationError(...)
    return value
```

**Rationale**: The Clarifications Q4 promise is "the registry MUST
refuse registration of an agent with this literal id." A two-layer
defense (regex rejection + explicit literal rejection) survives
future shape changes. Locating the constant in `agents/identifiers`
keeps the reservation in the module that owns the shape contract,
not scattered in FEAT-009. The sentinel collides with the regex by
construction (no hyphens allowed in `agt_<12-hex>`), so the
defensive check is doubly safe today but resilient to changes.

**Alternatives considered**:

- *Constant in `routing/__init__.py` only.* Couples FEAT-009 to the
  registry contract loosely; FEAT-009 needs to know what FEAT-006
  *guarantees* about reserved ids.
- *Database-side CHECK constraint on the agents table.* Adds a
  schema migration with no operational benefit over a code-side
  check; rejected for minimal-migration discipline.
- *Use a literal that's guaranteed to fail every conceivable future
  agent_id regex (e.g., `\x01\x01\x01`).* Unreadable in audit
  output and JSONL; rejected on observability grounds.

## R-005 — Host-origin detection at the socket boundary

**Decision**: Reuse the existing FEAT-005 `CallerContext` enrichment
that the socket server already attaches at the `accept()` boundary.
`CallerContext` carries a `caller_pane: Optional[PaneIdentity]`
field — populated when the request came from a bench-container
thin client (FEAT-005's pane identity round-trip), `None`
otherwise.

The discriminator for host-origin in FEAT-009 is:

```python
def is_host_origin(ctx: CallerContext) -> bool:
    return ctx.caller_pane is None and ctx.peer_uid == os.getuid()
```

The `peer_uid` check is necessary but not sufficient (a malicious
bench-container process could in principle share the host uid in
some socket configurations; the pane-absence check is the actual
discriminator). Both checks combined are the FR-027 gate.

**Rationale**: Reusing the existing surface keeps the boundary
check uniform — every socket method that needs origin-awareness
(`routing.enable`, `routing.disable`, plus the symmetric
`send-input` sender-pane check) reads from the same `CallerContext`.
No new mechanism is invented.

**Alternatives considered**:

- *Inspect the connecting socket's path (host socket vs container-
  mounted socket).* Today both use the same Unix socket path
  (FEAT-001 invariant — the bench container bind-mounts the host
  socket). Origin can't be detected from the path.
- *Use `SO_PEERCRED` PID + check for container-namespace
  membership.* Adds Linux/namespace coupling for a check the
  FEAT-005 pane-identity surface already gives us cheaply.
- *Add a `--from-host` CLI flag that the daemon trusts.* Trivially
  bypassable; rejected on safety grounds.

## R-006 — Pre-paste re-check scope (FR-025)

**Decision**: The pre-paste re-check evaluates exactly three
conditions, in this order:

1. Routing flag is still `enabled`. If disabled at re-check time,
   the row was already eligible for blocking before the worker
   picked it up — but the spec says "in-flight rows finish"
   (Session 2 Q1), so re-check happens BEFORE the
   `delivery_attempt_started_at` stamp, not after.
2. Target agent is still registered AND `active=true`. If not →
   `target_not_active`.
3. Target container + pane are still active (FEAT-003 container
   service `containers/list` + FEAT-004 pane resolution against
   the captured `target_container_id` + `target_pane_id`). If not
   → `target_container_inactive` or `target_pane_missing` (the
   first failing check determines the reason).

The sender role and sender liveness are NOT re-checked (FR-025
Assumption — authorization is locked at enqueue).

The block_reason precedence at re-check matches the FR-019 enqueue-
time precedence so a queued row that re-blocks for the same reason
emits a consistent code.

**Rationale**: The spec's FR-025 wording — "re-evaluate permission
and availability checks at the start of every delivery attempt" —
is broad; locking the exact ordering removes implementation
ambiguity and lets the unit test enumerate the matrix without
guessing.

**Alternatives considered**:

- *Re-check sender liveness too.* Rejected per FR-025 Assumption.
- *Re-check the routing flag AFTER stamping `delivery_attempt_
  started_at`.* Would make the Session 2 Q1 "in-flight rows finish"
  contract impossible to assert — the stamp would be the gate.
  Rejected.
- *Re-check pane identity by querying `tmux list-panes` instead of
  the cached daemon state.* More accurate but each re-check would
  cost a `docker exec`. The spec's "few seconds" SC-001 budget
  argues against the extra round-trip; the daemon's pane state is
  refreshed by FEAT-004 on its own schedule and is the right
  source-of-truth for the re-check.

## R-007 — Shell-injection AST gate scope (FR-038)

**Decision**: A new unit test
`tests/unit/test_no_shell_string_interpolation.py` walks the AST of
`src/agenttower/tmux/subprocess_adapter.py` and asserts:

- No `ast.Call` whose function resolves to `subprocess.run`,
  `subprocess.Popen`, `subprocess.check_output`,
  `subprocess.check_call`, `subprocess.call`, or
  `subprocess.getoutput` has a `shell=True` keyword (literal or
  via expansion).
- No call to `os.system`, `os.popen`.
- For every `subprocess.run`-family call, the `args` positional
  is an `ast.List` whose elements are `ast.Constant` (string
  literals) or `ast.Name` references — not `ast.JoinedStr`
  (f-strings), `ast.Call` to `.format` / `.join` / `%`-formatting,
  nor any expression involving the `body` parameter name.
- The `body` parameter, when present in the call's keyword set,
  appears ONLY as the value of an `input=` keyword (the stdin
  conduit).

The gate covers `subprocess_adapter.py` only. The fakes and
abstract adapter Protocol are not exercised because they don't run
real processes.

**Rationale**: AST-level checks catch the wrong shape at test time
even when the production code looks innocent at a glance. The set
of patterns enumerated covers every shell-string-construction
idiom we've seen in this codebase plus the obvious f-string trap.
The test is fast (parses one file), deterministic, and runs in
unit CI.

**Alternatives considered**:

- *Type-only check (`body: bytes` annotation everywhere).* Useful
  but doesn't prove the bytes never flow into a shell string.
- *Runtime check with a `mock.patch.object(subprocess, 'run')`
  that asserts `shell=False`.* Tests the call, not the pattern;
  the AST gate is stricter.
- *Use a linter (`bandit`).* Bandit catches `shell=True` and
  `os.system`, but adding a third-party dev dep for one check is
  heavier than a 100-line unit test.

## R-008 — JSONL `event_type` namespace disjointness

**Decision**: A new unit test
`tests/unit/test_jsonl_namespace_disjointness.py` imports the closed
sets from FEAT-007 (`logs.lifecycle._LIFECYCLE_EVENT_TYPES`),
FEAT-008 (`events.classifier_rules._DURABLE_EVENT_TYPES`), and
FEAT-009 (`routing.errors._QUEUE_AUDIT_EVENT_TYPES`), and asserts:

- The three sets are pairwise disjoint.
- The union is the complete set of `event_type` values that may
  appear in `events.jsonl`.

The closed sets are exported from each domain's `__init__.py` for
the test to import.

**Rationale**: FEAT-008 introduced multi-namespace JSONL; FEAT-009
adds a third namespace. A consolidated test prevents accidental
overlap (e.g., a future `error` durable event clashing with a
hypothetical `error` audit). The test runs in unit CI and fails the
build if any domain adds a colliding type.

**Alternatives considered**:

- *Single global registry of event types.* Higher coupling across
  domains; rejected for additive-only discipline.
- *Prefix every type with its FEAT number.* Loses readability
  (`feat008_error` is not as scan-friendly as `error`); also
  changes FEAT-008's wire format. Rejected.

## R-009 — Defaults for non-spec-locked configuration

**Decision**: The plan's `## Implementation Notes` table lists eight
configurable settings. The values not pinned by the spec are chosen
as follows:

| Setting | Default | Reason |
|---|---|---|
| `delivery_attempt_timeout_seconds` | `5.0` | tmux paste round-trip via `docker exec` is < 1 s in steady state; 5 s gives 5× margin before declaring `tmux_paste_failed`. Smaller than the 10 s `send_input_default_wait_seconds` so the CLI's wait can observe a failure within budget. |
| `delivery_worker_idle_poll_seconds` | `0.1` | Wakeup granularity for the empty-queue idle path. 100 ms keeps SC-001 (3 s budget) well in margin. Overridable by the test seam `AGENTTOWER_TEST_DELIVERY_TICK`. |
| `degraded_audit_buffer_max_rows` | `1024` | Sized at ≤ 1 minute of sustained 10 events/s peak from the Scale/Scope budget; older entries drop and `agenttower status` raises the visible alarm. Mirrors FEAT-008 `_pending` cap proportionally. |

The remaining defaults (`envelope_body_max_bytes`, `excerpt_max_chars`,
`excerpt_truncation_marker`, `send_input_default_wait_seconds`,
`submit_keystroke`) are all spec-locked.

**Rationale**: Each value sits comfortably inside the spec's
quantified budgets (SC-001, SC-009) and leaves operator-visible
headroom. None of them is a hot dial; all are configurable via the
`[routing]` section in `config.toml` for atypical deployments.

**Alternatives considered**: None worth recording — these are sized
to the existing budgets.

## R-010 — Deferred decisions (out of FEAT-009 scope)

The following decisions are deliberately deferred and documented
here so they don't reappear in `/speckit.tasks` or `/speckit.analyze`:

- **Per-row retention / purge / rotation.** No background job
  prunes `message_queue` or `events.jsonl`. The Assumptions block
  in the spec is the operator's contract. Manual SQLite delete is
  allowed.
- **Multi-master arbitration prompt.** Per-target FIFO is in scope
  (FR-044); the arbitration prompt itself is FEAT-010.
- **Per-target / per-role kill switches.** Single global flag only;
  fine-grained gating belongs in FEAT-010 or later.
- **Event-driven `send-input` triggers.** Out of scope (FR-051).
- **Body classification / summarization / LLM inference.** Out of
  scope (FR-053).
- **TUI / web UI / desktop notifications.** Out of scope (FR-054).
- **Cross-host targets.** Out of scope; "reachable bench container"
  means same-host in MVP.

## R-011 — Test seam ergonomics

**Decision**: The two new seams
(`AGENTTOWER_TEST_ROUTING_CLOCK_FAKE`,
`AGENTTOWER_TEST_DELIVERY_TICK`) follow the FEAT-008 idiom verbatim:

- Both are environment variables read by the daemon at boot, not at
  every call.
- Both default to `None` / unset, meaning "use the production
  surface."
- The clock seam accepts JSON encoded as
  `{"now_iso_ms_utc": <ISO-string>, "monotonic": <float>}`; tests
  rewrite the env-var between operations to advance the perceived
  time deterministically.
- The tick seam is a Unix socket path; tests write a single byte to
  advance the worker by exactly one row.

Existing FEAT-001..008 tests are not affected (the seams have no
production-time observable effect when unset).

**Rationale**: Consistency with FEAT-008 reduces cognitive load for
future test maintainers and lets the existing
`tests/integration/_daemon_helpers.py` fixtures be extended
without invention.

## R-012 — `daemon.py` boot ordering with FR-040 recovery

**Decision**: The daemon's `start()` method is extended to call
`delivery_worker.run_recovery_pass()` synchronously BEFORE
`delivery_worker.start()` (the thread spawn). The recovery pass
does the single `UPDATE` of all interrupted rows and emits one
JSONL audit per affected row, then returns. The thread spawn only
happens after the synchronous call returns.

```python
# FEAT-009 boot extension (in agenttower.daemon.Daemon._start_services)
# ... after FEAT-001..008 services are initialized ...
delivery_worker = DeliveryWorker(...)
delivery_worker.run_recovery_pass()         # synchronous
delivery_worker.start()                      # spawn thread
ctx.register_shutdown_hook(delivery_worker.stop)
```

**Rationale**: SC-004 demands "100% of interrupted rows resolve to
terminal before the next delivery worker cycle." Doing the
recovery synchronously at boot is the simplest way to make this
provable — the worker thread doesn't exist yet when recovery runs,
so by construction there is no "next cycle" to race against. A
unit test asserts the call order at function-mock granularity.

**Alternatives considered**:

- *Run recovery as the worker thread's first iteration.* Race-
  prone: a `send-input` arriving on the socket would be queued
  before recovery completes, and the worker would have to
  carefully not pick it up. The synchronous-at-boot variant
  eliminates this entirely.
- *Run recovery lazily on the first read of `message_queue`.*
  Coupling the read path to the recovery responsibility violates
  separation of concerns; rejected.

## Summary

Every `NEEDS CLARIFICATION` in Technical Context is resolved.
Every planning-level question surfaced by the deep checklists
(`security.md`, `api.md`, `reliability.md`, `data.md`,
`observability.md`, `ux.md`) is either:

- Locked by the two `/speckit.clarify` sessions (10 questions
  total).
- Locked by this `research.md` (R-001 — R-012).
- Explicitly deferred under R-010 with rationale.

Ready for Phase 1 (data-model, contracts, quickstart).
