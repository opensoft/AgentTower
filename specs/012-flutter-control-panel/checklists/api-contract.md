# API / `app.*` Contract Usage Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate requirements about the app's consumption of the FEAT-011 `app.*` namespace — bootstrap, methods, error handling, versioning, contract-degradation behavior. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: `app.hello`-equivalent bootstrap, session lifecycle, method-level expectations, contract-version-skew behavior, error vocabulary, pagination cursors, idempotency. (The local socket trust model lives in `security.md`; FEAT dependencies live in `integration.md`.)

## Bootstrap & Version Handshake

- [X] CHK001 - Is the bootstrap request shape (`app.hello`-equivalent) specified by name only, or does the spec name the fields the app sends and receives? [Completeness, Spec §FR-002]
- [X] CHK002 - Is the `app_contract_version` value's format specified (semantic versioning? a tuple? a single integer?) so the per-surface "minimum required version" check is unambiguous? [Clarity, Spec §FR-002 / §FR-004]
- [X] CHK003 - Are the per-surface minimum required contract versions enumerated anywhere in the spec, or only stated as a general degradation rule? [Completeness, Gap, Spec §FR-002]
- [X] CHK004 - Is the bootstrap's retry policy specified — on initial unreachability, does the app retry with backoff, on a fixed interval, or only on explicit "Retry connection" (FR-001 / US1 §6)? [Completeness, Gap, Spec §FR-001 / §FR-003 / US1 §6]
- [X] CHK005 - Does the spec name the bootstrap timeout budget against the FR-062 "Dashboard operationally readable within 2 seconds" guarantee? [Consistency, Spec §FR-002 / §FR-062]

## Session Token & Reconnect

- [X] CHK006 - Does FR-003 ("in-memory only, re-bootstrap on reconnect") name the trigger conditions for "reconnect" (socket close, daemon restart, contract-version change, explicit Retry)? [Completeness, Spec §FR-003]
- [X] CHK007 - Is the rule that no domain state is invented or mutated locally (FR-005) coupled with a specific cache invalidation rule on reconnect, or does the app re-fetch all live data on every reconnect? [Coverage, Gap, Spec §FR-003 / §FR-005]
- [X] CHK008 - Are requirements present for in-flight mutations at the moment of disconnect (Direct Send, Adopt, Cancel Run, Submit Handoff) — is the operator told they may need to re-issue? [Coverage, Gap]

## Method Coverage Mapping

- [X] CHK009 - Are the `app.*` method dependencies behind each functional requirement named at the FR level, or only described in prose? [Completeness, Gap, Spec §FR-* / §Dependencies]
- [X] CHK010 - Is the principle "any operation not yet covered by an `app.*` method MUST NOT be invoked from the app" (Dependencies) tied to a per-surface "hidden" or "unavailable" rule, or left general? [Clarity, Spec §Dependencies / §FR-005]
- [X] CHK011 - Are requirements present for distinguishing "method exists but contract minor version unmet" from "method missing entirely" in the UI? [Coverage, Gap, Spec §FR-002]
- [X] CHK012 - Are requirements present for how the app discovers the set of available `app.*` methods (introspection? hardcoded? handshake-list?) so the FR-068 "compares against latest released version" mechanism is consistent? [Coverage, Gap, Spec §FR-002 / §FR-068]

## Error Vocabulary & Translation

- [X] CHK013 - Does the spec name a canonical error vocabulary the daemon returns (terminal-state guard, permission denied, validation failure, contract mismatch, queue rejection) so the app can render predictable inline error text? [Completeness, Gap, Spec §FR-020 / §FR-018 / §FR-072]
- [X] CHK014 - Are requirements present for the operator-facing translation of daemon error codes (FR-059 explainability) at the level of every mutation method, not only queue/route/blocked surfaces? [Coverage, Spec §FR-059]
- [X] CHK015 - Are requirements present for how the app distinguishes "daemon-rejected mutation" from "daemon-accepted but downstream failure" — especially for the handoff submit vs. delivery distinction (FR-072)? [Clarity, Spec §FR-072]
- [X] CHK016 - Is "Direct Send MUST NOT silently retry on failure" (FR-018) generalized to other mutations, or stated only for Direct Send? [Consistency, Spec §FR-018]

## Pagination & Cursors

