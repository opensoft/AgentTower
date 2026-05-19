# Sessions Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for app session identity, token lifecycle, peer-cred authorization, and audit attribution semantics.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Is the `app_session_token` format/length/charset specified (uuid v4 mentioned in Clarifications — is the canonical hex vs. base32 vs. integer-encoded form fixed)? [Completeness, Clarifications §Session 2026-05-18]
- [X] CHK002 Is the `app_session_id` numeric range, monotonicity, and reset-behavior-on-daemon-restart defined? [Gap, Spec §App Session entity]
- [X] CHK003 Is the maximum number of concurrent app sessions per daemon defined? [Gap, Edge Cases §Concurrent app sessions]
- [X] CHK004 Are session lifetime bounds defined beyond "until the connection closes" (idle timeout, hard cap)? [Gap, Spec §FR-008]
- [X] CHK005 Is the behavior defined for a session token presented on a different connection than the one that received it? [Gap, Spec §FR-008]
- [X] CHK006 Is the rule defined for `app.hello` called twice on the same connection — does it invalidate the prior token and issue a new one, or reject? [Gap]

## Requirement Clarity

- [X] CHK007 Is "best-effort scoped to the calling process" (Clarifications §Sessions) defined operationally — strictly connection-scoped, or also bound to PID via SO_PEERCRED? [Clarity, Clarifications §Session 2026-05-18]
- [X] CHK008 Is "opaque" (FR-006) defined — does the daemon promise the token has no embedded semantics decodable by clients? [Clarity, Spec §FR-006]
- [X] CHK009 Is the difference between `app_session_token` (secret-like) and `app_session_id` (audit-friendly) clearly documented as a privacy boundary? [Clarity, Spec §FR-009]
- [X] CHK010 Is `app_session_required` vs `app_session_expired` distinguished consistently — same error for missing-token and invalid/stale-token, or different codes? [Clarity, Spec §FR-007, §FR-034]

## Requirement Consistency

- [X] CHK011 Do FR-006, FR-007, FR-008, and the Edge Cases section agree on the session-lifecycle trigger (connection close = invalidation)? [Consistency]
- [X] CHK012 Are FR-009's "SHOULD record `app_session_id`" and FR-044's "SHOULD emit JSONL audit entries with `app_session_id`" consistent in modality (both SHOULD, neither MUST)? [Consistency, Spec §FR-009, §FR-044]
- [X] CHK013 Is "Sessions are not durable" (App Session entity) consistent with FR-006 "neither of which is persisted across daemon restarts"? [Consistency, Spec §App Session entity, §FR-006]

## Scenario Coverage

- [X] CHK014 Are requirements defined for daemon restart mid-session — does the token become invalid with a distinct code from connection close (`app_session_expired` vs `daemon_restarted`)? [Gap, Edge Cases]
- [X] CHK015 Are requirements defined for token replay attempts across concurrent connections by the same UID? [Gap, Edge Cases §Session token replay]
- [X] CHK016 Are concurrent-session ordering guarantees specified (e.g., do two app sessions see writes in a consistent global order)? [Coverage, Edge Cases §Concurrent app sessions]
- [X] CHK017 Is the behavior defined when `client_id` or `client_version` is empty or absent in `app.hello`? [Gap, Spec §FR-010, §App Session entity]
- [X] CHK018 Is there a closed-set code for "session token format invalid" distinct from "expired"? [Gap, Spec §FR-034]

## Measurability

- [X] CHK019 Can "session is invalidated when the underlying socket connection closes" (FR-008) be objectively verified by a contract test that reconnects with the prior token? [Measurability, Spec §FR-008]
- [X] CHK020 Can "the opaque `app_session_token` MUST NOT appear in any JSONL row" (SC-008) be programmatically asserted by a grep test? [Measurability, Spec §SC-008]
- [X] CHK021 Is "the daemon does not gate concurrency between sessions" (Edge Cases) objectively testable? [Measurability]

## Ambiguities, Conflicts, Gaps

- [X] CHK022 Is the rule defined when the peer UID check (FR-041) fails *after* `app.hello` succeeded — can a session outlive a UID change (e.g., setuid binary handoff)? [Gap, Spec §FR-041]
- [X] CHK023 Is "audit attribution" preserved if the connection drops between mutation and audit row write — does the row carry the now-invalid session_id? [Gap, Spec §FR-044]
- [X] CHK024 Is `host_user_id` (FR-010) guaranteed stable across the lifetime of a session, or could it change (e.g., session crosses a su/sudo boundary)? [Gap, Spec §FR-010]
