# Security Requirements Quality Checklist: Host Daemon Lifecycle and Unix Socket API

**Purpose**: Validate that the security-relevant requirements in
`spec.md` (and the design choices in `plan.md`, `research.md`, and
`contracts/`) are complete, clear, consistent, and measurable enough
to act as a release gate before `/speckit.tasks`. This is a "unit
test for English" — every item asks whether the **requirements are
written well**, not whether the implementation works.
**Created**: 2026-05-05
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [research.md](../research.md) · [contracts/](../contracts/)
**Scope**: Broad (socket/file permissions + listener prohibition + protocol input validation + DoS resistance + TOCTOU/symlink + supply chain + audit/observability + startup-race security)
**Depth**: Release gate — each unchecked item must either pass review or become a task before `/speckit.tasks`.
**Audience**: PR reviewer with security awareness.

## Listener prohibition (no network surface)

- [ ] CHK001 Are the address families forbidden by FR-010 (TCP, UDP, IPv4, IPv6, raw, "or other") enumerated explicitly enough that an automated check can be written without further interpretation? [Completeness, Spec §FR-010]
- [ ] CHK002 Is the verification mechanism for "no network listener" specified as a measurable acceptance criterion (named tool, syscall family, or pattern) rather than only as a goal? [Measurability, Spec §SC-007]
- [ ] CHK003 Are the *permitted* address families (`AF_UNIX` only) named explicitly so an implementer cannot accidentally introduce `AF_NETLINK`, `AF_VSOCK`, or `AF_PACKET` and remain compliant with the letter of FR-010? [Gap, Spec §FR-010]
- [ ] CHK004 Is the prohibition applied consistently to **all** FEAT-002 processes (`agenttowerd run`, the three CLI commands), not only the daemon? [Consistency, Spec §FR-010, §FR-018]

## Permission and ownership policy

- [ ] CHK005 Are required modes specified as exact octal values for each artifact (lock, pid, socket, lifecycle log) instead of being summarized as "host-user-only"? [Clarity, Spec §FR-011]
- [ ] CHK006 Is ownership enforcement (e.g., `st_uid == os.geteuid()`) named in the requirements, not only mode bits, so that a setgid or shared-uid edge case cannot be silently accepted? [Completeness, Spec §FR-011]
- [ ] CHK007 Is the set of paths subject to permission enforcement enumerated end-to-end (state directory, log directory, lock file, pid file, socket file, lifecycle log file) so no path is silently exempt? [Completeness, Spec §FR-011]
- [ ] CHK008 Is the policy for pre-existing artifacts with broader-than-required modes ("refuse" vs "fix") stated unambiguously and consistently with FEAT-001's precedent? [Consistency, Spec §FR-011 vs FEAT-001 §FR-015]
- [ ] CHK009 Is the error-output shape for unsafe-permission refusal specified (path-specific stderr line, exit code, lifecycle log entry) so refusals are testable? [Clarity, Spec §SC-008]
- [ ] CHK010 Are the permission requirements applied at startup verified as a *gate* (refuse before any irreversible action) rather than as a post-hoc check? [Clarity, Spec §SC-008]

## Stale-artifact classification and refusal

- [ ] CHK011 Are the criteria for classifying a path as "AgentTower-owned and stale" enumerated as requirements, not only as design notes? [Completeness, Spec §FR-009]
- [ ] CHK012 Are all observed kinds of pre-existing path at the socket location (regular file, directory, symlink, FIFO, dev node, socket) and their disposition (refuse vs unlink) specified? [Coverage, Spec §Edge Cases]
- [ ] CHK013 Is the lock-ownership-as-authority principle ("only the holder of `LOCK_EX` may classify or unlink lifecycle artifacts") expressed as a requirement, not only an implementation choice in research.md? [Gap, Research §R-002 / R-004]
- [ ] CHK014 Is it specified that recovery never modifies an artifact whose ownership cannot be proven, even when the daemon holds the lock? [Consistency, Spec §FR-009]

## Protocol input validation

- [ ] CHK015 Are the validation steps for incoming JSON requests ordered and unambiguous as requirements (UTF-8 → JSON parse → object check → method check → params check)? [Clarity, Spec §FR-021]
- [ ] CHK016 Is the maximum request line size specified as a *requirement* (with a value) rather than as a plan-level implementation detail only? [Gap, Spec §FR-021 vs Plan §R-006]
- [ ] CHK017 Are the response error codes for every failure mode a closed, enumerated set in the spec or a contract document, so a security review can confirm none are missing? [Completeness, Spec §FR-014, Contracts §socket-api.md §3]
- [ ] CHK018 Is behavior for non-object JSON values (arrays, scalars, `null`) specified, including which error code applies? [Edge Case, Spec §FR-021]
- [ ] CHK019 Is the requirement that "additional bytes after the first newline are ignored" stated as a security property (no command smuggling, no replay) and not only as a connection-lifecycle convenience? [Coverage, Spec §FR-026]
- [ ] CHK020 Is forward-compatibility for unknown top-level or `params` keys specified as "ignore" rather than "reject", with the security trade-off acknowledged? [Clarity, Spec §FR-021]

## DoS resistance and resource bounds

