# Phase 0 Research: Event Ingestion, Classification, and Follow CLI

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10
**Plan**: [plan.md](./plan.md)

## Purpose

Resolve every open decision point that would otherwise be marked
NEEDS CLARIFICATION in the Technical Context, plus document the
rationale for choices made in the plan that look material on review.
Topic order tracks the plan's structure.

The five spec-level clarifications (`spec.md` → `## Clarifications` →
`### Session 2026-05-10`) are NOT re-litigated here; they are the
input. This document covers the planning-level choices left open by
those clarifications.

---

## R1 — Schema migration v5 → v6 strategy

**Decision**: Add one new table (`events`) and four indexes in a
single `BEGIN IMMEDIATE` migration step `_migrate_v5_to_v6` invoked
from `state/schema._apply_pending_migrations`. No existing table is
touched. Forward-version refusal mirrors FEAT-007.

**Rationale**: Mirrors the FEAT-007 migration shape verbatim
(`v4 → v5`), which is already proven against the FEAT-002+ daemon
harness and has a passing migration test. Reusing the pattern
minimizes risk and keeps the schema-version path linear.

**Alternatives considered**:

- *Two-table split (`events` + `events_debounce_windows`)*: rejected.
  The debounce window state is materialized into the durable Event
  row at emission time per the spec's Key Entities ("no separate
  persistent table required for MVP"); a separate table would
  require a join on every read and add a foreign-key surface for
  no MVP benefit.
- *Reuse FEAT-001 `events.jsonl` as authoritative*: rejected. FR-022
  forbids it ("Restart resume MUST NOT depend on JSONL state"). A
  durable SQLite table is the source of truth; JSONL is append-only
  history.
- *Per-agent SQLite databases*: rejected. The existing project uses
  one shared `agenttower.sqlite3` for all state; sharding would
  break FEAT-006 / FEAT-007 cross-table queries and complicate
  backups.

---

## R2 — Reader scheduling: thread vs asyncio vs subprocess

**Decision**: One daemon-side `threading.Thread` running the reader
loop. The thread wakes on a `threading.Event` for shutdown signaling
and uses `time.monotonic()` for its cycle wall-clock budget.
Per-cycle work is sequential across attachments (no per-attachment
thread pool).

**Rationale**: Matches the existing FEAT-001..007 codebase pattern
(no asyncio anywhere). At MVP scale (≤ 50 agents × ≤ a few KB/s)
sequential per-attachment work fits comfortably in a 1 s cycle. The
reader's hot path is dominated by SQLite commits, which serialize on
WAL anyway. One thread keeps the lock story simple — every commit
goes through this thread plus the FEAT-007 per-`log_path` mutex.

**Alternatives considered**:

- *asyncio*: rejected. Introduces the project's first asyncio
  surface; adds maintenance complexity for one feature; SQLite's
  thread/connection model is already understood by the team.
- *Per-attachment thread*: rejected. 50 threads idle most of the
  time wastes resources; concurrent SQLite writes contend on the
  WAL writer lock; per-attachment fairness is already achievable
  in a single-thread round-robin.
- *External process*: rejected. The constitution mandates the
  daemon owns durable state; spawning a subprocess inverts that.

---

## R3 — Defaults for spec-FR-045 configuration knobs

**Decision**: The defaults below are committed in `events/__init__.py`
constants, surfaced through `[events]` in `config.toml`, and shown by
`agenttower config paths` (FR-045).

| Setting | Default | Why |
|---|---|---|
| `reader_cycle_wallclock_cap_seconds` | `1.0` | FR-001 explicit cap |
| `per_cycle_byte_cap_bytes` | `65536` | 64 KiB drains a fast burst (≈ 50 ms of typical PTY output) without starving other attachments |
| `per_event_excerpt_cap_bytes` | `1024` | Long enough to capture a typical traceback frame or test name; short enough to keep SQLite rows compact |
| `excerpt_truncation_marker` | `"…[truncated]"` | 12 visible bytes; obvious to humans; UTF-8 safe |
| `debounce_activity_window_seconds` | `5.0` | Spec MVP cap of ≤ 5 s; matches typical agent burst patterns (a Python REPL print loop) |
| `pane_exited_grace_seconds` | `30.0` | Spec MVP cap of ≤ 30 s; longer than typical "background-task-finished, shell prints prompt" gap |
| `long_running_grace_seconds` | `30.0` | Same magnitude as `pane_exited_grace_seconds` |
| `default_page_size` | `50` | Spec MVP cap (≤ 50) |
| `max_page_size` | `50` | Same; clients cannot exceed the MVP cap |
| `follow_long_poll_max_seconds` | `30.0` | Comfortable middle ground: long enough to amortize CLI ↔ daemon round-trips during quiet periods, short enough that a stuck daemon surfaces within 30 s |
| `follow_session_idle_timeout_seconds` | `300.0` | Five-minute idle GC for stale follow sessions (e.g., a CLI killed by SIGKILL); does not affect a normally-flowing follower |

