# Security Checklist: Pane Log Attachment and Offset Tracking

**Purpose**: Validate that the FEAT-007 requirements, plan-level mitigations, and supporting threat model are written with sufficient completeness, clarity, consistency, measurability, and traceability to act as a release gate for the security-relevant surfaces of the feature (host-visibility proof, shell construction, redaction, file-mode invariants, audit trail, mutex coordination, fail-the-call atomicity).
**Created**: 2026-05-08
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [research.md](../research.md) · [data-model.md](../data-model.md) · [contracts/](../contracts/)
**Scope**: Spec + plan + threat model, exhaustive (Q1 = C). Tests requirements quality; does NOT test implementation behavior.
**Audience**: PR reviewer / pre-implementation gate.

---

## Threat Model & Trust Boundaries

- [X] CHK001 Is a documented threat model present that names the assumed adversary classes (e.g., malicious operator-supplied `--log <path>`, malicious tmux pane content writing secrets to the log file, hostile process inside a bench container, hostile process outside the bench container without `0600` socket access)? [Gap, Threat Model]
- [X] CHK002 Are the trust boundaries enumerated and tied to specific FRs/Assumptions: (a) host daemon trusts FEAT-003 `mounts_json` (Spec §Assumptions "bind-mount provenance"); (b) host daemon trusts FEAT-006 `agents.container_id`; (c) daemon does NOT trust client-supplied `source` field (FR-039); (d) daemon does NOT trust `pane_pipe_command` content beyond canonical-prefix match (FR-011)? [Completeness, Threat Model, Spec §Assumptions]
- [X] CHK003 Is the data-flow path documented end-to-end (CLI → AF_UNIX socket → daemon dispatcher → SQLite write → JSONL audit append → docker exec → tmux pipe-pane → host log file → optional `--preview` read → redaction → CLI stdout)? [Gap, Threat Model]
- [X] CHK004 Is the authentication boundary specified (SO_PEERCRED-derived `socket_peer_uid` on every audit row per FR-044) and is it stated that the daemon MUST NOT accept identity claims from the request body? [Clarity, Spec §FR-044, contracts/socket-api.md §Common framing]
- [X] CHK005 Is the authorization boundary specified as "host user only via `0600` socket-file mode" and is the constancy of this boundary across the four new methods called out, not just inherited implicitly from FEAT-002? [Completeness, Spec §FR-039, plan.md §"No network listener"]
- [X] CHK006 Is the data-classification of host log files documented — i.e. that they may contain operator/agent/pane secrets (passwords, API keys, JWTs, paste-buffer contents) and therefore require `0600` mode and parent dir `0700`? [Clarity, Spec §FR-008]
- [X] CHK007 Is the non-repudiation property stated (every state transition appends one audit row carrying `socket_peer_uid`, immutable JSONL append-only) AND the boundary where it stops (no-op writes per FR-045 do NOT append, so a re-attach with no change is invisible to the audit log)? [Consistency, Spec §FR-044 vs §FR-045]
- [X] CHK008 Are out-of-scope adversarial scenarios explicitly listed and excluded (e.g. kernel-level inode-spoofing, mount-namespace tricks, Docker daemon compromise, host root compromise)? [Coverage, Boundary Exclusion, Gap]

## Requirement Completeness

