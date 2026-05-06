# Security Checklist: Container tmux Pane Discovery (FEAT-004)

**Purpose**: Unit-test the *requirements writing* in spec.md, plan.md, research.md, data-model.md, contracts/cli.md, and contracts/socket-api.md for FEAT-004's security-critical surface area before tasks are generated. This is the first feature that runs subprocesses **inside** bench containers and the first feature that persists user-controllable data from a container surface, so completeness, clarity, and consistency on argv hardening, sanitization, timeout enforcement, audit-channel hygiene, and threat-model boundaries directly determines implementation correctness.
**Created**: 2026-05-06
**Feature**: [spec.md](../spec.md)

## Subprocess Argv Hardening

- [ ] CHK001 Are the in-container subprocess invocations enumerated as a closed set with explicit argv shape for each? [Completeness, Spec FR-033, Research R-001]
- [ ] CHK002 Is the `shell=False` invariant for every `docker exec` invocation stated in the requirements rather than left to implementation discretion? [Clarity, Spec FR-021]
- [ ] CHK003 Are the user-supplied tokens that flow into argv (`<bench-user>`, `<container-id>`, `<uid>`, `<socket-name>`, format string) enumerated with the requirement that none of them is interpolated into a shell string? [Completeness, Research R-001, Spec FR-021]
- [ ] CHK004 Are the requirements consistent between plan §Constraints, research R-001, and spec FR-021/FR-033 about which subprocess shapes are allowed? [Consistency]
- [ ] CHK005 Is it specified that container metadata (id, name), socket basenames, pane titles, and pane cwds MUST be treated as ordinary argv data even when they contain shell metacharacters? [Clarity, Spec FR-021]
- [ ] CHK006 Are requirements defined for what happens when a socket basename or container name itself contains a leading `/`, `..`, or path-separator characters from `ls -1` output? [Edge Case, Research R-007]
- [ ] CHK007 Are requirements explicit that no FEAT-004 code path SHOULD construct an in-container helper script, multi-command chain, or `sh -c` payload? [Completeness, Research R-001 alternatives section]

## Bench User & UID Resolution

- [ ] CHK008 Is the resolution order for the bench user (`containers.config_user` → daemon `$USER`) specified and unambiguous? [Clarity, Spec FR-020, Research R-005]
- [ ] CHK009 Are requirements consistent between FR-020, R-005, and data-model §2.1 on whether `containers.config_user` is read once per scan or once per `docker exec`? [Consistency]
- [ ] CHK010 Is the rejection of a hardcoded uid (`1000`) stated as a requirement, not just a design preference? [Clarity, Spec §Assumptions, Research R-006]
- [ ] CHK011 Is the failure path for `id -u` (timeout, non-zero exit, non-numeric stdout, empty stdout) specified with a closed-set error code per case? [Completeness, Research R-006, Spec FR-019]
- [ ] CHK012 Are requirements defined for what happens when the daemon process has no `$USER` env var set AND `containers.config_user` is NULL? [Edge Case, Gap]
- [ ] CHK013 Is the per-scan caching scope of the resolved uid explicitly bounded ("one scan only"), and is it specified that the cache MUST NOT survive into a subsequent scan? [Clarity, Research R-006]
- [ ] CHK014 Are requirements consistent on whether `containers.config_user` of the form `user:uid` is parsed or rejected? [Consistency, Gap, Research R-006]

## Timeout Enforcement & Subprocess Lifecycle

- [ ] CHK015 Is the 5-second per-call timeout stated as a requirement on every FEAT-004 `docker exec` invocation (not just `tmux list-panes`)? [Completeness, Spec FR-018]
- [ ] CHK016 Is the requirement that a timed-out child be terminated and waited on before the reconciler proceeds explicit? [Clarity, Spec FR-018, Research R-003]
- [ ] CHK017 Are requirements defined for what happens when termination of a timed-out child itself fails or hangs (defensive)? [Edge Case, Gap]
- [ ] CHK018 Is the worst-case mutex hold time bounded as a requirement, not just an estimate, when every container is wedged? [Measurability, Plan §Performance Goals]
- [ ] CHK019 Are the closed error codes for timeout (`docker_exec_timeout`) and other subprocess failures (`docker_exec_failed`, `output_malformed`) defined consistently across spec FR-019, research R-011, and contracts/socket-api.md §2? [Consistency]
- [ ] CHK020 Is it specified that an orphaned subprocess child MUST NOT survive the scan (no zombies)? [Completeness, SC-006, Spec FR-018]
- [ ] CHK021 Are requirements specified for partial output (stdout received before timeout) — discarded, parsed, or treated as malformed? [Edge Case, Gap]