**Alternatives considered**:

- *Per-cycle byte cap = 16 KiB*: rejected. Too tight for a burst of
  test output; would defer too much work to subsequent cycles.
- *Excerpt cap = 4096 bytes*: rejected. SQLite rows would be 4×
  larger for content that is mostly not load-bearing for routing.
- *Activity debounce = 1 s*: rejected. Would emit too many activity
  events for normal interactive output (each keystroke echo).

---

## R4 — Classifier rule shapes

**Decision**: Each rule is a frozen dataclass:

```python
@dataclass(frozen=True)
class ClassifierRule:
    rule_id: str                 # stable, e.g. "swarm_member.v1"
    event_type: str              # one of the 10 enum values
    matcher: Pattern[str]        # re.compile(..., flags)
    priority: int                # lower is higher priority
    extract: Callable[[Match[str]], dict[str, Any]] = lambda m: {}
```

The catalogue is an ordered tuple `RULES: tuple[ClassifierRule, ...]`
in `events/classifier_rules.py`, sorted by `priority` ascending. The
classifier walks the tuple and returns the first match.

The MVP catalogue contents are documented in
`contracts/classifier-catalogue.md`; the priority table is:

1. `swarm_member.v1` (priority 10) → `swarm_member_reported`
2. `manual_review.v1` (priority 20) → `manual_review_needed`
3. `error.traceback.v1` (priority 30) → `error`
4. `error.line.v1` (priority 31) → `error`
5. `test_failed.pytest.v1` (priority 40) → `test_failed`
6. `test_failed.generic.v1` (priority 41) → `test_failed`
7. `test_passed.pytest.v1` (priority 50) → `test_passed`
8. `test_passed.generic.v1` (priority 51) → `test_passed`
9. `completed.v1` (priority 60) → `completed`
10. `waiting_for_input.v1` (priority 70) → `waiting_for_input`
11. `activity.fallback.v1` (priority 999) → `activity`

