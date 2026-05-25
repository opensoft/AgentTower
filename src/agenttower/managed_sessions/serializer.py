"""FEAT-013 per-container serializer.

Per-container ``asyncio.Lock`` map with FIFO waiter semantics (research
§R2). Implements FR-019 — a second ``create_layout`` request targeting
the same bench container blocks until the first finishes.

Implementation in T010.
"""

from __future__ import annotations