## Sanitization & Truncation Pipeline

- [ ] CHK022 Are the per-field truncation maximums (2048 / 2048 / 4096) stated as numeric requirements? [Clarity, Spec FR-023, Research R-009]
- [ ] CHK023 Is sanitization required at every output boundary (SQLite, JSONL, socket response, CLI default, CLI `--json`, lifecycle log) — or just one canonical helper? [Completeness, Spec FR-023, FR-026]
- [ ] CHK024 Are the byte classes that MUST be stripped (NUL `\x00`, C0 `\x01`–`\x08`, `\x0b`–`\x1f`, `\x7f`) enumerated rather than referred to as "control bytes"? [Clarity, Research R-009]
- [ ] CHK025 Is the substitution rule for embedded `\t` and `\n` (replace with single space) specified, and is it consistent between R-009 and contracts/cli.md / contracts/socket-api.md? [Consistency]
- [ ] CHK026 Is "UTF-8-aware truncation, not bytes" stated as a requirement for the per-field maximums? [Clarity, Research R-009]
- [ ] CHK027 Are requirements clear that truncation MUST NOT reject the pane row, and that a `pane_truncations` note MUST be recorded in the scan result? [Clarity, Spec FR-023]
- [ ] CHK028 Are the truncation note fields (`tmux_pane_id`, `field`, `original_len`) specified at every boundary they appear (data-model §3.5, contracts/cli.md, contracts/socket-api.md, error_details_json)? [Consistency]
- [ ] CHK029 Are requirements defined for sanitization of error_message strings before they enter SQLite, JSONL, lifecycle logs, and socket responses (not just pane field strings)? [Completeness, Spec FR-026, Research R-009]
- [ ] CHK030 Is it specified what happens when a non-pane-text field (e.g., `pane_pid` claimed integer but parsed as text) violates expected type — flagged as `output_malformed`, coerced, or persisted? [Edge Case, Gap]
- [ ] CHK031 Are requirements explicit that the bounded `error_message` cap (2048 chars) applies to every stderr-derived string before it enters SQLite, JSONL, lifecycle logs, and socket responses? [Completeness, Spec FR-026, Research R-018]
- [ ] CHK032 Is the requirement that raw `tmux list-panes` output, raw `docker exec` stderr beyond the bounded message, raw env values, and raw pane titles MUST NOT appear in audit channels stated identically across FR-026, R-014, and R-018? [Consistency]

## Audit-Channel Hygiene

- [ ] CHK033 Are the lifecycle log fields for `pane_scan_started` and `pane_scan_completed` enumerated exhaustively (so reviewers can verify nothing else leaks)? [Completeness, Research R-014]
- [ ] CHK034 Is "healthy scans MUST NOT append to events.jsonl" stated as a requirement, not just a default? [Clarity, Spec FR-025]
- [ ] CHK035 Is "exactly one JSONL record per degraded scan_id" stated as a requirement, including the case where the same scan_id is retried? [Clarity, Spec FR-028]
- [ ] CHK036 Are the JSONL `pane_scan_degraded` payload fields enumerated, and do they match the persisted `pane_scans.error_details_json` shape? [Consistency, Research R-010]
- [ ] CHK037 Is the write-order requirement (mutex acquired → `pane_scan_started` → SQLite commit → JSONL append → `pane_scan_completed` → response) specified in a single canonical place? [Clarity, Spec FR-025, Research R-014]
- [ ] CHK038 Are requirements defined for what happens when the JSONL append fails after the SQLite commit succeeded (post-commit side-effect failure)? [Edge Case, Research R-015, Spec FR-024]
- [ ] CHK039 Are requirements defined for what happens when the lifecycle log write fails (disk full, fd exhausted) during the scan? [Edge Case, Gap]

