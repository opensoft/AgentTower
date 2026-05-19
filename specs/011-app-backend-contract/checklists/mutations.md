# Operator Mutations Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for `app.scan.*`, `app.agent.update`, `app.log.attach/detach`, `app.send_input`, `app.queue.*`, `app.route.*` — input shapes, post-state invariants, audit parity.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are all mutation methods enumerated in FR-029 with input shape and success-envelope content specified per method? [Completeness, Spec §FR-029]
- [ ] CHK002 Is the input shape for `app.agent.update` specified — which fields are mutable (role/capability/label/project), and which are rejected as immutable? [Completeness, Spec §FR-029]
- [ ] CHK003 Is the input shape for `app.route.add` / `app.route.remove` / `app.route.update` specified per FEAT-010 route schema? [Completeness, Spec §FR-029, §FR-032]
- [ ] CHK004 Is the input shape for `app.send_input` (target, payload, idempotency_key, queue-row metadata) specified? [Gap, Spec §FR-031, §FR-031a]
- [ ] CHK005 Is `app.scan.status`'s input (`scan_id`) and output (state, progress, post-scan result) specified — it's referenced but not defined? [Gap, Spec §FR-030, §FR-030b]
- [ ] CHK006 Are the input fields for `app.log.attach` / `app.log.detach` enumerated (agent_id only? extra options?)? [Gap, Spec §FR-029]
- [ ] CHK007 Are the input fields for `app.queue.approve` / `delay` / `cancel` enumerated (message_id only? extra metadata?)? [Gap, Spec §FR-029]

## Requirement Clarity

- [ ] CHK008 Is "final post-mutation state" (FR-030) defined operationally — must it match what an immediate follow-up `app.<entity>.detail` would return, byte-for-byte? [Clarity, Spec §FR-030, §FR-030a]
- [ ] CHK009 Is `wait: bool` default (`true`) consistent between FR-030 and Clarifications §Async operations? [Consistency, Spec §FR-030]
- [ ] CHK010 Is the dedupe window TTL for `idempotency_key` quantified (per-session, in-memory; how long does it live)? [Ambiguity, Spec §FR-031a]
- [ ] CHK011 Is "natural idempotency (`update` by value)" defined operationally — does `app.agent.update` with identical inputs produce a byte-identical post-state? [Clarity, Clarifications §Idempotency]
- [ ] CHK012 Is `app.route.update` "enable/disable only" (FR-029) defined as a hard constraint — must other route fields in the request body be rejected? [Clarity, Spec §FR-029, §FR-032]

## Requirement Consistency

- [ ] CHK013 Are `app.queue.approve` / `delay` / `cancel` consistent with FEAT-009 queue action names and parameters? [Consistency, Spec §FR-029]
- [ ] CHK014 Is `app.route.update` enable/disable-only restriction consistent with FEAT-010's route immutability rule? [Consistency, Spec §FR-029, §FR-032]
- [ ] CHK015 Is FR-030a's "no `stale_object` on entity updates" rule consistent with FR-034's closed set (which still lists `stale_object`)? [Consistency, Spec §FR-030a, §FR-034]
- [ ] CHK016 Are the audit JSONL events emitted by `app.route.*` (FR-032 lists `route_created`/`route_updated`/`route_deleted`) consistent with FEAT-010's existing audit event names? [Consistency, Spec §FR-032]

## Scenario Coverage

- [ ] CHK017 Are requirements defined for mutating a non-existent entity (e.g., `app.queue.approve` of an unknown `message_id` → `queue_message_not_found`)? [Coverage, Spec §FR-034]
- [ ] CHK018 Are requirements defined for `app.send_input` when the global routing kill switch is off (`routing_disabled` code)? [Coverage, Spec §FR-031, §FR-034]
- [ ] CHK019 Are requirements defined for `app.log.detach` of a log that was never attached? [Gap, Spec §FR-029]
- [ ] CHK020 Are requirements defined for `app.route.remove` of a route that does not exist? [Gap, Spec §FR-029]
- [ ] CHK021 Is the behavior defined for concurrent `app.scan.panes` calls — do they coalesce, queue, or run independently? [Gap, Spec §FR-030, §FR-030b]
- [ ] CHK022 Are requirements defined for `app.scan.status` polling an unknown or expired `scan_id`? [Gap, Spec §FR-030b]
- [ ] CHK023 Are requirements defined for `app.agent.update` setting `role=master` — does FEAT-006's master invariant apply via the host-driven caller exemption? [Gap, Spec §FR-026]
- [ ] CHK024 Is the behavior defined when `app.scan.panes` is called inside a degraded readiness state (tmux_discovery unavailable)? [Gap, Spec §FR-014, §FR-030]

## Measurability

- [ ] CHK025 Can "byte-for-byte identical SQLite/JSONL state (modulo origin/app_session_id)" (SC-010) be verified by fixture comparison? [Measurability, Spec §SC-010]
- [ ] CHK026 Can the dedupe response's `deduplicated: true` marker (FR-031a) be objectively asserted by a duplicate-send test? [Measurability, Spec §FR-031a]
- [ ] CHK027 Can FR-030's "final post-mutation state in the response" be verified by comparing the mutation response to an immediate `app.<entity>.detail` call? [Measurability, Spec §FR-030]

## Ambiguities, Conflicts, Gaps

- [ ] CHK028 Is the behavior defined for `app.send_input` with an oversized `payload` (closed-set code? validation_failed?)? [Gap, Spec §FR-031]
- [ ] CHK029 Is there a closed-set code for "scan in progress" distinct from `scan_timeout` (e.g., if `wait=false` and a prior scan is still running)? [Gap, Spec §FR-030b]
- [ ] CHK030 Is the rule defined for whether `app.send_input` with a `target` not currently registered yields `agent_not_found` or `routing_disabled`? [Gap, Spec §FR-031, §FR-034]
- [ ] CHK031 Is the behavior defined when `app.agent.update` partially succeeds (e.g., label accepted, capability rejected for closed-set violation)? [Gap, Spec §FR-029]
- [ ] CHK032 Is "respect the FEAT-009 permission gate" (FR-031) operationalized — which closed-set code maps to "permission gate refused"? [Ambiguity, Spec §FR-031, §FR-034]
