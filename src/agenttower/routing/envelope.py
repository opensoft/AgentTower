"""FEAT-009 envelope rendering and body validation.

Builds the structured prompt envelope per FR-001 / FR-002 and validates
the body per FR-003 / FR-004.

See plan.md §"Envelope rendering" and contracts/queue-row-schema.md for
the shape; FR-004 size cap applies to the serialized envelope (not the
raw body) so header-stuffing cannot bypass the limit.
"""

from __future__ import annotations