`pane_exited` and `long_running` are NOT in the matcher catalogue
(they are synthesized by the reader; see plan §"`pane_exited` and
`long_running` synthesis").

**Rationale**:

- Priority is explicit at the dataclass level, making the priority
  table self-documenting at runtime (`agenttower events
  --classifier-rules` is a debug-only flag for tests).
- `rule_id` is stable across the catalogue; the JSONL `classifier_
  rule_id` field is exactly this string. Tests assert this is what
  appears in the durable row.
- `error` precedes `test_failed` so a record like `Error: test_x
  failed in setup` classifies as `error` — the operator's "what
  happened" question is answered correctly.

**Alternatives considered**:

- *Single regex disjunction with named groups*: rejected. Priority
  becomes implicit, debugging is harder, and the FR-008 fixture
  requirement ("test fixture for every rule") is awkward to express.
- *Compiled trie / Aho-Corasick*: rejected. Premature optimization;
  10 regexes per record well under the 1 ms/record budget.
- *Pluggable rule registry (entry points)*: rejected. Out of scope
  per FR-007 ("rule catalogue is closed; additions are per-feature
  changes"). A future feature can introduce plug-in support.

---

## R5 — Debounce state model

**Decision**: Per-attachment, per-event-class in-memory state held
in a `dict[(attachment_id, event_class), DebounceWindow]` on the
reader's debounce manager. `activity` is the only collapse-eligible
class (FR-014); for the other nine classes the manager is a pass-
through that emits one event per qualifying record. The manager is
NOT persisted (FR-015 — debounce state does not span restarts).

`DebounceWindow` shape:

```python
@dataclass
class DebounceWindow:
    window_id: str          # 12-hex, fresh per window
    started_at: ISOString
    ended_at: ISOString | None
    collapsed_count: int
    latest_excerpt: str
    latest_byte_range: tuple[int, int]
    latest_line_range: tuple[int, int]
    latest_observed_at: ISOString
    latest_classifier_rule_id: str
```

When a new `activity` record arrives:

- If no window OR `now - started_at >= debounce_activity_window_
  seconds`: close any prior window (set `ended_at`, emit one
  durable event with the prior window's `latest_*` and
  `collapsed_count`), then open a new window seeded with this
  record (`collapsed_count = 1`).
- Otherwise (within window): increment `collapsed_count`, replace
  `latest_*` fields with this record's values, do NOT emit yet.

A wall-clock-cycle visit to the debounce manager flushes any window
whose `now - started_at >= debounce_activity_window_seconds`, even
if no new record arrived (this lets a single `activity` record
emit an event after the window closes).

**Rationale**:

- Matches FR-014 exactly: collapse-eligible only for `activity`,
  one-to-one for the other nine, in-memory only.
- `window_id` is opaque (12-hex per FEAT-006 / FEAT-007 conventions)
  so the operator cannot derive timing from it.
- Latest-excerpt-wins matches the spec ("excerpt is the latest
  record's redacted excerpt").

**Alternatives considered**:

- *First-excerpt-wins*: rejected. The spec explicitly says "latest
  record's redacted excerpt".
- *Persist windows across restarts*: rejected by FR-015.
- *Apply debounce to `error` for "burst of stack-trace lines"*:
  rejected by FR-014 (one-to-one for `error`). A 200-line traceback
  emits 200 `error` events in MVP; a future feature may revisit.

---

## R6 — JSONL retry watermark

**Decision**: Each `events` row carries a nullable `jsonl_appended_at`
column. The reader's commit transaction sets this to NULL on insert.
After the SQLite commit, the reader synchronously calls
`events.writer.append_event` and, on success, executes a separate
small transaction that sets `jsonl_appended_at = now()` for the just-
inserted row (or batch).

If the JSONL append fails, `jsonl_appended_at` stays NULL and the
daemon raises a `degraded_jsonl_persistence` condition on
`agenttower status`. On every subsequent cycle, before processing
new bytes, the reader queries
`SELECT event_id, ... FROM events WHERE jsonl_appended_at IS NULL
ORDER BY event_id ASC LIMIT N` and retries each row's JSONL append.
Successful retries clear the watermark and (when the queue empties)
the degraded condition.

The partial index `idx_events_jsonl_pending` makes this query O(N)
in the unfinished-append count, not the whole table.

**Rationale**:

- SQLite is the source of truth (FR-022), so the watermark is
  recoverable across restarts (no in-memory queue).
- The retry batch size N reuses `default_page_size` (50) so JSONL
  catch-up does not starve fresh ingestion.
- Idempotence: `events.writer.append_event` does not check for
  duplicates, so the reader MUST guarantee at-most-once (the
  watermark prevents replay).

**Alternatives considered**:

- *Two-phase commit (SQLite + JSONL atomic)*: rejected. JSONL is a
  flat file with `O_APPEND`; there is no portable atomic write-and-
  flush for "this line is one of these N events". The watermark
  approach is the SQLite-source-of-truth realization.
- *Drop the JSONL on failure and rebuild from SQLite at next
  startup*: rejected by FR-029 ("never silently dropped").

---

## R7 — FR-040 degraded SQLite buffered retry

**Decision**: The reader keeps a per-attachment in-memory deque
`_pending_events` (cap = `per_cycle_byte_cap_bytes` worth of events,
which at typical excerpt sizes is hundreds of events but bounded).
On a SQLite write error during commit:

1. Push the failed-cycle's events onto `_pending_events` for that
   attachment.
2. Do NOT advance offsets for that attachment. Bytes remain on
   disk; the next cycle re-reads and re-classifies them, producing
   the same events deterministically.
3. Surface `degraded_events_persistence: {attachment_id, since_iso,
   buffered_count, last_error_class}` through `agenttower status`.
4. On the next cycle, before reading bytes, attempt to flush
   `_pending_events` first. If flush succeeds, advance offsets and
   clear the degraded condition for that attachment.

Crucially, because the events are deterministically re-classifiable
from the same bytes (FR-010 pure function), the buffer is actually
optional — the next cycle would re-derive the same events from the
unread bytes. The buffer exists as a CONFORMANCE OBSERVABLE: tests
can assert that on degraded recovery, the same `event_id`s appear
that would have appeared without the failure (modulo the
auto-increment skipping any rolled-back insert attempts).

**Rationale**:

- The locked clarification (`### Session 2026-05-10` Q1) requires
  buffer + retry + visible status. The buffer is small, observable,
  and bounded.
- Not advancing offsets means the data on disk IS the queue. SQLite
  is still the source of truth post-recovery.
- The visible status field is a closed-set object so scripts can
  parse it.

**Alternatives considered**:

- *In-memory queue only, advance offsets on read*: rejected. A
  daemon crash during the degraded window would lose the buffered
  events with no replay path.
- *Persist the buffer to a side file*: rejected. Adds a new file
  surface, new mode bits, new corruption-recovery story for no
  benefit over re-reading bytes.

---

## R8 — Cursor encoding choice

**Decision**: The cursor is `base64url(json({"e": <event_id>, "r":
<reverse_flag>}))` with `=` padding stripped (URL-safe variant).

**Rationale**:

- Operator-opaque: cannot be hand-edited without decoding.
- Forward-tolerant: the decoder's strict validation of currently-
  defined keys is on the encoder side; a future encoder adding an
  optional key (e.g., `t` for token-version) does NOT need to
  break older clients because they only round-trip the value.
- Standard library only: `base64.urlsafe_b64encode` +
  `json.dumps` / `json.loads`.
- Compact: 12-byte `event_id` ints encode to ~24 base64 chars.

**Alternatives considered**:

- *Raw base64 of integer bytes*: rejected. No room for the reverse
  flag without an external state, and `events --reverse` plus
  `--cursor` semantics get murky.
- *Hex string of `(observed_at, event_id)` tuple*: rejected. Larger,
  exposes internal timing, and operators might be tempted to parse.
- *Signed JWT-style cursor*: rejected. Overkill for a local socket;
  no adversary boundary.

---

## R9 — Follow-session lifetime and cleanup

**Decision**: `events.follow_open` returns a `session_id` (12 hex,
stored in a server-side `dict[session_id, FollowSession]`). Each
session has an `expires_at = now + follow_session_idle_timeout_
seconds`. Every `events.follow_next` call refreshes `expires_at`.
A daemon-side janitor (running on the reader thread between cycles)
removes any session past `expires_at`. The CLI calls
`events.follow_close` on SIGINT and on stream-error.

**Rationale**:

- The protocol is request/response; sessions are server-side state
  that need explicit cleanup.
- 5 min idle is generous for human-controlled use, short enough
  that a SIGKILLed CLI does not leave permanent server state.
- The janitor on the reader thread avoids a separate thread.

**Alternatives considered**:

- *No idle timeout*: rejected. SIGKILLed CLIs would leak sessions.
- *Per-call session creation (no `open`)*: rejected. Each
  `follow_next` call would need to re-derive `last_emitted` from
  the client, exposing the integer event_id contrary to the
  cursor opacity rule.
- *Daemon-side weakref on the socket connection*: rejected. The
  socket protocol does not keep a connection open between calls.

---

## R10 — Two new test seams

**Decision**: Two new environment-variable test seams:

- `AGENTTOWER_TEST_EVENTS_CLOCK_FAKE`: JSON-encoded `{"observed_at_
  iso": <ISO-string>, "monotonic": <float>}`. When set, the reader's
  `Clock` Protocol reads from this var (not real time). Tests mutate
  the file via a helper to advance time deterministically.
- `AGENTTOWER_TEST_READER_TICK`: Path to a Unix domain socket. When
  set, the reader replaces its inter-cycle `Event.wait()` with a
  `socket.recv` on this path. Tests write one byte to advance one
  cycle.

Both seams are gated by the FEAT-007 production-test-seam guard
(`_guard_production_test_seam_unset`) so production daemons cannot
accidentally use them. The reader test-seam imports are also
checked by the AST gate
(`tests/unit/test_logs_offset_advance_invariant.py` is extended to
also forbid `AGENTTOWER_TEST_*_FAKE` reads from production code
paths — the existing pattern).

**Rationale**:

- The clock seam makes US3 / US4 tests deterministic without
  `time.sleep` (CI flake risk).
- The tick seam decouples test wall-clock from reader wall-clock
  for SC-006's 100-iteration assertion.
- Following the existing FEAT-007 seam pattern (env-var JSON
  payload) keeps the harness uniform.

**Alternatives considered**:

- *Monkeypatch `time.monotonic` globally*: rejected. Bleeds into
  unrelated daemon code (FEAT-002 socket timeouts, etc.).
- *Pytest fixtures only*: rejected. Integration tests run the
  daemon as a subprocess; fixtures don't reach that process.

---

## R11 — `pane_exited` and `long_running` synthesis ordering

**Decision**: At the START of each reader cycle, BEFORE the per-
attachment `reader_cycle_offset_recovery` call, the reader invokes
two synthesis passes:

1. **`pane_exited` synthesis**: query FEAT-004's pane service for
   the bound pane state of every active attachment; if pane is
   inactive AND the lifecycle has not yet emitted `pane_exited`
   AND the grace window has elapsed, mark this attachment for a
   `pane_exited` emission this cycle.
2. **`long_running` synthesis**: walk every active attachment;
   apply the eligibility table from FR-013 against the most recent
   prior emitted event; if eligible AND the grace window has
   elapsed since `last_output_at`, mark this attachment for a
   `long_running` emission this cycle.

These synthesized events are committed as part of the per-
attachment cycle commit (FR-006), with `byte_range_start =
byte_range_end = persisted_byte_offset`, `excerpt = ""`, and
`classifier_rule_id` set to a synthetic id (`pane_exited.synth.v1`
or `long_running.synth.v1`).

**Rationale**:

- Synthesizing BEFORE byte read means the synthesized events get
  the same persisted offset as the byte-driven ones; ordering is
  natural by `event_id`.
- Both depend on time, not log content, so they are not regex
  rules. Putting them in the matcher catalogue would be a category
  error.
- The synthetic `classifier_rule_id` keeps the JSONL schema
  uniform (FR-027 always has the field).

**Alternatives considered**:

- *Synthesize at end of cycle*: rejected. Would make `event_id`
  ordering between byte-driven events and synthesized events
  depend on the order they happened to land in the same
  transaction.
- *Out-of-band emitter thread*: rejected. Two writers would
  contend on the SQLite WAL writer; the single-thread invariant
  would break.

---

## R12 — Backwards compatibility test scope

**Decision**: `test_feat008_backcompat.py` re-runs every FEAT-001 …
FEAT-007 CLI command surface (every documented `agenttower …`
invocation in those features' specs and quickstarts), captures
stdout, stderr, and exit code, and asserts byte-identical output
against fixtures recorded against the FEAT-007 head-of-tree commit
(captured during FEAT-008 plan time). Any divergence fails the
build.

**Rationale**:

- Mirrors FEAT-007's `test_feat007_backcompat.py` pattern.
- The single highest-risk regression for FEAT-008 is the daemon
  init path (reader thread now starts at boot); the backcompat
  test catches any side-effect on the existing surfaces.

**Alternatives considered**:

- *Trust unit tests only*: rejected. Unit tests cover individual
  surfaces; the backcompat test catches cross-surface regressions
  the unit tests miss.

---

## Summary

All NEEDS CLARIFICATION items from the plan are resolved:

| Topic | Resolution |
|---|---|
| Schema migration shape | R1 — `_migrate_v5_to_v6`, additive |
| Reader scheduling model | R2 — single thread, no asyncio |
| FR-045 default values | R3 — table of 11 settings |
| Classifier rule shape | R4 — frozen dataclass + ordered tuple, priorities |
| Debounce model | R5 — per-(attachment,class) in-memory window |
| JSONL retry watermark | R6 — `jsonl_appended_at` column + partial index |
| FR-040 buffered retry | R7 — bounded deque + offsets-not-advanced |
| Cursor encoding | R8 — base64url(json({"e","r"})) |
| Follow session lifetime | R9 — 5 min idle GC on reader thread |
| Test seams | R10 — clock fake + tick socket |
| Synthesis ordering | R11 — synthesize BEFORE byte read at cycle start |
| Backcompat coverage | R12 — re-run every prior CLI surface |

No items remain marked NEEDS CLARIFICATION. Phase 1 (data model and
contracts) can proceed.
