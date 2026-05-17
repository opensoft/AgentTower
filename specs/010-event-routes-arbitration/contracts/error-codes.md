# Closed-Set Error & Skip-Reason Vocabulary

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16

This document enumerates every closed-set string FEAT-010
introduces, with the surface where it appears, the semantic
trigger, and (where applicable) the FEAT-009 exception that maps
to it.

There are three vocabularies:
1. **CLI exit codes** — string codes returned in `{"code": "...",
   "message": "..."}` on non-zero exit (FR-049 revised). Tooling
   branches on the string.
2. **JSONL `route_skipped(reason=...)` values** — closed set
   from FR-037, appears in `events.jsonl` audit entries only
   (NOT as CLI exit codes).
3. **`route_skipped(sub_reason=...)` values for
   `reason=template_render_error`** — finer-grained discriminator
   inside the template-render-error class.

## 1. CLI exit codes (added to FEAT-009 vocabulary)

| Code | Surface | Triggered by |
|---|---|---|
| `route_id_not_found` | `route show`, `route remove`, `route enable`, `route disable` | No row in `routes` matches the provided `route_id`. |
| `route_event_type_invalid` | `route add` | `--event-type` not in FEAT-008 vocabulary (FR-005). |
| `route_master_rule_invalid` | `route add` | `--master-rule` not in `{auto, explicit}` (FR-007). |
| `route_target_rule_invalid` | `route add` | `--target-rule` not in `{explicit, source, role}` (FR-006). |
| `route_source_scope_invalid` | `route add` | `--source-scope` not in `{any, agent_id, role}` OR malformed `--source-scope-value` (Clarifications Q1, FR-049 revised). |
| `route_template_invalid` | `route add` | `--template` references field outside FR-008 whitelist OR template too large. |
| `route_creation_failed` | `route add` | SQLite write failed (e.g., UNIQUE constraint somehow violated on `route_id` — shouldn't happen with UUIDv4 but defended). |
| `queue_origin_invalid` | `queue --origin` | `--origin` not in `{direct, route}`. |

Integer values are allocated by the existing FEAT-002
`socket_api/errors.py` registry; tooling MUST branch on the
string code, not the integer (FR-050).

## 2. JSONL `route_skipped(reason=...)` values (FR-037)

These appear in `events.jsonl` audit entries only, NOT as CLI
exit codes.

### 2a. Arbitration-failure reasons

| Reason | Source | When |
|---|---|---|
| `no_eligible_master` | FEAT-010 `arbitration.pick_master` | `master_rule=auto` and zero active masters exist. |
| `master_inactive` | FEAT-010 `arbitration.pick_master` | `master_rule=explicit`, the named agent exists in the registry, but is not currently an active master. |
| `master_not_found` | FEAT-010 `arbitration.pick_master` | `master_rule=explicit`, the named agent has no record in the registry. |

`winner_master_agent_id` is `null` in the audit entry; `target_agent_id` and `target_label` are also `null` (target resolution never started).

### 2b. Target-resolution-failure reasons

| Reason | Source | When |
|---|---|---|
| `target_not_found` | FEAT-010 `target_resolver` → FEAT-009 exception | `target_rule=explicit` and the agent (by id or label) does not exist; OR `target_rule=source` and the source agent has been deregistered. |
| `target_role_not_permitted` | FEAT-009 `permissions` | The resolved target's role is not in `{slave, swarm}` (FEAT-009 inheritance). |
| `target_not_active` | FEAT-009 `permissions` | The resolved target exists but is not currently active. |
| `target_pane_missing` | FEAT-009 `delivery` precheck | The resolved target has no tmux pane registered. |
| `target_container_inactive` | FEAT-009 `delivery` precheck | The resolved target's container is not running. |
| `no_eligible_target` | FEAT-010 `worker` | `target_rule=role` and zero agents match the role+capability filter. |

`winner_master_agent_id` is non-null (arbitration succeeded). `target_agent_id` and `target_label` are populated when target resolution succeeded but enqueue precondition failed (`target_role_not_permitted`, `target_not_active`, `target_pane_missing`, `target_container_inactive`); they are `null` when resolution never produced an identity (`target_not_found`, `no_eligible_target`).

### 2c. Template-render-failure reasons

| Reason | Source | When |
|---|---|---|
| `template_render_error` | FEAT-010 `template.render_template` | Any render-time failure. The `sub_reason` field discriminates. |

`winner_master_agent_id` is non-null (arbitration succeeded); `target_agent_id` and `target_label` are populated (target resolution succeeded; render is the post-resolve step).

## 3. `route_skipped(sub_reason=...)` values

These appear only when `reason=template_render_error`. All other
reasons have `sub_reason=null`.

| Sub-reason | Source | When |
|---|---|---|
| `missing_field` | FEAT-010 `template.render_template` | A whitelisted field placeholder is present in the template but the event row does not have that field populated. Defended; should be impossible if parse-time validation passes. |
| `body_empty` | FEAT-009 `envelope.validate_body_bytes` | Rendered body is zero-length. |
| `body_invalid_chars` | FEAT-009 `envelope.validate_body_bytes` | Rendered body contains a NUL byte or disallowed control character. |
| `body_invalid_encoding` | FEAT-009 `envelope.validate_body_bytes` | Rendered body is not valid UTF-8. |
| `body_too_large` | FEAT-009 `envelope.validate_body_bytes` | Rendered body exceeds the FEAT-009 size cap. |

The `body_*` sub-reasons come from the FEAT-009 body validator
without modification — FEAT-010 catches the FEAT-009 exception
and maps to the matching sub-reason.

## 4. Internal-error vocabulary (FR-051)

Not CLI exit codes; appear in the `routing_worker_degraded`
state and in the daemon log only. Used by the worker to record
transient internal failures that prevent cursor advance.

| Internal code | When |
|---|---|
| `routing_sqlite_locked` | `BEGIN IMMEDIATE` failed because another transaction held the write lock; retry next cycle. |
| `routing_duplicate_insert` | The defense-in-depth UNIQUE index on `(route_id, event_id) WHERE origin='route'` fired; indicates a logic bug. The worker logs the full SQL error and continues with the next event (cursor does NOT advance for the offending event). |
| `routing_internal_render_failure` | An unexpected exception in `template.render_template` (e.g., bug). Cursor does NOT advance; retried next cycle. |
| `routing_audit_buffer_overflow` | The 10,000-entry JSONL buffer rolled over; one entry dropped. |

## 5. Mapping table: FEAT-009 exception → FEAT-010 outcome

| FEAT-009 exception | FEAT-010 outcome |
|---|---|
| `KillSwitchOff` | Queue row inserted with `state=blocked, block_reason='kill_switch_off'`; audit emits `route_matched` (NOT `route_skipped`); cursor advances. (FR-032, Story 5 #1) |
| `TargetNotFound` | `route_skipped(reason='target_not_found')`; cursor advances. |
| `TargetRoleNotPermitted` | `route_skipped(reason='target_role_not_permitted')`; cursor advances. |
| `TargetNotActive` | `route_skipped(reason='target_not_active')`; cursor advances. |
| `TargetPaneMissing` | `route_skipped(reason='target_pane_missing')`; cursor advances. |
| `TargetContainerInactive` | `route_skipped(reason='target_container_inactive')`; cursor advances. |
| `BodyEmpty` | `route_skipped(reason='template_render_error', sub_reason='body_empty')`; cursor advances. |
| `BodyInvalidChars` | `route_skipped(reason='template_render_error', sub_reason='body_invalid_chars')`; cursor advances. |
| `BodyInvalidEncoding` | `route_skipped(reason='template_render_error', sub_reason='body_invalid_encoding')`; cursor advances. |
| `BodyTooLarge` | `route_skipped(reason='template_render_error', sub_reason='body_too_large')`; cursor advances. |
| `sqlite3.OperationalError(database is locked)` | `RoutingTransientError`; cursor does NOT advance; retried next cycle; degraded flag flips. |
| `sqlite3.IntegrityError(UNIQUE constraint failed)` on `(route_id, event_id)` | `RoutingDuplicateInsert`; cursor does NOT advance; logged as `routing_duplicate_insert`. |

## 6. Stability guarantee

The closed-set strings in §1, §2, §3 are part of the public CLI
+ audit contract. They MUST NOT be renamed or removed except via
a SemVer major bump of the daemon. Adding new strings is
backward-compatible.