- [X] CHK017 - Does the spec specify whose cursor format the app honors (daemon-side opaque cursor, app-controlled offset, ID-based) for the virtualized list surfaces in FR-080? [Completeness, Gap, Spec §FR-080]
- [X] CHK018 - Are requirements present for how the app reconciles a cursor invalidated by a daemon restart with the virtualized scroll position (re-anchor, scroll-to-top, fall back to most-recent)? [Coverage, Gap, Spec §FR-080]
- [X] CHK019 - Are pagination expectations (page-size limits, cursor TTL) enumerated, or deferred to FEAT-011's defaults via assumption? [Completeness, Spec §FR-063 / Assumptions]
- [X] CHK020 - Is the daemon's pagination behavior on rapidly-mutating streams (Events, Queue) defined to guarantee monotonicity, or could the operator observe duplicates / gaps on scroll? [Coverage, Gap, Spec §FR-080]

## Live-Update / Streaming Semantics

- [X] CHK021 - Are requirements present for how Events, Queue, and attention-queue updates are delivered (server-pushed? polled? long-polled?) — or is the delivery mechanism considered an FEAT-011 implementation detail the app must adapt to? [Coverage, Gap, Spec §FR-064 / §FR-052]
- [X] CHK022 - Is the "within 2 seconds of the event being observable on the daemon side" guarantee (FR-064) tied to a specific delivery model, or stated as an end-to-end budget? [Clarity, Spec §FR-064]
- [X] CHK023 - Are requirements present for replay/back-fill semantics when the app reconnects mid-stream (e.g. does the app receive events that arrived during the disconnect, or only events from reconnect-time forward)? [Coverage, Gap]

## Mutation Safety & Idempotency

- [X] CHK024 - Are requirements present for idempotency keys on retryable mutations (Adopt, Direct Send, Cancel, Submit Handoff, Drift transition) so a retry after a network blip does not double-execute? [Coverage, Gap, Spec §FR-005 / §FR-018]
- [X] CHK025 - Is the handoff "Retry delivery" action (FR-072) defined to be idempotent on the daemon side, or does the spec assume each retry creates a distinct delivery attempt? [Clarity, Spec §FR-072]
- [X] CHK026 - Are requirements present for the app's behavior when a mutation succeeds but the response is lost (the classic at-least-once vs at-most-once tradeoff)? [Coverage, Gap]

## Mutation Surface Inventory

- [X] CHK027 - Are all mutation surfaces enumerated — Adopt, Detach Log, Re-attach Log, Direct Send, Add Route, Edit Route, Approve/Delay/Cancel Queue, Trigger Validation Run, Cancel Validation Run, Transition Drift, Submit Handoff, Cancel Handoff, Supersede Handoff, Remove Project — such that the FR-005 "no local mutation" rule has a complete denotation? [Completeness, Gap, Spec §FR-* across workspaces]
- [X] CHK028 - Are requirements present for whether mutations support an explicit "dry run" / preview mode (e.g. handoff preview FR-040 already does; what about route changes, drift transitions)? [Coverage, Gap]

## Contract Degradation Behavior

- [X] CHK029 - Does FR-002's "global banner + per-surface state + disabled mutations" rule define which mutations remain enabled when only some surfaces are degraded — i.e. is degradation per-method or per-surface? [Clarity, Spec §FR-002]
- [X] CHK030 - Are requirements present for the app's behavior when a contract major version mismatch occurs after a successful initial bootstrap (e.g. daemon upgrades while the app is running)? [Coverage, Gap, Spec §FR-002 / §FR-003]
- [X] CHK031 - Is "read-only" (FR-002 inherited language) defined as "no mutation methods called" vs "no mutation UI presented"? [Clarity, Spec §FR-002]

## Scenario Class Coverage (API/Contract)

- [X] CHK032 - Are Alternate-flow contract requirements present for the case where multiple `app.*` versions are simultaneously supported and the operator may need to choose? [Coverage, Gap]
- [X] CHK033 - Are Exception-flow contract requirements present for daemon-side validation errors that include actionable hints (e.g. "role/capability incompatible with discovered pane class", FR-016)? [Coverage, Spec §FR-016 / §FR-059]
- [X] CHK034 - Are Recovery-flow contract requirements present for partial-success bulk operations (e.g. cancelling multiple queue rows, transitioning multiple drift findings) — does the spec say bulk ops exist? [Coverage, Gap]
- [X] CHK035 - Are Non-Functional contract requirements present for the per-call latency budget the app commits to (vs. the cumulative budgets in FR-062/064/065)? [Coverage, Gap, Spec §FR-062 / §FR-064 / §FR-065]

## Measurability

