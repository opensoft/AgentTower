"""FEAT-009 audit writer with FR-046 dual-write.

`QueueAuditWriter.append(...)` writes every state transition to BOTH:
1. The FEAT-008 `events` SQLite table (source of truth per FR-048),
   using the column mapping declared in data-model.md §7.1.
2. The FEAT-008 `events.jsonl` stream (best-effort replica with a
   per-row `jsonl_appended_at` watermark; FR-029-style retry pattern).

On any exception from the JSONL write (not just `OSError` — see
Group-A walk Q6), the record is buffered in a bounded deque
(`degraded_audit_buffer_max_rows` from config), the exception class
is captured for forensics, and `degraded_queue_audit_persistence` is
surfaced through `agenttower status`. The SQLite row remains intact;
the JSONL watermark stays NULL until a later drain succeeds.

`append_routing_toggled(...)` is a sibling method for the kill-switch
audit shape (contracts/queue-audit-schema.md "Routing toggle audit
entry").
"""

from __future__ import annotations
