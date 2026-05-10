# Implementation Plan: Event Ingestion, Classification, and Follow CLI

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-event-ingestion-follow/spec.md`

## Summary

FEAT-008 turns the FEAT-007-attached pane logs into durable, inspectable
AgentTower events. The work splits into five additive layers, each
narrow:

1. **SQLite migration v5 → v6** that adds one new table (`events`),
   four indexes (PK is implicit; the new indexes are: by-agent +
   `event_id`, by-type + `event_id`, by-`observed_at` + `event_id`, and
   by-`jsonl_appended_at` for the FR-029 retry watermark).
2. **A pure rule-based classifier** in a new
   `src/agenttower/events/classifier.py` that consumes a single
   already-redacted record (FEAT-007 redaction utility) and emits
   exactly one of the ten closed-set `event_type` values, with rule
   priority documented as an ordered table fixture-tested per rule
   (FR-007 — FR-013).
3. **A background reader loop** in a new
   `src/agenttower/events/reader.py` that the daemon starts at boot,
   visits every `active` `log_attachments` row at most once per cycle
   (FR-001), calls FEAT-007's `reader_cycle_offset_recovery` first
   (FR-002 / FR-041), reads up to the per-cycle byte cap from disk,
   splits on `\n`, classifies each complete record, runs per-
   attachment debounce, then commits the durable event row plus the
   advanced `log_offsets` row in a single atomic transaction (FR-006).
   The reader is the SOLE production caller that advances
   `log_offsets.byte_offset` / `line_offset` / `last_event_offset`
   (FR-004 / SC-008) and continues to satisfy the existing
   `tests/unit/test_logs_offset_advance_invariant.py` AST gate.
4. **JSONL append** to the existing FEAT-001 `events.jsonl` file via
   `agenttower.events.writer.append_event` AFTER the SQLite commit
   (FR-006 / FR-025), with a per-row `jsonl_appended_at` timestamp that
   doubles as the FR-029 retry watermark for the JSONL-degraded path.
5. **A new `agenttower events` CLI** (`list`, `--follow`,
   `--target`, `--type`, `--since`, `--until`, `--limit`, `--cursor`,
   `--reverse`, `--json`) routed through four new socket methods
   (`events.list`, `events.follow_open`, `events.follow_next`,
   `events.follow_close`) over the existing FEAT-002 / FEAT-005 thin-
   client envelope (FR-030 — FR-035, FR-035a). `--follow` is built as a
   long-poll on `events.follow_next` (≤ 30 s wall-clock per call, the
   server-side wait budget) since the FEAT-002 socket protocol is
   request/response by design — the request shape is the streaming
   surface, the protocol is unchanged.

The five locked clarifications from `### Session 2026-05-10` shape the
implementation rather than constrain the spec:

