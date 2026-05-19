# Versioning & Evolution Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for `app_contract_version` semantics, capability flag protocol, additive minor evolution, and cross-major drift.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Are MAJOR.MINOR semantics fully specified (when to bump major vs minor, what "additive" means concretely)? [Completeness, Spec §FR-035]
- [X] CHK002 Is `client_app_contract_major` declaration's source defined — is it a separate field in `app.hello` request, or inferred from `client_version`? [Gap, Spec §FR-036]
- [X] CHK003 Is `supported_minor_range`'s semantics defined when the daemon advertises e.g., `{min: "1.0", max: "1.0"}` — does that mean only minor 1.0 clients, or also lower-minor clients (none in v1.0)? [Clarity, Spec §FR-010]
- [X] CHK004 Is the upgrade path for adding a new closed-set error code defined as an additive minor change? [Coverage, Spec §FR-034, §FR-035]
- [X] CHK005 Is the upgrade path for adding a new readiness subsystem (FR-013 last sentence) defined as an additive minor change? [Coverage, Spec §FR-013, §FR-035]
- [X] CHK006 Is the upgrade path for adding a new `capability_flags` entry defined as additive (FR-039)? [Coverage, Spec §FR-035, §FR-039]

## Requirement Clarity

- [X] CHK007 Is "newer-daemon/older-app is always allowed within the same major" (Clarifications §Version compatibility) testable — what must an older client ignore? [Clarity, Clarifications §Version]
- [X] CHK008 Is "Clients MUST treat unknown response fields as ignorable" (FR-037) operationalized — what failure mode is observed if a client crashes on unknown fields? [Clarity, Spec §FR-037]
- [X] CHK009 Is "Daemons MUST treat unknown request fields as ignorable" (FR-038) symmetric — what happens with conflicting field values (older field plus newer field naming the same concept)? [Clarity, Spec §FR-038]
- [X] CHK010 Is "Removing or renaming any of the above MUST increment major" (FR-035) defined to include changes in error-code `details` fields, or only top-level methods/fields? [Gap, Spec §FR-035]

## Requirement Consistency

- [X] CHK011 Are FR-010's `app_contract_version` "MAJOR.MINOR" format and FR-035's `MAJOR.MINOR` consistent in case and punctuation? [Consistency, Spec §FR-010, §FR-035]
- [X] CHK012 Is "no token issued" on major mismatch (Clarifications §Version) consistent with FR-036's "no session token"? [Consistency, Spec §FR-036]
- [X] CHK013 Are FR-039's `capability_flags = {}` at v1.0 and Clarifications §capability_flags consistent? [Consistency, Spec §FR-039]
- [X] CHK014 Is `app_contract_major_unsupported` (FR-034, FR-036, US5) consistent in name and shape everywhere it appears? [Consistency]

## Scenario Coverage

- [X] CHK015 Are requirements defined for the case where the daemon's `supported_minor_range` advertises minors beyond what's implemented (e.g., an erroneously high `max`)? [Gap, Spec §FR-010]
- [X] CHK016 Are requirements defined for negative major declarations or malformed `client_app_contract_major` (e.g., a string instead of an integer)? [Gap, Spec §FR-036]
- [X] CHK017 Is the behavior defined when a future client opts-in to a major bump that the daemon also implements (both at major N+1)? [Coverage, Spec §FR-035, §US5]
- [X] CHK018 Is the behavior defined for an app that calls `app.hello` declaring equal major but a higher minor than the daemon (allowed under additive evolution — what response does it get)? [Coverage, Spec §US5 step 2]
- [X] CHK019 Is the rule defined when a daemon supports `1.0–1.2` but the app expects exactly `1.0` — must the daemon downshift behavior, or always advertise its full range? [Gap, Spec §FR-010]
- [X] CHK020 Is the behavior defined when a major-version mismatch is detected by `app.preflight` (does preflight expose the daemon's major before `app.hello`)? [Gap, Spec §FR-011]

## Measurability

- [X] CHK021 Can SC-005's "zero stray fields and zero internal state mutation on major mismatch" be verified by a contract test? [Measurability, Spec §SC-005]
- [X] CHK022 Can SC-009's within-major additive evolution test (synthetic minor-N client vs minor-(N+1) daemon) be reproducibly run against the current spec without inventing speculative future methods? [Measurability, Spec §SC-009]
- [X] CHK023 Is "no internal state mutation" (SC-005) testable from outside the daemon (no side effects observable, no audit row written)? [Measurability, Spec §SC-005]

## Ambiguities, Conflicts, Gaps

- [X] CHK024 Is there a contract for the `app_contract_major_unsupported` response — must it include `daemon_app_contract_version` and `client_app_contract_major` in `details`? [Gap, Spec §FR-036, §US5]
- [X] CHK025 Is the rule defined for what happens when a new `capability_flags` key is added in a minor — should older clients tolerate the unknown key (yes per FR-037), and is that explicitly cross-referenced? [Coverage, Spec §FR-037, §FR-039]
- [X] CHK026 Is the major-bump policy defined for changes that are *behaviorally* breaking but *structurally* additive (e.g., changing the default `limit` from 50 to 25)? [Gap, Spec §FR-035]
- [X] CHK027 Is the rule defined for whether `app_contract_version` is allowed to change *during* a session (e.g., daemon hot-reload), or whether it's fixed at `app.hello`? [Gap, Spec §FR-006, §FR-035]
