"""FEAT-009 closed-set error codes and exit-code map.

Re-exports the FEAT-009 closed-set string codes from
`socket_api/errors.py` and provides:

- `CLI_EXIT_CODE_MAP: Final[dict[str, int]]` — the integer-exit-code
  mapping from contracts/error-codes.md "Integer exit code map". The
  integer codes MAY shift across MVP revisions per FR-050; the string
  codes are the stable contract.
- `_QUEUE_AUDIT_EVENT_TYPES: Final[frozenset[str]]` — the seven
  `queue_message_*` audit event types (consumed by the R-008
  disjointness test, T086).
- `_ROUTING_AUDIT_EVENT_TYPES: Final[frozenset[str]]` — singleton
  containing `routing_toggled`.

Plus the FEAT-009 exception types (`QueueServiceError`,
`TargetResolveError`, `TmuxDeliveryError`, `SqliteLockConflict`,
`OperatorPaneInactive`) consumed by the service / DAO / worker.
"""

from __future__ import annotations
