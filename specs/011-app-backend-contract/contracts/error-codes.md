# Contract: Closed-Set Error Codes & `details` Registry

**Feature**: FEAT-011 — Local App Backend Contract
**Authoritative FRs**: FR-003a, FR-003b, FR-033, FR-034, FR-034a

Every failure envelope is `{ok: false, app_contract_version, error: {code, message, details}}`. `error.code` is drawn from the closed set below. `error.message` is human-readable prose (operator-facing, never machine-parsed). `error.details` is **always** a JSON object, even when empty `{}`.

`error.code` MUST match the regex `^[a-z][a-z0-9_]*$`. Contract tests assert both regex membership and registry membership.

## Closed Set of Codes (27 entries at v1.0)

The following codes are valid at `app_contract_version = "1.0"`. Adding a new code in a future minor is additive (FR-034, FR-035). Removing a code requires a major bump. Round-4 added `malformed_request` (#5), bumping the set from 26 → 27.

| # | `error.code` | Typical trigger |
|---|---|---|
| 1  | `app_session_required` | Method other than `app.preflight`/`app.hello` called without an `app_session_token`. |
| 2  | `app_session_expired`  | Session token presented but no longer valid (connection closed and reopened, daemon restarted, token format malformed, etc.). |
| 3  | `app_contract_major_unsupported` | `app.hello` declared a major the daemon doesn't speak. No session is issued. |
| 4  | `unknown_method` | A method name in the `app.*` namespace that the daemon doesn't implement at its minor. |
| 5  | `malformed_request` | Wire-framing failure on a request line: not valid JSON, trailing content after the first object, stray `\r`, embedded `\x00`, or empty line. Daemon refuses **before** dispatch. (FR-003b) |
| 6  | `validation_failed` | Request param failed type / range / closed-set / cross-field validation. |
| 7  | `not_found` | Generic not-found when no entity-specific code applies. |
| 8  | `stale_object` | Queue lifecycle terminal-state guard (FEAT-009). Only emitted by `app.queue.approve/delay/cancel`. **Never** emitted by `app.agent.update` / `app.route.update` (FR-030a). |
| 9  | `pane_already_registered` | `app.agent.register_from_pane` for a pane that already has an agent. |
| 10 | `pane_not_found` | Pane identity in `app.agent.register_from_pane` doesn't match a currently-discovered pane (full 6-field identity match required — FR-028a). |
| 11 | `agent_not_found` | `agent_id` parameter (or `parent_agent_id` on adopt — FR-028c, or `target_agent_id` on send_input — FR-031) doesn't match any row. |
| 12 | `route_not_found` | `route_id` parameter doesn't match any row. |
| 13 | `queue_message_not_found` | `message_id` parameter doesn't match any row. |
| 14 | `scan_timeout` | `wait=true` scan exceeded the 30 s cap (FR-030b). Scan continues server-side. |
| 15 | `scan_not_found` | `app.scan.status(scan_id)` for an unknown or evicted scan record (FR-030c). |
| 16 | `daemon_unavailable` | `app.preflight` diagnostic: daemon process not reachable. |
| 17 | `socket_missing` | `app.preflight` diagnostic: socket file absent. |
| 18 | `socket_permission_denied` | `app.preflight` diagnostic: OS denied open. |
| 19 | `docker_unavailable` | A scan or readiness probe found Docker unreachable. |
| 20 | `tmux_unavailable` | A scan found tmux unavailable inside a container. |
| 21 | `container_inactive` | A mutation targeted an entity inside an inactive container (incl. adopt with `attach_log: true` against an inactive container — FR-028b). |
| 22 | `log_attach_blocked` | `app.log.attach` failed for a reason captured in `details.reason`. |
| 23 | `routing_disabled` | The FEAT-009 **global routing kill switch** is off, blocking the mutation. *Not* used for per-message permission-gate refusals — those are `permission_denied` (FR-031, Round-4 Block B Q7). |
| 24 | `permission_denied` | Peer UID failed the FR-041 same-host-user check, **or** the FEAT-009 per-message permission gate refused `app.send_input` (`details.reason == "feat009_permission_gate"` in the second case). |
| 25 | `host_only` | Peer is a bench-container caller; the entire `app.*` namespace is host-only (FR-042). |
| 26 | `payload_too_large` | Single NDJSON request line exceeded the request-line cap (FR-003a) — 1 MiB contract target, currently an effective 64 KiB (`MAX_REQUEST_BYTES`); `details.size_limit_bytes` reports the value enforced. Daemon refuses before handler dispatch. |
| 27 | `internal_error` | Uncaught daemon-side exception (incl. `details.reason == "shutting_down"` during graceful daemon shutdown — Round-4 Block B Q9); safety-net code so the contract envelope shape is preserved. |

## Per-Code `details` Registry (FR-034a)

Each table row lists the required keys for `error.details`. Additional keys MAY appear and are additive across minors. Codes not listed below carry `error.details == {}`.

| `error.code` | Required `details` keys | Types |
|---|---|---|
| `malformed_request` | `reason` | `str` |
| `validation_failed` | `field`, `reason` | both `str` |
| `app_contract_major_unsupported` | `daemon_app_contract_version`, `client_app_contract_major` | `str`, `int` |
| `pane_already_registered` | `agent_id` | `str` |
| `pane_not_found` | `pane_id`, `mismatch_field` (when emitted by FR-028a full-identity check) | `str`, `str` |
| `agent_not_found` | `agent_id` | `str` |
| `route_not_found` | `route_id` | `str` |
| `queue_message_not_found` | `message_id` | `str` |
| `scan_timeout` | `scan_id` | `str` |
| `scan_not_found` | `scan_id` | `str` |
| `container_inactive` | `container_id` | `str` |
| `log_attach_blocked` | `agent_id`, `reason` | both `str` |
| `payload_too_large` | `size_limit_bytes`, `actual_size_bytes` | both `int` |

**Optional keys on existing codes** (additive minor, but documented for callers):

- `permission_denied` MAY carry `details.reason == "feat009_permission_gate"` when emitted by `app.send_input` for a FEAT-009 per-message permission-gate refusal (FR-031). Absence of `reason` indicates the FR-041 peer-UID rejection path.
- `internal_error` MAY carry `details.reason == "shutting_down"` during graceful daemon shutdown (Round-4 Block B Q9).
- `pane_not_found` carries `details.mismatch_field` (a member of `{container_id, tmux_socket, session_name, window_index, pane_index, pane_id}`) when emitted by the FR-028a full-identity check on adopt. Other emitters of `pane_not_found` carry only `details.pane_id`.

**Codes with `details == {}`** (no required keys at v1.0):

`app_session_required`, `app_session_expired`, `unknown_method`, `not_found`, `stale_object`, `daemon_unavailable`, `socket_missing`, `socket_permission_denied`, `docker_unavailable`, `tmux_unavailable`, `routing_disabled`, `permission_denied`, `host_only`, `internal_error` (14 codes).

## Evolution Rules

- **Adding a new code** → additive minor; existing clients must surface unknown codes as `internal_error`-class display states without crashing (SC-009).
- **Adding a new required key** to an existing code's `details` → **major bump** per FR-034a (clients depend on the shape).
- **Adding a new optional key** to an existing code's `details` → additive minor.
- **Removing a required key** from any code → **major bump**.
- **Renumbering or reordering the closed set** → irrelevant (the set is unordered).
- **Renaming a code** → **major bump** (it's a removal + addition).

## Contract Test Surface

The contract test suite (`tests/contract/test_app_errors.py`) MUST:

1. Assert `error.code` regex `^[a-z][a-z0-9_]*$` on every failure path covered by any other test (SC-003 "100% of mutation methods").
2. Assert `error.code ∈ <the 27-code registry above>` on every failure.
3. For each code listed in the per-code registry, assert every required key is present in `details` and has the correct type.
4. Assert `error.details` is a JSON object (never `null`, never an array, never a primitive) on every failure.
5. Assert codes not listed in the registry carry `details == {}`.
6. Assert `app_contract_version` is present on **both** success and failure envelopes (FR-033).
7. Cover the `malformed_request` wire-framing paths (stray `\r`, embedded `\x00`, trailing content, JSON decode error, empty line) per SC-028.
8. Cover the `routing_disabled` vs `permission_denied` distinction on `app.send_input` per SC-038.
