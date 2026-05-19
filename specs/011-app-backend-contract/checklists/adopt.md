# Adopt Mutation Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for `app.agent.register_from_pane` — input shape, validation parity with FEAT-006, race conditions, post-state invariants.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are all input fields of `app.agent.register_from_pane` enumerated (FR-025 lists 11 fields including 5 pane identity + 4 metadata + 2 optional)? [Completeness, Spec §FR-025]
- [ ] CHK002 Is each input field's type and validation rule specified (e.g., `pane_id` format, `role` closed set, `project_path` allowed characters, length caps)? [Gap, Spec §FR-025]
- [ ] CHK003 Is the success envelope's full content specified (agent_id, full agent fields, app_contract_version)? [Completeness, Spec §US2 acceptance 3]
- [ ] CHK004 Is the post-adopt state of the `panes` row defined — must `registered: true` reflect within the same transaction that creates the `agents` row? [Clarity, Spec §US2 step 4]
- [ ] CHK005 Is the post-adopt audit JSONL entry shape defined (which audit event type is emitted)? [Gap, Spec §FR-044]

## Requirement Clarity

- [ ] CHK006 Is "the same daemon-side validation and persistence path as FEAT-006 `register-self`" (FR-026) specified by reference to exact FEAT-006 functions, or only by intent? [Clarity, Spec §FR-026]
- [ ] CHK007 Is "no silent promotion to master" defined — under exactly what FEAT-006 rules MAY a host-driven caller set `role=master`? [Ambiguity, Spec §FR-026]
- [ ] CHK008 Is "explicitly scoped to host-driven registration" defined — does the contract enforce a caller marker, or is it implied by the method existing only in `app.*`? [Clarity, Clarifications §Discovered panes]
- [ ] CHK009 Is the rule defined for whether the daemon trusts the client-supplied pane identity, or re-discovers and matches before accepting? [Ambiguity, Spec §FR-025, §FR-028]

## Requirement Consistency

- [ ] CHK010 Is `pane_already_registered` (FR-027, FR-034) consistent across the spec (same code in mutation, same `details.agent_id` shape)? [Consistency, Spec §FR-027, §FR-034]
- [ ] CHK011 Is `pane_not_found` (FR-028, FR-034) consistent with the FR-034 closed-set entry? [Consistency, Spec §FR-028, §FR-034]
- [ ] CHK012 Are Story 2 acceptance #5 (`validation_failed` with `details.field`) and FR-034's `validation_failed` consistent in shape? [Consistency, Spec §US2, §FR-034]
- [ ] CHK013 Are FR-025's fields consistent with FEAT-004's `panes` row schema and FEAT-006's `agents` row schema? [Consistency]

## Scenario Coverage

- [ ] CHK014 Are requirements defined when only some pane identity fields match (e.g., `pane_id` matches but `session_name` differs from current discovery)? [Gap, Spec §FR-028]
- [ ] CHK015 Are requirements defined for the adopt-mode race where a CLI `register-self` lands between the app's list and adopt calls? [Coverage, Edge Cases §Adopt-mode race]
- [ ] CHK016 Is the behavior defined when `attach_log: true` is requested and the underlying `log.attach` would fail (`container_inactive`)? Does the adopt fail entirely, or succeed and report a partial state? [Gap, Spec §FR-025]
- [ ] CHK017 Are requirements defined for `parent_agent_id` referring to a non-existent agent? [Gap, Spec §FR-025]
- [ ] CHK018 Is the behavior defined for adopt when the underlying pane is discovered but the container becomes inactive between scan and adopt? [Gap]
- [ ] CHK019 Is the behavior defined for adopt when two `app.*` sessions race the same pane (one wins with success, the other receives `pane_already_registered`)? [Coverage, Edge Cases §Adopt-mode race]

## Measurability

- [ ] CHK020 Can "an `agents` row indistinguishable from a CLI `register-self` row" (SC-004) be byte-for-byte verified by SQLite fixture comparison? [Measurability, Spec §SC-004]
- [ ] CHK021 Can the 2-second adopt-mode round-trip budget be reproducibly measured for the full chain `scan.panes → pane.list → register_from_pane → agent.detail`? [Measurability, Spec §SC-004]
- [ ] CHK022 Can "no second `agents` row created" on duplicate adopt (FR-027) be verified by a SQLite row-count assertion? [Measurability, Spec §FR-027]

## Ambiguities, Conflicts, Gaps

- [ ] CHK023 Is `label` required, optional, or normalized (trimmed, lowercased, length-capped)? [Gap, Spec §FR-025]
- [ ] CHK024 Is `capability` validated against a closed set or accepted as free-form? [Gap, Spec §FR-025]
- [ ] CHK025 Is the behavior defined for empty-string vs absent-field semantics on optional inputs (`project_path`, `parent_agent_id`)? [Gap, Spec §FR-025]
- [ ] CHK026 Is the response shape for `pane_already_registered` defined to include only `agent_id` in `details`, or also the full pre-existing agent envelope? [Gap, Spec §FR-027]
- [ ] CHK027 Is the rule defined for whether an `app.scan.panes` call is automatically retried internally when `pane_not_found` would be returned, or whether the app must always re-scan? [Gap, Spec §FR-028]
