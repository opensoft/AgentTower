"""FEAT-009 QueueService façade.

Orchestrates the `send-input` and operator-action paths consumed by
`socket_api/methods.py`. Each method routes: envelope render →
permission gate → DAO insert/transition → audit emit. Operator-action
endpoints (`approve`/`delay`/`cancel`) also enforce the caller-pane
liveness check (Group-A walk Q8 → `operator_pane_inactive` on inactive
caller pane).

`send_input` waits on a per-`message_id` `Condition` if `wait=True`
(default; FR-009), with a configurable wait timeout.
"""

from __future__ import annotations
