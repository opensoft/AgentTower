# Security & Permissions Checklist: Package, Config, and State Foundation

**Purpose**: Pre-implementation requirements gate for the security / permissions surface — validates that every requirement governing file modes, directory modes, host-only enforcement, the "no network listener" / "no terminal input" boundaries, and the threat model around pre-existing artifacts is complete, clear, consistent, measurable, and traceable BEFORE `/speckit.implement` runs.
**Created**: 2026-05-05
**Feature**: [spec.md](../spec.md) §FR-014/015/016 + §Clarifications Q1, [plan.md](../plan.md) §Constitution Check + §Constraints, [data-model.md](../data-model.md) §1, [research.md](../research.md) R-006/R-007, [contracts/cli.md](../contracts/cli.md) C-CLI-004 + Cross-cutting, [contracts/event-writer.md](../contracts/event-writer.md) C-EVT-003
**Depth**: Strict pre-implementation gate — every item must be resolved (or explicitly accepted as out of scope) before T010/T011/T012/T017 begin.
**Audience**: Spec author, peer reviewer, and compliance reviewer (mixed).

**Note**: This checklist tests the REQUIREMENTS, not the implementation. Each item asks whether the requirement is well-written — complete, clear, consistent, measurable, and unambiguous. Items end with `[Quality dimension, traceability]` where traceability is either a spec section reference or one of the markers `[Gap]`, `[Ambiguity]`, `[Conflict]`, `[Assumption]`.

## Requirement Completeness

- [ ] CHK001 - Are file-mode requirements specified for every artifact FEAT-001 may create, including SQLite companion files (`-journal`, `-wal`, `-shm`) and lock files? [Completeness, Spec §FR-015, Gap]
- [ ] CHK002 - Are directory-mode requirements specified for every directory FEAT-001 may create, including the intermediate `opensoft/` parents under `~/.config`, `~/.local/state`, and `~/.cache`? [Completeness, Spec §FR-015, Data-Model §1]
- [ ] CHK003 - Are setuid (`04000`), setgid (`02000`), and sticky-bit (`01000`) prohibitions explicitly documented for every created artifact? [Completeness, Gap]
- [ ] CHK004 - Are executable-bit prohibitions documented for data files (config, state DB, events, logs)? [Completeness, Gap, Spec §FR-015]
- [ ] CHK005 - Are umask-interaction requirements documented — i.e. does `mkdir(mode=0o700)` / `os.open(..., 0o600)` need an explicit `os.umask(0)` or `fchmod` afterward to defeat a permissive umask? [Completeness, Gap, Plan R-006/R-007]
- [ ] CHK006 - Are TOCTOU mitigations specified for the create-then-chmod sequence (e.g. atomic `os.open(..., O_CREAT, 0o600)` vs. `open()` then `chmod`)? [Completeness, Gap, Plan R-006/R-007]
- [ ] CHK007 - Are symlink-handling requirements specified for `STATE_DB`, `EVENTS_FILE`, `CONFIG_FILE`, `LOGS_DIR`, and `SOCKET` (refuse symlinks, follow with `O_NOFOLLOW`, or accept silently)? [Completeness, Gap]
- [ ] CHK008 - Are hard-link attack mitigations documented (a pre-existing hard link with permissive mode pointing at `STATE_DB`)? [Completeness, Gap]
- [ ] CHK009 - Is the "no network listener" requirement enumerated comprehensively — TCP, UDP, Unix listening socket, abstract namespace, IPv6, raw sockets — or only "no network listener" abstractly? [Completeness, Spec §FR-016, Gap]
- [ ] CHK010 - Is the requirement to NOT bind the daemon socket (`SOCKET` path) in FEAT-001 stated independently of the "no daemon start" requirement, since they are technically separable? [Completeness, Spec §FR-016, Data-Model §1]
- [ ] CHK011 - Is the audit-trail boundary documented — Q4 says no FEAT-001 command writes to `events.jsonl`, but is there any alternative audit (syslog, stdout transcript) required for security-relevant init events? [Completeness, Spec §Clarifications Q4, §FR-016, Gap]
- [ ] CHK012 - Are requirements specified for the `daemon.py` `--version` stub explicitly NOT performing any privileged action (no socket bind, no fork, no setuid)? [Completeness, Contracts §C-CLI-005, Spec §FR-016]

## Requirement Clarity

