# CLI Contract: `agenttower events`

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10
**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md)

`agenttower events` is the only new top-level subcommand FEAT-008
introduces. Three forms:

1. `agenttower events [options]` — list events (one shot).
2. `agenttower events --follow [options]` — stream new events.
3. `agenttower events --classifier-rules` — print the rule catalogue
   (debug; hidden from `--help`).

The CLI runs identically on the host (resolves daemon socket via
FEAT-001 `paths.resolve_paths`) and inside a bench container
(routes through the FEAT-005 mounted Unix socket; SC-012). All
output goes to stdout; all errors go to stderr; all exit codes are
documented below.

---

## C-CLI-EVT-001 — `agenttower events` (list mode)

### Synopsis

```text
agenttower events [--target AGENT_ID]
                  [--type TYPE]...
                  [--since ISO-8601]
                  [--until ISO-8601]
                  [--limit N]
                  [--cursor TOKEN]
                  [--reverse]
                  [--json]
```

### Flags

| Flag | Description |
|---|---|
| `--target AGENT_ID` | Filter to one agent. AGENT_ID must be in the FEAT-006 registry; otherwise exit 4 (`agent_not_found`). |
| `--type TYPE` | Filter to one event type (one of the ten closed-set values). Repeatable; multiple `--type` flags OR together. |
| `--since ISO-8601` | Lower bound on `observed_at` (inclusive). |
| `--until ISO-8601` | Upper bound on `observed_at` (exclusive). |
| `--limit N` | Page size. Default 50, max 50. |
| `--cursor TOKEN` | Opaque pagination cursor returned by a previous call's `next_cursor`. Round-trip verbatim. |
| `--reverse` | Newest-first instead of oldest-first. |
| `--json` | One JSON object per event per line on stdout (FR-027 / FR-032 schema). |

### Default human output (FR-031)

One line per event, oldest-first, columns:

```text
2026-05-10 12:34:56  builder-1 (agt_a1b2c3d4e5f6)  error          Error: foo bar baz
2026-05-10 12:34:57  builder-1 (agt_a1b2c3d4e5f6)  test_failed    FAILED tests/test_x.py::test_y
2026-05-10 12:34:58  worker-2  (agt_b2c3d4e5f6a1)  activity       (4 collapsed) running pytest …
```

The trailing column is the redacted excerpt, further truncated to fit
the operator's terminal width (terminal-only truncation; the SQLite
`excerpt` column is intact). Format is NOT contractually stable
across MVP minor versions (FR-031); scripts use `--json`.

### `--json` output (stable contract)

One object per line per the FR-027 schema. See
`event-schema.md` for the full JSON Schema. Example:

```json
{"event_id":42,"event_type":"error","agent_id":"agt_a1b2c3d4e5f6","attachment_id":"atc_aabbccddeeff","log_path":"/home/.../agent.log","byte_range_start":1024,"byte_range_end":1078,"line_offset_start":32,"line_offset_end":33,"observed_at":"2026-05-10T12:34:56.789000+00:00","record_at":null,"excerpt":"Error: foo bar baz","classifier_rule_id":"error.line.v1","debounce":{"window_id":null,"collapsed_count":1,"window_started_at":null,"window_ended_at":null},"schema_version":1}
```

### Pagination

When the response includes `next_cursor`, the CLI prints it on stderr
in human mode (e.g. `# next_cursor: <token>`) and includes it in a
single trailing JSON line in `--json` mode:

```json
{"event_id":50, ...}
{"next_cursor":"eyJlIjo1MCwiciI6ZmFsc2V9"}
```

In `--json` mode the cursor line has exactly one key (`next_cursor`)
to make it parseable; consumers MAY skip the line by matching this
key.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (zero or more events printed) |
| 1 | General error (parsing, IO, daemon protocol violation) |
| 2 | Argument error (incompatible flags, malformed value) |
| 3 | Daemon unreachable (FEAT-002 surface) |
| 4 | `agent_not_found` |
| 6 | `events_invalid_cursor` |
| 7 | `events_filter_invalid` |

---

## C-CLI-EVT-002 — `agenttower events --follow`

### Synopsis

```text
agenttower events --follow [--target AGENT_ID]
                           [--type TYPE]...
                           [--since ISO-8601]
                           [--json]
```

### Behavior

