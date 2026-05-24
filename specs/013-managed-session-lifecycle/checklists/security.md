# Security Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that security and protection requirements (auth, authz, injection, integrity, isolation) are complete, clear, consistent, and measurable for this feature.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Threat Model & Authorization

- [ ] CHK001 Is the threat model documented or referenced for this feature? [Gap]
- [ ] CHK002 Are the authentication requirements for the daemon socket specified, or explicitly absent for MVP per the Assumptions? [Clarity, Spec §Assumptions]
- [ ] CHK003 Are the local-socket access controls specified (file permissions, group ownership, UID match policy)? [Gap, Spec §FR-017]
- [ ] CHK004 Are authorization requirements specified for destructive lifecycle actions (remove, recreate) beyond "any socket caller"? [Gap, Spec §FR-010, FR-011]
- [ ] CHK005 Is the protection mechanism specified that prevents an operator from removing adopted panes via managed-pane operations (FR-012)? [Completeness, Spec §FR-012]
- [ ] CHK006 Are authentication/authorization requirements specified for the `promoted_from_adopted` transition stub (so it cannot be accidentally invoked in MVP)? [Gap, Spec §FR-018]
- [ ] CHK007 Are deny-by-default requirements specified for any future per-user/per-container ACL extension? [Gap, Spec §Assumptions]

## Input Validation & Injection

- [ ] CHK008 Are command-injection protections specified for launch commands (FR-002)? [Gap, Spec §FR-002]
- [ ] CHK009 Are constraints specified on what launch commands a profile may contain (whitelist, sandbox, no shell metachars)? [Gap, Spec §FR-002]
- [ ] CHK010 Are requirements specified for sanitizing the human-readable label patterns to prevent injection into tmux pane titles or terminal output? [Gap, Spec §FR-003]
- [ ] CHK011 Are validation requirements specified for the tmux session name to reject names that could confuse other surfaces (control characters, length limits)? [Gap, Spec §FR-016]

## Confidentiality

- [ ] CHK012 Are requirements specified for what data the lifecycle events contain (any sensitive material such as full command lines, environment variables, working directories)? [Gap, Spec §FR-015]
- [ ] CHK013 Are `managed_session_name_conflict` and other error responses specified to not leak sensitive information (other tmux sessions, paths)? [Gap, Spec §FR-016]
- [ ] CHK014 Are requirements specified for redacting any sensitive fields in launch command profiles before persistence/observability? [Gap, Cross-ref: configuration.md, observability.md]

## Integrity

- [ ] CHK015 Are protections specified against TOCTOU between scan and creation flow (the pending-managed marker is the mitigation — is its integrity guaranteed)? [Gap, Spec §FR-014]
- [ ] CHK016 Is there a requirement that managed-layout state survival across daemon restart (FR-020) preserves integrity (no tampering between restart cycles)? [Gap, Spec §FR-020]
- [ ] CHK017 Are protections specified against an operator removing tmux sessions they did not create through the managed-pane path? [Completeness, Spec §FR-010]
- [ ] CHK018 Are protections specified against forging the predecessor_id linkage (an operator cannot fabricate a chain to mask history)? [Gap, Spec §FR-011]
- [ ] CHK019 Are audit-log integrity requirements specified for the indefinite event retention (FR-021)? [Gap, Spec §FR-021]

## Containment / Isolation

- [ ] CHK020 Are the security implications of the bench-container thin-client model specified (untrusted in-container code calling the daemon via the mounted socket)? [Gap, Spec §FR-017]
- [ ] CHK021 Are isolation requirements specified between managed layouts in different bench containers (cross-container leakage protections)? [Gap, Spec §FR-009]

## Exception / Recovery

- [ ] CHK022 Are security requirements specified for the daemon-restart recovery path (verifying that recovered tmux panes really match the durable records)? [Gap, Spec §FR-020]
- [ ] CHK023 Are security requirements specified for the case where two callers race for the same destructive action on the same pane (lock+permission order)? [Gap, Spec §FR-019]
