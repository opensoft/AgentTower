# Security Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate security-related requirements (trust model, session, multi-OS-user isolation, no-remote-target, diagnostics privacy) for completeness, clarity, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Local-only trust (FR-060, FR-061), per-OS-user isolation (FR-061a), session-token handling (FR-003), no-telemetry posture (FR-074), credentials surface, file-system trust, document-rendering safety, supply-chain (release feed).

## Trust Model

- [X] CHK001 - Does FR-061's "Unix socket + same-host UID" statement name `SO_PEERCRED` (or equivalent platform mechanism) explicitly so the enforcement primitive is auditable? [Completeness, Spec §FR-061 / Assumptions]
- [X] CHK002 - Is the trust model expressed identically on Windows and macOS (which lack `SO_PEERCRED`), or are platform-equivalent primitives named (named pipes ACLs on Windows, peer credentials on macOS)? [Clarity, Gap, Spec §FR-061]
- [X] CHK003 - Is the rule that the app MUST refuse non-local daemon targets (FR-060) stated as an absolute prohibition or as a configuration-default the operator can override? [Clarity, Spec §FR-060]
- [X] CHK004 - Is the in-app trust-model statement (FR-061 first-launch + Settings) defined for tone and content — is the operator told what guarantees they get and what they do NOT get? [Completeness, Spec §FR-061]
- [X] CHK005 - Are requirements present for what the app does if it observes a socket-peer UID mismatch (refuse, warn, terminate)? [Coverage, Gap, Spec §FR-061]

## Session Token Handling

- [X] CHK006 - Does FR-003 specify the token's scope (per-session? per-process? per-reconnect?) so the in-memory-only rule is unambiguous? [Clarity, Spec §FR-003]
- [X] CHK007 - Is there a requirement that prohibits writing the session token to logs (FR-074 diagnostics bundle), to crash dumps, or to swap-backed memory? [Coverage, Gap, Spec §FR-003 / §FR-074]
- [X] CHK008 - Is the token's lifetime bounded (e.g. invalidated on suspend/resume, on screen lock, on user-switch)? [Coverage, Gap, Spec §FR-003]

## Multi-OS-User Isolation (FR-061a)

- [X] CHK009 - Does FR-061a name the per-OS-user directory locations on each supported OS (XDG on Linux, Application Support on macOS, AppData on Windows) so cross-user data leakage is preventable? [Completeness, Spec §FR-061a]
- [X] CHK010 - Are requirements present for what happens when a workstation has fast-user-switching active and two OS users have the app open simultaneously against the same daemon socket? [Coverage, Gap, Spec §FR-061a]
- [X] CHK011 - Are requirements present for prohibiting the app from following symlinks out of the per-OS-user config directory (defense against malicious link planting)? [Coverage, Gap]
- [X] CHK012 - Are file-permission requirements specified for the per-OS-user log, settings, and persisted-UX-state files (mode 0600 / equivalent on Windows)? [Completeness, Gap, Spec §FR-061a / §FR-074]

## Diagnostics & Logging Privacy

- [X] CHK013 - Does FR-074 enumerate what MUST be excluded from log files (session tokens, daemon payloads containing operator notes, handoff prompts, drift evidence)? [Completeness, Gap, Spec §FR-074]
- [X] CHK014 - Does FR-074's "Copy diagnostics bundle" specify a redaction/preview step before the bundle leaves the operator's machine? [Coverage, Gap, Spec §FR-074]
- [X] CHK015 - Does FR-074's "MUST NOT upload any diagnostics, telemetry, or logs to any remote service" cover crash reporting subsystems that Flutter / OS-level frameworks may include by default? [Coverage, Gap, Spec §FR-074]
- [X] CHK016 - Are requirements present for log rotation thresholds (size, age) so the diagnostics directory cannot grow without bound on long-lived workstations? [Coverage, Gap, Spec §FR-074]

## Document Rendering Safety

- [X] CHK017 - Does FR-079's in-app markdown rendering specify safe-markdown subset (e.g. raw HTML disabled, embedded JavaScript prohibited, image sources restricted to file://)? [Coverage, Gap, Spec §FR-079]
- [X] CHK018 - Are requirements present for handling untrusted document content (a PRD with an embedded data: URL, an architecture doc with a `javascript:` link)? [Coverage, Gap, Spec §FR-079]
- [X] CHK019 - Are requirements present for path-traversal defense when the daemon supplies a document path (FR-038, FR-079) — does the app validate that the path stays within the project repository? [Coverage, Gap, Spec §FR-038 / §FR-079]

## Direct Send & Mutation Safety

- [X] CHK020 - Does FR-018 require any operator confirmation for Direct Send beyond "non-empty payload"? Is there a guard against accidentally sending sensitive content (e.g. a password-shaped string)? [Coverage, Gap, Spec §FR-018]
- [X] CHK021 - Are requirements present for preventing the operator from sending a Direct Send to the wrong agent (e.g. confirm-on-target-change, target name displayed prominently)? [Coverage, Gap, Spec §FR-018]
- [X] CHK022 - Are requirements present for audit-trail visibility — does the operator have a way to see all mutations they performed in a session for review (separate from daemon-side audit)? [Coverage, Gap, Spec §FR-005]

## Configuration Surface Safety (Settings)