- [ ] CHK021 Are connection-level limits (max concurrent connections, accept backlog) specified as requirements or explicitly declared out of scope? [Gap]
- [ ] CHK022 Is a per-connection slow-client timeout (peer holds connection without writing) specified or explicitly declared out of scope? [Gap]
- [ ] CHK023 Are rate-limit requirements specified or explicitly declared out of scope, with a documented justification grounded in the single-host-user threat model? [Gap, Spec §Assumptions]

## TOCTOU and symlink hardening

- [ ] CHK024 Are symlink-shaped paths at the socket location addressed in requirements with a specific resolution policy (resolve and refuse vs unlink as stale)? [Coverage, Spec §Edge Cases]
- [ ] CHK025 Is it required that the socket parent directory be verified safe (mode + ownership) *before* socket bind, not only at the socket inode? [Completeness, Spec §FR-011]
- [ ] CHK026 Is the temporal order between permission verification and socket bind specified to close TOCTOU windows (verify → operate atomically while holding the lock)? [Gap]

## Startup-race security

- [ ] CHK027 Is the security guarantee of FR-028 stated explicitly: the lock prevents two daemons binding the socket *simultaneously*, not only two daemons running long-term? [Clarity, Spec §FR-028]
- [ ] CHK028 Is it required that the loser of the lock race never modifies stale artifacts on its own — only the lock holder may do so? [Coverage, Spec §FR-028]
- [ ] CHK029 Are the failure modes of the loser path enumerated (lock held by live daemon vs. lock held by another starting daemon vs. acquisition timeout) so that none silently downgrades to "start anyway"? [Completeness, Spec §FR-028]

## Supply-chain and dependency surface

- [ ] CHK030 Is "no third-party runtime dependencies" stated as a FEAT-002 *requirement* (not only as inherited from FEAT-001), so a future reviewer cannot assume it has been relaxed? [Gap, Spec §Constraints / Plan §Technical Context]
- [ ] CHK031 Are the standard-library modules used by FEAT-002 enumerated in plan/research so a security review can spot unexpected additions in the implementation? [Traceability, Plan §Technical Context]
- [ ] CHK032 Is there a requirement (or explicit out-of-scope statement) for verifying that the package wheel published by FEAT-001 has not introduced runtime third-party deps that FEAT-002 would inherit? [Assumption, Spec §Assumptions]

## Audit and observability of security events

- [ ] CHK033 Are the security-relevant lifecycle log events (permission refusal, ownership refusal, stale-recovery actions, lock-contention failures) enumerated as required entries? [Completeness, Spec §FR-027]
- [ ] CHK034 Is the lifecycle log file's *own* permission and ownership specified at the same level of rigor as the socket, lock, and pid file? [Consistency, Spec §FR-027]
- [ ] CHK035 Is the policy for what MUST NOT appear in the lifecycle log specified (request payloads, future agent identifiers, future container ids out of FEAT-002 scope) to prevent leakage of unmodelled data? [Coverage, Spec §FR-027]
- [ ] CHK036 Is the lifecycle log expected to be append-only at the application layer, with a requirement that no FEAT-002 code path truncates or rewrites it? [Gap, Spec §FR-027]

## Shutdown security

- [ ] CHK037 Is it specified that artifacts removed on shutdown are exclusively those the daemon owns, with no broader cleanup that could affect operator files (e.g., the lifecycle log itself)? [Consistency, Spec §FR-017]
- [ ] CHK038 Is the security behavior under SIGTERM/SIGINT during stale-recovery specified (does the daemon leave a half-cleaned state, and is that state still safe for the next `ensure-daemon`)? [Edge Case, Spec §FR-022]
- [ ] CHK039 Is it required that signal-driven shutdown obey the same finish-in-flight semantics as the API shutdown method, so a SIGTERM cannot be used to truncate a still-writing audit response? [Consistency, Spec §FR-017 / clarification Q4]

## Threat model and assumptions

- [ ] CHK040 Is the implicit threat model documented (single host user, malicious local process at the same uid out of scope, no remote attacker) so security reviewers can reason about the boundary? [Gap, Spec §Assumptions]
- [ ] CHK041 Is the "another local process running at the same uid" attacker model excluded from the threat model explicitly with a documented rationale, rather than assumed away by silence? [Assumption, Spec §Assumptions]
- [ ] CHK042 Are the security implications of `setsid()` / detached-session daemonization (R-009) — including loss of controlling-terminal isolation between the daemon and other host processes — surfaced as either a requirement or an explicit non-issue? [Gap, Plan §R-009]

## Notes

- Each item asks whether the *requirement* is written well, not whether the *implementation* works.
- Mark `[x]` to record that an item passes review; record `[~]` (or add a child bullet) when an item passes only after a spec edit was made during this review.
- Items flagged `[Gap]` typically indicate the spec or plan does not yet say anything about the topic — those are the most common candidates to either fix in `spec.md` or convert into explicit out-of-scope statements before `/speckit.tasks`.
- Items flagged `[Ambiguity]` or `[Conflict]` should be resolved by editing the spec rather than deferring to implementation.
- ≥80% of items carry a traceability reference (`[Spec §...]`, `[Plan §...]`, `[Research §...]`, `[Contracts §...]`, `[Edge Cases]`, or an explicit `[Gap]` marker), per the `/speckit.checklist` traceability rule.