- **FR-040 degraded SQLite is "buffer + retry + visible status".**
  The reader keeps a bounded per-attachment in-memory `_pending`
  deque (capped at one cycle's worth of byte cap × split lines), does
  NOT advance offsets while the SQLite write is failing, surfaces a
  `degraded_events_persistence` field through `agenttower status`, and
  clears it only after the buffered events successfully commit on a
  later cycle.
- **`event_id` is `INTEGER PRIMARY KEY AUTOINCREMENT`.** SQLite's
  rowid alias gives monotonic-per-daemon identity for free, sorts
  naturally as the final tie-breaker after `(observed_at,
  byte_range_start)`, serializes as a JSON number in JSONL, and is
  what `--cursor` encodes (the cursor is `base64url(json({"e":
  <event_id>, "r": <reverse>}))` so it remains opaque at the CLI
  boundary).
- **`record_at` is always `null` in MVP.** The column exists in the
  SQLite schema and the JSONL field is always present-and-null, so
  any future source-time extraction is a non-breaking schema-version
  bump that does not change ordering semantics.
- **No automatic retention, purge, or rotation.** No background job
  prunes the `events` table or the JSONL history; both grow
  indefinitely. Disk usage scales linearly with classifier output.
  The Assumptions block is the operator's contract.
- **Unknown `--target` errors with closed-set `agent_not_found`.**
  The CLI calls `agents.list` (FEAT-006) before returning empty; if
  the agent is not in the FEAT-006 registry the daemon surfaces a
  closed-set `agent_not_found` error envelope and the CLI exits non-
  zero, distinct from "agent registered, no events" which returns
  success with an empty stream.

The single highest-stakes property FEAT-008 introduces — that the
FEAT-007 carry-over invariant "no durable event whose excerpt comes
from pre-reset bytes" holds across truncation, recreation, deletion-
and-recreation, and operator re-attach (FR-043, US4 AS1 — AS5,
SC-004 / SC-005 / SC-006) — is enforced inside the reader by the
ordering rule "ALWAYS call `reader_cycle_offset_recovery` BEFORE any
byte read on that attachment in that cycle" (FR-002), and the
ordering is unit-tested at call-count granularity. The reader does
NOT independently classify file-change events; it consumes
`detect_file_change` / `reader_cycle_offset_recovery` verbatim
(FR-041 / FR-042) and treats the returned `ReaderCycleResult.change`
as the authority on whether the cycle skips bytes (TRUNCATED,
RECREATED, MISSING) or proceeds with a normal read (UNCHANGED,
REAPPEARED — note REAPPEARED on a stale row still skips byte reads
because the row stays stale until operator re-attach per FR-026 of
the FEAT-007 spec).

The second highest-stakes property is rule-priority determinism:
when one record matches multiple regex rules, the catalogue's
documented priority order resolves the tie deterministically every
time (FR-008, SC-007). The catalogue lives in
`events/classifier_rules.py` as an ordered tuple of dataclasses,
each with `rule_id`, `event_type`, `matcher` (compiled regex with
`re.ASCII` for the closed-set patterns and `re.NOFLAG` for everything
else), and `priority` (lower = higher priority). The classifier
walks the tuple in order and returns at the first match. Rule fixtures
in `tests/unit/test_classifier_rules.py` exercise every rule
positively, every rule negatively (line that MUST fall through), and
every documented overlap case (e.g., `Error: test_<x> failed` MUST
classify as `error`, not `test_failed`, by priority).

The CLI surface is intentionally narrow: `agenttower events` is the
only new subcommand, and `--follow` is the only flag whose semantics
require a longer protocol round-trip (long-poll). Every other flag
is a pure SQLite filter expression that compiles to a single
parameterized query in the daemon. `--json` re-uses the JSONL stable
schema verbatim (FR-027 / FR-032) so a script piping `events --json`
to `events.jsonl` would see the same shape (modulo `jsonl_appended_
at`, which is internal-only and never exposed in the CLI output).

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001 — FEAT-007;
`pyproject.toml` pins `requires-python>=3.11`). Standard library only —
no third-party runtime dependency added.

**Primary Dependencies**: Standard library only — `sqlite3` (events
table CRUD; `INTEGER PRIMARY KEY AUTOINCREMENT` rowid alias for
`event_id`; per-statement parameterization), `re` (compiled rule
matchers; `re.ASCII` flag for the closed-set `AGENTTOWER_SWARM_MEMBER`
parser; no `re.DOTALL` on user-influenced lines to avoid newline
ambiguity), `os` / `pathlib` (`os.read` from already-open log file
descriptors managed by the reader, `os.fstat` for liveness checks),
`time` (`time.monotonic()` for the cycle-cap clock and the long-poll
budget; `time.time()` is forbidden inside the reader's hot path —
the test seam injects a `Clock` Protocol), `datetime` (`observed_at`
ISO-8601 microsecond UTC timestamps consistent with FEAT-007's
`attached_at` shape), `threading` (one daemon-side reader thread,
plus a `threading.Event`-based wakeup for graceful shutdown; FEAT-007's
per-`log_path` mutex registry is reused verbatim for the per-
attachment commit critical section), `dataclasses`, `typing`, `json`,
`base64` (cursor encoding), `argparse` (CLI). Reuses FEAT-001
`events.writer.append_event` verbatim for the JSONL append (FR-025);
reuses FEAT-002 socket server (`socket_api/server.py`), client
(`socket_api/client.py`), envelope (`socket_api/errors.py`) verbatim
and adds five new closed-set error codes (`agent_not_found`,
`events_session_unknown`, `events_session_expired`,
`events_invalid_cursor`, `events_filter_invalid`); reuses FEAT-005
in-container identity detection for the CLI side; reuses FEAT-006
`agents/service.py` `list_agents` / resolution helpers for the
`--target` registry lookup that drives the `agent_not_found` check;
reuses FEAT-007 `logs/redaction.py` `redact_one_line` verbatim
(FR-012); reuses FEAT-007 `logs/reader_recovery.py`
`reader_cycle_offset_recovery` verbatim (FR-002 / FR-023 / FR-041);
reuses FEAT-007 `state/log_offsets.py` `detect_file_change`
verbatim (FR-042); reuses FEAT-007 `logs/lifecycle.py` for any
diagnostic emissions on the FEAT-007 surface (FR-026 / FR-037).

