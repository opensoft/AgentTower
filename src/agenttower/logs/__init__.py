"""FEAT-007 — Pane log attachment and offset tracking.

This package owns the durable log-attachment registry, the offset-tracking
schema, the `tmux pipe-pane` shell construction, the host-visibility proof,
the per-line redaction utility, and the orphan-detection startup pass.

See `specs/007-log-attachment-offsets/plan.md` § Project Structure for the
authoritative module breakdown.
"""

from __future__ import annotations
