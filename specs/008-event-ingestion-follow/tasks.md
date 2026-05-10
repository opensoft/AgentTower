---
description: "Task list for FEAT-008: Event Ingestion, Classification, and Follow CLI"
---

# Tasks: Event Ingestion, Classification, and Follow CLI

**Input**: Design documents from `/specs/008-event-ingestion-follow/`
**Prerequisites**: plan.md, spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: REQUIRED. The spec mandates fixture coverage and integration tests (FR-008 "test fixture MUST exist for every rule", FR-043 "MUST ship integration tests", SC-007 100 % rule coverage, SC-011 schema strictness, SC-006 100-iteration round-trip).

**Organization**: Tasks are grouped by user story (US1 — US6). Phases 1 and 2 are blocking prerequisites; phases 3 onward map 1:1 to spec.md user stories in priority order (P1, P2, P2, P2, P3, P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User-story label (US1 — US6) for tasks scoped to one story
- File paths are absolute relative to the repository root

## Path Conventions

Single-project Python CLI + daemon. `src/agenttower/` for production code, `tests/unit/` and `tests/integration/` for tests, `specs/008-event-ingestion-follow/` for design artifacts.

---

## Phase 1: Setup

**Purpose**: Land the additive package skeleton, the schema-version bump scaffolding, and the test seams. No user-story logic yet.

- [X] T001 Add `[events]` defaults block constants to `src/agenttower/events/__init__.py` per Plan §"Defaults locked": `READER_CYCLE_WALLCLOCK_CAP_SECONDS = 1.0`, `PER_CYCLE_BYTE_CAP_BYTES = 65536`, `PER_EVENT_EXCERPT_CAP_BYTES = 1024`, `EXCERPT_TRUNCATION_MARKER = "…[truncated]"`, `DEBOUNCE_ACTIVITY_WINDOW_SECONDS = 5.0`, `PANE_EXITED_GRACE_SECONDS = 30.0`, `LONG_RUNNING_GRACE_SECONDS = 30.0`, `DEFAULT_PAGE_SIZE = 50`, `MAX_PAGE_SIZE = 50`, `FOLLOW_LONG_POLL_MAX_SECONDS = 30.0`, `FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS = 300.0`. Re-export `append_event` (FEAT-001 unchanged).
- [X] T002 [P] Add `[events]` configuration parsing to the FEAT-001 config surface (path: `src/agenttower/config.py`); resolved values fall through to T001 constants. Surface them via `agenttower config paths` (FR-045).
- [X] T003 [P] Register the two new test seams in `tests/conftest.py`: `AGENTTOWER_TEST_EVENTS_CLOCK_FAKE` (JSON `{observed_at_iso, monotonic}`) and `AGENTTOWER_TEST_READER_TICK` (Unix-domain-socket path). Include the FEAT-007 production-test-seam guard so production daemons refuse to honor either var.
- [X] T004 [P] Extend the AST gate at `tests/unit/test_logs_offset_advance_invariant.py` to enforce the broader FR-003 / FR-004 prohibitions: (a) forbid imports of `AGENTTOWER_TEST_EVENTS_CLOCK_FAKE` / `AGENTTOWER_TEST_READER_TICK` from any production module under `src/agenttower/`; (b) forbid raw `INSERT INTO log_attachments`, `UPDATE log_attachments`, `INSERT INTO log_offsets`, and `UPDATE log_offsets` SQL fragments from any production module under `src/agenttower/events/` (the reader must go through FEAT-007 helpers and the documented `lo_state.advance_*` API).
- [X] T005 [P] Commit the JSON Schema artifact for the FR-027 stable schema at `tests/integration/schemas/event-v1.schema.json` per `contracts/event-schema.md`. Add the test-only `jsonschema` package as a `[dependency-groups.test]` (or equivalent test-extras) entry in `pyproject.toml` — runtime is still stdlib-only per plan's "Primary Dependencies"; `jsonschema` is test-time only — and wire a validator helper in `tests/integration/_daemon_helpers.py` that loads the schema once per session.
- [X] T101 [P] Capture the FEAT-007 head-of-tree CLI baseline fixtures into `tests/integration/fixtures/feat007_baseline/`: for each FEAT-001..007 documented `agenttower …` invocation, record stdout, stderr, and exit code (one fixture per command, named `<command-with-dashes>.{stdout,stderr,exit}`). T092 in Phase 9 consumes these fixtures byte-for-byte. Plan §R12. **Note**: this PR commits `capture.py` + `README.md` as the capture provenance; the fixture sub-directories are produced by running `capture.py` against the FEAT-007 head-of-tree commit and committed in a follow-up.

**Checkpoint**: Package shell, defaults, schema artifact, baseline fixtures, and test seams are in place. Foundational phase can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema migration, error envelope additions, DAO scaffolding, and reader/follow primitives. NO user-story logic. ALL user-story phases depend on these landing.

- [X] T006 Bump `CURRENT_SCHEMA_VERSION` from `5` to `6` in `src/agenttower/state/schema.py` and add `_migrate_v5_to_v6` per `data-model.md` §2.1: create `events` table with all CHECK constraints, plus four indexes (`idx_events_agent_eventid`, `idx_events_type_eventid`, `idx_events_observedat_eventid`, partial `idx_events_jsonl_pending`). Idempotent (`IF NOT EXISTS`). Single `BEGIN IMMEDIATE`. Forward-version refusal mirrors FEAT-007.
- [X] T007 [P] Add five closed-set error codes to `src/agenttower/socket_api/errors.py`: `agent_not_found`, `events_session_unknown`, `events_session_expired`, `events_invalid_cursor`, `events_filter_invalid`. Map to CLI exit codes 4, 5, 5, 6, 7 per `contracts/socket-events.md` §"Error envelope additions".
- [X] T008 [P] Implement the cursor codec in `src/agenttower/events/dao.py`: `encode_cursor(event_id: int, reverse: bool) -> str` and `decode_cursor(token: str) -> tuple[int, bool]` per Research §R8. `decode_cursor` raises `events_invalid_cursor` on any malformed input.
- [X] T009 [P] Implement `events` table CRUD primitives in `src/agenttower/events/dao.py`: `insert_event(conn, EventRow) -> int`, `mark_jsonl_appended(conn, event_id, ts) -> None`, `select_events(conn, filter, cursor, limit, reverse) -> tuple[list[EventRow], cursor | None]`, `select_pending_jsonl(conn, limit) -> list[EventRow]`, `select_event_by_id(conn, event_id) -> EventRow | None`. All parameterized SQL. No `time.sleep`; all clock reads through the injected `Clock` Protocol.
- [X] T010 Define the `EventRow` dataclass and `EventFilter` dataclass in `src/agenttower/events/dao.py` with the field set from `data-model.md` §2.2.
- [X] T011 [P] Define the `Clock` Protocol and a default `SystemClock` implementation in `src/agenttower/events/__init__.py` (`now_iso() -> str`, `monotonic() -> float`). Tests substitute via the T003 seam.
- [X] T012 [P] Define the `FollowSession` dataclass and the `FollowSessionRegistry` in `src/agenttower/events/session_registry.py` (open / refresh / close / janitor) per `data-model.md` §6.
- [X] T013 [P] Add the `events_reader` and `events_persistence` fields to the `agenttower status` socket method response in `src/agenttower/socket_api/methods.py` per `data-model.md` §7. Stub: `running=true`, `last_cycle_*=null`, `degraded_*=null` until reader is wired.
- [X] T014 [P] Add unit tests for the migration in `tests/unit/test_schema_migration_v6.py`: v5→v6 upgrade, v6-already-current re-open is a no-op, forward-version refusal (v7+ DB rejected).
- [X] T015 [P] Add unit tests for cursor encode/decode round-trip in `tests/unit/test_events_dao_cursor.py`: positive round-trip, every error class (malformed base64, malformed JSON, missing keys, wrong types) → `events_invalid_cursor`.
- [X] T016 [P] Add unit tests for events DAO filters in `tests/unit/test_events_dao_filters.py`: every documented filter combination from `contracts/socket-events.md` C-EVT-001 produces the documented index-backed query plan; default ordering matches FR-028.

**Checkpoint**: Schema is at v6, error codes are wired, DAO + cursor + session registry compile. User-story phases can now begin in parallel.

---

## Phase 3: User Story 1 — Operator inspects classified events for an attached agent (Priority: P1) 🎯 MVP

**Goal**: An operator can write a classifier-trigger line into an attached pane log, wait one reader cycle, and see exactly one classified event via `agenttower events --target <agent-id>` with the expected type and a redacted excerpt.

**Independent Test**: Per spec §US1: register an agent, attach its log, write a known classifier-trigger line, wait one cycle, then run `agenttower events --target <agent-id>` and verify exactly one event with the expected classifier type and a redacted excerpt.

### Classifier rule catalogue and matchers

- [X] T017 [P] [US1] Implement the rule dataclass `ClassifierRule` and the ordered tuple `RULES` in `src/agenttower/events/classifier_rules.py` per `contracts/classifier-catalogue.md` §"Catalogue". 11 matcher rules; priorities 10/20/30/31/40/41/50/51/60/70/999.
- [X] T018 [P] [US1] Implement the `swarm_member.v1` strict parser in `src/agenttower/events/classifier_rules.py` with `re.ASCII` flag and the documented capture groups (`parent`, `pane`, `label`, `capability`, `purpose`). Malformed variants return no match (fall through).
- [X] T019 [P] [US1] Implement the synthetic rule ids `pane_exited.synth.v1` and `long_running.synth.v1` as constants in `src/agenttower/events/classifier_rules.py` (NOT part of the matcher tuple — synthesized by the reader).
- [X] T020 [US1] Implement `classify(record: str, prior_event_type: str | None) -> ClassifierOutcome` in `src/agenttower/events/classifier.py`. Walks `RULES` in priority order, returns the first match. Guarantees the `activity.fallback.v1` catch-all matches any non-empty record (FR-011). Pure function — no I/O, no clock reads (FR-010).
- [X] T021 [US1] Implement the excerpt-cap truncation logic in `src/agenttower/events/classifier.py`: redact_one_line first (FR-012), then truncate to `PER_EVENT_EXCERPT_CAP_BYTES` with `EXCERPT_TRUNCATION_MARKER`. Edge case: marker fits within the cap (cap is the OUTER bound).

### Classifier unit tests

- [X] T022 [P] [US1] Add positive + negative + overlap fixtures in `tests/unit/test_classifier_rules.py`. Every rule has at least three lines: matches, must-not-match, edge-of-pattern. Coverage per FR-008 ("test fixture MUST exist for every rule").
- [X] T023 [P] [US1] Add priority-order determinism tests in `tests/unit/test_classifier_priority.py` per `contracts/classifier-catalogue.md` §"Priority overlap fixtures". Every overlap row in the table is one assertion.
- [X] T024 [P] [US1] Add `swarm_member.v1` strict-parse tests in `tests/unit/test_classifier_swarm_member.py`: positive parse with capture validation, malformed-variants → `activity.fallback.v1` (FR-009).
- [X] T025 [P] [US1] Add redaction-before-truncation tests in `tests/unit/test_classifier_redaction.py`: secret-pattern split exactly at the cap boundary remains redacted; redaction utility version-pin assertion.

### Reader cycle, debounce, and DAO

- [X] T026 [P] [US1] Implement `DebounceManager` in `src/agenttower/events/debounce.py` with `submit(attachment_id, classifier_outcome) -> Iterable[EmittedEvent]` per Research §R5. `activity` collapses, the other 9 classes pass through one-to-one. State is `dict[(attachment_id, event_class), DebounceWindow]`. Window flush on cycle visit even when no new record arrives.
- [X] T027 [P] [US1] Add unit tests for `activity` collapse in `tests/unit/test_debounce_activity.py`: one window per `debounce_activity_window_seconds`, `collapsed_count` math, `latest_excerpt` wins, `window_id` is opaque 12-hex.
- [X] T028 [P] [US1] Add unit tests for one-to-one classes in `tests/unit/test_debounce_one_to_one.py`: `error`, `test_failed`, etc. emit one event per qualifying record with `collapsed_count=1` and `window_id=null`.
- [X] T102 [P] [US1] Add unit tests for FR-015 (debounce state MUST NOT span daemon restarts) in `tests/unit/test_debounce_restart_reset.py`: simulate a fresh `DebounceManager` after restart; assert (a) the in-memory window dict is empty, (b) the first `activity` record post-restart opens a NEW window with `collapsed_count=1` (no pre-restart `collapsed_count` carries over), (c) any in-flight pre-restart `collapsed_count > 1` is NOT recoverable.
- [X] T029 [US1] Implement `EventsReader.run_cycle_for_attachment(conn, attachment, clock)` in `src/agenttower/events/reader.py`. Order: (1) `pane_exited` synthesis (FR-016); (2) `long_running` synthesis (FR-013); (3) call FEAT-007 `reader_cycle_offset_recovery` exactly once (FR-002 / FR-023); (4) honor recovery's `change` (skip byte read on TRUNCATED/RECREATED/MISSING); (5) read up to `PER_CYCLE_BYTE_CAP_BYTES`; (6) split on `\n` (FR-005), keep partial trailing bytes for next cycle; (7) per record: `redact_one_line` → `classify` → debounce → emit. Atomic SQLite + offset commit per emitted event (FR-006 / FR-024). Contract: reader does NOT mutate `log_attachments` / `log_offsets` rows directly (FR-003) and is the SOLE production caller of the `log_offsets` advance API (FR-004).
- [X] T030 [US1] Implement `EventsReader.run_loop()` in `src/agenttower/events/reader.py`: thread main; `time.monotonic()`-budgeted cycles capped at `READER_CYCLE_WALLCLOCK_CAP_SECONDS` (FR-001 / FR-007: rule-based only, no LLM call); honors `threading.Event` for shutdown; honors `AGENTTOWER_TEST_READER_TICK` seam in lieu of inter-cycle sleep.
- [X] T031 [US1] Wire reader thread lifecycle into `src/agenttower/daemon.py`: start after FEAT-001..007 init completes; stop cleanly on SIGTERM/SIGINT; surface state to `agenttower status` via the T013 stub.
- [X] T032 [US1] After every successful SQLite commit, append the event to `events.jsonl` via `agenttower.events.writer.append_event` and execute a small follow-up transaction setting `jsonl_appended_at = now_iso()` (FR-025 / FR-029 happy path). Failure leaves the column NULL.

### Reader unit tests

- [X] T033 [P] [US1] Add `tests/unit/test_reader_recovery_first.py`: assert `reader_cycle_offset_recovery` is called exactly once per cycle BEFORE any byte read (FR-002). Fails if call-count is wrong or if read happens first.
- [X] T034 [P] [US1] Add `tests/unit/test_reader_partial_line_carry.py`: a cycle ending on a partial line emits zero events; the next cycle re-reads from the partial-line offset and emits exactly one event (FR-005).
- [X] T035 [P] [US1] Add `tests/unit/test_reader_byte_cap.py`: a cycle with > `PER_CYCLE_BYTE_CAP_BYTES` available emits events for ≤ cap bytes; remaining bytes processed next cycle (FR-019).
- [X] T103 [P] [US1] Add `tests/unit/test_reader_cycle_cap.py` for FR-001: with the T003 `AGENTTOWER_TEST_EVENTS_CLOCK_FAKE` injected, drive `EventsReader.run_loop` for one cycle under a contrived heavy-load fixture (50 fake attachments, each with one classifier-trigger line); assert the cycle's logical-clock duration is ≤ `READER_CYCLE_WALLCLOCK_CAP_SECONDS` (default 1.0 s). Failing this asserts a regression on FR-001's wall-clock cap.
- [X] T036 [P] [US1] Add `tests/unit/test_reader_atomic_commit.py`: simulate SQLite commit failure mid-batch; assert no event row is visible AND no offset advance occurred (FR-006).

### Daemon socket method `events.list`

- [X] T037 [US1] Implement `_events_list` dispatcher in `src/agenttower/socket_api/methods.py` per `contracts/socket-events.md` C-EVT-001: validate filter (T009 DAO), return `agent_not_found` envelope when `target` is not in FEAT-006 registry (FR-035a), return `events_filter_invalid` for unknown types / inverted ranges, return `events_invalid_cursor` for malformed cursors. Returns `{events, next_cursor}`.
- [X] T038 [US1] Wire `_events_list` into the dispatcher table and add peer-uid auth check (reuse FEAT-002 pattern). Also expose the diagnostic `events.classifier_rules` method per C-EVT-005.

### CLI `events` (list mode)

- [X] T039 [US1] Add `events` subparser to `src/agenttower/cli.py` per `contracts/cli-events.md` C-CLI-EVT-001: flags `--target`, `--type` (repeatable), `--since`, `--until`, `--limit`, `--cursor`, `--reverse`, `--json`, plus the hidden `--classifier-rules`. Client-side validation: agent_id shape, type enum, ISO-8601, limit bounds, mutually-exclusive flag combos.
- [X] T040 [US1] Implement `_events_command` (human + JSON output) in `src/agenttower/cli.py`. Human format per `contracts/cli-events.md` (timestamp / agent label & id / event_type / excerpt) — FR-031 default human output. JSON output is the FR-027 / FR-032 stable contract: one event per line, NDJSON-compatible, terminating `\n`. `next_cursor` printed on stderr (`# next_cursor: <token>`) in human mode and as a final single-key JSON line in `--json` mode. FR-030 flag set wired via T039.
- [X] T041 [US1] Map daemon error envelopes to CLI exit codes per `contracts/socket-events.md` §"Error envelope additions" — 4 for `agent_not_found`, 6 for `events_invalid_cursor`, 7 for `events_filter_invalid`. Print human stderr message; in `--json` mode write `{"error": {...}}` to stderr (NOT stdout).

### US1 integration tests

- [X] T042 [P] [US1] `tests/integration/test_events_us1_inspect.py` — Acceptance Scenario 1: write one `error` line, wait one reader cycle, assert exactly one `error` event with the redacted excerpt and `observed_at >= write time`. SC-001 timing assertion: end-to-end (write → reader cycle → SQLite commit → CLI render) wall-clock ≤ 5 s on a normal local SSD-backed CI runner; the test fails if any step blows the budget.
- [X] T043 [P] [US1] `test_events_us1_inspect.py` — AS2: write one `error` then one `test_passed`, assert both appear in strict reader-observed order, oldest-first.
- [X] T044 [P] [US1] `test_events_us1_inspect.py` — AS3: write a line containing one of the FEAT-007 redaction patterns, assert the SQLite excerpt and the JSONL excerpt are both the redacted form.
- [X] T045 [P] [US1] `test_events_us1_inspect.py` — AS4: registered agent with no log attachment → `events --target` returns empty result, exit 0, no synthesized "no attachment" event.
- [X] T046 [P] [US1] `tests/integration/test_events_agent_not_found.py` — AS5 / FR-035a: `events --target agt_doesnotexist` exits 4, stderr contains `agent_not_found`. Same path for `events --follow --target agt_doesnotexist`.

**Checkpoint**: US1 is the MVP increment — list and inspect events end-to-end, with JSON output, redaction, and the `agent_not_found` error contract wired. SC-001 testable from here.

---

## Phase 4: User Story 2 — Operator follows the live event stream (Priority: P2)

**Goal**: `agenttower events --follow` streams new events as they are emitted, optionally filtered by `--target`, with backlog-then-live ordering when `--since` is set.

**Independent Test**: Per spec §US2: start `agenttower events --follow --target <agent-id>` in one terminal; in a second terminal write three classifier-trigger lines spaced > debounce window apart; verify three events appear in order within ≤ 1 reader cycle each, no backlog re-printing.

### Follow session daemon-side

- [X] T047 [US2] Implement `_events_follow_open` dispatcher in `src/agenttower/socket_api/methods.py` per `contracts/socket-events.md` C-EVT-002: register session in `FollowSessionRegistry`, return `{session_id, backlog_events, live_starting_event_id}`. Returns `agent_not_found` for unknown `target`. (Serialize with T048/T049 — same file.)
- [X] T048 [US2] Implement `_events_follow_next` dispatcher in `src/agenttower/socket_api/methods.py` per C-EVT-003: long-poll on `threading.Condition` keyed by session filter; return events with `event_id > last_emitted_event_id` matching the filter, or empty array on timeout. Refresh `expires_at` on each call. Errors `events_session_unknown` / `events_session_expired`. (Serialize after T047.)
- [X] T049 [US2] Implement `_events_follow_close` dispatcher in `src/agenttower/socket_api/methods.py` per C-EVT-004: idempotent; returns `events_session_unknown` for unknown session ids (clients ignore). (Serialize after T048.)
- [X] T050 [US2] Wire reader-thread post-commit notification into the registry: after every successful SQLite commit, the reader calls `registry.notify(event_row)`; followers wake on the condition, requery DAO, return matching events.
- [X] T051 [US2] Implement the cycle-time janitor on the reader thread: between cycles, evict any session whose `expires_at_monotonic < now`. Plan §R9.

### CLI `--follow`

- [X] T052 [US2] Implement `--follow` mode in `_events_command` (`src/agenttower/cli.py`) — FR-033 / FR-034: call `events.follow_open`, optionally print backlog, then loop on `events.follow_next` (≤ 30 s budget per call), print events with stdout flushing, handle SIGINT to call `events.follow_close` and exit 0. On daemon-unreachable mid-stream, exit 3 (FR-034 daemon-unavailable surface).
- [X] T053 [US2] Reject `--limit` / `--cursor` / `--reverse` with `--follow` (exit 2). Handle `BrokenPipeError` (downstream `head -n N`) by calling `events.follow_close` and exiting 0 (treat SIGPIPE as success).

### US2 integration tests

- [X] T054 [P] [US2] `tests/integration/test_events_us2_follow.py` — AS1: `events --follow` (no target) prints any attached agent's new event within ≤ 1 cycle.
- [X] T055 [P] [US2] `test_events_us2_follow.py` — AS2: `events --follow --target X` does NOT print events from agent Y.
- [X] T056 [P] [US2] `test_events_us2_follow.py` — AS3: SIGINT after idle exits 0, stdout has no further output. Use the T003 reader-tick seam to drive the timing deterministically.
- [X] T057 [P] [US2] `test_events_us2_follow.py` — `--since`-then-live ordering: `--since` prints bounded backlog FIRST, live events SECOND, with no overlap (uses `live_starting_event_id` from `follow_open`).

**Checkpoint**: US2 follow stream is live; SC-002 testable from here.

---

## Phase 5: User Story 3 — Daemon restart does not duplicate events (Priority: P2)

**Goal**: After a daemon stop and restart, the reader resumes from the persisted offset; the SQLite events count and JSONL appended-line count remain unchanged for every attached agent (zero duplicates, zero drops).

**Independent Test**: Per spec §US3: write five trigger lines, allow one cycle, stop daemon, verify count = 5, restart, wait two cycles with no new writes, verify count is still 5.

### Restart-resume verification

- [ ] T058 [US3] Confirm reader uses persisted `log_offsets.byte_offset` as the authoritative resume point on cold start (FR-020). Add explicit assertion in `EventsReader.__init__` that no in-memory offset cache is loaded across restart. Document the FR-022 invariant in the module docstring (restart resume MUST NOT depend on JSONL state; SQLite + persisted offsets are the source of truth).
- [ ] T059 [US3] Confirm FR-021 invariant: `EventsReader.run_cycle_for_attachment` emits no event whose `byte_range_start < persisted_byte_offset` at cycle entry. Add a guard with a clear assertion message. Document the FR-023 invariant: the cycle delegates file-change classification to `reader_cycle_offset_recovery` (no inlined logic, FR-042).

### US3 integration tests

- [ ] T060 [P] [US3] `tests/integration/test_events_us3_restart.py` — AS1: persist N events, stop daemon, count rows, restart, wait two cycles, assert SQLite + JSONL counts unchanged.
- [ ] T061 [P] [US3] `test_events_us3_restart.py` — AS2: simulate daemon kill mid-cycle (after read but before commit; use the T003 tick seam to position the kill); restart; assert no duplicates, no drops, offsets resumed.
- [ ] T062 [P] [US3] `test_events_us3_restart.py` — AS3: append bytes while daemon is down; restart; assert reader ingests only the post-stop bytes and emits events only for them.
- [ ] T063 [P] [US3] `test_events_us3_restart.py` — SC-003: 10 consecutive restarts with no log writes; SQLite event count and JSONL line count unchanged for every attached agent across all 10 iterations.

**Checkpoint**: Restart safety proven; SC-003 satisfied.

---

## Phase 6: User Story 4 — File-change carry-over from FEAT-007 (Priority: P2)

**Goal**: Truncation, recreation, deletion, and operator-explicit re-attach behave per the FEAT-007 spec, including timing assertions (≤ 1 reader cycle) and the no-replay invariant. Lands T175, T176, T177 carried over from FEAT-007.

**Independent Test**: Per spec §US4: drive each of (truncate-in-place, delete-and-recreate with new inode, delete-and-leave-missing, missing-then-reappear-then-re-attach) against a real reader loop; assert documented row-status transitions, lifecycle event emissions, offset resets, and absence of any event whose excerpt comes from pre-reset bytes.

### Reader integration with FEAT-007

- [ ] T064 [US4] Audit `EventsReader.run_cycle_for_attachment` (T029) for the FR-003 / FR-041 / FR-042 obligations: `reader_cycle_offset_recovery` is the SOLE entry to file-change classification; the reader does NOT call `detect_file_change` directly nor inline its logic; the reader does NOT mutate `log_attachments` or `log_offsets` rows directly. Add docstring assertion and a unit test (`tests/unit/test_reader_recovery_first.py` extension).
- [ ] T065 [US4] Confirm the no-replay invariant in code: when `recovery_result.change in {TRUNCATED, RECREATED}`, the reader skips ALL byte reads in this cycle and does NOT emit any event from the pre-reset window. Add explicit branch and assertion.

### US4 integration tests (T175 / T176 / T177 carried over)

- [ ] T066 [P] [US4] `tests/integration/test_events_us4_carryover.py` — AS1 (T175 truncation): truncate the log in place; assert offsets reset to (0, 0, 0) within ≤ 1 reader cycle; `file_size_seen` updated; one `log_rotation_detected` lifecycle event; zero durable events from pre-truncate bytes.
- [ ] T067 [P] [US4] `test_events_us4_carryover.py` — AS2 (T176 recreation): delete-and-recreate with new inode; offsets reset; one `log_rotation_detected`; no pre-recreation event.
- [ ] T068 [P] [US4] `test_events_us4_carryover.py` — AS3: file deleted; row transitions `active → stale`; one `log_file_missing`; one `log_attachment_change` audit row; offsets unchanged.
- [ ] T069 [P] [US4] `test_events_us4_carryover.py` — AS4: stale file recreated at same path (no operator action); one `log_file_returned` (suppression-keyed by `(agent_id, log_path, file_inode)`); row stays `stale`; offsets unchanged; no durable event.
- [ ] T070 [P] [US4] `test_events_us4_carryover.py` — AS5 (T177 round-trip): missing → recreated → operator-explicit `attach-log`; re-attach via FEAT-007 file-consistency check; offsets reset per FEAT-007 rules; only post-re-attach bytes produce durable events.
- [ ] T071 [US4] `test_events_us4_carryover.py` — SC-006: 100 iterations of T177 round-trip, 100% pass rate. Use the T003 clock + tick seams to remove wall-clock timing dependency.

**Checkpoint**: All four file-change paths exercised end-to-end; SC-004 / SC-005 / SC-006 satisfied.

---

## Phase 7: User Story 5 — Operator gets machine-readable event output (Priority: P3)

**Goal**: `events --json` produces one JSON object per event per line in the FR-027 stable schema, validated by the JSON Schema artifact from T005.

**Independent Test**: Per spec §US5: append a known trigger line; run `events --target X --json --limit 1`; pipe through `jq` and assert the documented field set is present and types match.

### Schema validation tests

- [ ] T072 [P] [US5] `tests/integration/test_events_us5_json.py` — AS1: append known event-trigger line; `events --target X --json --limit 1` is exactly one JSON object on a single line containing the FR-027 fields and no fields beyond the schema.
- [ ] T073 [P] [US5] `test_events_us5_json.py` — AS2: `--follow --json` extends with new events as one JSON line per event, terminating `\n`.
- [ ] T074 [P] [US5] `test_events_us5_json.py` — SC-011: every event in the integration suite parses against `tests/integration/schemas/event-v1.schema.json` with zero validation failures. Aggregate fixture across US1..US6 events.
- [ ] T075 [P] [US5] `tests/unit/test_event_schema_negative.py` — every documented negative case from `contracts/event-schema.md` §"Negative validation tests" fails schema validation as expected.

### Host vs container parity

- [ ] T076 [P] [US5] `tests/integration/test_events_host_container_parity.py` — SC-012: `events --target X --json --limit 10` from host and from inside a bench container against the same daemon produces byte-identical stdout (modulo newline normalization).

**Checkpoint**: Stable JSON contract proven; SC-011 / SC-012 satisfied.

---

## Phase 8: User Story 6 — Failure surfaces are visible without crashing the daemon (Priority: P3)

**Goal**: Per-attachment failures isolate cleanly (FR-036), unreadable files surface diagnostically (FR-038), missing offset rows skip the cycle (FR-039), degraded SQLite uses the FR-040 buffered-retry pattern, degraded JSONL uses the FR-029 watermark pattern, and `agenttower status` exposes everything.

**Independent Test**: Per spec §US6: make one log unreadable; trigger a cycle; assert other agents still produce events AND the affected attachment's failure is visible via `agenttower status` (or the FEAT-007 lifecycle surface).

### Reader degraded-mode implementation

- [ ] T077 [US6] Implement FR-040 buffered-retry path in `EventsReader`: on SQLite write error, push events onto per-attachment `_pending_events` deque (bounded by `PER_CYCLE_BYTE_CAP_BYTES`), do NOT advance offsets, surface `degraded_sqlite` field on `agenttower status`. On next cycle, attempt flush before reading new bytes; on success, advance offsets and clear the indicator.
- [ ] T078 [US6] Implement FR-029 JSONL retry watermark in `EventsReader`: on JSONL append failure after a successful SQLite commit, leave `jsonl_appended_at` NULL and surface `degraded_jsonl` on `status`. On every subsequent cycle, before processing new bytes, query rows with `jsonl_appended_at IS NULL` (limit `DEFAULT_PAGE_SIZE`) and retry; advance watermark on success.
- [ ] T079 [US6] Implement FR-038 EACCES / I/O failure isolation: per-attachment failure surfaces in `agenttower status.events_reader.attachments_in_failure`; attachment row is NOT lost; FEAT-007 lifecycle surface reuse for mapped failure classes (FR-037).
- [ ] T080 [US6] Implement FR-039 missing-offset-row handling: skip the cycle for that attachment, log the inconsistency through the FEAT-007 lifecycle logger, do NOT invent offset values.

### Reader unit tests

- [ ] T081 [P] [US6] `tests/unit/test_reader_degraded_sqlite.py` — FR-040: simulate SQLite write error mid-cycle; assert events buffered; offsets NOT advanced; status surfaces `degraded_sqlite`. Recovery cycle flushes buffer; condition clears.
- [ ] T082 [P] [US6] `tests/unit/test_reader_jsonl_watermark.py` — FR-029: simulate JSONL append failure post-commit; assert `jsonl_appended_at` stays NULL; status surfaces `degraded_jsonl`; recovery cycle replays via the partial index; condition clears when queue empties.
- [ ] T083 [P] [US6] `tests/unit/test_reader_missing_offset_row.py` — FR-039: attachment row exists, offset row missing; reader skips cycle for that attachment, surfaces inconsistency, no offset invention.
- [ ] T084 [P] [US6] `tests/unit/test_reader_eaccess_isolated.py` — FR-036 / FR-038: one attachment's log unreadable (chmod 0); assert other attachments continue producing events; failed attachment surfaces in `status.events_reader.attachments_in_failure`.

### US6 integration tests

- [ ] T085 [P] [US6] `tests/integration/test_events_us6_failure.py` — AS1: two agents, B's log made unreadable; one cycle elapses; A keeps producing events; B's failure visible via `agenttower status`.
- [ ] T086 [P] [US6] `test_events_us6_failure.py` — AS2: induce SQLite read-only condition; assert FR-040 retry-and-surface; visible failure in status; events flush after recovery (no silent drop).
- [ ] T087 [P] [US6] `test_events_us6_failure.py` — AS3: missing offset row condition; reader skips cycle; inconsistency logged; no offset invention.
- [ ] T088 [P] [US6] `test_events_us6_failure.py` — SC-010: 100 iterations of "one attachment fails, others continue"; 100 % pass rate.

### Synthesized event types (`pane_exited` / `long_running`)

- [ ] T089 [P] [US6] `tests/unit/test_classifier_long_running.py` — FR-013 eligibility table line-by-line per `contracts/classifier-catalogue.md`. Exactly one `long_running` per running task; reset rules; test with the T003 clock seam.
- [ ] T090 [P] [US6] Add `tests/unit/test_classifier_pane_exited.py` — FR-016 / FR-017 / FR-018: `pane_exited` requires FEAT-004 pane-inactive observation AND grace-window expiry; never inferred from log text alone; one-per-lifecycle; pane-id reuse with new attachment counts as a new lifecycle.

**Checkpoint**: Failure surface fully wired; SC-010 satisfied.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Backwards-compat gate, lifecycle separation gate, documentation, and the constitution re-check.

- [ ] T091 [P] `tests/integration/test_lifecycle_separation.py` — FR-026 / FR-044 / SC-009: drive a contrived rotation+classify sequence; partition `events.jsonl` by `event_type`; assert FEAT-007 lifecycle types and FEAT-008 durable types both present, no overlap.
- [ ] T092 [P] `tests/integration/test_feat008_backcompat.py` — every FEAT-001..007 CLI command (full surface enumeration) produces byte-identical stdout, stderr, exit codes, and `--json` shapes against pre-FEAT-008 fixtures captured at plan time. Plan §R12.
- [ ] T093 [P] Update `agenttower config paths` integration test (`tests/integration/test_cli_paths.py`) to assert the `[events]` subsection surfaces every FR-045 default with its resolved value.
- [ ] T094 [P] Add `events` quickstart validation: drive `specs/008-event-ingestion-follow/quickstart.md` Steps 2 — 9 end-to-end as a manual smoke test; record runtime and capture any operator-facing message drift.
- [ ] T095 [P] Update `docs/architecture.md` §13 ("Event Pipeline") with a one-line pointer to `specs/008-event-ingestion-follow/plan.md` for the FEAT-008 implementation. Do NOT duplicate the spec — reference only.
- [ ] T096 [P] Update `docs/mvp-feature-sequence.md` FEAT-008 section to mark the "Acceptance" checklist items as complete (post-implementation), and tick off the four "Carried over from FEAT-007" obligations.
- [ ] T097 Re-run constitution check against the implemented code: confirm no network listener was added, no in-container daemon process spawned, no automatic input delivery path introduced, no LLM/inference invocations on the classifier path, and `agenttower events` is fully scriptable. Document pass in this tasks file.
- [ ] T098 [P] Run a performance smoke test (Plan §"Performance Goals"): 50 simulated agents at the upper-bound throughput; measure SC-001 / SC-002 latency; assert per-cycle CPU budget is comfortably below saturation. Capture results in `specs/008-event-ingestion-follow/perf-smoke.md` (NEW artifact, optional — only if results need follow-up).
- [ ] T099 Final lint / typecheck / test sweep: `pyproject.toml`-defined linters, mypy if used, full `pytest` run. Confirm SC-008 AST gate passes (the existing `test_logs_offset_advance_invariant.py` is green AND the T004 extension catches the new test seams).
- [ ] T100 Tag for review: ensure `tests/unit/test_logs_offset_advance_invariant.py`, `test_feat008_backcompat.py`, `test_lifecycle_separation.py`, all six US integration test files, and the schema migration test are all in the diff and all green. PR-ready.

---

## Dependencies

```text
Phase 1 (Setup, T001..T005) — no story dependencies; mostly parallel.
        |
        v
Phase 2 (Foundational, T006..T016) — must complete before any user-story phase.
        |   T006 (schema) blocks T009/T010 (DAO).
        |   T007 (errors) blocks T037..T041 (CLI), T047..T053 (follow).
        |   T011 (Clock) blocks T020..T032 (classifier+reader).
        |   T012 (FollowSessionRegistry) blocks T047..T053.
        |   T013 (status surface) blocks T077..T080 (degraded mode).
        v
Phase 3 (US1) — MVP. Depends on Phase 2.
        |   T017..T019 (rules) -> T020 (classify) -> T026 (debounce) -> T029 (reader cycle) -> T032 (JSONL append).
        |   T037 (events.list) -> T039..T041 (CLI).
        |   T042..T046 integration tests parallel after T032 + T041.
        v
Phase 4 (US2) — Depends on Phase 3 (reader cycle + DAO + CLI exist).
        |   T047..T051 follow-session + reader notify -> T052..T053 CLI.
        v
Phase 5 (US3) — Depends on Phase 3 (reader + DAO).
Phase 6 (US4) — Depends on Phase 3 (reader cycle calls FEAT-007 helper).
Phase 7 (US5) — Depends on Phase 3 (events flow exists; we test JSON shape).
Phase 8 (US6) — Depends on Phase 3 + Phase 7 (status surface + JSON contract).
        v
Phase 9 (Polish) — Depends on all prior phases.
```

User-story dependencies are minimal: US2 needs US1's reader; US3/US4/US5/US6 each independently extend the same reader+CLI surface. After Phase 3 completes, phases 4 — 8 can be implemented in parallel by different contributors if needed.

---

## Parallel Execution Examples

Within Phase 2 (after T006 lands):

```text
T007, T008, T009, T011, T012, T013   # all parallel — different files
T014, T015, T016                     # parallel unit tests
```

Within Phase 3 — classifier subgraph after T017..T019 land:

```text
T022, T023, T024, T025                 # rule + priority + swarm-member + redaction tests, parallel
T027, T028, T102                       # debounce tests (incl. FR-015 restart-reset), parallel
T033, T034, T035, T103, T036           # reader unit tests (incl. FR-001 cycle cap), parallel
T042, T043, T044, T045, T046           # US1 integration tests, parallel
```

Within Phase 4 (US2 follow):

```text
T047 -> T048 -> T049                 # serialize: all three edit src/agenttower/socket_api/methods.py
T054, T055, T056, T057               # US2 integration tests, parallel
```

(T047/T048/T049 do NOT carry the `[P]` marker because they edit the same dispatcher table in `methods.py`. Sequencing is required even though they implement logically independent methods.)

Within Phase 8 (US6 failure surface):

```text
T077, T078, T079, T080               # different reader paths, parallel within reader.py if seams allow
T081, T082, T083, T084               # parallel unit tests
T085, T086, T087, T088               # parallel integration tests
T089, T090                           # parallel synthesized-type tests
```

Within Phase 9:

```text
T091, T092, T093, T094, T095, T096, T098   # all parallel
T097, T099, T100                            # serialize: re-check, sweep, tag
```

---

## Independent Test Criteria (per User Story)

| Story | Independent test |
|---|---|
| US1 | Register agent, attach log, write trigger line, wait one cycle, run `agenttower events --target X` → exactly one event with the expected type and a redacted excerpt. |
| US2 | Run `events --follow --target X` in one terminal; write three trigger lines in another (spaced > debounce) → three events appear in order within ≤ 1 cycle each, no backlog re-print. |
| US3 | Persist N events; stop daemon; restart; wait two cycles; SQLite events count and JSONL line count unchanged for every attached agent. |
| US4 | For each of {truncate, recreate, delete, delete+recreate+re-attach}: drive scenario; assert documented row-status transitions, lifecycle emissions, offset resets, and absence of any event from pre-reset bytes. |
| US5 | Append known trigger line; `events --target X --json --limit 1` produces one JSON object on one line; pipe through schema validator → zero failures. |
| US6 | Make one log unreadable (chmod 0); trigger a cycle; other attached agents continue producing events; failed attachment visible in `agenttower status`. |

---

## Implementation Strategy

**MVP**: Phase 1 → Phase 2 → Phase 3 (US1). At Phase 3 close, the operator can already write to a log and inspect classified events end-to-end. SC-001 satisfied. This is the minimum shippable increment.

**Increment 2** (US2 follow): Live tail; SC-002 satisfied. After this, a human can monitor a live agent in real time.

**Increment 3** (US3 + US4): Restart safety + FEAT-007 carry-over invariants. Closes the durability gap. T175/T176/T177 land here.

**Increment 4** (US5 + US6): Stable JSON contract for scripting + visible failure surface. After this, downstream FEAT-009 / FEAT-010 features can subscribe with confidence.

**Polish** (Phase 9): Backwards-compatibility gate, lifecycle separation gate, doc updates, constitution re-check, perf smoke. Required before merge.

---

## Format Validation

Every task in this file follows the strict checklist format:

- Checkbox `- [ ]` ✓
- Sequential IDs `T001` — `T100` plus three out-of-band additions `T101`, `T102`, `T103` (added during the post-`/speckit.analyze` remediation pass) ✓
- `[P]` marker on parallelizable tasks ✓
- `[US1]` — `[US6]` story labels on all user-story-phase tasks; setup, foundational, and polish phases have no story label ✓
- Concrete file path (or test path) on every implementation task ✓

Total: 103 tasks. Distribution:

| Phase | Tasks | Story |
|---|---:|---|
| 1 (Setup) | 6 (T001 — T005, T101) | (none) |
| 2 (Foundational) | 11 (T006 — T016) | (none) |
| 3 (US1) | 32 (T017 — T046, T102, T103) | US1 |
| 4 (US2) | 11 (T047 — T057) | US2 |
| 5 (US3) | 6 (T058 — T063) | US3 |
| 6 (US4) | 8 (T064 — T071) | US4 |
| 7 (US5) | 5 (T072 — T076) | US5 |
| 8 (US6) | 14 (T077 — T090) | US6 |
| 9 (Polish) | 10 (T091 — T100) | (none) |

Parallel opportunities: 70 of 103 tasks carry `[P]`. The serial-only tasks are the mutating-edit-on-shared-files tasks (T006 schema migration; T029–T032 reader code in `reader.py`; T037, T038, T047, T048, T049 socket dispatchers in `methods.py`; T052/T053 CLI in `cli.py`) and the polish gates (T097 / T099 / T100).

### Remediation pass (post-`/speckit.analyze`) — added tasks

| Task | Addresses | Phase |
|---|---|---|
| T101 | L1 (capture FEAT-007 baseline fixtures for backcompat gate) | Phase 1 Setup |
| T102 | H1 (FR-015 debounce-restart-reset test) | Phase 3 US1 |
| T103 | M2 (FR-001 reader cycle wall-clock cap timing test) | Phase 3 US1 |

### Remediation pass (post-`/speckit.analyze`) — edited tasks

| Task | Addresses | Edit |
|---|---|---|
| T004 | M3 | Extended AST gate to cover broader FR-003 / FR-004 direct-mutation prohibitions (`log_attachments` / `log_offsets` SQL fragments). |
| T005 | L2 | Settled on `jsonschema` as a test-time-only dependency in `pyproject.toml`'s test extras (runtime stays stdlib-only). |
| T029 | L4 | Added explicit FR-003 / FR-004 / FR-013 / FR-016 / FR-024 citations. |
| T030 | L4 | Added explicit FR-001 / FR-007 citations. |
| T040 | L4 | Added explicit FR-027 / FR-030 / FR-031 / FR-032 citations. |
| T042 | M4 | Added explicit SC-001 ≤ 5 s end-to-end timing assertion. |
| T047 — T049 | L3 | Removed `[P]` markers (same-file edits in `methods.py` must serialize); parallel-execution example updated. |
| T052 | L4 | Added explicit FR-033 / FR-034 citations. |
| T058 | L4 | Added FR-022 documentation obligation. |
| T059 | L4 | Added FR-023 / FR-042 documentation obligation. |
| T064 | L4 | Added explicit FR-003 obligation. |