## Whole-Scan-Failure vs Partial-Degraded Asymmetry

- [ ] CHK040 Is the asymmetry between envelope-level codes (only `docker_unavailable`) and per-scope codes (the other seven) stated identically in research R-011 and contracts/socket-api.md §2? [Consistency]
- [ ] CHK041 Are requirements explicit that `docker_unavailable` still persists a `pane_scans` row with `status="degraded"` even though the envelope is `ok:false`? [Clarity, Research R-011, contracts/socket-api.md §3.4]
- [ ] CHK042 Are requirements specified for whether `internal_error` from a SQLite rollback writes a `pane_scans` row at all? [Edge Case, Research R-015, Spec FR-024]
- [ ] CHK043 Are FEAT-003's `docker_*` codes (e.g., `docker_failed`, `docker_timeout`) explicitly excluded from the FEAT-004 emit set? [Clarity, contracts/socket-api.md §2]

## Mutex Independence

- [ ] CHK044 Is the requirement that the pane-scan mutex is independent of the FEAT-003 container-scan mutex stated explicitly, not just implied by "new mutex"? [Clarity, Spec FR-017, Research R-004]
- [ ] CHK045 Is the requirement that `list_panes` MUST NOT acquire the pane-scan mutex stated explicitly? [Clarity, Spec FR-016]
- [ ] CHK046 Are requirements defined for two concurrent `scan_panes` callers' relative ordering (FIFO or runtime lock scheduling)? [Clarity, Research R-004, contracts/socket-api.md §3.5]
- [ ] CHK047 Are requirements defined for what happens to an in-flight scan when the daemon is sent `shutdown`? [Edge Case, Spec §Edge Cases, Research R-004]
- [ ] CHK048 Is the requirement that the mutex is in-process only and recreated on daemon restart stated, with the implication that no on-disk lock or PID file is added? [Completeness, Research R-004]

## Schema Migration Safety

- [ ] CHK049 Is the requirement that the v2→v3 migration runs in a single transaction stated, with explicit rollback-on-failure semantics? [Clarity, Spec FR-029]
- [ ] CHK050 Is the requirement that an unknown future schema version (v4) MUST refuse daemon startup explicit? [Clarity, Spec FR-029, Research R-016]
- [ ] CHK051 Are requirements explicit that the v3 migration is idempotent on re-open of an already-v3 database? [Clarity, Research R-016]
- [ ] CHK052 Is "the v3 migration MUST NOT alter FEAT-003 `containers` or `container_scans` tables" stated as a requirement, not just an observation? [Clarity, Spec FR-030]
- [ ] CHK053 Are requirements defined for what happens when migration partially succeeds and the daemon is killed mid-transaction? [Edge Case, Research R-016]

## Threat Model & Trust Boundaries

- [ ] CHK054 Is the trust boundary (host user trusted; container metadata, tmux output, pane titles, pane cwds, `docker exec` stderr untrusted) stated explicitly in the requirements? [Completeness, Spec §Assumptions]
- [ ] CHK055 Is the deferral of secret redaction to FEAT-007 stated as a requirement, with the implication that pane titles and cwds are persisted unredacted in MVP? [Clarity, Spec §Assumptions, Research R-018]
- [ ] CHK056 Are requirements defined for how the daemon handles a container whose `Config.User` is a numeric `:uid` form (e.g., `:0` for root) — accepted, rejected, or normalized? [Edge Case, Gap]
- [ ] CHK057 Is the requirement that `docker exec` runs as the daemon user (no `sudo`, no host-side uid/gid change) stated? [Clarity, Spec FR-032]
- [ ] CHK058 Is the inheritance of FEAT-002's socket-file authorization (`0600`, host user only) stated as a requirement, not just an assumption? [Completeness, Spec FR-031]
- [ ] CHK059 Is the absence of a network listener stated as a requirement that includes a test invariant (no AF_INET / AF_INET6)? [Measurability, Spec FR-031, contracts/cli.md §Cross-cutting]
- [ ] CHK060 Are requirements explicit that no in-container daemon, agent, or relay process is started by FEAT-004? [Clarity, Spec FR-031, FR-032]
- [ ] CHK061 Is the requirement that the resolved Docker binary is trusted (same posture as FEAT-003) stated, including the implication that PATH shadowing is out of scope for FEAT-004? [Clarity, Spec FR-022, Plan §Constraints]