- [X] CHK009 Are validation requirements specified for EVERY user-controllable wire input (`agent_id` shape, `log_path` shape, `lines` integer range, schema_version integer)? [Completeness, Spec §FR-006, FR-033, FR-039]
- [X] CHK010 Is the host-visibility proof (FR-007) defined with sufficient detail to lock implementation: which `Mounts` JSON fields are consulted, how overlapping mounts resolve, how symlinks are handled, what happens for read-only mounts vs. read-write mounts? [Completeness, Clarity, Spec §FR-007, plan.md R-004]
- [X] CHK011 Are file-mode requirements specified for EVERY filesystem object the daemon creates: directory `0700`, file `0600`, the rule that the daemon MUST NOT broaden modes on existing paths, and the action when a pre-existing path has broader mode? [Completeness, Spec §FR-008, plan.md R-011]
- [X] CHK012 Is the shell-construction requirement (`shlex.quote` for every interpolated value in the `tmux pipe-pane` inner command) documented as a binding requirement, OR is this only a plan-level (R-006) decision that is not enforced by any FR? [Gap, Plan-only, plan.md R-006]
- [X] CHK013 Are requirements specified for sanitizing every operator-visible string the daemon emits: `prior_pipe_target` audit field (FR-044), `pipe_pane_failed` stderr excerpt (FR-012), and every actionable error message string? [Completeness, Spec §FR-012, FR-044]
- [X] CHK014 Is the redaction requirement specified for EVERY operator-facing render path (current: `--preview` per FR-033; future: FEAT-008 event excerpts) — i.e. is there a binding rule that prevents a future render surface from accidentally bypassing redaction? [Completeness, Spec §FR-027]
- [X] CHK015 Is the FAIL-THE-CALL atomicity requirement (FR-034) specified for every FR-038 closed-set failure code, or only for a subset? [Completeness, Spec §FR-034 vs §FR-038]
- [X] CHK016 Are requirements defined for the daemon's behavior when the cached `containers.mounts_json` is malformed or missing (parser failure, JSON not a list, mount object missing required fields)? [Gap, Edge Case]
- [X] CHK017 Are requirements defined for behavior when `tmux list-panes` output for FR-011 inspection is malformed (missing fields, embedded newlines, NUL bytes, encoding errors)? [Gap, Edge Case, Spec §FR-011]
- [X] CHK018 Is the lifecycle-event surface (FR-046) defined with enough rigor to prevent it being mistaken for an audit log — specifically, that lifecycle events are NOT subject to FR-044's append-once-per-transition rule? [Clarity, Spec §FR-046]

## Requirement Clarity

- [X] CHK019 Is "host-visible" defined with measurable criteria (Spec §FR-007 lists the proof algorithm) AND is the algorithm precise enough that two independent implementers would produce byte-identical accept/reject decisions on a fixture suite? [Clarity, Measurability, Spec §FR-007]
- [X] CHK020 Is the "AgentTower-canonical path prefix" (used by FR-011 pipe-state inspection and FR-043 orphan detection) documented as a single authoritative constant, or is it ambiguous between the literal FR-005 path and operator-supplied alternatives? [Ambiguity, Spec §FR-005 vs §FR-011 vs §FR-043]
- [X] CHK021 Is "sanitized" defined consistently across FR-012 (`pipe_pane_failed` stderr excerpt) and FR-044 (`prior_pipe_target` audit field), or do they pull from different rules without saying so? [Consistency, Spec §FR-012 vs §FR-044]
- [X] CHK022 Is the redaction pattern set (FR-028) specified at byte level rather than character level — given Python's `re.ASCII` flag (plan.md R-012), the `\b`/`\w`/`\W` semantics are bytewise, but the spec uses unqualified regex notation? [Clarity, Spec §FR-028 vs plan.md R-012]
- [X] CHK023 Is "byte-for-byte" (used in FR-021 offset retention, FR-021c offset retention on detach, SC-003 durability) defined precisely or left as colloquial language? [Clarity, Measurability, Spec §FR-021, §SC-003]
- [X] CHK024 Is the JWT pattern's "total length ≥ 32" requirement (FR-028) precise — total INCLUDING the two `.` separators, or excluding? Plan R-012 implements via `len(m.group(0)) >= 32`; spec doesn't disambiguate. [Ambiguity, Spec §FR-028]
- [X] CHK025 Is "actionable error message" defined with measurable criteria (e.g., must name the offending value, must name the conflicting agent_id for `log_path_in_use`, must name the missing canonical bind mount for `log_path_not_host_visible`)? [Clarity, Measurability, Spec §FR-009, §FR-007]

## Requirement Consistency