- [ ] CHK013 - Is "host-only" (FR-015, plan §Constitution Check) defined precisely — POSIX mode bits 0700/0600 only, or also POSIX ACLs (`setfacl`), security xattrs, SELinux contexts? [Clarity, Spec §FR-015, Gap]
- [ ] CHK014 - Is "single host user" quantified — UID match required, GID match, both, or neither (pure mode-bit posture)? [Clarity, Spec §Assumptions, Plan §Constraints]
- [ ] CHK015 - Is the umask precedence rule clear — does the documented mode (`0o700` / `0o600`) survive a process umask of e.g. `0o077`, `0o022`, or `0o000`, and is the implementation required to neutralize the umask? [Ambiguity, Plan R-006/R-007]
- [ ] CHK016 - Is "actionable error message naming the offending path" (FR-014) bounded against information-disclosure risk — e.g. is it acceptable to print absolute paths under `$HOME` to a captured stderr that may be tee'd to a shared log? [Ambiguity, Spec §FR-014, Gap]
- [ ] CHK017 - Is the term "pre-existing artifacts MAY retain their existing permissions" (FR-015 last sentence) clear about whether this applies to artifacts FEAT-001 itself created on a prior run vs. artifacts created by an external party? [Ambiguity, Spec §FR-015]

## Requirement Consistency

- [ ] CHK018 - Do FR-015 ("MUST be created with 0600/0700") and FR-011 ("MUST NOT … mutate any pre-existing … artifact") agree on the resolution when a pre-existing artifact has WEAKER (more permissive) modes than required — does the spec accept the security gap, refuse, or warn? [Conflict, Spec §FR-015 vs §FR-011]
- [ ] CHK019 - Do FR-015 ("config file MUST be 0600") and contracts/event-writer.md C-EVT-003 ("existing file mode unchanged") use the same pre-existing-file policy, or do config / events apply different rules? [Consistency, Contracts §C-EVT-003 vs Spec §FR-015]
- [ ] CHK020 - Are mode requirements consistent across spec.md (FR-015), plan.md (§Constraints), data-model.md (§1 mode column), research.md (R-006/R-007), contracts/cli.md (C-CLI-004 §Side effects), and contracts/event-writer.md (C-EVT-003) — is `0700` for dirs and `0600` for files unanimous? [Consistency]
- [ ] CHK021 - Is the constitution's "host user only" posture (Principle I) consistent with the spec's silence on runtime UID validation — i.e. does "host user only" mean "owned by the invoking UID" or just "mode-bit-restricted"? [Consistency, Plan §Constitution Check, Gap]
- [ ] CHK022 - Does FR-016's enumeration ("no network listener, no daemon, no Docker scan, no tmux scan, no agent registration, no log ingest, no event classification, no message routing, no terminal input, no FEAT-001 command writes events") match the side-effect "must NOT" lists in contracts/cli.md C-CLI-004 / C-CLI-005? [Consistency, Spec §FR-016, Contracts §C-CLI-004/005]

## Acceptance Criteria Quality

- [ ] CHK023 - Is SC-009's enumeration of artifacts subject to file-permission tests exhaustive — does it list config dir, state dir, logs dir, cache dir, config file, state DB file, events file (when present), AND the `opensoft/` intermediate parents, sqlite WAL/SHM, and any temp file? [Measurability, Spec §SC-009, Gap]
- [ ] CHK024 - Can FR-016's "no network listener" requirement be objectively measured by an automated test (e.g. process-level `ss`, `lsof`, or library-level mock) and is the chosen measurement specified? [Measurability, Spec §FR-016, Gap]
- [ ] CHK025 - Is the "FEAT-001 commands write no record to events.jsonl" invariant (FR-016 / Q4) testable as both a positive ("no file created") and a negative ("if file pre-exists, byte length is unchanged") assertion? [Measurability, Spec §FR-016, Quickstart §11]
- [ ] CHK026 - Are exit-code requirements (`0` success, `1` failure) consistently defined as the boundary between "security-relevant failure" and "informational warning" (e.g. is a pre-existing world-readable config a `0` or `1`)? [Measurability, Contracts §C-CLI-004, Gap]

## Scenario & Edge-Case Coverage

- [ ] CHK027 - Are requirements specified for the case where `STATE_DB` pre-exists as a symlink to a privileged path (e.g. `/etc/passwd`)? [Coverage, Exception Flow, Gap]
- [ ] CHK028 - Are requirements specified for the case where `CONFIG_FILE` pre-exists with mode `0644` (world-readable) — does init refuse, chmod, warn, or silently accept per FR-015 last sentence? [Coverage, Spec §FR-015, Gap]
- [ ] CHK029 - Are requirements specified for the case where `~/.config/opensoft/` pre-exists with mode `0755` because another Opensoft tool created it? [Coverage, Spec §FR-015, Edge Case]
- [ ] CHK030 - Are requirements specified for filesystems that do not honor POSIX mode bits (vfat, exfat, ntfs-3g, certain SMB mounts) — is graceful degradation, refusal, or silent acceptance the contract? [Coverage, Gap, Spec §Assumptions]
- [ ] CHK031 - Are requirements specified for inherited POSIX ACLs from a parent directory that override mode bits in practice? [Coverage, Gap]
- [ ] CHK032 - Are requirements specified for the case where a stale `agenttowerd.sock` file exists with permissive mode at init time — left as is per spec edge case, or sanitized? [Coverage, Spec §Edge Cases, Gap on permissions]
- [ ] CHK033 - Are concurrent-init security implications covered (one race winner creates files at `0600`, but the loser sees ENOENT and creates them at the permissive umask default)? [Coverage, Gap]
- [ ] CHK034 - Are requirements specified for `EVENTS_FILE` whose pre-existing mode is permissive — C-EVT-003 says "existing file mode unchanged"; is that the security-aware contract or a known gap? [Coverage, Contracts §C-EVT-003, Spec §FR-015]

