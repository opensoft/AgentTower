"""FEAT-009 redacted-excerpt rendering pipeline.

Implements FR-047b: redact → collapse whitespace → truncate → append `…`
on truncation. Applied uniformly to queue listings, audit excerpts,
JSONL audit rows, and `send-input --json` (per FR-047a). On redactor
failure, falls back to a fixed placeholder string; the raw body MUST
NEVER appear as a fallback (Group-A walk Q3).
"""

from __future__ import annotations
