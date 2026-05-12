"""FEAT-009 canonical timestamp encoding (FR-012b / Clarifications Q5).

Every FEAT-009 timestamp surface — SQLite columns, `events.jsonl` rows,
all `--json` outputs, the queue listing — uses the same ISO 8601 form:
millisecond resolution, UTC, literal `Z` suffix. Example:
`2026-05-11T15:32:04.123Z`.

The `Clock` Protocol seam is consumed by the delivery worker, the
audit writer, and every state transition so tests can advance perceived
time deterministically via `AGENTTOWER_TEST_ROUTING_CLOCK_FAKE`.
"""

from __future__ import annotations