## Non-Functional Requirements

- [ ] CHK035 - Is a threat model documented (assets, actors, attack vectors) so that 0700/0600 mode bits can be evaluated as adequate or inadequate mitigation? [Completeness, Gap]
- [ ] CHK036 - Are defense-in-depth requirements specified beyond mode bits (e.g. is process-level seccomp / capability dropping required for `agenttowerd` even in its FEAT-001 stub)? [Completeness, Gap, Spec §FR-016]
- [ ] CHK037 - Are compliance / framework requirements documented (CIS Linux benchmark, NIST 800-53 AC-3, etc.) — or is local-first single-user posture the entire compliance story? [Completeness, Gap]
- [ ] CHK038 - Is the security boundary between FEAT-001 (no network) and FEAT-005 (container socket mount) documented so a reviewer knows what additional security requirements arrive later vs. ship now? [Completeness, Plan §Constitution Check, Spec §FR-016]

## Dependencies & Assumptions

- [ ] CHK039 - Is the assumption "POSIX filesystem semantics (mode bits work)" stated explicitly and traceable to a section the reviewer can sign off on? [Assumption, Spec §Assumptions, Plan §Target Platform]
- [ ] CHK040 - Is the assumption "trusted dev environment — no malicious local process racing init" stated explicitly, since 0700/0600 alone do not defend against same-UID adversarial code? [Assumption, Gap]
- [ ] CHK041 - Is the assumption "`$HOME` points to a directory the user controls" stated, given the resolver fully trusts `$HOME`? [Assumption, Gap, Plan R-003]
- [ ] CHK042 - Is the dependency on the OS not silently downgrading mode bits via `nosuid`/`noexec` mount options or container-runtime overlay quirks documented? [Assumption, Gap]

## Ambiguities & Conflicts

- [ ] CHK043 - Is the "strict host-only" posture (Q1, FR-015) reconciled with the "pre-existing artifacts MAY retain their existing permissions" exception — is the resulting security gap an acknowledged trade-off in the spec, or is it implicit? [Conflict, Spec §FR-015 vs §Clarifications Q1]
- [ ] CHK044 - Is the relationship between FR-016 ("no FEAT-001 command writes events") and auditability (no audit trail of who/when init ran with what env) made explicit and accepted as a deliberate trade-off, or just stated as a fact? [Ambiguity, Spec §FR-016, §Clarifications Q4]
- [ ] CHK045 - Does the spec resolve the latent ambiguity in FR-015 about whether "every directory it creates" includes the chain of `opensoft/` intermediate parents, or only the deepest leaf (`agenttower/`)? [Ambiguity, Spec §FR-015, Data-Model §1]
- [ ] CHK046 - Does the spec resolve whether `umask` mutation by FEAT-001 is permissible — some operators set restrictive umasks intentionally; an implementation that calls `os.umask(0)` may surprise them? [Ambiguity, Gap, Plan R-006/R-007]

## Notes

- Resolution policy for this gate: every item must be marked complete (`[x]`) OR replaced with an explicit `[OUT OF SCOPE — accepted by <name>]` note before `/speckit.implement` runs.
- Several items overlap with `state.md` (CHK019/CHK021 in state.md ↔ CHK020/CHK023 here). Resolutions on one side SHOULD propagate to the other.
- `[Gap]` items SHOULD trigger a spec amendment (re-run `/speckit.specify` or `/speckit.clarify`) unless the gap is intentional and accepted in writing.
- `[Conflict]` and `[Ambiguity]` items MUST be resolved in spec.md before implementation — the implementation MUST NOT be where the security trade-off is made.
- `[Assumption]` items either get promoted to documented assumptions in `Spec §Assumptions` or down-graded to validated facts.
- This checklist evaluates the QUALITY of requirements; behavioral verification (do the modes actually land at 0600/0700? does any listener bind?) is owned by `tests/integration/test_cli_init.py` (T014) and the polish task T020.

