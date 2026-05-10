# Classifier Rule Catalogue Contract

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10
**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md)

The MVP rule catalogue is closed (FR-007). Each rule is defined by:

- `rule_id`: stable, dotted, with `vN` suffix (e.g.,
  `error.traceback.v1`).
- `event_type`: one of the ten closed-set values.
- `priority`: integer, lower = higher priority. Walked in ascending
  order; first match wins (FR-008 deterministic tie-break).
- `matcher`: a compiled `re.Pattern` against ONE complete record
  (post-redaction).
- `extract`: optional callable producing structured fields (only
  used by `swarm_member.v1` to record parsed parent/pane/label etc.
  in tests; not exposed in MVP JSONL).

`pane_exited` and `long_running` are synthesized by the reader and
do NOT appear in the matcher catalogue (`research.md` §R11). Their
synthetic rule ids (`pane_exited.synth.v1`, `long_running.synth.v1`)
appear in `events.classifier_rules` output for completeness but are
returned under a separate `synthetic_rule_ids` array.

---

## Catalogue

| # | priority | `rule_id` | `event_type` | Matcher (post-redaction, ASCII flag where noted) |
|---|---:|---|---|---|
| 1 | 10 | `swarm_member.v1` | `swarm_member_reported` | `^AGENTTOWER_SWARM_MEMBER parent=(?P<parent>agt_[0-9a-f]{12}) pane=(?P<pane>%[0-9]+) label=(?P<label>[^\s]+) capability=(?P<capability>[^\s]+) purpose=(?P<purpose>.{1,256})$` (`re.ASCII`). Strict — malformed variants fall through to `activity.fallback.v1`. |
| 2 | 20 | `manual_review.v1` | `manual_review_needed` | `(?:^|\s)(?:MANUAL[_-]REVIEW|TODO\(human\)|REVIEW[_-]REQUIRED)\b` |
| 3 | 30 | `error.traceback.v1` | `error` | `^Traceback \(most recent call last\):` |
| 4 | 31 | `error.line.v1` | `error` | `^(?:Error|ERROR|Exception)[: ]` (anchored at line start) |
| 5 | 40 | `test_failed.pytest.v1` | `test_failed` | `^(?:FAILED|ERROR) [^\s].*::.*$` (pytest summary line) |
| 6 | 41 | `test_failed.generic.v1` | `test_failed` | `\b(?:test failed|tests failed|FAIL\b)` |
| 7 | 50 | `test_passed.pytest.v1` | `test_passed` | `^=+ \d+ passed( in [\d.]+s)? =+$` |
| 8 | 51 | `test_passed.generic.v1` | `test_passed` | `\b(?:all tests passed|tests passed)\b` |
| 9 | 60 | `completed.v1` | `completed` | `(?:^|\s)(?:DONE|completed successfully|task completed|build succeeded)\b` |
| 10 | 70 | `waiting_for_input.v1` | `waiting_for_input` | `(?:^|\n)(?:.*\?\s*$|.* \[Y/n\]\s*$|.* \(yes/no\)\s*$|>>>\s*$|>\s+$|Continue\?\s*$)` |
| 11 | 999 | `activity.fallback.v1` | `activity` | `^.*$` (matches any non-empty record; conservative default per FR-011) |

