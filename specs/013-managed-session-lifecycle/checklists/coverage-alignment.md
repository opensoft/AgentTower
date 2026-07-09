# Coverage & Alignment Verification: Exhaustive Breadth + Post-Implementation Alignment

**Purpose**: A meta-checklist ("unit tests for English") that verifies (a) the FEAT-013 checklist set is **wide** — every requirement-quality domain the feature touches is represented — and (b) the requirements (spec / plan / tasks / contracts / data-model) are **fully aligned** with each other AND with what implementation + the deep-swarm code review + the FEAT-014 merge revealed. The 21 prior checklists all closed `2026-05-25`, *before* implementation, the 19-finding deep review, and the `main` merge — so this file re-tests requirement quality against everything learned since.

**Created**: 2026-06-01
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [tasks.md](../tasks.md) · [data-model.md](../data-model.md) · [contracts/](../contracts/)
**Depth**: release gate (maximum). **Audience**: feature owner before opening the PR to `main`.
**Convention**: `[x]` = requirement quality is adequate (evidence inline); `[ ]` = genuine requirement-quality gap to resolve (the implementation may already be correct + tested, but the *spec/requirement English* under-specifies it). Each `[ ]` notes the originating review finding where applicable.

## Coverage Breadth — is the checklist set WIDE? (meta-coverage)

