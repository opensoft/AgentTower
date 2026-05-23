# Security Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for local-only invariant, peer-cred authorization, host-only restrictions, and the no-new-secrets boundary.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Are the FR-002 socket-permission model rules referenced or duplicated, and which is the source of truth? [Clarity, Spec §FR-040]
- [X] CHK002 Is the SO_PEERCRED check (FR-041) specified down to: which UID is compared (effective vs. real), and what to do on platforms where SO_PEERCRED is unavailable (macOS uses LOCAL_PEERPID/LOCAL_PEERCRED variants)? [Gap, Spec §FR-041]
- [X] CHK003 Is the threat model documented (what is and isn't protected against — root-on-same-host, other UIDs on same host, mounted containers)? [Gap, Spec §FR-005, §FR-040..§FR-043]
- [X] CHK004 Is "host-only constraint from FEAT-009" (FR-042) cross-referenced precisely — what is the canonical FEAT-009 rule it inherits? [Clarity, Spec §FR-042]
- [X] CHK005 Is the closed-set code for "called from container when host-only is required" specified — FR-042 mentions `routing_toggle_host_only` *or* a closed-set equivalent; which is canonical? [Ambiguity, Spec §FR-042, §FR-034]

## Requirement Clarity

- [X] CHK006 Is "trust assumption is 'same host UID'" (Edge Cases §Permission boundary) defined operationally — is the daemon required to drop privileges on startup, or assumed to run as the user already? [Clarity, Edge Cases]
- [X] CHK007 Is "MUST NOT introduce any new persisted secret, token, key, or remote authentication primitive" (FR-043) verifiable by inspecting the schema diff between FEAT-010 and FEAT-011? [Measurability, Spec §FR-043]
- [X] CHK008 Is the `app_session_token`'s status ("not a security boundary against malicious local processes" per Assumptions) called out in every place a reader might mistake it for an auth secret? [Coverage, Spec Assumptions]
- [X] CHK009 Is "host OR mounted into a bench container" (FR-040) defined operationally — must the daemon detect container origin via the socket peer's namespace? [Ambiguity, Spec §FR-040]

## Requirement Consistency

- [X] CHK010 Are FR-003 (no network listener), FR-040 (socket-permission model unchanged), and FR-043 (no new auth primitives) mutually consistent — does any FR imply behavior that violates another? [Consistency]
- [X] CHK011 Are FR-042's "MUST NOT expose to bench-container callers" and FR-041's peer-UID check consistent — the container caller's peer UID is still the host UID, so what distinguishes them? [Clarity, Spec §FR-041, §FR-042]
- [X] CHK012 Is "permission_denied" (FR-034) consistent with the actual code returned when peer UID mismatches? [Consistency, Spec §FR-034, §FR-041]

## Scenario Coverage

- [X] CHK013 Are requirements defined for SUID/SGID transitions or attacks across processes owned by the same UID (e.g., a sandboxed subprocess inheriting the socket fd)? [Gap]
- [X] CHK014 Are requirements defined for the case where the daemon's socket file is recreated with different permissions mid-session (umask change, manual chmod)? [Gap, Spec §FR-040]
- [X] CHK015 Are requirements defined for symbolic-link attacks on the socket path? [Gap, Spec §FR-040]
- [X] CHK016 Are requirements defined for clients that successfully pass peer UID but issue a method that should be host-only (FR-042)? [Coverage, Spec §FR-042]
- [X] CHK017 Are requirements defined for the case where a malicious local process opens many connections to exhaust session slots? [Gap, Edge Cases §Concurrent app sessions]
- [X] CHK018 Is there a requirement to redact secrets (if any leak in via `payload`) from `error.message` / `error.details`? [Gap]

## Measurability

- [X] CHK019 Can SC-006's "zero non-Unix-socket I/O" be verified by an `strace` or packet capture during the test run? [Measurability, Spec §SC-006]
- [X] CHK020 Can FR-043's "MUST NOT introduce any new persisted secret" be verified by a schema-diff contract test? [Measurability, Spec §FR-043]
- [X] CHK021 Can "daemon MUST NOT bind any TCP or non-Unix-domain socket during the entire test run" (SC-006) be verified at both startup and shutdown? [Measurability, Spec §SC-006]

## Ambiguities, Conflicts, Gaps

- [X] CHK022 Is the rule defined for whether peer-cred is checked at *every* request, or only at connection acceptance? [Gap, Spec §FR-041]
- [X] CHK023 Is the behavior defined when the host daemon is running as root and the calling client is a non-root user (root accepts non-root peer)? [Gap, Spec §FR-041]
- [X] CHK024 Is the rule defined for whether the socket file's group can be elevated (e.g., a `agenttower` group) without breaking the FR-041 UID check? [Gap, Spec §FR-040, §FR-041]
- [X] CHK025 Is the spec consistent about whether "no new persisted secret" (FR-043) includes the in-memory `app_session_token` (Assumptions clarify it is not persisted, but is it a "secret"?)? [Ambiguity, Spec §FR-043, Assumptions]
- [X] CHK026 Is "any future remote/multi-host access is explicitly a different feature" (Edge Cases §No network listener) sufficient as a guard, or should there be a static-analysis test ensuring no `socket.AF_INET` import lands in FEAT-011 code? [Gap, Spec §FR-003]