Matchers compile with `re.NOFLAG | re.MULTILINE`-OFF (each match
operates on a single record, single line in MVP because FR-005 splits
on `\n`). `re.ASCII` is added only to the `swarm_member.v1` rule
(its closed-set vocabulary is ASCII by spec; consistent with
FEAT-007's redaction utility).

---

## Conservative default rule (FR-011)

`activity.fallback.v1` is the LAST rule. Every record reaches it if
no earlier rule matched. It matches any non-empty string. Its
priority (`999`) is intentionally far above the next-highest (`70`)
to make it visually obvious it's the catch-all.

If a future feature adds a domain rule, it must use a priority
strictly less than `999` AND greater than `70` (or fit into one of
the existing tiers).

---

## Priority overlap fixtures (SC-007)

Each of these records MUST classify as the documented `event_type`
on the right; the test fixture at
`tests/unit/test_classifier_priority.py` enumerates them.

| Record (one line) | Expected | Why |
|---|---|---|
| `Error: pytest test_x failed in setup` | `error` | `error.line.v1` (priority 30) precedes `test_failed.generic.v1` (41) |
| `Traceback (most recent call last):` | `error` | `error.traceback.v1` (30) — anchored beats line-style `error.line.v1` (31) |
| `MANUAL_REVIEW: Error: foo` | `manual_review_needed` | `manual_review.v1` (20) precedes `error.line.v1` (31) |
| `=== 12 passed in 1.34s ===` | `test_passed` | `test_passed.pytest.v1` matches |
| `FAILED tests/test_x.py::test_y - assertion` | `test_failed` | `test_failed.pytest.v1` (40) — note this STARTS WITH `FAILED`, would NOT match `error.line.v1` (anchored on `Error|ERROR|Exception`) |
| `AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%2 label=foo capability=bar purpose=baz` | `swarm_member_reported` | `swarm_member.v1` (10), highest priority |
| `AGENTTOWER_SWARM_MEMBER parent=agt_x` (malformed) | `activity` | strict parse fails → fallthrough to `activity.fallback.v1` (FR-009) |
| `running tests…` | `activity` | no domain rule matches |
| `>>> ` (Python REPL prompt) | `waiting_for_input` | `waiting_for_input.v1` |
| `Build succeeded` | `completed` | `completed.v1` |

---

## `long_running` eligibility table (FR-013)

`long_running` is synthesized when `now - last_output_at >=
long_running_grace_seconds` AND the most-recent prior emitted event
for the attachment falls in the eligible set:

| Most recent prior emitted event | `long_running` eligible? |
|---|---|
| `activity` | yes |
| `error` | yes |
| `test_failed` | yes |
| `swarm_member_reported` | yes |
| `manual_review_needed` | yes |
| (no prior event since last `long_running`) | no |
| `completed` | NO (task is done) |
| `test_passed` | NO (task is done) |
| `waiting_for_input` | NO (FR-013 explicit ineligible) |
| `pane_exited` | NO (pane is gone) |
| `long_running` (already emitted) | NO (one per running task) |

Once `long_running` is emitted, the attachment is "marked"; it
cannot emit another `long_running` until at least one event from
the eligible set lands AFTER the `long_running` emission AND a
fresh grace window elapses.

The eligibility table is asserted line-by-line in
`tests/unit/test_classifier_long_running.py`.

---

## `pane_exited` semantics (FR-016 — FR-018)

`pane_exited` is synthesized when, in a single reader cycle:

1. FEAT-004's pane service reports the bound pane's `(container_id,
   pane_composite_key)` as inactive (pane no longer in tmux
   discovery).
2. AND `now - last_output_at >= pane_exited_grace_seconds`.
3. AND the attachment's lifecycle has not yet emitted `pane_exited`.

Pane-id reuse: if FEAT-004 reuses the same pane id later AND a new
attachment is bound to it, the lifecycle counter resets and
`pane_exited` becomes eligible again for the new lifecycle.

`pane_exited` is NEVER inferred from log text (FR-016 — "MUST NOT be
inferred from log text alone"). A line saying "pane exited" is just
an `activity` event.

---

## Redaction obligation (FR-012)

EVERY rule operates on the post-redaction record. The reader's
order is:

1. Read raw bytes from the log file.
2. Split on `\n` to produce complete records (FR-005).
3. For each complete record, call
   `agenttower.logs.redaction.redact_one_line(record)`.
4. Pass the redacted record to the classifier.
5. The classifier's `excerpt` IS the redacted record (truncated to
   `per_event_excerpt_cap_bytes` with the truncation marker).

Step 3 happens BEFORE step 4 — the classifier never sees the raw
record. This means a regex like `\b[A-Z0-9]{32,}\b` (which might
match a redacted token like `[REDACTED-JWT]`) will see the redaction
sentinel, not the original secret. Tests verify this by feeding
known secret patterns and asserting the persisted excerpt and the
classifier's input are both redacted.

---

## Rule extension policy

The catalogue is CLOSED for FEAT-008. Adding a new rule (or a new
event type) is:

1. A feature-level change (its own spec).
2. A `schema_version` bump from 1 → 2 (non-breaking add).
3. A new priority slot (must not collide with existing).
4. New positive + negative + overlap fixtures in the priority test.
5. An update to the `event_type` enum in the JSON Schema (and a new
   schema-version artifact).

This contract document MUST be amended in lockstep with any such
addition.