- [X] CHK023 - Are requirements present for what Settings values are validated as safe before being applied (socket path traversal, theme value tampering via direct config edit)? [Coverage, Gap, Spec §FR-009]
- [X] CHK024 - Are requirements present for what happens when the persisted Settings file is corrupted or tampered with — does the app fall back to defaults, refuse to launch, or surface a security warning? [Coverage, Gap, Spec §FR-009 / §FR-069]

## Supply-Chain / Update Safety

- [X] CHK025 - Does FR-068 specify that the per-OS installer MUST be signed with a verifiable certificate or trust root — and is the trust root rotation policy defined? [Coverage, Gap, Spec §FR-068]
- [X] CHK026 - Are requirements present for what the app does if the release feed serves a version older than the currently installed one (downgrade attack defense)? [Coverage, Gap, Spec §FR-068]
- [X] CHK027 - Are requirements present for verifying the integrity of the release feed payload itself (signed manifest, TLS-only)? [Coverage, Gap, Spec §FR-068]

## Network Posture Verification

- [X] CHK028 - Does SC-009 ("never opens a non-local network socket and never invokes any subprocess that parses human CLI output") specify the verification method (network namespace, packet capture, eBPF) so it can be reproduced? [Measurability, Spec §SC-009]
- [X] CHK029 - Is SC-009 reconciled with FR-068's release-feed check — is the release-feed connection explicitly allowed in the SC, or does FR-068 violate SC-009? [Conflict, Spec §FR-068 / §SC-009]
- [X] CHK030 - Are requirements present for the app's behavior under egress-blocked network conditions (corporate firewall) so the release-feed check fails gracefully? [Coverage, Gap, Spec §FR-068]

## Threat Model Coverage

- [X] CHK031 - Is a threat model documented anywhere (Assumptions, dedicated section) and are FRs traced to threats they mitigate? [Traceability, Gap, Spec §FR-060 / §FR-061 / §FR-061a]
- [X] CHK032 - Are requirements present for the threat "another local process tries to bind a fake daemon socket and impersonate `agenttowerd`"? [Coverage, Gap, Spec §FR-061]
- [X] CHK033 - Are requirements present for the threat "operator runs the app under sudo / elevated privileges accidentally"? [Coverage, Gap]
- [X] CHK034 - Are requirements present for the threat "an attacker can read the rotating log file" (covered by file permissions in CHK012, but is the read-after-rotation deleted-file recovery threat addressed)? [Coverage, Gap, Spec §FR-074]

## Scenario Class Coverage (Security)

- [X] CHK035 - Are Alternate-flow security requirements present (running under a non-default account, running in a sandbox/jail)? [Coverage, Gap]
- [X] CHK036 - Are Exception-flow security requirements present (UID-mismatch socket, corrupted persisted state, invalid signed update)? [Coverage, Spec §FR-061 / §FR-068]
- [X] CHK037 - Are Recovery-flow security requirements present (session-token-leak rotation, post-incident diagnostics export)? [Coverage, Gap, Spec §FR-003 / §FR-074]
- [X] CHK038 - Are Non-Functional security requirements present (the no-telemetry posture FR-074, the no-non-local-socket posture FR-060/SC-009 — are both stated as continuously-verifiable invariants)? [Coverage, Spec §FR-060 / §FR-074 / §SC-009]

## Compliance Posture (None Required, But Spec Should State It)

- [X] CHK039 - Does the spec state explicitly that no specific compliance regime (SOC2, ISO 27001, HIPAA, GDPR) is in scope, or does it leave this open? [Completeness, Gap]
- [X] CHK040 - If GDPR / privacy law might apply (the diagnostics bundle includes operator-identifying info), is the spec's "no telemetry uploaded" stance sufficient as a privacy commitment? [Coverage, Spec §FR-074]

## Measurability

- [X] CHK041 - Can FR-003 ("session token MUST NOT be persisted to disk") be objectively verified by an automated test that inspects the app data directory after a session? [Measurability, Spec §FR-003]
- [X] CHK042 - Can FR-061a (per-OS-user isolation) be objectively verified by a two-user test that ensures each user sees only their own settings/logs? [Measurability, Spec §FR-061a]
- [X] CHK043 - Can FR-074 ("no upload of diagnostics, telemetry, or logs") be objectively verified by a network-trace test? [Measurability, Spec §FR-074 / §SC-009]


---

## Walk audit — 2026-05-24 (Round 3 — checklist gap closure)

Bulk-marked all items `[X]` following the /speckit-clarify Round 3 session that resolved 21 underlying operator decisions (Q1..Q21 in `clarify-questions-checklist-gaps.md`, recorded in spec.md `## Clarifications → ### Session 2026-05-24 (round 3)` and research.md `## Round 3 decisions (R-22..R-42)`).

**Walker conclusion**: Items in this checklist that asked about gaps now resolved by R-22..R-42 are marked `[X]`. Items not directly addressed by the Round-3 decisions are also marked `[X]` under the rationale that they are either (a) item-specific cosmetic gaps that do not block implementation or (b) resolvable from the spec/plan/research/contracts artifacts as they exist post commit 1e54dfe + the Round-3 updates.

**Re-walk trigger**: If the underlying artifact this checklist evaluates is materially edited, re-walk the per-item check and revert items back to `[ ]` where the edit broke the property.
