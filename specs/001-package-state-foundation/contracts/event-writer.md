# Contract: Internal Event-Writer Utility (FEAT-001)

**Branch**: `001-package-state-foundation` | **Date**: 2026-05-05

The event-writer is the single, shared way for AgentTower components to
append durable JSONL audit records. FEAT-001 ships the writer ready for
FEAT-002+ callers; FEAT-001 itself does **not** call it from any CLI
command (per FR-016 and clarification Q4). This contract is therefore
exercised entirely by tests in this feature.

The writer lives in the package as `agenttower.events.writer`. The
contract below is normative; implementations MUST satisfy it exactly.

---

## C-EVT-001 — `append_event(events_file, payload)`

### Signature

```python
from collections.abc import Mapping
from pathlib import Path
from typing import Any

def append_event(events_file: Path, payload: Mapping[str, Any]) -> None: ...
```

### Inputs

| Parameter | Type | Constraints |
|---|---|---|
| `events_file` | `pathlib.Path` | Absolute path. Must equal the resolver's `EVENTS_FILE` member at runtime; the writer does not re-resolve paths itself. |
| `payload` | `Mapping[str, Any]` | JSON-serializable mapping. Keys are strings. Values are anything `json.dumps` accepts with `allow_nan=False`. |

### Behavior

1. If the parent directory of `events_file` does not exist, create it
   (and any missing intermediate parents) with mode `0700`.
2. Build the record dict in this exact order:
   ```python
   record = {"ts": <ISO-8601 UTC>, **payload}
   ```
   Where `<ISO-8601 UTC>` is produced by
   `datetime.datetime.now(datetime.UTC).isoformat(timespec="microseconds")`,
   yielding a string like `"2026-05-05T12:34:56.789012+00:00"`.
   Caller-supplied `"ts"` keys in `payload` overwrite the writer's
   default `ts` (i.e. `**payload` wins on collision).
3. Serialize the record with
   `json.dumps(record, separators=(",", ":"), ensure_ascii=False,
   allow_nan=False)`.
4. Acquire a module-level `threading.Lock` for the duration of steps
   5–7.
5. Open `events_file` with `O_WRONLY | O_CREAT | O_APPEND`, mode
   `0o600`. If the file already existed, its mode is **not** changed.
6. Write the JSON string immediately followed by `"\n"` in a single
   `write()` call, then `os.fsync(fd)`.
7. Close the file handle.

### Outputs

Returns `None`. The function has no return value channel beyond
side effects.

### Side effects

- Exactly one new line appended to `events_file`.
- If `events_file` did not previously exist, it now exists with mode
  `0600`.
- If the parent directory did not previously exist, it now exists with
  mode `0700`.

### Exceptions

| Exception class | Cause |
|---|---|
| `OSError` (any `errno`) | Underlying filesystem error (permission denied, no space, etc.). The writer does **not** swallow errors. |
| `TypeError` / `ValueError` | Raised by `json.dumps` for non-serializable payloads or `NaN`/`inf` floats. |

The writer does **not** catch these; callers handle them. FEAT-001
tests assert that an `OSError` from a read-only `events_file` parent
propagates unchanged.

### Concurrency contract

- Concurrent calls from multiple threads in the same process MUST each
  produce exactly one well-formed line. No bytes from one call may
  interleave with bytes from another. Enforced by the module-level
  lock.
- Cross-**process** append safety is **not** guaranteed in FEAT-001.
  The lock is in-process. FEAT-002 may add `fcntl.flock` once the
  daemon participates.

### Performance contract

- Each call performs at most one directory `mkdir` (only when the
  parent is missing), one `open`, one `write`, one `fsync`, and one
  `close`.
- The function holds the lock for the duration of the I/O, so callers
  that need throughput should batch upstream rather than hammer the
  writer with single-event calls.

---

## C-EVT-002 — Output line shape

Every line written by `append_event` MUST satisfy:

| Property | Value |
|---|---|
| Encoding | UTF-8, no BOM |
| Terminator | exactly one `\n` per line |
| Compactness | `json.dumps` with `separators=(",", ":")` — no inter-token whitespace |
| `ts` key | present, ISO-8601 UTC with offset, microsecond precision |
| Trailing whitespace | none |

Lines are independently parseable by `json.loads`. The file as a whole
is valid JSON Lines (one object per line).

---

## C-EVT-003 — File creation and permissions

| Aspect | Value |
|---|---|
| Mode on creation | `0o600` |
| Parent dir mode on creation | `0o700` |
| Existing file mode | unchanged if no broader than `0o600`; otherwise refused |
| Existing parent dir mode | unchanged if no broader than `0o700`; otherwise refused |
| Truncation | never |
| Rotation | never (out of scope for FEAT-001; FEAT-008 may add) |

The writer does **not** chmod a pre-existing `events_file` or parent
directory. If a previous tool or test left either with a mode broader than
the FR-015 host-only requirement, the writer raises `OSError` before
appending and leaves existing bytes untouched. Newly-created files and
directories are chmod'd/fchmod'd after creation as needed so process
`umask` cannot broaden the final mode.

---

## C-EVT-004 — Test-only invariants for FEAT-001

These invariants are verified in `tests/unit/test_events_writer.py`:

1. **Single append**: one call produces exactly one line; the line
   parses with `json.loads` to a dict containing the writer-injected
   `ts` plus all keys from `payload`.
2. **Timestamp shape**: `ts` matches the regex
   `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$`.
3. **Caller `ts` override**: a `payload` containing
   `{"ts": "carrier-supplied"}` produces a line whose `ts` value is
   `"carrier-supplied"` (caller wins).
4. **File creation**: when `events_file` does not exist, the first
   call creates it with mode `0o600`, including under a permissive
   process `umask`. (Verified by `os.stat`.)
5. **Parent creation**: when the parent directory does not exist, the
   first call creates the directory chain with mode `0o700` on each
   newly created leaf.
6. **Concurrency**: 100 threads each calling `append_event` once with
   distinct payloads produce a file with exactly 100 lines, each
   independently `json.loads`-parseable, and the union of all lines'
   payloads equals the union of submitted payloads (no loss, no
   duplication).
7. **Append-only**: a pre-existing file's prior contents are preserved;
   the writer adds to the end and never truncates.
8. **Weak pre-existing mode refusal**: a pre-existing `events_file` with a
   broader mode than `0o600` causes `append_event` to raise `OSError`
   before appending.