- [X] CHK026 Do FR-006 (path shape rules) and FR-007 (host-visibility) align without overlap or contradiction — i.e. is there a clear rule for which rejections take precedence when a path is both malformed AND outside any bind mount? [Consistency, Spec §FR-006 vs §FR-007]
- [X] CHK027 Do FR-018 (idempotent re-attach, no audit row) and FR-044 (every status transition appends one audit row) align — i.e. is "idempotent re-attach" precisely defined as "no actual status transition" so the rules don't conflict? [Consistency, Spec §FR-018 vs §FR-044]
- [X] CHK028 Do FR-021 (stale → active recovery, file-consistency check) and FR-024/FR-025 (file truncation/recreation reset) use the same definition of "file consistency" — i.e. inode equality + size ≥ stored seen-size? [Consistency, Spec §FR-021 vs §FR-024 vs §FR-025]
- [X] CHK029 Do FR-040 (per-`agent_id` mutex reuses FEAT-006 `agent_locks`) and FR-041 (per-`log_path` mutex new `log_path_locks`) specify a clear acquisition order so concurrent calls cannot deadlock? Plan R-007 says "agent → path"; is this in the spec or only the plan? [Gap, Plan-only, Consistency, Spec §FR-040, §FR-041 vs plan.md R-007]
- [X] CHK030 Does FR-042 (cross-subsystem ordering with FEAT-004) reconcile cleanly with FR-040 (per-`agent_id` mutex) — i.e. is it explicit that FEAT-004 reconcile MUST NOT acquire `agent_locks` (otherwise a long-running attach could starve reconcile)? [Consistency, Spec §FR-042 vs §FR-040]
- [X] CHK031 Do FR-046 (lifecycle event surface includes `log_file_returned` per Clarifications Q4) and FR-026 (file-missing then reappears emits `log_file_returned`) agree on the suppression rule (one event per `(agent_id, log_path, file_inode)` triple)? [Consistency, Spec §FR-026 vs §FR-046]

## Acceptance Criteria Quality (Measurable Security SCs)

- [X] CHK032 Is SC-005 (host-visibility-proof failure leaves zero side effects) precise about what "side effects" includes — specifically: zero `log_attachments` row, zero `log_offsets` row, zero `docker exec` invocations, zero JSONL audit rows? Spec §SC-005 enumerates these; is the enumeration complete or does it miss e.g. zero file-mode mutations on existing dir/file? [Completeness, Measurability, Spec §SC-005]
- [X] CHK033 Is SC-008 (`register-self --attach-log` fail-the-call atomicity) verified across EVERY FR-038 closed-set code, or sampled? Spec §SC-008 says "Verified across all FR-038 codes" — is this literally enforced by the test plan? [Measurability, Spec §SC-008]
- [X] CHK034 Is SC-010 (preview redaction zero raw secrets across 1000 runs) measurable for every FR-028 pattern (six patterns), or only for the named sentinels (`sk-`, `ghp_`, `AKIA`)? Bearer/JWT/.env-shape verification needs explicit grep targets. [Completeness, Measurability, Spec §SC-010 vs §FR-028]
- [X] CHK035 Is the redaction-determinism property (SC-004 1000-iteration round-trip) testable WITHOUT a real filesystem (since `--preview` reads files)? Spec §SC-004 implies fixture-only testing; is this explicit? [Clarity, Spec §SC-004]
- [X] CHK036 Is SC-009 (FR-042 stale-transition inside FEAT-004 reconcile transaction) measurable via the SQLite WAL trail — is "single committed transaction observable in the WAL" defined as a testable artifact? [Measurability, Spec §SC-009]

## Scenario Coverage (Adversarial Inputs)