**Storage**: One SQLite migration `v5 → v6` (FEAT-008), adding
exactly one new table (`events`) and four supporting indexes; no
existing table is touched. `CURRENT_SCHEMA_VERSION` advances from
`5` (FEAT-007) to `6`. Migration is idempotent on re-open via
`IF NOT EXISTS`, runs under a single `BEGIN IMMEDIATE` transaction
inside `schema._apply_pending_migrations`, and refuses to serve the
daemon on rollback (mirrors FEAT-007's pattern). The events table
schema (full text in `data-model.md`):

```sql
CREATE TABLE events (
    event_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type         TEXT NOT NULL CHECK (event_type IN (
        'activity', 'waiting_for_input', 'completed', 'error',
        'test_failed', 'test_passed', 'manual_review_needed',
        'long_running', 'pane_exited', 'swarm_member_reported'
    )),
    agent_id           TEXT NOT NULL,
    attachment_id      TEXT NOT NULL,
    log_path           TEXT NOT NULL,
    byte_range_start   INTEGER NOT NULL,
    byte_range_end     INTEGER NOT NULL,
    line_offset_start  INTEGER NOT NULL,
    line_offset_end    INTEGER NOT NULL,
    observed_at        TEXT NOT NULL,
    record_at          TEXT CHECK (record_at IS NULL),   -- MVP-enforced
    excerpt            TEXT NOT NULL,              -- redacted, ≤ excerpt cap
    classifier_rule_id TEXT NOT NULL,
    debounce_window_id          TEXT,
    debounce_collapsed_count    INTEGER NOT NULL DEFAULT 1,
    debounce_window_started_at  TEXT,
    debounce_window_ended_at    TEXT,
    schema_version     INTEGER NOT NULL DEFAULT 1,
    jsonl_appended_at  TEXT                        -- NULL until JSONL succeeds
);

CREATE INDEX idx_events_agent_eventid
    ON events (agent_id, event_id);
CREATE INDEX idx_events_type_eventid
    ON events (event_type, event_id);
CREATE INDEX idx_events_observedat_eventid
    ON events (observed_at, event_id);
CREATE INDEX idx_events_jsonl_pending
    ON events (event_id) WHERE jsonl_appended_at IS NULL;
```

The JSONL append target is the existing FEAT-001 `events.jsonl`
file at `~/.local/state/opensoft/agenttower/events.jsonl`; no new
audit log path is introduced (FR-025). Because FEAT-007 already
appends `log_attachment_change` audit rows AND lifecycle events
through the FEAT-007 lifecycle logger surface (which writes to the
SAME `events.jsonl` per FEAT-001 / FEAT-007), the FR-026 separation
is preserved by the `event_type` field being the discriminator: the
durable FEAT-008 events use the closed-set ten types only, the
FEAT-007 lifecycle events use the FEAT-007 closed-set types
(`log_rotation_detected`, `log_file_missing`, `log_file_returned`,
`log_attachment_orphan_detected`, `mounts_json_oversized`,
`socket_peer_uid_mismatch`, plus `log_attachment_change` audit), and
no overlap exists by spec construction. The optional consolidated
test (FR-044) reads the JSONL after a contrived rotation-and-classify
sequence and asserts both sets of types appear, both with their
expected counts, with no cross-contamination.

**Testing**: pytest (≥ 7), reusing the FEAT-002 / FEAT-003 / FEAT-004
/ FEAT-005 / FEAT-006 / FEAT-007 daemon harness in
`tests/integration/_daemon_helpers.py` verbatim — every FEAT-008
integration test spins up a real host daemon under an isolated
`$HOME` and drives the `agenttower` console script as a subprocess.
The five existing test seams (`AGENTTOWER_TEST_DOCKER_FAKE`,
`AGENTTOWER_TEST_TMUX_FAKE`, `AGENTTOWER_TEST_PROC_ROOT`,
`AGENTTOWER_TEST_LOG_FS_FAKE`) are reused unchanged. Two new test
seams are introduced:

- `AGENTTOWER_TEST_EVENTS_CLOCK_FAKE` — a JSON-encoded
  `{"observed_at_iso": <ISO-string>, "monotonic": <float>}` consumed
  by the reader's `Clock` Protocol so debounce windows, the per-cycle
  wall-clock cap, the `pane_exited` grace window, and the
  `long_running` grace window are all deterministic in tests without
  real-time `time.sleep` calls.
- `AGENTTOWER_TEST_READER_TICK` — a unix domain socket path the
  reader, when set, blocks on instead of `time.sleep` between
  cycles; tests write one byte to the socket to advance the reader
  by exactly one cycle. This makes US3 restart tests, US4 carry-over
  tests, and US2 follow tests deterministic on slow CI runners.

Integration tests cover every US1 / US2 / US3 / US4 / US5 / US6
acceptance scenario plus the spec's 14 edge cases. Unit tests cover
every concern enumerated in the spec's SCs:

- Classifier rule catalogue: priority order (FR-008), every rule
  positive + negative + overlap fixture (SC-007), conservative-default
  rule (FR-011), strict `swarm_member_reported` parser including
  malformed-fallback (FR-009), redaction-before-truncation (Edge
  Cases), every rule's `re.ASCII` / non-ReDoS audit;
- Debounce: `activity`-only collapse (FR-014), one-to-one classes
  pass through, debounce state does NOT span restarts (FR-015),
  `window_id` opacity, collapsed_count math, latest excerpt
  preservation;
- Reader cycle: ordering rule "recovery FIRST" (FR-002 call-count
  assertion), atomic SQLite + offset commit per emitted event
  (FR-006 partial-failure unit), partial-line carryover (FR-005),
  per-cycle byte cap (FR-019), the FR-040 buffered-retry path, the
  FR-029 JSONL retry path with watermark advance, the FR-039
  missing-offset-row skip path, the FR-038 EACCES surfacing path;
- `pane_exited` inference: requires FEAT-004 pane-inactive
  observation AND grace-window expiry (FR-016 / FR-017), one-per-
  lifecycle (FR-018), pane-id-reuse counts as new lifecycle once
  re-attached;
- `long_running` inference: per-attachment last-output-at tracking
  (FR-013), eligibility table line-by-line, exactly-once-per-running-
  task semantics, debounce interaction;
- Schema migration v5 → v6: v5-only DB upgrade, v6-already-current
  re-open, forward-version refusal (mirrors FEAT-007's
  `test_schema_migration_v5.py`);
- Events DAO: insert with idempotent JSONL watermark, list with
  every filter combination, cursor round-trip stability, `--reverse`
  inverts ordering, `agent_not_found` lookup;
- CLI: `events` human output, `events --json` schema validation
  against `contracts/event-schema.md` JSON Schema, `events --follow`
  long-poll budget, SIGINT handling, daemon-unreachable surface,
  host-vs-container parity (SC-012);
- AST gate: `tests/unit/test_logs_offset_advance_invariant.py`
  continues to pass (SC-008) — the reader imports `lo_state` but
  never imports `advance_offset_for_test`.

A backwards-compatibility test (`test_feat008_backcompat.py`) gates
the SC parallel to FEAT-007's by re-running every FEAT-001..007 CLI
command and asserting byte-identical stdout, stderr, exit codes, and
`--json` shapes. T175 (truncation timing), T176 (recreation timing),
and T177 (round-trip) move from FEAT-007's `tasks.md` carryover queue
to FEAT-008's `tests/integration/`. The optional consolidated lifecycle
test (FR-044) lands as `test_lifecycle_separation.py` and asserts
the JSONL audit log contains both FEAT-007 lifecycle types and
FEAT-008 durable types with no overlap (per `event_type` whitelist).

**Target Platform**: Linux/WSL developer workstations. The daemon
continues to run exclusively on the host (constitution principle I);
FEAT-008 introduces zero new in-container processes and zero new
`docker exec` codepaths. The reader is a single host-side thread
that reads from local files (the FEAT-007 host-visible log paths
under `~/.local/state/opensoft/agenttower/logs/<container_id>/...`).
The `events` CLI runs from inside a bench container as a short-lived
thin client (FR-035 via FEAT-005) or from the host with `--target`,
and routes every call through the existing Unix socket. No new
network listener.

**Project Type**: Single-project Python CLI + daemon. Extends
`src/agenttower/`. Three existing modules (`cli.py`,
`state/schema.py`, `socket_api/methods.py`) gain additive surfaces;
one existing module (`socket_api/errors.py`) gains five new closed-
set error codes; one existing module (`daemon.py`) gains the reader-
thread lifecycle (start at boot after FEAT-007 attachments are
loaded, stop on graceful shutdown signal); one existing package
(`events/`) gains four new modules (`classifier.py`,
`classifier_rules.py`, `reader.py`, `debounce.py`, `dao.py`,
`session_registry.py`); zero existing modules have their semantics
changed.

**Performance Goals**:

- SC-001 — End-to-end (write → reader cycle → SQLite commit → CLI
  render) ≤ 5 s. The reader cycle target is ≤ 1 s (FR-001), the
  SQLite commit budget is ≤ 50 ms per event (parameterized insert
  + offset advance in one transaction; SQLite WAL on a local SSD
  measures ≪ 10 ms), and the CLI render budget is the human's
  query time, capped at the page size (50). The 5 s budget is
  comfortable.
- SC-002 — `events --follow` prints a new event within ≤ 1 s of the
  last byte of its triggering record being flushed to disk. The
  follow long-poll wakes within `EVENTS_FOLLOW_POLL_GRANULARITY` =
  100 ms (the daemon's reader-thread wakeup pings the
  follow_session_registry); SC-002 is met with a margin.
- Classifier per-record budget: ≤ 1 ms per record, dominated by
  the highest-priority regex match. With 10 rules of bounded length
  and `re.ASCII` patterns this is trivially met; the test seam in
  `test_classifier_perf.py` measures and asserts.
- Reader memory bound: per-attachment cycle buffer ≤ 64 KiB
  (per-cycle byte cap) + the FR-040 pending deque cap (≤ 64 KiB
  worth of events) ≈ ≤ 128 KiB per active attachment. At MVP scale
  (≤ 50 agents) this is ≤ 6.4 MiB total, well below any practical
  bound.
- Default page size 50 (FR-030); `--limit` cap is the same MVP
  default; cursor-based pagination is O(log N) per page through
  `idx_events_agent_eventid`.

**Constraints**:

- Reader cycle wall-clock cap: ≤ 1 s (FR-001 / SC-002), enforced by
  `Clock`-injected `monotonic()` budget per cycle. If a single
  attachment's classify+commit run exceeds half the cycle (≤ 500 ms),
  the reader yields and processes the remaining attachments on the
  next cycle (per-attachment fairness). The cap is configurable
  (FR-045) via `[events]` section in `config.toml`.
- Per-cycle byte cap: 65 536 bytes (64 KiB) per attachment per cycle
  (FR-019). Configurable.
- Per-event excerpt cap: 1024 bytes after redaction; truncation
  marker `"…[truncated]"` (12 bytes) is appended within the cap.
  Configurable (FR-045).
- Debounce window for `activity`: 5 s wall-clock from the first
  collapse-eligible record (FR-014). Configurable.
- `pane_exited` grace window: 30 s after FEAT-004 marks the pane
  inactive AND no new log bytes (FR-017). Configurable.
- `long_running` grace window: 30 s after the last byte on an
  ongoing task (FR-013). Configurable.
- `events.follow_next` long-poll budget: ≤ 30 s wall-clock per call
  (server-side); the CLI re-issues automatically on timeout.
- Reader is a single thread (no asyncio in MVP) to keep the lock
  story simple — every commit goes through one writer thread plus
  the FEAT-007 per-`log_path` mutex.
- No third-party dependencies beyond stdlib (project rule).
- File modes: SQLite WAL files inherit FEAT-001's `0o600` / `0o700`;
  `events.jsonl` is owned by FEAT-001; FEAT-008 introduces zero new
  file modes.

**Scale/Scope**: ≤ 50 attached agents, ≤ a few KB/s per agent of
typical interactive output, ≤ ~10 events/s sustained per attachment
under burst (most collapse via debounce). The events table grows
unbounded (no retention in MVP — Assumptions). At 1 event/s × 50
agents × 86400 s/day = 4.32 M rows/day — local SQLite handles this
comfortably for months at this scale. The operator owns retention.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Justification |
|---|---|---|
| I. Local-First Host Control | **PASS** | The reader runs on the host daemon; bench containers continue to use thin-client CLI over the mounted Unix socket. No network listener. Durable state lives entirely under the host user's `~/.local/state/opensoft/agenttower/`. The new `events` table is an additive SQLite migration in the existing state DB. |
| II. Container-First MVP | **PASS** | FEAT-008 ingests pane logs that FEAT-007 already attached for bench containers. No host-only tmux ingestion (Assumption: MVP scope is bench containers only). No new in-container processes — the reader is host-side and reads from host-visible log files. |
| III. Safe Terminal Input | **PASS** | FEAT-008 only OBSERVES log output, it never types into terminals. The classifier is rule-based, conservative (FR-011), and produces redacted excerpts only (FR-012). No automatic input delivery (out of scope, Assumptions). |
| IV. Observable and Scriptable | **PASS** | The whole point of FEAT-008. Durable SQLite + append-only JSONL, fully scriptable CLI (`events --json`), failure-visibility through `agenttower status` (`degraded_events_persistence`) and FEAT-007's lifecycle logger (FR-037). Failures produce actionable CLI output (`agent_not_found`, daemon-unreachable, etc.) — never silent degradation. |
| V. Conservative Automation | **PASS** | The classifier is rule-based only, the rule catalogue is closed for MVP (FR-007), no LLM call, no model inference. FEAT-008 emits events; it does NOT decide workflows or execute commands based on classification (out-of-scope per Assumptions). Masters / FEAT-009 / FEAT-010 own automation. |

No constitution violations to justify; the Complexity Tracking section
is empty.

## Project Structure

### Documentation (this feature)

```text
specs/008-event-ingestion-follow/
├── spec.md              # Clarified spec
├── plan.md              # This file
├── research.md          # Phase 0: defaults, classifier rule shapes, deferred decisions
├── data-model.md        # Phase 1: events table schema, JSONL schema, in-memory state
├── contracts/           # Phase 1: socket methods, CLI surface, JSON schema, classifier catalogue
│   ├── socket-events.md
│   ├── cli-events.md
│   ├── event-schema.md
│   └── classifier-catalogue.md
├── quickstart.md        # Phase 1: end-to-end ingest+follow demo
├── checklists/          # Already populated by /speckit.checklist
│   ├── requirements.md
│   ├── reliability.md
│   ├── classifier.md
│   ├── cli.md
│   ├── carryover.md
│   └── failure.md
└── tasks.md             # NOT created by this command
```

### Source Code (repository root)

```text
src/agenttower/
├── events/
│   ├── __init__.py            # Package metadata; re-exports public types
│   ├── writer.py              # FEAT-001 JSONL writer (UNCHANGED)
│   ├── classifier.py          # NEW — pure classify(record, state) -> ClassifierOutcome
│   ├── classifier_rules.py    # NEW — ordered tuple of Rule dataclasses
│   ├── debounce.py            # NEW — per-attachment per-class window state
│   ├── reader.py              # NEW — EventsReader, run_loop(), one cycle
│   ├── dao.py                 # NEW — events table CRUD + cursor encode/decode
│   ├── session_registry.py    # NEW — follow-session lifecycle (open/next/close)
│   └── service.py             # NEW — daemon-side façade consumed by socket methods
├── state/
│   ├── schema.py              # MODIFIED — bump CURRENT_SCHEMA_VERSION 5 → 6,
│   │                          #   add _migrate_v5_to_v6 with the events DDL above
│   ├── log_attachments.py     # UNCHANGED
│   └── log_offsets.py         # UNCHANGED (reader uses existing advance helpers
│                              #   via insert_into_logs API; no new public symbol)
├── socket_api/
│   ├── methods.py             # MODIFIED — add _events_list / _events_follow_open /
│   │                          #   _events_follow_next / _events_follow_close
│   │                          #   dispatchers; add _agent_not_found error envelope
│   ├── errors.py              # MODIFIED — add 5 closed-set error codes
│   └── server.py              # UNCHANGED (request/response only)
├── cli.py                     # MODIFIED — add `events` subparser + flags
├── daemon.py                  # MODIFIED — start/stop reader thread,
│                              #   register follow_session_registry in DaemonContext
└── logs/                      # All UNCHANGED (FEAT-007 surfaces consumed verbatim)

tests/
├── unit/
│   ├── test_classifier_rules.py             # NEW — every rule positive/negative/overlap
│   ├── test_classifier_priority.py          # NEW — priority order determinism
│   ├── test_classifier_swarm_member.py      # NEW — strict parse + malformed fallback
│   ├── test_classifier_redaction.py         # NEW — redaction before truncation
│   ├── test_classifier_long_running.py      # NEW — last-output-at, eligibility
│   ├── test_debounce_activity.py            # NEW — collapse + window math
│   ├── test_debounce_one_to_one.py          # NEW — non-collapse classes pass through
│   ├── test_debounce_restart_reset.py       # NEW — FR-015
│   ├── test_reader_recovery_first.py        # NEW — FR-002 call-count
│   ├── test_reader_partial_line_carry.py    # NEW — FR-005
│   ├── test_reader_byte_cap.py              # NEW — FR-019
│   ├── test_reader_atomic_commit.py         # NEW — FR-006
│   ├── test_reader_degraded_sqlite.py       # NEW — FR-040 buffered retry
│   ├── test_reader_jsonl_watermark.py       # NEW — FR-029
│   ├── test_reader_missing_offset_row.py    # NEW — FR-039
│   ├── test_reader_eaccess_isolated.py      # NEW — FR-038, FR-036
│   ├── test_events_dao_cursor.py            # NEW — round-trip stability
│   ├── test_events_dao_filters.py           # NEW — every filter combination
│   ├── test_schema_migration_v6.py          # NEW — v5 upgrade, v6 re-open, forward refusal
│   ├── test_logs_offset_advance_invariant.py # UNCHANGED — must continue to pass (SC-008)
│   └── (existing FEAT-001..007 unit tests UNCHANGED)
├── integration/
│   ├── test_events_us1_inspect.py           # NEW — US1 acceptance scenarios 1–5
│   ├── test_events_us2_follow.py            # NEW — US2 acceptance scenarios
│   ├── test_events_us3_restart.py           # NEW — US3 acceptance scenarios + SC-003
│   ├── test_events_us4_carryover.py         # NEW — US4 AS1–AS5; subsumes T175/T176/T177
│   ├── test_events_us5_json.py              # NEW — US5 acceptance + SC-011
│   ├── test_events_us6_failure.py           # NEW — US6 + SC-010
│   ├── test_events_host_container_parity.py # NEW — SC-012
│   ├── test_lifecycle_separation.py         # NEW — FR-026 / FR-044 / SC-009
│   ├── test_events_agent_not_found.py       # NEW — FR-035a
│   ├── test_feat008_backcompat.py           # NEW — every FEAT-001..007 CLI byte-identical
│   └── (existing FEAT-001..007 integration tests UNCHANGED)
└── conftest.py                # MODIFIED — register the two new test seams
```

**Structure Decision**: Single-project Python CLI + daemon, mirroring
the package-per-domain split established by FEAT-003 (`discovery/`),
FEAT-004 (`tmux/`), FEAT-005 (`config_doctor/`), FEAT-006 (`agents/`),
and FEAT-007 (`logs/`). The existing `events/` package gains five new
modules but keeps `writer.py` (FEAT-001's JSONL writer) unchanged. No
new top-level package is introduced.

## Implementation Notes

### Defaults locked (FR-045 obligations)

The MVP defaults named in the spec are codified in
`config.toml` under a new `[events]` section. The values in the
table below are also encoded as constants in
`src/agenttower/events/__init__.py` so the daemon can boot without
a config file.

| Setting | Default | Spec ref |
|---|---|---|
| `reader_cycle_wallclock_cap_seconds` | `1.0` | FR-001, SC-002 |
| `per_cycle_byte_cap_bytes` | `65536` (64 KiB) | FR-019 |
| `per_event_excerpt_cap_bytes` | `1024` | Edge Cases |
| `excerpt_truncation_marker` | `"…[truncated]"` | Edge Cases |
| `debounce_activity_window_seconds` | `5.0` | FR-014 |
| `pane_exited_grace_seconds` | `30.0` | FR-017 |
| `long_running_grace_seconds` | `30.0` | FR-013 |
| `default_page_size` | `50` | FR-030 |
| `max_page_size` | `50` | FR-030 |
| `follow_long_poll_max_seconds` | `30.0` | (internal) |
| `follow_session_idle_timeout_seconds` | `300.0` | (internal) |

`agenttower config paths` is extended to surface a `[events]`
subsection (FR-045) listing the resolved values.

### `--cursor` encoding

The cursor is opaque at the CLI boundary. Internally:

```python
cursor = base64url(json.dumps(
    {"e": last_event_id, "r": reverse_flag},
    separators=(",", ":"),
)).rstrip("=")
```

The decoder validates: (a) base64url-decodable, (b) JSON object with
exactly the two keys, (c) `e` is a positive int, (d) `r` is a bool.
Any failure → closed-set `events_invalid_cursor`. This keeps the
encoding stable across MVP minor versions while letting future
features add an opaque field without breaking older clients (the
decoder is forward-tolerant of new keys but the current coder is
strict).

### Follow long-poll model

`events.follow_open(target?, types[]?, since?)` registers a follow-
session in `session_registry` keyed by a UUID-like opaque
`session_id` (12 hex, mirrors FEAT-006 `agent_id` shape). The
session stores: filter predicate, last-emitted `event_id`,
expiration timestamp.

`events.follow_next(session_id, max_wait_seconds?)` blocks (≤ 30 s
server-side) until either: (a) a new event matching the filter is
committed and visible, OR (b) the budget expires. Returns
`{events: [...], session_open: true}`. The reader thread, after
each successful SQLite commit, signals a `threading.Condition` on
the session registry; followers wake, query the DAO with
`event_id > last_emitted`, and return.

`events.follow_close(session_id)` removes the session. The CLI
calls this on SIGINT and on stream-error.

`events.follow_open` against an unknown `--target` returns the same
`agent_not_found` error envelope used by `events.list` (FR-035a).

### `pane_exited` and `long_running` synthesis

These two event types are NOT regex matches on log text. They are
synthesized by the reader at cycle entry, BEFORE classification:

- **`long_running`**: each cycle, the reader walks every attachment's
  `last_output_at`. If `now - last_output_at >= long_running_grace`
  AND the most recent prior emitted event for that attachment is in
  the FR-013 eligibility set (`activity`, `error`, `test_failed`,
  `test_passed`, `manual_review_needed`, `swarm_member_reported`,
  `completed` only when its content was an in-progress marker) AND
  no `long_running` has been emitted since the last eligible event,
  emit one `long_running` event with `byte_range_start =
  byte_range_end = persisted_byte_offset`, `excerpt = ""`.
- **`pane_exited`**: each cycle, the reader queries FEAT-004's pane
  service for the attached `(container_id, pane_composite_key)`. If
  pane is inactive AND `now - last_output_at >= pane_exited_grace`,
  emit one `pane_exited` event for that attachment's lifecycle.
  Re-binding (FEAT-004 pane-id reuse + new attachment) starts a new
  lifecycle counter.

These two synthesized types are debounce-class one-to-one (FR-014)
and exactly-once-per-trigger (FR-018 for `pane_exited`).

### `agent_not_found` flow

Both `events.list` and `events.follow_open` accept an optional
`target` parameter. When present, the daemon calls
`agents.list_agents` (FEAT-006), filters by exact `agent_id` match,
and:

- If a row exists → proceed to query/follow path.
- If no row → return `{error: {"code": "agent_not_found",
  "message": "no agent registered with id <id>"}}`.

The CLI maps the closed-set code to non-zero exit status `4` (a new
exit code; existing codes 0-3 are reserved by FEAT-001..007). The
human message is also written to stderr; stdout receives no event
output. `--json` mode writes `{"error": {...}}` to stderr (NOT
stdout) so a downstream `jq` consumer cannot mistake an error for
an event.

## Implementation Deviations

None for FEAT-008. The plan does not deviate from spec-locked
behavior. Five points are worth flagging because they look like
deviations on first read but are explicit per-spec choices documented
in `## Clarifications`:

### 1. `record_at` is a column but always NULL in MVP

The spec's clarification locks `record_at` as always-`null` for
FEAT-008. Rather than omit the column from the SQLite schema and the
JSONL field set, the implementation includes both — the column is
nullable, the JSONL emits `null` (not "missing key") — so any future
feature that populates `record_at` is a non-breaking schema-version
bump per FR-027.

### 2. `jsonl_appended_at` is internal, never exposed

The events table includes a `jsonl_appended_at` column used solely as
the FR-029 watermark. It is NOT part of the JSONL stable schema
(FR-027 / FR-032), is NOT returned by `events.list`, and is NOT
visible through `agenttower events --json`. It exists only so the
reader can recover from a JSONL-degraded period without holding state
in memory across restarts.

### 3. Reader is a single thread, not asyncio

The constitution and existing code (FEAT-001..007) use plain
`threading`. FEAT-008 follows the same pattern: one daemon-side
reader thread, no asyncio. The follow-session registry uses
`threading.Condition` for the long-poll wakeup. Concurrency between
followers is bounded by the registry lock; concurrency between
follower reads and the writer commit is bounded by SQLite's
default WAL snapshot isolation. This is the same pattern FEAT-002's
socket server already uses.

### 4. Cursor is integer-backed but encoded for opacity

The clarification explicitly chose `event_id` as `INTEGER PRIMARY
KEY AUTOINCREMENT`. The cursor is opaque at the CLI boundary
(operator MUST round-trip the value verbatim) but is internally a
base64url-encoded JSON object containing the integer event_id. This
matches FEAT-006's pattern for `agent_id` (12-hex strings backed by
a TEXT column) — the type of the underlying identifier and the type
of its serialized form differ, intentionally.

### 5. `events --follow` is long-poll, not server push

The FEAT-002 socket protocol is request/response. Adding bidirectional
streaming would require a protocol change and is out of scope for
FEAT-008. Instead, `--follow` is a CLI loop around
`events.follow_next` with a 30 s server-side wait budget. This
preserves the existing protocol surface while meeting SC-002's
≤ 1 s latency target (the reader signals followers on every commit;
the long-poll wakes within tens of milliseconds in steady state).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations. This section intentionally empty.