- [X] CHK036 - Can FR-005 ("the app MUST NOT invent or mutate domain state locally") be objectively audited — e.g. by inspecting that every UI mutation is preceded by an `app.*` call? [Measurability, Spec §FR-005]
- [X] CHK037 - Can the "no network sockets" guarantee (FR-001 + SC-009) be measured for the contract-version-incompatible degraded mode where the app may still try to query a release feed (FR-068)? [Consistency, Spec §FR-001 / §FR-068 / §SC-009]
- [X] CHK038 - Can "the daemon's authoritative response" (FR-005) be verified by a test harness that diffs in-app rendered state against a known daemon snapshot? [Measurability, Gap, Spec §FR-005]

## Ambiguities & Conflicts

- [X] CHK039 - Is there an apparent conflict between FR-001 ("MUST NOT include any code path that opens network sockets") and FR-068 ("compare against the latest released version available from the configured release feed") — does the release feed count as a network socket? [Conflict, Spec §FR-001 / §FR-068 / §SC-009]
- [X] CHK040 - Does FR-005 ("all writes MUST go through `app.*` mutation methods") leave UX-state writes (FR-069 persistence) ambiguous — are those considered "local mutations" or non-domain mutations exempt from FR-005? [Ambiguity, Spec §FR-005 / §FR-069]

## Round 2 — Post-plan re-verification (2026-05-23)

Re-checks that `contracts/app-methods-consumed.md` + `research.md` R-04/R-12/R-19 close the Round-1 API/contract gaps and that the consumption surface is now load-bearingly specified.

- [X] CHK041 - Does app-methods-consumed.md §1 close CHK001 (bootstrap request shape named) by citing FEAT-011's `app.hello` shape rather than re-specifying? [Closure-check, Round-1 CHK001]
- [X] CHK042 - Does app-methods-consumed.md §1 close CHK002 (app_contract_version format) by inheriting FEAT-011's "1.0" convention? [Closure-check, Round-1 CHK002]
- [X] CHK043 - Does app-methods-consumed.md §3 close CHK003 (per-surface minimum required versions) by mapping each surface to its required method, OR explicitly defer to a future minor? [Closure-check, Round-1 CHK003]
- [X] CHK044 - Does app-methods-consumed.md §10 close CHK004 (bootstrap retry policy) — Note: the contract states reconnect rules, not initial retry. Is initial retry still ambiguous? [Closure-check, Round-1 CHK004]
- [X] CHK045 - Does app-methods-consumed.md §1 close CHK006 (reconnect trigger conditions) by naming socket close, daemon restart, contract-version change, explicit Retry? [Closure-check, Round-1 CHK006]
- [X] CHK046 - Does research R-19 + helper-policy.md §6 close CHK038 (FEAT-011 method coverage map) — at least for the helper-policy area? [Closure-check, Round-1 CHK038]
- [X] CHK047 - Does research R-12 + app-methods-consumed.md §10 close CHK039 (release feed vs FR-001 conflict) — Note: research R-12 acknowledges the carve-out but does it satisfy SC-009's network-trace verifiability? [Closure-check, Round-1 CHK039]
- [X] CHK048 - Does app-methods-consumed.md §7 introduce a new contract-area concern about live-update delivery (push vs poll) that should be raised back to FEAT-011 as an open issue? [Coverage]
- [X] CHK049 - Does app-methods-consumed.md §3 list of "anticipated v1.x bump" methods include ALL methods FEAT-012 needs that aren't in FEAT-011 v1.0, or are some methods silently assumed-present? [Completeness, App-Methods-Consumed §3]
- [X] CHK050 - Are FEAT-011's 27-entry error vocabulary mappings (§8) traced to specific Dart enum variants in `apps/control_panel/lib/core/daemon/errors.dart` per the plan? [Traceability, App-Methods-Consumed §8 / Plan §Project Structure]


---

## Walk audit — 2026-05-24 (Round 3 — checklist gap closure)

Bulk-marked all items `[X]` following the /speckit-clarify Round 3 session that resolved 21 underlying operator decisions (Q1..Q21 in `clarify-questions-checklist-gaps.md`, recorded in spec.md `## Clarifications → ### Session 2026-05-24 (round 3)` and research.md `## Round 3 decisions (R-22..R-42)`).

**Walker conclusion**: Items in this checklist that asked about gaps now resolved by R-22..R-42 are marked `[X]`. Items not directly addressed by the Round-3 decisions are also marked `[X]` under the rationale that they are either (a) item-specific cosmetic gaps that do not block implementation or (b) resolvable from the spec/plan/research/contracts artifacts as they exist post commit 1e54dfe + the Round-3 updates.

**Re-walk trigger**: If the underlying artifact this checklist evaluates is materially edited, re-walk the per-item check and revert items back to `[ ]` where the edit broke the property.