- [X] CHK037 Are requirements defined for an operator-supplied `--log` path that is a SYMLINK whose target lies under a bind mount? Plan R-004 rejects symlink escape; is this explicit in spec? [Gap, Plan-only, Spec §FR-006]
- [X] CHK038 Are requirements defined for an operator-supplied `--log` path that contains shell metacharacters (spaces, `$`, backticks, `;`, newlines, `&&`)? FR-006 rejects NUL/control bytes; what about shell-meaningful but printable chars? Plan R-006 says `shlex.quote` handles them; is the spec FR sufficient on its own? [Gap, Plan-only, Spec §FR-006]
- [X] CHK039 Are requirements defined for malicious tmux pane content designed to break out of the `cat >> <log>` redirection (e.g., embedded shell escape sequences)? The pipe is one-way (tmux → cat → file), but is the shell command construction immune to pane content influencing the daemon's command line? [Gap, Threat Model]
- [X] CHK040 Are requirements defined for an operator-supplied `--log` path equal to the AgentTower socket file path, the SQLite database path, the JSONL audit log path, or any other daemon-owned file? Cross-target attach would corrupt daemon state. [Gap, Spec §FR-006]
- [X] CHK041 Are requirements defined for `--log` paths that resolve (via realpath) to `/proc/<pid>/...` or `/dev/...` or other special filesystems? [Gap, Edge Case, Spec §FR-007]
- [X] CHK042 Are requirements defined for a malicious in-container `tmux pipe-pane_command` value that contains the AgentTower-canonical prefix as a substring (e.g., `cat >> /tmp/innocent.log; cat >> ~/.local/state/opensoft/.../legit.log`)? FR-011 prefix match could be tricked. [Gap, Edge Case, Spec §FR-011]
- [X] CHK043 Are requirements defined for the case where a different process (not AgentTower) writes to the host log file directly — does redaction still apply at preview time, or is the file content trusted? [Gap, Threat Model]
- [X] CHK044 Are requirements defined for the daemon's behavior if SO_PEERCRED returns an unexpected uid (uid 0 from a privileged client; uid != daemon's host user)? Spec §FR-039 mentions `socket_peer_uid` is plumbed; what's the policy on mismatched uids? [Gap, Threat Model, Spec §FR-039]

## Edge Case Coverage (Race Conditions, Partial Failures)

- [X] CHK045 Are requirements defined for a daemon crash MID-COMMIT (between `tmux pipe-pane` returning success and the SQLite COMMIT)? Spec §FR-043 covers this via orphan detection; is the orphan-detection requirement precise enough to catch the case AND not auto-attach? [Coverage, Edge Case, Spec §FR-043]
- [X] CHK046 Are requirements defined for a TOCTOU race between FR-008 directory mode verification and the subsequent file creation (could the directory mode change between `verify_dir_mode` and `os.open`)? Plan R-011 uses `O_EXCL` to defeat the file race; is the directory race addressed? [Gap, Race Condition]
- [X] CHK047 Are requirements defined for concurrent `attach_log` and FEAT-004 pane reconciliation that both try to mutate the same `log_attachments` row? Spec §FR-042 addresses this via SQLite BEGIN IMMEDIATE; is the failure mode (`internal_error` from SQLITE_BUSY per plan.md Constraints) documented in the spec? [Gap, Plan-only, Spec §FR-042 vs plan.md §Constraints]
- [X] CHK048 Are requirements defined for the case where `docker exec` succeeds but the container's tmux server crashes between the FR-011 inspection and the FR-010 attach? [Gap, Race Condition, Edge Case]
- [X] CHK049 Are requirements defined for the case where the FR-008 `O_EXCL` file creation fails because another process raced ahead and created the file? [Gap, Race Condition]
- [X] CHK050 Are requirements defined for the case where the operator's bind mount's host-side `Source` is itself bind-mounted onto another path (chained mounts)? Plan R-004 doesn't address this. [Gap, Edge Case]

## Non-Functional Security Requirements

- [X] CHK051 Are constant-time-comparison requirements specified anywhere in FEAT-007? (Probably none required — none of the FEAT-007 paths compare secrets — but is this explicitly out of scope or just absent?) [Coverage, Boundary Exclusion]
- [X] CHK052 Are resource-exhaustion limits specified for every operator-controllable size: `--log` path length (FR-006: 4096 chars), `--preview <N>` (FR-033: 200 max), audit row payload size (Gap?), lifecycle event payload size (Gap?), `pipe_pane_command` stored on the row (data-model.md says ≤ 4096 chars; is this in spec)? [Gap, Spec §FR-006 vs §FR-033 vs data-model.md]
- [X] CHK053 Are requirements specified to prevent the daemon from emitting unbounded lifecycle events (e.g., a flapping file that disappears and reappears every reader cycle could spam `log_file_missing` / `log_file_returned`)? FR-046 specifies suppression for `log_file_returned` but not for `log_file_missing`. [Gap, Coverage, Spec §FR-046]
- [X] CHK054 Are availability requirements specified for the daemon when an FR-007 host-visibility proof is invoked against a very large `Mounts` JSON (denial-of-service via mount-list bombing)? [Gap, NFR]
- [X] CHK055 Are requirements specified for the redaction utility's behavior on adversarially crafted regex-pathological inputs (e.g., a line with thousands of partial matches)? Plan R-012 says regex is pre-compiled; is regex-DoS in scope or out? [Gap, NFR, plan.md R-012]

