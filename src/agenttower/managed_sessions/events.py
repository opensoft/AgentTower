"""FEAT-013 lifecycle event emitter.

Emits the 12 event types from research §R11 through the existing FEAT-008
JSONL audit pipeline with ``origin = "managed"``. Enforces per-pane FIFO
and per-layout FIFO ordering (FR-015 amendment) and env-var redaction
(FR-021 amendment — case-insensitive substring match against
``*TOKEN*`` / ``*SECRET*`` / ``*KEY*`` / ``*PASSWORD*``).

Implementation in T014.
"""

from __future__ import annotations
