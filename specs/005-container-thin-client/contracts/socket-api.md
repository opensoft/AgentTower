# Socket API Contract: Container-Local Thin Client Connectivity

**Branch**: `005-container-thin-client` | **Date**: 2026-05-06

This document is short by design. **FEAT-005 introduces no new
socket method, no new error code, no new request envelope, no new
response envelope, and no new dispatch entry.** It is recorded
explicitly so a future reviewer cannot reopen the question without
amending the spec.

---

## C-API-501 — Reused FEAT-002 / FEAT-003 / FEAT-004 methods (no extension)

### What FEAT-005 calls

The doctor's three round-trips reuse existing methods exactly as
defined by FEAT-002 / FEAT-003 / FEAT-004:

| # | Method | Defined by | Used by FEAT-005 for |
| - | ------ | ---------- | -------------------- |
| 1 | `status`           | FEAT-002 | `socket_reachable` (proves the round-trip works) AND `daemon_status` (echoes `daemon_version` + `schema_version`) |
| 2 | `list_containers`  | FEAT-003 | `container_identity` cross-check (full-id + 12-char short-id prefix match) |
| 3 | `list_panes`       | FEAT-004 | `tmux_pane_match` cross-check (filter by resolved container id when known) |

`list_panes` is called with `params.container` set to the full
id from `IdentityResolution.matched_id` when the cross-check
classified as `unique_match`; otherwise it is called with no
filter. The parameter name is `container` (not `container_id`)
to match the FEAT-004 method shape at
`src/agenttower/socket_api/methods.py::_list_panes`. Both shapes
are already supported by the FEAT-004 method contract.

### What FEAT-005 does NOT add

- **No new method.** `socket_api/methods.py` is unchanged. The
  daemon dispatch table gains no entry.
- **No new error code.** `socket_api/errors.py` is unchanged. The
  doctor maps existing FEAT-002 client exceptions
  (`DaemonUnavailable`, `DaemonError`) to its own closed-set
  per-check sub-codes (FR-016, R-009); the daemon-side error code
  set is untouched.
- **No new request shape.** Every doctor call uses the existing
  newline-delimited JSON request envelope:
  ```json
  {"method": "<name>", "params": {...}?}
  ```
- **No new response shape.** Every doctor call consumes the existing
  newline-delimited JSON response envelope:
  ```json
  {"ok": true,  "result": {...}}
  {"ok": false, "error":  {"code": "...", "message": "..."}}
  ```
- **No new authorization tier.** The mounted-default socket file
  inherits the FEAT-002 socket-file authorization (`0600`, host
  user only) verbatim from the host file the bind-mount targets.
- **No new mutex.** None of the three methods FEAT-005 calls
  acquires a scan mutex on the daemon side; the existing FEAT-003 /
  FEAT-004 read methods are read-only.

### Pinned FRs

- **FR-022**: forbids any new socket method, in-container daemon,
  or relay.
- **FR-026**: forbids any change to FEAT-001 / FEAT-002 / FEAT-003
  / FEAT-004 socket envelopes or schemas.
- **FR-029**: forbids any disk write during `agenttower config
  doctor`; the three round-trips above are read-only and produce
  no SQLite or JSONL writes on either side.

---

## C-API-502 — Client extension (additive only)

### What FEAT-005 changes in `socket_api/client.py`

`socket_api/client.py` is extended **additively only** with one
attribute on the existing `DaemonUnavailable` exception:

```python
class DaemonUnavailable(RuntimeError):
    kind: Literal[
        "socket_missing",
        "socket_not_unix",
        "connection_refused",
        "permission_denied",
        "connect_timeout",
        "protocol_error",
    ]
    # __init__ gains an additive keyword-only ``kind`` parameter;
    # existing positional callers (FEAT-002 / FEAT-003 / FEAT-004)
    # continue to work without modification.
```

The doctor's `socket_reachable` check catches `DaemonUnavailable`
and dispatches on `.kind` to map to the FR-016 closed-set sub-code
without parsing the exception's message string.

**Backward-compat invariants** (FR-026):

- `str(DaemonUnavailable(...))` returns the same text as before.
- The exception's repr is unchanged.
- Every existing FEAT-002 / FEAT-003 / FEAT-004 caller of
  `send_request(...)` continues to work without modification; the
  new attribute is set on the exception before it is raised but is
  ignored by callers that do not look at it.
- No new exception class is introduced. `DaemonError` is unchanged.

The mapping from underlying syscall / parsing failure to `.kind`:

| Underlying signal in `_connect_via_chdir` / `_recv_line` / decode | `.kind` |
| ------------------------------------------------------------------ | ------- |
| `FileNotFoundError`                                                | `socket_missing` |
| (pre-flight `S_ISSOCK` check fails, raised by `socket_resolve.py` before `send_request`) | `socket_not_unix` |
| `ConnectionRefusedError`                                           | `connection_refused` |
| `OSError` with `errno.EACCES`                                      | `permission_denied` |
| `TimeoutError` / `socket.timeout`                                  | `connect_timeout` |
| `OSError` (other)                                                  | `connect_timeout` (only when wrapping a generic connect/read I/O failure; the doctor's actionable_message echoes the bounded message) |
| `UnicodeDecodeError` / `json.JSONDecodeError` / malformed envelope / non-dict result | `protocol_error` |

`socket_not_unix` is set by FEAT-005's pre-flight (in
`socket_resolve.py`) before any connect attempt; the existing
`client.py` connect path never produces it.

---

## C-API-503 — No-leak invariant (FR-024)

Raw `socket(2)` / `connect(2)` errno text MUST NOT appear in any
FEAT-005 stderr line, JSON payload, or log row. The CLI catches
`DaemonUnavailable` once, reads `.kind`, looks up the closed-set
sub-code, and emits exactly:

- a sub-code token (closed set),
- a one-line bounded `actionable_message` (sanitized + ≤ 2048
  chars; R-008),
- the `details` field (sanitized + ≤ 2048 chars; R-008).

The wrapped exception's `__cause__` chain is not formatted into
output. The bounded message MAY include classification context
(e.g., "socket file does not exist") but MUST NOT include the raw
errno number, the raw `OSError.strerror`, or any path beyond the
already-sanitized resolved socket path.

This invariant is verified by `tests/integration/test_cli_config_doctor_daemon_down.py`
and `tests/unit/test_doctor_render.py` (FR-024, SC-004).