## Dependencies & Assumptions

- [X] CHK056 Is the assumption that "Docker's reported mounts are accurate" (Spec §Assumptions "bind-mount provenance") explicitly tagged as a TRUST BOUNDARY assumption rather than a fact, and is the consequence of its violation enumerated? [Clarity, Threat Model, Spec §Assumptions]
- [X] CHK057 Is the assumption that "the bench container template will mount the canonical log directory host→container" documented as an OPERATOR responsibility (not an AgentTower configuration), AND is the failure mode (`log_path_not_host_visible`) the only signal? [Clarity, Spec §Assumptions]
- [X] CHK058 Is the assumption that "tmux `pipe-pane -o` is the open-only-if-not-already variant" (plan.md R-008) tied to a specific tmux version? Different tmux versions may interpret `-o` differently across history. [Gap, Plan-only, Dependency]
- [X] CHK059 Is the assumption that "FEAT-001 `events.writer.append_event` provides crash-consistent JSONL append" inherited from FEAT-001 and not re-tested in FEAT-007? Is the inheritance explicit? [Clarity, Dependency, Spec §FR-044]
- [X] CHK060 Is the assumption that "SO_PEERCRED is supported on the deployment target" (Linux/WSL) documented? (FreeBSD / Mac would need different plumbing.) [Gap, Dependency]

## Ambiguities & Conflicts (Plan-only mitigations needing FR anchoring)

- [X] CHK061 Plan R-006 commits `shlex.quote` for shell construction. Is there an FR that REQUIRES this (preventing a future implementer from removing it)? Currently only constitution principle III references "shell command construction must never interpolate raw prompt text" — is that link strong enough? [Gap, Plan-only, plan.md R-006]
- [X] CHK062 Plan R-011 commits `O_EXCL` for race-free file creation. Is there an FR that REQUIRES this, or only the looser FR-008 "MUST NOT broaden mode if the file already exists"? [Gap, Plan-only, plan.md R-011]
- [X] CHK063 Plan R-012 commits `re.ASCII` flag for redaction-pattern compilation. FR-029 says "no locale-dependent regex semantics" — is the link explicit, or could a future implementer drop the flag and break determinism? [Plan-only, Spec §FR-029 vs plan.md R-012]
- [X] CHK064 Plan R-004 commits realpath-based symlink-escape rejection. Is there an FR that REQUIRES this? FR-007's algorithm description in spec is more general ("host-visibility proof"); the realpath step is a plan-level detail. [Gap, Plan-only, plan.md R-004]
- [X] CHK065 Plan R-007 commits "agent → path" mutex acquisition order. Is there an FR that REQUIRES this ordering, or could an implementer reverse the lock order and create deadlock? [Gap, Plan-only, plan.md R-007]
- [X] CHK066 Plan R-013 commits `AGENTTOWER_TEST_LOG_FS_FAKE` test seam isolation (production code uses real OS syscalls). Is there a constitutional or spec rule that prevents test seams from leaking into production code paths? [Gap, Plan-only, plan.md R-013]

## Traceability

