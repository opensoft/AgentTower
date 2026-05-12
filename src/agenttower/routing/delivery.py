"""FEAT-009 delivery worker (FR-040 — FR-045, plan §"Delivery worker loop").

Single host-side thread that:
1. Runs the FR-040 crash-recovery pass synchronously at boot, BEFORE
   `start()` is called (research §R-012).
2. Loops: drain buffered audits → check routing flag → pick next ready
   row → pre-paste re-check → stamp `delivery_attempt_started_at` →
   load_buffer → paste_buffer → send_keys → delete_buffer → transition
   `delivered`.

Failure handling encoded per Group-A walk:
- Q1: on `paste_buffer`/`send_keys` failure after a successful
  `load_buffer`, invoke `delete_buffer` best-effort in a `finally`
  block; cleanup errors are logged but never raised.
- Q2: `delete_buffer` failure AFTER a successful paste+submit does
  NOT downgrade the row — it stays `delivered`; the orphan is logged
  and surfaced through `agenttower status`.
- Q4: `stop()` aborts the loop immediately; no drain — in-flight rows
  are resolved by the next boot's FR-040 recovery.
- Q5/Q7: every SQLite call uses the bounded retry helper from
  `routing.dao`; exhausted retries → `sqlite_lock_conflict`.
"""

from __future__ import annotations