- `--target`, `--type`, `--since`, `--json` have the same semantics
  as list mode.
- WITHOUT `--since`, the stream prints ONLY events emitted at or
  after the moment `events.follow_open` returns. No backlog.
- WITH `--since`, the stream first prints the bounded backlog (≤
  default page size), then transitions seamlessly into the live tail.
- `--limit`, `--cursor`, `--reverse` are NOT accepted with `--follow`
  (exit code 2).

### Lifecycle

```text
open follow session  (events.follow_open)
  -> print backlog if requested
  -> loop:
       events.follow_next  (long-poll, ≤ 30 s server-side wait)
       print any returned events
       on session_open=false, break
       on SIGINT, break
  -> events.follow_close
exit 0  (clean SIGINT)
exit 3  (daemon unreachable mid-stream)
```

### SIGINT handling

The CLI installs a SIGINT handler that:

1. Sets a flag the long-poll loop checks between calls.
2. Calls `events.follow_close` on the current `session_id`.
3. Prints nothing more on stdout.
4. Exits 0.

### Daemon-unreachable mid-stream

If `events.follow_next` returns a connection error (FEAT-002
surface), the CLI:

1. Prints `# daemon unreachable; exiting follow` on stderr (or
   `{"error":{"code":"daemon_unreachable",...}}` on stderr in
   `--json` mode).
2. Skips `events.follow_close` (best-effort cleanup is fine; the
   session will GC after idle timeout).
3. Exits 3.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean SIGINT exit |
| 1 | General error |
| 2 | Argument error (e.g., `--limit` with `--follow`) |
| 3 | Daemon unreachable |
| 4 | `agent_not_found` (at session open only) |
| 7 | `events_filter_invalid` |

---

## C-CLI-EVT-003 — `agenttower events --classifier-rules`

### Synopsis

```text
agenttower events --classifier-rules [--json]
```

### Behavior

Hidden from `--help`. Calls `events.classifier_rules` and prints
the catalogue. Default human output:

```text
priority  rule_id                  -> event_type
       10 swarm_member.v1          -> swarm_member_reported
       20 manual_review.v1         -> manual_review_needed
       30 error.traceback.v1       -> error
       31 error.line.v1            -> error
       40 test_failed.pytest.v1    -> test_failed
       41 test_failed.generic.v1   -> test_failed
       50 test_passed.pytest.v1    -> test_passed
       51 test_passed.generic.v1   -> test_passed
       60 completed.v1             -> completed
       70 waiting_for_input.v1     -> waiting_for_input
      999 activity.fallback.v1     -> activity

synthetic rules (not regex; reader-synthesized):
  pane_exited.synth.v1     -> pane_exited
  long_running.synth.v1    -> long_running
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 3 | Daemon unreachable |

---

## Argument validation

Done client-side BEFORE the socket call:

- `--target` shape: `agt_<12 hex>` (FEAT-006 contract). Bad shape →
  exit 2 with stderr message; no daemon call.
- `--type`: each value must be one of the ten closed-set strings.
  Bad value → exit 2.
- `--since` / `--until`: must parse as ISO-8601 with explicit offset
  (e.g., `Z`, `+00:00`). Bad shape → exit 2.
- `--limit`: positive integer ≤ 50. Bad value → exit 2.
- `--cursor`: not validated client-side beyond non-empty; the daemon
  validates and may return `events_invalid_cursor` (exit 6).
- `--limit` / `--cursor` / `--reverse` with `--follow` → exit 2.

## Stream-flush behavior (`--follow`)

After every printed event, the CLI flushes stdout (sets line buffering
on stdout in `--follow` mode). This is critical for piping into `jq`
/ `head` / etc. — without explicit flushing, glibc-buffered stdout
would buffer events for tens of seconds.

`SIGPIPE` on stdout (e.g., piping into `head -n 5`) is handled by
catching `BrokenPipeError`, calling `events.follow_close`, and
exiting 0. (POSIX SIGPIPE is converted to exit 0 because we treat
"downstream consumer is done" as success.)

## Cross-host parity (SC-012)

Running `agenttower events --target X --json --limit 10` from the
host vs from inside the bench container against the same daemon
must produce byte-identical stdout (modulo newline normalization;
both should emit `\n`). Test
`tests/integration/test_events_host_container_parity.py`.