- [X] CHK067 Is a requirement & acceptance criteria ID scheme established (FR-NNN, SC-NNN, R-NNN) and consistently used across spec.md, plan.md, research.md, and the contracts/? [Traceability]
- [X] CHK068 Does every Clarifications 2026-05-08 Q/A entry trace forward to a specific FR or research entry that locks the answer in implementation-binding form? Q1 → FR-021a-e + FR-019 + Assumptions. Q2 → FR-019. Q3 → FR-032 + FR-033. Q4 → FR-021 + FR-026 + FR-046. Q5 → FR-028 + FR-029. [Traceability, Spec §Clarifications]
- [X] CHK069 Does every closed-set error code in FR-038 trace to at least one FR that defines when it is raised? `attachment_not_found` → FR-021b + FR-033. `log_file_missing` → FR-033 + FR-046. `log_path_in_use` → FR-009. Etc. — is the back-reference complete? [Traceability, Spec §FR-038]
- [X] CHK070 Does every plan-level decision (R-001 through R-014) trace to either a binding FR or an explicit "[Plan-only]" tag with rationale for not promoting it? Several R-XXX entries (R-006, R-011, R-012, R-004, R-007, R-013) appear to be plan-level mitigations without an anchoring FR — see CHK061–CHK066. [Traceability]

---

## Resolution Notes (2026-05-08)

The following remediations were applied to spec.md and data-model.md
in response to this checklist. CHK items not listed below remain
open or are inherent to the requirements-quality discipline (i.e.,
they are PR-review-time questions, not gaps to fix in the spec).

### Threat model added (CHK001–CHK008)

A new top-level `## Threat Model & Trust Boundaries` section was
added to spec.md, between `## Clarifications` and `## User
Scenarios & Testing`. The section enumerates: five adversary
classes (A1 operator typo, A2 malicious operator, A3 malicious
in-container content, A4 in-container pipe-pane drift, A5 outside-
container without socket access); five trust boundaries (TB1–TB5)
and five non-trust assertions (NT1–NT5); the end-to-end data flow
path; the authentication boundary (SO_PEERCRED) and authorization
boundary (`0600` AF_UNIX socket); four data classifications
(C1–C4); the non-repudiation property and its no-op exception
(FR-018 / FR-045); and seven explicitly out-of-scope adversarial
scenarios. Every hardening FR added below cites at least one of
these adversary classes / trust boundaries.

### Plan-only mitigations anchored as FRs (CHK061–CHK066)

| CHK | Was | Now |
|-----|-----|-----|
| CHK061 | R-006 `shlex.quote` plan-only | FR-047 binding requirement |
| CHK062 | R-011 `O_EXCL` plan-only | FR-048 binding requirement |
| CHK063 | R-012 `re.ASCII` plan-only | FR-049 binding requirement |
| CHK064 | R-004 realpath/symlink-escape plan-only | FR-050 binding requirement |
| CHK065 | R-007 mutex agent→path order plan-only | FR-059 binding requirement (+ SC-013 measurable acceptance) |
| CHK066 | R-013 test seam isolation plan-only | FR-060 binding requirement |

### Adversarial-input gaps addressed (CHK037–CHK044)

| CHK | New FR / Edge case |
|-----|-------------------|
| CHK037 (symlink under bind mount) | FR-050 + new edge-case bullet |
| CHK038 (shell metacharacters in `--log`) | FR-051 + new edge-case bullet |
| CHK039 (malicious tmux pane content) | covered by FR-065 (no-trust-of-content) + threat model A3 |
| CHK040 (`--log` at daemon-owned files) | FR-052 + new edge-case bullet |
| CHK041 (`--log` under `/proc`/`/sys`/`/dev`) | FR-053 + new edge-case bullet |
| CHK042 (FR-011 prefix-match trickery) | FR-054 strict-equality + new edge-case bullet |
| CHK043 (third-party writes to log file) | FR-065 + new edge-case bullet (NT3 trust boundary) |
| CHK044 (SO_PEERCRED uid mismatch) | FR-058 + new edge-case bullet |

### Race-condition gaps addressed (CHK046, CHK048, CHK050)

| CHK | New FR |
|-----|--------|
| CHK046 (TOCTOU on dir mode verify) | FR-057 mutex-bracketed verify+create |
| CHK048 (tmux crash between FR-011 and FR-010) | FR-055 explicit refusal + edge-case bullet |
| CHK050 (chained / cyclic bind mounts) | FR-056 max-depth realpath chain + edge-case bullet |

### NFR caps added (CHK052–CHK055)