## Observable Counters & Measurability

- [ ] CHK062 Are the seven `pane_scans` counters (containers_scanned, sockets_scanned, panes_seen, panes_newly_active, panes_reconciled_inactive, containers_skipped_inactive, containers_tmux_unavailable) defined consistently between FR-012, data-model §2.2, and contracts/socket-api.md §3.2? [Consistency]
- [ ] CHK063 Is each counter defined precisely enough that two implementers would compute the same value on the same scan? [Measurability, Spec FR-012]
- [ ] CHK064 Is "containers_skipped_inactive does NOT include containers whose `tmux_unavailable` ended their scan" specified explicitly to prevent double-counting? [Clarity, Gap]
- [ ] CHK065 Are the success criteria SC-001…SC-009 each measurable without subjective judgment? [Measurability, Spec §Measurable Outcomes]

## Test Hooks (Security-Adjacent)

- [ ] CHK066 Is the `AGENTTOWER_TEST_TMUX_FAKE` env var documented as a test seam, with the requirement that the daemon's production behavior is unaffected when the env var is unset? [Clarity, Research R-012]
- [ ] CHK067 Is the requirement that `AGENTTOWER_TEST_TMUX_FAKE` MUST NOT be exposed via a CLI flag (production surface contamination) stated? [Clarity, Research R-012]
- [ ] CHK068 Are the FakeTmuxAdapter fixture's failure-injection knobs (`id_u_failure`, `socket_dir_missing`, per-socket `failure`) exhaustive enough to cover every closed-set error code? [Coverage, Research R-012]
- [ ] CHK069 Is "no real `docker` or `tmux` invocation in the test suite" stated as a hard requirement with a positive-assertion test, not just a goal? [Measurability, Spec FR-034, SC-009, Research R-017]

## Edge Cases & Scenario Coverage

- [ ] CHK070 Are pane-id-reuse-across-restart, partial format-string honoring, concurrent FEAT-003+FEAT-004 scans, and container rename addressed in requirements? [Coverage, Spec §Edge Cases]
- [ ] CHK071 Are requirements defined for stale, broken, or other-user-owned files inside `/tmp/tmux-<uid>/`? [Edge Case, Spec §Edge Cases, Research R-007]
- [ ] CHK072 Are requirements defined for symlinks inside `/tmp/tmux-<uid>/` that resolve outside the directory? [Edge Case, Spec FR-004, Research R-007]
- [ ] CHK073 Are requirements defined for the case where `/tmp/tmux-<uid>/` is a symlink rather than a directory? [Edge Case, Gap]
- [ ] CHK074 Are requirements defined for the case where a tmux pane's title or cwd contains valid UTF-8 multi-byte sequences that would be split mid-sequence by a naive byte truncation? [Edge Case, Research R-009]
- [ ] CHK075 Are requirements defined for the case where `tmux list-panes` returns CRLF line endings instead of LF? [Edge Case, Gap]
- [ ] CHK076 Are requirements defined for what happens when `containers` rows are deleted manually (orphan `panes` rows) — masked by the `list_panes` JOIN, surfaced, or rejected? [Edge Case, contracts/socket-api.md §4.3]

## Notes

- Each item tests the *requirements writing*, not the implementation. Findings should be encoded as spec/plan/research/contract amendments before `/speckit.tasks` runs.
- Markers used: `[Gap]` = not currently specified; `[Ambiguity]`, `[Conflict]`, `[Edge Case]`, `[Coverage]`, `[Clarity]`, `[Completeness]`, `[Consistency]`, `[Measurability]`.
- Spec section references use FR-### / SC-### / R-### / contract section numbers as they appear in the artifacts on this branch.
- This checklist intentionally excludes implementation-level checks (test runner, code review patterns, CI wiring) — those belong in a separate `quality.md` checklist if desired.