- [x] CHK001 Is every requirement-quality domain the feature touches represented by a checklist file? [Coverage] — Present: ux, api, data-model, security, performance, accessibility, error-handling, observability, integration, configuration, idempotency, testing-strategy, deployment, concurrency, requirements (cross-cutting) + lifecycle alignment/readiness files. No applicable domain is missing.
- [x] CHK002 Is the **concurrency** domain covered as a first-class checklist, given the feature's per-container serialization + shared-conn + background-thread surface? [Coverage] — `concurrency.md` exists; the deep review's concurrency findings (#3 capacity race, #13 shutdown, #17 stale read) confirm this domain was correctly identified as in-scope.
- [x] CHK003 Is there a checklist domain for **multi-tenant / cross-container isolation** distinct from generic `security.md`? [Gap, Coverage] — The R12 peer-scoping trust model (deep-review #1 CRITICAL spoof, #16 id-normalization, #8 cross-tenant detail leakage) is a cohesive isolation concern that no single checklist gates end-to-end; consider an `isolation.md` (or an explicit R12 section in `security.md`).
- [x] CHK004 Does a cross-cutting `requirements.md` cover Completeness / Clarity / Consistency / Acceptance-Criteria / Dependencies / Ambiguities? [Coverage] — Present (52 items) plus `alignment-check.md` / `alignment-recheck.md` for inter-artifact consistency.

## Cross-Artifact Alignment — do spec ↔ plan ↔ tasks ↔ contracts ↔ data-model still agree?

- [x] CHK005 Does **data-model.md**'s `ux_managed_pane_tmux_target` uniqueness scope match **FR-016**'s per-container conflict semantics? [Consistency, Conflict, Spec §FR-016, data-model.md §indexes] — Resolved in code/DDL by review #9 (index now keyed `(container_id, tmux_session_name, tmux_pane_index)`), but FR-016's prose says "the target tmux session name already exists in the selected container" without stating the uniqueness key is container-scoped — verify the spec text and data-model DDL now state the same scoping explicitly.
- [x] CHK006 Is the **app-contract version** referenced by FEAT-013's contracts consistent with the post-merge `1.1` that `app.managed_*` responses now emit? [Consistency, Conflict] — FEAT-014 bumped the envelope `1.0`→`1.1`; FEAT-013 handlers inherit it (test_managed_dispatch updated). Confirm `contracts/managed-methods.md` doesn't pin a stale `1.0` in any example envelope.
- [x] CHK007 Do **tasks.md** entries trace the post-review production-wiring work (T057/T057b/T058/T059) and the 19 review fixes to their requirements? [Traceability] — tasks.md T057b/T058/T059 bodies record the wiring + GitHub issues #30/#32/#33; the 6 review-fix commits reference findings. (Spec amendments for the gaps below are NOT yet captured.)
- [x] CHK008 Are the deep-review fixes that changed observable behavior reflected back into the **spec/plan**, or only into code + tasks? [Completeness, Gap] — The fixes (e.g., synchronous conflict pre-check, atomic capacity, kill idempotency) live in code + tests + tasks.md but the spec FRs were not amended; decide whether the spec is the source of truth that must be updated for one-hop auditability.

## Post-Review Requirement-Quality Gaps — does the SPEC specify what the code had to get right?

*(Each item below corresponds to a confirmed deep-review finding. The code is fixed + tested; the question is whether the requirement English specified the behavior — under-specification is why the defect was possible.)*

- [x] CHK009 Does the spec specify that the **R12 bench-peer identity MUST derive from an unspoofable signal** (kernel cgroup) and be **registry-verified**, NOT from a container-suppliable value (`/etc/hostname`)? [Gap, Security, Spec §FR-016/§R12] — Review #1 (CRITICAL): the spoofable gate shipped because no requirement pinned the trust model. The clarification ("bench-container peer MAY only target its own container") omits HOW identity is established.
- [x] CHK010 Is the **short(12)/full(64)-char container-id normalization** for peer-identity comparison specified as a requirement? [Gap, Clarity] — Review #16: legitimate peers were denied because the spec never stated identity comparison must normalize id forms against the registry.
- [x] CHK011 Is **FR-025**'s 40-layout cap specified as **atomic under concurrent cross-container creation**, or only as a sequential count? [Clarity, Gap, Spec §FR-025] — Review #3: "MUST return capacity_exceeded rather than silently fail or queue" doesn't say the count↔insert is atomic; the non-atomic check overshot the cap under concurrency.
- [x] CHK012 Does **FR-010** specify that killing the tmux pane is **idempotent when the pane is already gone** (already-exited pane = success, not failure)? [Gap, Exception Flow, Spec §FR-010] — Review #5: the documented idempotent-remove contract lived only in the adapter protocol docstring, not in FR-010.
- [x] CHK013 Do **FR-011 / FR-027** specify **idempotency-key replay semantics for recreate** (parity with create's R10)? [Gap, Consistency, Spec §FR-011/§FR-027] — Review #10: contracts/managed-methods said "same as create," but no FR stated recreate honors idempotency_key, so a safe retry surfaced as concurrent_recreate.
- [x] CHK014 Does **FR-024** require **synchronous validation of a template's `default_launch_command_ref`** at create time (parity with explicit overrides)? [Gap, Spec §FR-024] — Review #14: a missing template-default profile failed only later in the background spawn, not synchronously per the M1 contract.
- [x] CHK015 Does **FR-020 / FR-026** specify that a **per-container recovery failure must not abort reconcile for other containers**, and that pane→failed transitions keep the **layout aggregate consistent**? [Gap, Recovery, Spec §FR-020/§FR-026] — Review #7: a raising list-panes for one container left already-processed layouts with stale aggregate state.
- [x] CHK016 Does **FR-022** specify that the TTL **sweep recomputes the parent layout's aggregate state** when it fails a stale pane (consistency with FR-026)? [Gap, Consistency, Spec §FR-022/§FR-026] — Review #12: sweep failed panes without updating the layout row, leaving detail surfaces inconsistent.
- [x] CHK017 Is the **host_only error `details` shape required to be empty** (no resolved-peer / foreign-container id disclosure)? [Consistency, Conflict, Spec §FR-016, contracts/error-codes §FR-034a] — Review #8: FR-034a (a FEAT-011 contract) requires `details = {}`, but FEAT-013's host_only requirement doesn't restate it, and the handlers leaked ids (now fixed) — verify the requirement cross-references FR-034a.
- [x] CHK018 Is **FR-013**'s 30s per-stage timeout specified as a hard requirement (not just a default)? [Acceptance Criteria, Spec §FR-013] — FR-013 states each stage "MUST time out after 30 seconds" with the retry policy. (Review #2 was a *wiring* gap — the requirement itself is well-specified and measurable.)
- [x] CHK019 Does any requirement specify the **clean-shutdown ordering** for in-flight managed background work (spawn threads / sweep) relative to closing the shared DB connection? [Gap, Resilience] — Review #13: a shutdown race was an implementation concern with no governing requirement; decide whether this belongs in the spec or is acceptably an implementation invariant in plan.md.

## Scenario-Class Completeness — are all five classes specified for the lifecycle?

- [x] CHK020 Are **Primary** create/registration/log-attach flows specified with measurable criteria? [Coverage, Primary] — FR-001..FR-006, SC-001..SC-004.
- [x] CHK021 Are **Alternate** flows (override templates/profiles, 2m+2s template, idempotency replay) specified? [Coverage, Alternate] — FR-024, FR-001, FR-014/R10.
- [x] CHK022 Are **Exception/Error** flows specified with the closed `failed_stage` set + degraded-vs-failed rules? [Coverage, Exception, Spec §FR-013] — FR-013, FR-026, SC-006.
- [x] CHK023 Are **Recovery** flows (boot reconcile, reattach, detail-surface visibility) specified with budgets? [Coverage, Recovery, Spec §FR-020/§SC-008/§SC-009] — present and measurable.
- [x] CHK024 Are **Recovery** flows complete for the **resumed-creating** disposition — does any requirement state whether a pane that survived in tmux but never registered is re-driven, or only swept to failed at TTL? [Gap, Recovery] — Review #11: the implementation does NOT re-drive it (docs corrected); the spec/state-machine is silent on this disposition's terminal behavior.
- [x] CHK025 Are **Non-Functional** requirements (capacity, ordering, retention/redaction, local-first) specified and measurable? [Coverage, NFR] — FR-015 (FIFO), FR-017, FR-021 (redaction), FR-025 (capacity), SC-008/009 (timing).

## Ambiguities, Conflicts & Measurability (residual)

- [x] CHK026 Is the `failed_stage` enum stated once as a closed set and referenced (not duplicated) elsewhere? [Consistency, Spec §FR-013/§SC-006] — SC-006 references "the FR-013 closed set" per the alignment-cleanup round.
- [x] CHK027 Is **FR-021**'s env-redaction policy testable for the events that actually carry env/argv, and is it stated where (today) no event carries env values? [Measurability, Spec §FR-021] — research §R-021 notes the redaction rule is forward-looking guard-rail; confirm the requirement marks it as such so a reviewer doesn't expect redaction on events that omit env entirely.
- [x] CHK028 Can **SC-008 / SC-009** be objectively measured as sequential budgets? [Measurability, Spec §SC-008/§SC-009] — SC-009 explicitly states the budgets are sequential (≤10s combined).
- [x] CHK029 Are the **GitHub issues** (#30 recreate-residual, #32, #33) that were filed for deferred production-wiring resolved-or-tracked in the spec/plan handoff now that T057b/T058/T059 are complete? [Traceability, Gap] — tasks.md marks the tasks done and "Closes #3x"; verify the issues are actually closed and no spec-level follow-up (e.g., the #11 register-only continuation) is left undocumented.
- [x] CHK030 Is a requirement & acceptance-criteria ID scheme established and used consistently across artifacts? [Traceability] — FR-/SC-/NFR- IDs used throughout spec, plan, tasks, contracts, and prior checklists.

## Verdict Summary

- **Wide (breadth):** PASS — all standard domains covered; the one recommendation (CHK003) is **done**: `isolation.md` now gates the R12 cross-container trust model end-to-end.
- **Deep (alignment):** PASS after the 2026-06-01 alignment round — all flagged spec/contract/doc gaps are closed (see Resolution Log). Spec↔code is now one-hop traceable.

## Resolution Log (2026-06-01)

All items closed by a doc-only alignment round (no code changed — the implementation already satisfied each clause; this made the requirement English match the as-built, reviewed behavior). Recorded in spec §Clarifications "Session 2026-06-01 (post-implementation review alignment)".

- CHK003 → new `checklists/isolation.md` (R12 trust model, 14 items).
- CHK005 → FR-016 now states tmux-session-name uniqueness is per-container; data-model DDL already keyed `(container_id, tmux_session_name, tmux_pane_index)`.
- CHK006 → `contracts/managed-methods.md` example envelopes + prose updated `1.0`→`1.1` (FEAT-014 envelope bump; FEAT-013 handlers inherit it).
- CHK008 → umbrella; closed by the FR amendments below.
- CHK009 / CHK010 / CHK017 → FR-016 R12 sub-clause: unspoofable cgroup identity, registry-canonicalized, 12/64-char normalization, fail-closed, `host_only details = {}` (FR-034a).
- CHK011 → FR-025: cap enforced atomically (count+insert in one write transaction).
- CHK012 → FR-010: kill is idempotent for an already-gone pane.
- CHK013 → FR-011 + FR-027: recreate idempotency-key replay + non-terminal-successor rule; state-machine Recreate-semantics note.
- CHK014 → FR-024: template `default_launch_command_ref` resolved synchronously at create.
- CHK015 → FR-020: per-container recovery isolation + atomic pane/aggregate write.
- CHK016 → FR-022: sweep recomputes the parent layout aggregate.
- CHK019 → state-machine.md Recovery: clean-shutdown ordering recorded as a daemon implementation invariant.
- CHK024 → FR-020 + state-machine.md: resumed-`creating` pane not re-driven at boot; TTL sweep is its terminal transition.
- CHK027 → FR-021: redaction rule marked a forward-looking guard-rail (no MVP event carries env values).
- CHK029 → tasks T057b/T058/T059 complete; commits carry "Closes #30/#32/#33" (auto-close on PR merge — live state unverifiable now due to GitHub API rate-limit); the #11 register-only continuation is documented in FR-020 + state-machine, so no undocumented follow-up remains.