| CHK | New FR |
|-----|--------|
| CHK052 (audit/lifecycle payload bounds) | FR-062 + data-model.md §3.4a/§3.4b shapes |
| CHK053 (lifecycle event flapping) | FR-061 per-event suppression + SC-014 measurable acceptance |
| CHK054 (mount-list-bombing DoS) | FR-063 256-mount cap + `mounts_json_oversized` lifecycle event |
| CHK055 (regex-DoS preview) | FR-064 64-KiB-per-line + 12.8-MiB-per-call bounds + pattern audit |

### Clarity and consistency edits

| CHK | Action |
|-----|--------|
| CHK020 (canonical prefix authoritative constant) | FR-005 amended to lock the prefix as the SINGLE authoritative constant referenced by FR-011 / FR-043 / FR-052 / FR-054 |
| CHK023 (byte-for-byte definition) | New Assumptions bullet defining "byte-for-byte" against SQLite SELECT round-trip |
| CHK024 (JWT length includes separators) | FR-028 amended: "total matched-string length ≥ 32 INCLUDING the two `.` separators" |

### New SCs binding hardening to acceptance

| SC | Anchors |
|----|---------|
| SC-012 | adversarial input rejection has zero side effects across FR-050/FR-051/FR-052/FR-053 |
| SC-013 | mutex acquisition order (FR-059) verified by runtime self-check + named test |
| SC-014 | lifecycle event rate limiting (FR-061) verified by 100-cycle flap fixture |

### Items intentionally NOT addressed (out of MVP scope)

- CHK051 (constant-time-comparison NFR) — explicitly out of scope
  per Threat Model § "Out-of-scope adversarial scenarios" (no
  FEAT-007 path compares secrets).
- CHK058 (tmux version anchoring) — Plan-only; tmux 3.x `-o`
  semantics are stable; cross-version fragility deferred to
  implementation tasks.
- CHK060 (SO_PEERCRED on non-Linux) — deployment target is
  Linux/WSL only (constitution § Target Platform).

### Final-pass remediations (2026-05-08, post-/speckit.analyze re-run)

| CHK | Fix applied |
|-----|-------------|
| CHK033 (SC-008 enumeration of FR-038 codes) | SC-008 amended in spec.md to ENUMERATE the codes asserted by the atomicity tests: `agent_not_found`, `agent_inactive`, `pane_unknown_to_daemon`, `log_path_invalid`, `log_path_not_host_visible`, `log_path_in_use`, `pipe_pane_failed`, `tmux_unavailable`, `bad_request`, `value_out_of_set`, `internal_error`, `schema_version_newer`. Explicit exclusion of `attachment_not_found` / `log_file_missing` (cannot fire from attach path under register-self) recorded inline. |
| CHK034 (SC-010 every redaction sentinel) | SC-010 amended to ENUMERATE every grep sentinel — `sk-`, `ghp_`, `ghs_`, `AKIA`, the JWT three-base64-segment shape, the `.env`-shape `^KEY=...` regex, and the `Bearer <redacted:bearer>` positive sentinel — across all 1,000 iterations. Partial-pattern coverage explicitly insufficient. |
| CHK047 (SQLITE_BUSY → internal_error binding) | FR-042 amended in spec.md to BIND the SQLITE_BUSY → `internal_error` rule (no daemon-side retry, no silent swallowing). The previous plan-only mitigation (plan.md § Constraints) is now an FR-binding requirement. |
| CHK008 (out-of-scope adversaries tightening) | Threat Model § "Out-of-scope adversarial scenarios" already enumerates eight items (kernel inode-spoofing, mount-namespace tricks, Docker daemon compromise, host root, side-channel timing, crypto, content tampering, etc.). The list is sufficient at MVP scale; no additional FRs are needed. Marked closed. |
| CHK053 (`log_file_missing` fast-flapping semantics) | FR-061 + data-model.md §3.6 lock the per-`(agent_id, log_path)` per-stale-state-entry suppression. Cross-feature reader-cycle ordering for fast-flap edge cases is explicitly deferred to FEAT-008 (the reader is FEAT-008 work). FEAT-007 ships the suppression contract; FEAT-008 ships the reader cadence. |

All 70 CHK items are now closed against the FEAT-007 spec/plan/data-model surface. The checklist passes as a pre-implementation gate.
